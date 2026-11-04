"""HTTP + WebSocket 服务。

单端口 18860 同时承载：
  /device              设备 WS
  /admin/              管理控制台（静态单页）
  /admin/api/*         控制台接口
  /firmware/           固件下载（供设备 OTA）

**可选口令** —— 设了 PETD_ADMIN_PASSWORD 才鉴权；没设就是老样子。
公网入口由 nginx 反代到 /ai-agent-pet/ 前缀。
"""
import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import pathlib
import time

from starlette.applications import Starlette
from starlette.responses import (HTMLResponse, JSONResponse, RedirectResponse,
                                 Response, StreamingResponse)
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import config as config_mod
from . import skins as skins_mod
from .app import PetApp
from .mdns import MdnsAdvertiser

log = logging.getLogger("petd.server")

STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
ADMIN_DIR = STATIC_DIR / "admin"
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

AUTH_COOKIE = "petd_admin"
AUTH_TTL = 7 * 24 * 3600


def _derive_key(material):
    """签名用的材料。传进来的已经是不含明文口令的东西。"""
    return hashlib.sha256(material.encode("utf-8")).digest()


class _Auth:
    """后台鉴权状态。

    三种状态：

      disabled  显式关掉（PETD_ADMIN_AUTH=off）—— 完全敞开，开发用
      set       已经设了口令 —— 要登录
      none      还没设 —— 第一次访问时设一个，设之前后台全锁

    口令的来源有两种：自动部署给的是明文（env / secrets.json），
    第一次访问设的是哈希（petd/data/admin.json）。两者都只用哈希值
    派生签名密钥 —— 明文口令不留在内存里太久。
    """

    # 试错限流：连错这么多次就先歇一会儿
    MAX_FAILS = 5
    LOCK_SECONDS = 30

    def __init__(self):
        self.mode = config_mod.admin_auth_mode()
        self.key = self._derive()
        self._fails = 0
        self._locked_until = 0.0

    def _material(self):
        digest = config_mod.admin_password_hash()
        if digest:
            return "hash:" + digest
        plain = config_mod.admin_password()
        return "plain:" + plain if plain else ""

    def _derive(self):
        material = self._material()
        return _derive_key(material) if material else None

    def reload(self):
        """设完口令后重新算 —— 签名密钥变了。"""
        self.mode = config_mod.admin_auth_mode()
        self.key = self._derive()

    def needs_setup(self):
        """还没设口令 —— 后台锁着，等用户来设。"""
        return self.mode == "none"

    def required(self):
        """要不要登录。"""
        return self.mode == "set"

    def open(self):
        """完全敞开。"""
        return self.mode == "disabled"

    def authed(self, request):
        if self.open():
            return True
        if self.key is None:
            return False
        return _token_ok(self.key, request.cookies.get(AUTH_COOKIE))

    def rate_limited(self):
        return self._locked_until > time.time()

    def note_failure(self):
        self._fails += 1
        if self._fails >= self.MAX_FAILS:
            self._locked_until = time.time() + self.LOCK_SECONDS
            self._fails = 0

    def note_success(self):
        self._fails = 0
        self._locked_until = 0.0


def _sign(key, payload):
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _make_token(key):
    exp = str(int(time.time()) + AUTH_TTL)
    return "%s.%s" % (exp, _sign(key, exp))


def _token_ok(key, raw):
    if not raw or "." not in raw:
        return False
    exp, sig = raw.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(key, exp)):
        return False
    try:
        return int(exp) > time.time()
    except ValueError:
        return False


def _start_mdns(pet):
    """开 mDNS 广播。

    mDNS 是增强功能：起不来只记日志，petd 该跑还得跑 ——
    没有它设备还能用 IP 直连，只是用不了 petd.local。
    """
    cfg_mdns = pet.cfg.get("mdns", {}) or {}
    if not cfg_mdns.get("enabled", True):
        pet.log("info", "mDNS 已关闭（配置 mdns.enabled=false）")
        return
    hostname = str(cfg_mdns.get("hostname") or "petd.local")
    adv = MdnsAdvertiser(port=pet.listen_port, hostname=hostname)
    adv.start()   # 起不来只记日志，petd 照跑
    pet.mdns = adv


def _stop_mdns(pet):
    adv = pet.mdns
    pet.mdns = None
    if adv is not None:
        try:
            adv.stop()
        except Exception as exc:
            log.warning("停止 mDNS 失败: %s", exc)


def create_app(cfg=None, start_gateway=True, port=None):
    cfg = cfg or config_mod.load()
    cfg["_repo_root"] = str(REPO_ROOT)
    pet = PetApp(cfg)
    # 命令行 --port 只影响这次运行，不写回 cfg —— 否则配置文件会被改掉。
    # mDNS 要广播的是实际在听的端口。
    if port:
        pet.listen_port = int(port)

    # 后台鉴权。默认是「还没设口令」—— 第一次访问时让用户设一个。
    # 设了就是一把共享锁 —— 不是账号体系，没有注册/多用户。
    _auth = _Auth()

    def _guard(fn):
        async def wrapper(request):
            if not _auth.authed(request):
                return JSONResponse({"ok": False, "error": "unauthorized"},
                                    status_code=401)
            return await fn(request)
        return wrapper

    @contextlib.asynccontextmanager
    async def lifespan(app):
        gateway = None
        gateway_task = None
        if start_gateway:
            from .gateway import GatewayClient

            gateway = GatewayClient(cfg, on_sessions=pet.on_sessions)
            pet._gateway = gateway
            gateway_task = asyncio.create_task(gateway.run_forever())
        _start_mdns(pet)
        await pet.start(gateway)
        try:
            yield
        finally:
            await pet.stop()
            _stop_mdns(pet)
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
                pet.on_device_disconnected(session)
                await pet.devices.detach(session)

    async def admin_index(request):
        index = ADMIN_DIR / "index.html"
        if not index.exists():
            return HTMLResponse("<h1>petd admin</h1><p>后台页缺失</p>", status_code=404)
        return HTMLResponse(index.read_text(encoding="utf-8"))

    async def admin_redirect(request):
        """规范成 /admin/。

        后台页用相对路径加载资源，URL 必须以 / 结尾，
        否则浏览器会把 assets/app.js 解析成 /assets/app.js。
        """
        return RedirectResponse("/admin/", status_code=307)

    async def api_login(request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)
        if _auth.open():
            return JSONResponse({"ok": True, "authRequired": False,
                                 "authMode": "disabled"})
        if _auth.needs_setup():
            return JSONResponse({"ok": False, "error": "还没设口令"},
                                status_code=409)
        if _auth.rate_limited():
            return JSONResponse({"ok": False, "error": "试太多次了，稍后再试"},
                                status_code=429)
        given = str((body or {}).get("password") or "")
        if not config_mod.verify_admin_password(given):
            _auth.note_failure()
            return JSONResponse({"ok": False, "error": "口令不对"}, status_code=401)
        _auth.note_success()
        resp = JSONResponse({"ok": True, "authRequired": True,
                             "authMode": _auth.mode})
        resp.set_cookie(AUTH_COOKIE, _make_token(_auth.key), max_age=AUTH_TTL,
                        httponly=True, samesite="lax")
        return resp

    async def api_setup_password(request):
        """第一次访问时设口令。

        只有「还没设」时才能调 —— 已经设了的话，这条路必须锁死，
        否则任何人都能改掉别人的口令。
        """
        if _auth.open():
            return JSONResponse({"ok": True, "authRequired": False,
                                 "authMode": "disabled"})
        if not _auth.needs_setup():
            return JSONResponse({"ok": False, "error": "口令已经设过了"},
                                status_code=403)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)
        password = str((body or {}).get("password") or "")
        if not password:
            return JSONResponse({"ok": False, "error": "口令不能为空"},
                                status_code=400)
        try:
            config_mod.set_admin_password(password)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        _auth.reload()
        pet.log("info", "后台口令已设置")
        resp = JSONResponse({"ok": True, "authRequired": True,
                             "authMode": _auth.mode})
        resp.set_cookie(AUTH_COOKIE, _make_token(_auth.key), max_age=AUTH_TTL,
                        httponly=True, samesite="lax")
        return resp

    async def api_session(request):
        return JSONResponse({"authRequired": _auth.required(),
                             "authMode": _auth.mode,
                             "authed": _auth.authed(request)})

    async def api_logout(request):
        """登出 —— 清掉 cookie。前端拿到 200 就回到口令页。"""
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(AUTH_COOKIE)
        return resp

    async def api_setup_public(request):
        """没登录也能看的那部分引导 —— 只含设备地址和配网说明。

        设备编号、会话数、帧数不在这里：那是登录之后才该知道的东西。
        """
        return JSONResponse(pet.setup_public_payload())

    async def api_preview(request):
        if not pet.last_jpeg:
            return Response(b"", media_type="image/jpeg", status_code=404)
        return Response(pet.last_jpeg, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    async def api_status(request):
        return JSONResponse(pet.snapshot())

    async def api_setup(request):
        """首次使用指引 —— 字段是前后端契约，别改名字。"""
        return JSONResponse(pet.setup_payload())

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

    async def api_sessions(request):
        """会话列表 —— 宠物反应全部会话，这里看得到每一条。"""
        return JSONResponse({"items": pet.public_sessions()})

    async def api_features_get(request):
        """功能清单 —— 每一项都对应一个真的能改的设置。"""
        return JSONResponse({"items": pet.settings_payload()})

    async def api_features_post(request):
        """改一项设置。改完立刻生效，也写进配置。"""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)
        fid = str(body.get("id") or "").strip()
        value = body.get("value")
        try:
            if fid == "features":
                names = value if isinstance(value, list) else [value]
                pet.set_features(names)
            elif fid == "dwell":
                pet.set_card_dwell(int(value))
            elif fid == "hold":
                pet.set_message_hold(int(value))
            elif fid == "sleepStart":
                pet.set_sleep_window(str(value), pet.sleep_end)
            elif fid == "sleepEnd":
                pet.set_sleep_window(pet.sleep_start, str(value))
            elif fid == "density":
                await pet.set_density(int(value))
            elif fid == "skin":
                await pet.set_skin(str(value))
            elif fid == "session":
                pet.set_session(str(value or ""))
            else:
                return JSONResponse({"ok": False, "error": "未知项：%s" % fid},
                                    status_code=400)
        except (TypeError, ValueError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return JSONResponse({"ok": True, "items": pet.settings_payload()})

    async def api_skins_get(request):
        root = pet.cfg.get("_repo_root", ".")
        return JSONResponse({"items": skins_mod.list_skin_info(root),
                             "current": pet.skin})

    async def api_skins_post(request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)
        op = str(body.get("op") or "")
        name = str(body.get("name") or "").strip()
        root = pet.cfg.get("_repo_root", ".")
        try:
            if op == "create":
                skins_mod.create_skin(root, name)
                pet.log("info", "新建形象 %s" % name)
            elif op == "delete":
                skins_mod.delete_skin(root, name)
                pet.log("info", "删除形象 %s" % name)
            elif op == "activate":
                await pet.set_skin(name)
            else:
                return JSONResponse({"ok": False, "error": "未知操作"},
                                    status_code=400)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return JSONResponse({"ok": True, "items": skins_mod.list_skin_info(root),
                             "current": pet.skin})

    async def api_skin_frame_post(request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)
        name = str(body.get("name") or "").strip()
        state = str(body.get("state") or "").strip()
        try:
            index = int(body.get("index", 0))
        except Exception:
            index = 0
        try:
            png = base64.b64decode(str(body.get("data") or ""))
        except Exception:
            return JSONResponse({"ok": False, "error": "图片数据不是 base64"},
                                status_code=400)
        root = pet.cfg.get("_repo_root", ".")
        try:
            path = skins_mod.save_frame(root, name, state, index, png)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        pet.log("info", "形象素材已保存 %s" % path.name)
        return JSONResponse({"ok": True, "items": skins_mod.list_skin_info(root),
                             "current": pet.skin})

    async def api_logs(request):
        since = int(request.query_params.get("since", 0))
        items = [e for e in pet.logs if e["seq"] > since]
        return JSONResponse({"items": items, "seq": pet._log_seq})

    async def api_events(request):
        async def gen():
            last = pet._log_seq
            while True:
                # 客户端断开就收尾。不查断连的话，这个长连接会一直挂着，
                # uvicorn 优雅关闭会干等，systemctl restart 卡在 stop-sigterm。
                if await request.is_disconnected():
                    break
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
        Route("/admin", admin_redirect),
        Route("/admin/", admin_index),
        Route("/admin/api/login", api_login, methods=["POST"]),
        Route("/admin/api/setup/password", api_setup_password, methods=["POST"]),
        Route("/admin/api/logout", api_logout, methods=["POST"]),
        Route("/admin/api/session", api_session),
        Route("/admin/api/setup/public", api_setup_public),
        Route("/admin/api/preview.jpg", _guard(api_preview)),
        Route("/admin/api/status", _guard(api_status)),
        Route("/admin/api/setup", _guard(api_setup)),
        Route("/admin/api/config", _guard(api_config_get), methods=["GET"]),
        Route("/admin/api/config", _guard(api_config_post), methods=["POST"]),
        Route("/admin/api/logs", _guard(api_logs)),
        Route("/admin/api/sessions", _guard(api_sessions)),
        Route("/admin/api/features", _guard(api_features_get), methods=["GET"]),
        Route("/admin/api/features", _guard(api_features_post), methods=["POST"]),
        Route("/admin/api/skins", _guard(api_skins_get), methods=["GET"]),
        Route("/admin/api/skins", _guard(api_skins_post), methods=["POST"]),
        Route("/admin/api/skins/frame", _guard(api_skin_frame_post), methods=["POST"]),
        Route("/admin/api/events", _guard(api_events)),
        Route("/admin/api/releases", _guard(api_releases)),
        Route("/admin/api/ota", _guard(api_ota), methods=["POST"]),
        Route("/admin/api/firmware", _guard(api_firmware_list)),
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
