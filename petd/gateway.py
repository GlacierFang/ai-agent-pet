"""petd ↔ OpenClaw gateway 客户端。

只读：operator.read scope，client.id=gateway-client + client.mode=backend。
实测配方见 memory/projects/ai-agent-pet.md §4.3b（2026-11-03）。

传输层只有一个 reader 任务在收包：
- ``res`` 按 id 派发到各自的 future
- ``event`` 进队列，由另一个任务串行处理

早先的写法是在 ``_call`` 里直接 ``recv()``，收到 event 就顺手处理，
而 event handler 内部又会调 ``_call``（sessions.list）—— 内层 recv 会把
外层等的那条 res 吃掉，外层只能超时，于是日志里刷出一串
"sessions.list 失败: sessions.list"。
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
        self._stop = False
        self._req_id = 0
        self._pending = {}
        self.last_error = ""
        self._events = None
        self._reader_task = None
        self._event_task = None
        self._refreshing = False
        self._refresh_again = False

    def _next_id(self):
        self._req_id += 1
        return "p%d" % self._req_id

    async def _call(self, method, params=None, timeout=15):
        """发 req、等它的 res。

        收包只由 reader 任务做，这里只等自己的 future ——
        不再自己 recv，所以 event handler 里嵌套调 _call 也不会抢消息。
        """
        rid = self._next_id()
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self.ws.send(json.dumps(
                {"type": "req", "id": rid, "method": method, "params": params or {}}))
            data = await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(rid, None)
        if not data.get("ok"):
            raise RuntimeError("%s failed: %s" % (method, data.get("error")))
        return data.get("payload") or {}

    # ---------- 传输层 ----------
    async def _reader_loop(self):
        """唯一的收包循环。连接断开时把异常抛给上层去重连。"""
        while not self._stop:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), 60)
            except asyncio.TimeoutError:
                await self.ws.ping()
                continue
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                continue
            kind = data.get("type")
            if kind == "res":
                fut = self._pending.get(data.get("id"))
                if fut is not None and not fut.done():
                    fut.set_result(data)
            elif kind == "event":
                self._events.put_nowait(data)

    async def _event_loop(self):
        """串行处理 event。处理期间可以发新 req —— reader 还在跑，不会死锁。"""
        while not self._stop:
            data = await self._events.get()
            try:
                await self._handle_event(data)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("event 处理失败")

    async def _handle_event(self, data):
        if self.on_event:
            try:
                await self.on_event(data)
            except Exception:
                log.exception("on_event  failed")
        name = data.get("event")
        if name in ("sessions.changed", "session.message", "session.tool", "chat", "socket.drain"):
            await self.refresh_sessions()

    def _fail_pending(self):
        """连接断了，把还在等的 future 立刻了结，别让调用方干等到超时。"""
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(ConnectionError("gateway 连接断开"))
        self._pending.clear()

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
            self._events = asyncio.Queue()
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
            deadline = asyncio.get_running_loop().time() + 15
            while asyncio.get_running_loop().time() < deadline:
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

            # 从这里起所有收包都归 reader
            self._reader_task = asyncio.create_task(self._reader_loop())
            self._event_task = asyncio.create_task(self._event_loop())

            try:
                sub = await self._call("sessions.subscribe",
                                       {"limit": g.get("subscribeLimit", 30), "ownerFirst": True})
                if self.on_sessions:
                    await self.on_sessions(self._rows(sub))
                log.info("sessions.subscribe 完成")

                await self._reader_task
            finally:
                self.connected = False
                self._fail_pending()
                for t in (self._event_task, self._reader_task):
                    if t and not t.done():
                        t.cancel()
            if self._stop:
                return
            raise RuntimeError("gateway 连接断开")

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
        if self._refreshing:
            # 事件成串来的时候合并，别把 gateway 刷爆
            self._refresh_again = True
            return
        self._refreshing = True
        try:
            while True:
                self._refresh_again = False
                try:
                    payload = await self._call("sessions.list", {"limit": 50})
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("sessions.list 失败: %s", exc)
                    self.last_error = str(exc)
                    break
                rows = self._rows(payload)
                if self.on_sessions:
                    await self.on_sessions(rows)
                if self.connected:
                    self.last_error = ""
                if not self._refresh_again:
                    break
        finally:
            self._refreshing = False

    async def run_forever(self):
        backoff = 1
        while not self._stop:
            try:
                await self.connect()
                backoff = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                self.last_error = str(exc)
                log.warning("gateway 连接失败(%s)，%ss 后重试", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def stop(self):
        self._stop = True
        for t in (self._event_task, self._reader_task):
            if t and not t.done():
                t.cancel()
