"""petd ↔ OpenClaw gateway 客户端。

只读：operator.read scope，client.id=gateway-client + client.mode=backend。
实测配方见 memory/projects/ai-agent-pet.md §4.3b（2026-11-03）。
"""
import asyncio
import json
import logging

import websockets

log = logging.getLogger("petd.gateway")


class GatewayClient:
    def __init__(self, cfg, on_sessions=None, on_event=None):
        self.cfg = cfg
        self.on_sessions = on_sessions
        self.on_event = on_event
        self.ws = None
        self.connected = False
        self._task = None
        self._stop = False
        self._req_id = 0
        self._pending = {}
        self.last_error = ""

    def _next_id(self):
        self._req_id += 1
        return "p%d" % self._req_id

    async def _call(self, method, params=None, timeout=15):
        rid = self._next_id()
        msg = {"type": "req", "id": rid, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(msg))
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=max(0.1, deadline - asyncio.get_event_loop().time()))
            data = json.loads(raw)
            if data.get("type") == "res" and data.get("id") == rid:
                if not data.get("ok"):
                    raise RuntimeError("%s failed: %s" % (method, data.get("error")))
                return data.get("payload") or {}
            if data.get("type") == "event":
                await self._handle_event(data)
        raise TimeoutError(method)

    async def _handle_event(self, data):
        if self.on_event:
            try:
                await self.on_event(data)
            except Exception:
                log.exception("on_event 失败")
        name = data.get("event")
        if name in ("sessions.changed", "session.message", "session.tool", "chat", "socket.drain"):
            await self.refresh_sessions()

    async def connect(self):
        g = self.cfg["gateway"]
        url = g.get("url") or "ws://127.0.0.1:18789"
        token = g.get("token") or ""
        # 本机 gateway 必须绕过 egress proxy：
        # 环境里全局设了 HTTP(S)_PROXY，websockets 默认 proxy=True 会把
        # 连 127.0.0.1 的请求也塞进代理 → 403。
        use_proxy = bool(g.get("useProxy", False))
        async with websockets.connect(url, max_size=32 * 1024 * 1024,
                                     proxy=url if use_proxy else None) as ws:
            self.ws = ws
            # gateway 先发 connect.challenge，先收掉
            try:
                await asyncio.wait_for(ws.recv(), 10)
            except asyncio.TimeoutError:
                pass
            params = {
                "minProtocol": 4,
                "maxProtocol": 4,
                "client": {
                    "id": g.get("clientId", "gateway-client"),
                    "version": "0.1.0",
                    "platform": "linux",
                    "mode": g.get("clientMode", "backend"),
                    "displayName": "petd",
                },
                "role": g.get("role", "operator"),
                "scopes": g.get("scopes", ["operator.read"]),
                "auth": {"token": token},
                "locale": "zh-CN",
                "userAgent": "petd/0.1.0",
            }
            await ws.send(json.dumps({"type": "req", "id": self._next_id(),
                                     "method": "connect", "params": params}))
            # 等 hello-ok
            deadline = asyncio.get_event_loop().time() + 15
            while asyncio.get_event_loop().time() < deadline:
                raw = await asyncio.wait_for(ws.recv(), 15)
                data = json.loads(raw)
                if data.get("type") == "res":
                    if not data.get("ok"):
                        raise RuntimeError("connect 被拒: %s" % data.get("error"))
                    self.connected = True
                    log.info("gateway 已连接，scope=%s",
                             (data.get("payload") or {}).get("auth", {}).get("scopes"))
                    break
            else:
                raise TimeoutError("hello-ok 超时")

            sub = await self._call("sessions.subscribe",
                                   {"limit": g.get("subscribeLimit", 30), "ownerFirst": True})
            if self.on_sessions:
                await self.on_sessions(self._rows(sub))
            log.info("sessions.subscribe 完成")

            # 事件循环
            while not self._stop:
                try:
                    raw = await asyncio.wait_for(ws.recv(), 60)
                except asyncio.TimeoutError:
                    await ws.ping()
                    continue
                data = json.loads(raw)
                if data.get("type") == "event":
                    await self._handle_event(data)

    @staticmethod
    def _rows(payload):
        if not payload:
            return []
        for key in ("sessions", "items", "list"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return []

    async def refresh_sessions(self):
        if not self.ws:
            return
        try:
            payload = await self._call("sessions.list", {"limit": 50})
        except Exception as exc:
            log.warning("sessions.list 失败: %s", exc)
            self.last_error = str(exc)
            return
        rows = self._rows(payload)
        if self.on_sessions:
            await self.on_sessions(rows)

    async def run_forever(self):
        backoff = 1
        while not self._stop:
            try:
                await self.connect()
                backoff = 1
            except Exception as exc:
                self.connected = False
                self.last_error = str(exc)
                log.warning("gateway 连接失败(%s)，%ss 后重试", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def stop(self):
        self._stop = True
