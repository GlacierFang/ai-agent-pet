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

# 支持游戏包的最低固件版本。
# 0.5.0 在 WS 回调里装包会撑爆 4KB 的回调栈 —— 设备 panic 重启，
# 重启后报「本地没装这些包」，后台再推一遍，于是永远重启。
# 所以低于这个版本一律不下发游戏包。
MIN_PACK_FW = (0, 5, 1)


def fw_tuple(fw):
    """把 '0.5.1' 拆成 (0, 5, 1)。认不出的段当 0。"""
    out = []
    for part in str(fw or "").split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


def fw_supports_packs(fw):
    """这个固件版本能不能收游戏包。"""
    return fw_tuple(fw) >= MIN_PACK_FW


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
        # 设备当前在哪个模式：idle / menu / playing。
        # 设备在游戏里时服务端停推帧 —— 抢屏。
        self.mode = str(info.get("mode") or "idle")
        # OTA 状态 —— 设备 hello 里带一份，之后按 otaStatus 消息更新。
        ota = info.get("ota") or {}
        self.ota_state = str(ota.get("state") or "idle")
        self.ota_version = str(ota.get("version") or "")
        self.ota_percent = int(ota.get("percent") or 0)
        self.ota_error = ""
        # 「预告 + 本体」成对发，中途不能被别的 binary 插进来。
        self._tx_lock = asyncio.Lock()

    async def send_json(self, obj):
        await self.ws.send_text(json.dumps(obj, ensure_ascii=False))

    async def send_pack(self, pack_id, version, raw):
        """下发一个游戏包 —— 文本预告 + binary 本体。

        本体走 binary：设备要把它原样写进 SPIFFS，不用在设备上把 JSON
        重新序列化一遍（那条路会走 newlib 的浮点 printf，几百字节栈）。

        两条消息必须挨着发 —— 设备靠预告知道「下一条 binary 是 pack」，
        中间夹一条别的 binary 就会串包。所以和推帧共用一把锁。
        """
        async with self._tx_lock:
            await self.send_json({"type": "pack", "id": pack_id,
                                  "version": version, "bytes": len(raw)})
            await self.ws.send_bytes(raw)
        return True

    async def send_ota_start(self, version, size):
        """告诉设备「要装这个固件了，一共这么多字节」。

        之后才是一片一条 otaChunk 预告 + binary 本体。
        """
        async with self._tx_lock:
            await self.send_json({"type": "otaStart", "version": version,
                                  "bytes": int(size)})
        return True

    async def send_ota_chunk(self, seq, data):
        """下发一片固件 —— 文本预告 + binary 本体。

        跟 pack 一样，两条必须挨着发：设备靠预告知道「下一条 binary
        是这一片」。中间夹一条别的 binary 就会把错的字节写进 flash。
        """
        async with self._tx_lock:
            await self.send_json({"type": "otaChunk", "seq": int(seq),
                                  "bytes": len(data)})
            await self.ws.send_bytes(data)
        return True

    async def send_ota_finish(self):
        """全部发完了 —— 设备校验、切分区、重启。"""
        async with self._tx_lock:
            await self.send_json({"type": "otaFinish"})
        return True

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
        async with self._tx_lock:
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
            "mode": s.mode,
            "otaState": s.ota_state,
            "otaVersion": s.ota_version,
            "otaPercent": s.ota_percent,
            "otaError": s.ota_error,
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

    async def send_pack(self, pack_id, version, raw):
        """下发一个游戏包。没有设备就什么都不做。"""
        if not self.session:
            return False
        try:
            await self.session.send_pack(pack_id, version, raw)
            return True
        except Exception:
            return False

    async def send_ota_start(self, version, size):
        """告诉设备要装新固件了。没有设备就什么都不做。"""
        if not self.session:
            return False
        try:
            await self.session.send_ota_start(version, size)
            return True
        except Exception:
            return False

    async def send_ota_chunk(self, seq, data):
        """下发一片固件。"""
        if not self.session:
            return False
        try:
            await self.session.send_ota_chunk(seq, data)
            return True
        except Exception:
            return False

    async def send_ota_finish(self):
        """全部发完了 —— 设备该校验切换重启了。"""
        if not self.session:
            return False
        try:
            await self.session.send_ota_finish()
            return True
        except Exception:
            return False
