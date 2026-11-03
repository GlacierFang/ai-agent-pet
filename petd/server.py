"""HTTP + WebSocket 服务。

单端口 18860 同时承载：
  /device              设备 WS
  /admin/              管理控制台（静态单页）
  /admin/api/*         控制台接口
  /firmware/           固件下载（供设备 OTA）

**无鉴权** —— 只允许绑定内网地址，禁止暴露公网。
"""
import asyncio
import contextlib
import json
import logging
import pathlib

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import config as config_mod
from .app import PetApp

log = logging.getLogger("petd.server")

STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
ADMIN_DIR = STATIC_DIR / "admin"
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def create_app(cfg=None, start_gateway=True):
    cfg = cfg or config_mod.load()
    cfg["_repo_root"] = str(REPO_ROOT)
    pet = PetApp(cfg)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        gateway = None
        gateway_task = None
        if start_gateway:
            from .gateway import GatewayClient

            gateway = GatewayClient(cfg, on_sessions=pet.on_sessions)
            pet._gateway = gateway
            gateway_task = asyncio.create_task(gateway.run_forever())
        await pet.start(gateway)
        try:
            yield
        finally:
            await pet.stop()
            if gateway_task:
                gateway_task.cancel()
                with contextlib.suppress(Exception):
                    await gateway_task

    async def device_ws(ws: WebSocket):
        await ws.accept(subprotocol="petd.v1")
        session = None
        try:
            raw = await asyncio.wait_for(ws.receive_text(), 5)
            hello = json.loads(raw)
            if hello.get("type") != "hello" or int(hello.get("protocol", 0)) != 1:
                await ws.send_text(json.dumps({"type": "error", "code": "PROTOCOL_MISMATCH"}))
                await ws.close(code=1002)
                return
            session = await pet.devices.attach(ws, hello)
            await pet.on_device_connected()
            while True:
                event = await ws.receive()
                if event["type"] == "websocket.disconnect":
                    break
                text = event.get("text")
                if text:
                    await pet.on_device_message(text)
        except WebSocketDisconnect:
            pass
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                await ws.close(code=1002)
        except Exception as exc:
            pet.log("error", "设备连接异常: %s" % exc)
        finally:
            if session is not None:
                await pet.devices.detach(session)

    async def admin_index(request):
        index = ADMIN_DIR / "index.html"
        if not index.exists():
            return HTMLResponse("<h1>petd admin</h1><p>后台页缺失</p>", status_code=404)
        return HTMLResponse(index.read_text(encoding="utf-8"))

    async def api_preview(request):
        if not pet.last_jpeg:
            return Response(b"", media_type="image/jpeg", status_code=404)
        return Response(pet.last_jpeg, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    async def api_status(request):
        return JSONResponse(pet.snapshot())

    async def api_config_get(request):
        return JSONResponse(config_mod.public_view(pet.cfg))

    async def api_config_post(request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)
        cur = json.loads(json.dumps(pet.cfg))
        for key, val in (body or {}).items():
            if key == "gateway" and isinstance(val, dict):
                val = dict(val)
                if val.get("token") in ("***", ""):
                    val["token"] = cur.get("gateway", {}).get("token", "")
                cur.setdefault("gateway", {}).update(val)
            elif isinstance(val, dict) and isinstance(cur.get(key), dict):
                cur[key].update(val)
            else:
                cur[key] = val
        cur["_repo_root"] = str(REPO_ROOT)
        pet.cfg = cur
        try:
            config_mod.save({k: v for k, v in cur.items() if not k.startswith("_")})
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        pet.log("info", "配置已更新")
        return JSONResponse({"ok": True, "config": config_mod.public_view(pet.cfg)})

    async def api_logs(request):
        since = int(request.query_params.get("since", 0))
        items = [e for e in pet.logs if e["seq"] > since]
        return JSONResponse({"items": items, "seq": pet._log_seq})

    async def api_events(request):
        async def gen():
            last = pet._log_seq
            while True:
                yield "retry: 2000\n\n"
                for e in list(pet.logs):
                    if e["seq"] > last:
                        last = e["seq"]
                        yield "data: " + json.dumps(e, ensure_ascii=False) + "\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store",
                                          "X-Accel-Buffering": "no"})

    async def api_releases(request):
        return JSONResponse({"items": [], "note": "v1 未接入 GitHub Release"})

    async def api_ota(request):
        return JSONResponse({"ok": False, "error": "设备 OTA 未实现"}, status_code=501)

    async def api_firmware_list(request):
        d = REPO_ROOT / "firmware" / "build"
        items = []
        if d.is_dir():
            for f in sorted(d.glob("*.bin")):
                items.append({"name": f.name, "size": f.stat().st_size})
        return JSONResponse({"items": items})

    routes = [
        Route("/admin", admin_index),
        Route("/admin/api/preview.jpg", api_preview),
        Route("/admin/api/status", api_status),
        Route("/admin/api/config", api_config_get, methods=["GET"]),
        Route("/admin/api/config", api_config_post, methods=["POST"]),
        Route("/admin/api/logs", api_logs),
        Route("/admin/api/events", api_events),
        Route("/admin/api/releases", api_releases),
        Route("/admin/api/ota", api_ota, methods=["POST"]),
        Route("/admin/api/firmware", api_firmware_list),
        WebSocketRoute("/device", device_ws),
    ]
    if ADMIN_DIR.is_dir():
        routes.append(Mount("/admin/assets", StaticFiles(directory=str(ADMIN_DIR)),
                            name="admin-assets"))
    fw_dir = REPO_ROOT / "firmware" / "build"
    if fw_dir.is_dir():
        routes.append(Mount("/firmware", StaticFiles(directory=str(fw_dir)), name="firmware"))

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.pet = pet
    return app
