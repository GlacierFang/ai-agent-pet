"""设备会话管理。

v1 单设备：一个 petd 对一台屏。
设备连上来 → 握手 → 下发 welcome → 推当前帧。
旋钮事件在这里收，转成语义动作后交给 app。
"""
import asyncio
import json
import logging
import time

from .render import MAX_FRAME_BYTES

log = logging.getLogger("petd.device")


class DeviceSession:
    def __init__(self, ws, info):
        self.ws = ws
        self.info = info
        self.connected_at = time.time()
        self.last_seen = time.time()
        self.inflight = 0
        self.pending = {}          # id -> 帧元信息
        self.density = 1
        self.state = "idle"
        self.frame_count = 0
        self.last_frame_ms = 0
        self.decode_ms = 0
        self.rssi = 0
        self.fw = info.get("fw", "")
        self.device_id = info.get("deviceId", "")
        # 下一版固件会上报：设备自己的 IP + 是否已配网。
        # 旧固件不上报就保持默认值，不影响现有流程。
        self.ip = str(info.get("ip", "") or "")
        self.provisioned = bool(info.get("provisioned", False))

    async def send_json(self, obj):
        await self.ws.send_text(json.dumps(obj, ensure_ascii=False))

    async def send_frame(self, jpeg, frame_id, mime="image/jpeg"):
        """文本预告 + binary，紧挨着发。"""
        if len(jpeg) > MAX_FRAME_BYTES:
            # 设备缓冲区装不下这一帧。发了它会被丢掉，而且设备不会回 ACK ——
            # 服务端的 inflight 就永远减不回来，之后再也不推帧。
            # 宁可不发，也不能让整条链路卡死。
            log.warning("帧过大(%d > %d)，已丢弃 id=%s",
                        len(jpeg), MAX_FRAME_BYTES, frame_id)
            return False
        if self.inflight >= 2:
            return False
        await self.send_json({"type": "frame", "id": frame_id,
                              "bytes": len(jpeg), "mime": mime})
        await self.ws.send_bytes(jpeg)
        self.inflight += 1
        self.pending[frame_id] = len(jpeg)
        self.frame_count += 1
        return True

    async def ack(self, frame_id):
        self.inflight = max(0, self.inflight - 1)
        self.pending.pop(frame_id, None)

    async def close(self):
        try:
            await self.ws.close()
        except Exception:
            pass


class DeviceManager:
    def __init__(self):
        self.session = None

    @property
    def online(self):
        return self.session is not None

    def status(self):
        s = self.session
        if not s:
            return {"online": False}
        return {
            "online": True,
            "deviceId": s.device_id,
            "fw": s.fw,
            "connectedAt": int(s.connected_at),
            "uptime": int(time.time() - s.connected_at),
            "density": s.density,
            "state": s.state,
            "frames": s.frame_count,
            "inflight": s.inflight,
            "lastFrameMs": s.last_frame_ms,
            "decodeMs": s.decode_ms,
            "rssi": s.rssi,
            "ip": s.ip,
            "provisioned": s.provisioned,
        }

    async def attach(self, ws, info):
        if self.session:
            await self.session.close()
        self.session = DeviceSession(ws, info)
        log.info("设备接入: %s fw=%s", info.get("deviceId"), info.get("fw"))
        return self.session

    async def detach(self, session):
        if self.session is session:
            self.session = None
            log.info("设备断开")

    async def push_frame(self, jpeg, frame_id):
        if not self.session:
            return False
        try:
            return await self.session.send_frame(jpeg, frame_id)
        except Exception as exc:
            log.warning("推帧失败: %s", exc)
            await self.detach(self.session)
            return False

    async def send_json(self, obj):
        if not self.session:
            return False
        try:
            await self.session.send_json(obj)
            return True
        except Exception:
            return False

    async def ack(self, frame_id):
        """设备回了一帧的 ACK —— inflight 减一。

        挂在 manager 上，不让 app 直接摸 session：
        app 手上一直只有 manager，session 会随重连换掉。
        """
        s = self.session
        if s is None:
            return False
        await s.ack(frame_id)
        return True
