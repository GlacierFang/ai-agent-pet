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
        # OTA 确认：设备每写完一片就报一次 otaStatus（带 seq）。
        # 服务端靠这个确认来控速 —— 不等确认就往下推，设备的 WS 收包
        # 队列会被顶爆，连接直接断在半路（真机表现：「下发中断在第 16 片」，
        # 而且每次断的片数都不一样）。
        self.ota_ack_seen = set()      # 已确认的 seq
        self.ota_ack = asyncio.Event()
        self.ota_round = 0             # 这一轮 OTA 的编号（服务端下发）
        self.ota_closed = False        # 设备断开了
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

    async def send_ota_start(self, version, size, round=None):
        """告诉设备「要装这个固件了，一共这么多字节」。

        之后才是一片一条 otaChunk 预告 + binary 本体。
        round 是这一轮的编号 —— 设备会回在 otaStatus 里，
        用来分辨「这一轮的确认」和「上一轮迟到的确认」。
        """
        async with self._tx_lock:
            msg = {"type": "otaStart", "version": version,
                   "bytes": int(size)}
            if round is not None:
                msg["round"] = int(round)
            await self.send_json(msg)
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

    def note_ota_ack(self, seq, round=None):
        """设备确认收到第 seq 片。

        round 是这一轮的编号 —— 上一轮 OTA 迟到的确认（seq 更大）落进
        新一轮时，会把中间的空缺填上，看起来像连续，镜像就写坏了。
        对不上轮次的确认直接丢掉。
        """
        if round is not None and round != self.ota_round:
            return
        self.ota_ack_seen.add(int(seq))
        self.ota_ack.set()

    def reset_ota_ack(self, round=None):
        """新一轮下发 —— 确认从头来。"""
        self.ota_ack_seen = set()
        self.ota_ack.clear()
        if round is not None:
            self.ota_round = int(round)

    def note_closed(self):
        """设备断开了 —— 别再等确认。"""
        self.ota_closed = True
        self.ota_ack.set()

    def ota_ack_ready(self, seq):
        """第 seq 片是不是已经确认齐了。

        要 0..seq **连续**都确认过才算数 —— 只看「最大 seq」不够：
        上一轮迟到的确认会填掉中间的空缺。
        """
        if self.ota_closed:
            return False
        return all(i in self.ota_ack_seen for i in range(seq + 1))

    async def wait_ota_ack(self, seq, timeout):
        """等设备确认收到第 seq 片。

        True = 确认了；False = 超时（设备断了，或者根本没回）。
        """
        deadline = time.monotonic() + timeout
        while True:
            if self.ota_ack_ready(seq):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self.ota_ack.clear()
            # clear 之后再查一遍 —— 确认可能正好落在检查和 clear 之间。
            if self.ota_ack_ready(seq):
                return True
            try:
                await asyncio.wait_for(self.ota_ack.wait(), remaining)
            except asyncio.TimeoutError:
                return False

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
            session.note_closed()
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

    async def send_ota_start(self, version, size, round=None):
        """告诉设备要装新固件了。没有设备就什么都不做。"""
        if not self.session:
            return False
        try:
            await self.session.send_ota_start(version, size, round)
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

    async def wait_ota_ack(self, seq, timeout):
        """等设备确认收到第 seq 片。"""
        if not self.session:
            return False
        return await self.session.wait_ota_ack(seq, timeout)

    def note_ota_ack(self, seq, round=None):
        """设备确认收到第 seq 片。"""
        if self.session:
            self.session.note_ota_ack(seq, round)

    async def reset_ota_ack(self, round=None):
        """开始新的一轮下发 —— 清掉上一轮的确认计数。"""
        if self.session:
            self.session.reset_ota_ack(round)

    def next_ota_round(self):
        """给这一轮 OTA 分配一个编号。"""
        self._ota_round = getattr(self, "_ota_round", 0) + 1
        return self._ota_round
