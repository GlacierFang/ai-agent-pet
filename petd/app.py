"""petd 主控：状态 → 渲染 → 推帧。

渲染循环按状态限帧：idle 1fps，working/waiting/error 10fps。

屏上仲裁在 petd/screen.py，这里只负责给它数据。
"""
import asyncio
import json
import logging
import threading
import time
from collections import deque

from . import chatter as chatter_mod
from . import confirm as confirm_mod
from . import config as config_mod
from . import album as album_mod
from . import features as feature_mod
from . import backgrounds as bg_mod
from . import gestures as gestures_mod
from . import ota as ota_mod
from .mdns import local_ipv4_addresses
from . import packs as packs_mod
from . import render as render_mod
from . import screen as screen_mod
from . import settings as settings_mod
from . import skins as skins_mod
from . import state as state_mod
from . import toys as toys_mod
from .device import DeviceManager, fw_supports_packs
from .state import DEFAULT_RULES, StateEngine, epoch_s

log = logging.getLogger("petd.app")

ACTIVE_STATES = ("working", "waiting", "error", "done")

# 通道名 → 人话。gateway 推的 channel 是英文标识，后台给人看要中文。
# 没登记的通道直接用原名 —— 不猜。
CHANNEL_LABELS = {
    "feishu": "飞书",
}

# 逐个推游戏包之间的间隔（秒）。
# 设备收包的队列只有 2 深，连着推会挤爆 —— 挤不进去的被丢掉，
# 设备留着旧包，服务端却看不出任何异常。
PACK_PUSH_GAP = 0.5

# 「设备连过没有」这类跨重启的事实要落在盘上，否则重启一次后台就退回未开始。
# 放 data/ 下 —— 那里已经在 systemd unit 的 ReadWritePaths 里。
#
# 路径在**调用时**取 DATA_DIR，不在 import 时绑死：
# 模块级常量会绕过 conftest 的隔离，测试里的假设备号会写进实机那份文件。
def _setup_state_path():
    return config_mod.DATA_DIR / "setup_state.json"

STATE_SUBTITLE = {
    "idle": "", "working": "正在处理", "waiting": "等你确认",
    "done": "已完成", "error": "出错了", "sleeping": "zZ",
}

# 天气这类要联网的 feature 在后台取数，间隔这么久一次
POLL_INTERVAL_SEC = 900


class PetApp:
    def __init__(self, cfg):
        self.cfg = cfg
        self.rules = self._load_rules()
        self.engine = StateEngine(self.rules)
        self.devices = DeviceManager()
        self.gestures = gestures_mod.load()
        # 逐包推送的间隔（秒）—— 见 _push_packs 的说明。
        self.pack_push_gap = PACK_PUSH_GAP
        self.density = int(cfg.get("ui", {}).get("density", 1))
        # 屏幕亮度 —— 透射式 TFT 的背光常亮，软件只能压内容。
        # "auto" 跟着睡觉时段走，固定档位则一直生效。
        self.brightness = str(cfg.get("ui", {}).get("brightness") or "auto")
        self.skin = cfg.get("ui", {}).get("skin", "default")
        # 背景 —— 和宠物形象解耦。换宠物不动背景，换背景不动宠物。
        self.background = str(cfg.get("ui", {}).get("background") or "default")
        # 卡片背景 —— 内容卡和骰子的底。跟宠物背景是分开的两套：
        # 换一边不动另一边。空 = 用卡片自己的深色渐变。
        self.card_background = str(cfg.get("ui", {}).get("cardBackground") or "")
        # 空闲时参与轮播的 feature。
        # 老配置里没有新功能的名字 —— 直接 normalize 会把它们悄悄关掉
        # （骰子会直接失灵）。所以配置里记着「用户看过第几版」，
        # 升上来时把这版新增的补上，补完记下版本。
        ui_cfg = cfg.setdefault("ui", {})
        self.features_enabled, fver = feature_mod.reconcile(
            ui_cfg.get("features"), ui_cfg.get("featuresVersion"))
        self._features_dirty = int(ui_cfg.get("featuresVersion") or 0) != fver
        if self._features_dirty:
            ui_cfg["featuresVersion"] = fver
            ui_cfg["features"] = sorted(self.features_enabled)
        self.card_dwell_sec = int(cfg.get("ui", {}).get("cardDwellSec", 8))
        self.message_hold_sec = int(cfg.get("ui", {}).get("messageHoldSec", 3))
        # 屏保 —— 忙多久之后上相册轮播。0 = 关掉。
        self.screensaver_after_sec = int(cfg.get("ui", {}).get(
            "screensaverAfterSec", 60))
        # 屏保期间多久换一张照片。
        self.screensaver_dwell_sec = int(cfg.get("ui", {}).get(
            "screensaverDwellSec", 15))
        self.sleep_start = str(cfg.get("ui", {}).get(
            "sleepStart", config_mod.DEFAULT_SLEEP_START))
        self.sleep_end = str(cfg.get("ui", {}).get(
            "sleepEnd", config_mod.DEFAULT_SLEEP_END))
        self.sleep_enabled = bool(cfg.get("ui", {}).get("sleepEnabled", True))
        # 后台选定的关注会话（空 = 自动跟最活跃的）
        self.engine.selected_key = cfg.get("ui", {}).get("session") or None
        self.frame_seq = 0
        self.last_jpeg = None
        self.last_jpeg_ts = 0
        self.logs = deque(maxlen=300)
        self._log_seq = 0
        self._stop = False
        self._task = None
        self._poll_thread = None
        # 后台取数线程的唤醒 / 退出信号
        self._poll_event = threading.Event()
        self._gateway = None
        self._picked = None
        # 确认卡 —— 开发中的选择题回到屏上。答案注回发起方会话。
        self.confirm = confirm_mod.ConfirmManager(on_answer=self._on_confirm_answer)
        # 待回程的答案。回调是同步的，发消息是异步的 —— 中间隔一个队列。
        self._confirm_outbox = []
        # 屏上仲裁：宠物形象 ↔ feature 卡片
        self.director = screen_mod.ScreenDirector(self.rules)
        self.chatter = chatter_mod.Chatter()
        # 屏上的玩具 —— 骰子（一次性覆盖层）和功德计数器。
        # 它们不是宠物状态，不进六态语义表；状态机一个字节都没动。
        self.merit = toys_mod.Merit(cfg.get("ui", {}).get("merit", 0))
        # 游戏 —— 跑在设备上。启用哪些 pack 存在 ui.games。
        # 短按进游戏菜单是设备本地接管的事，这里只管「哪些游戏开着」。
        # 没配过（None）= 全部可用；配了空列表 = 全关。
        raw_games = cfg.get("ui", {}).get("games")
        self.games_enabled = packs_mod.normalize(
            raw_games if raw_games is not None else packs_mod.known_ids())
        # 相册 —— 用户传的照片。照片列表读一次就够，
        # 用户增删时再 reload（见 reload_album）。
        self.album = feature_mod.get("album")
        if self.album is not None:
            self.album.reload()
        self.mdns = None          # server 生命周期里塞进来的 MdnsAdvertiser
        # 实际在听的端口。命令行 --port 会盖过配置，但不该被写回配置文件 ——
        # 那是「这次跑在哪个端口」，不是「以后都跑哪个端口」。
        self.listen_port = int((cfg.get("server", {}) or {}).get("port", 18860))
        self._sync_director()
        # 老配置升上来补了新功能 —— 落盘，记下「用户看过第几版」。
        # 用户之后自己勾掉，就不会再被加回来。
        if self._features_dirty:
            self._persist_config()

    @staticmethod
    def _load_rules():
        import pathlib
        p = pathlib.Path(__file__).resolve().parent / "data" / "state_rules.json"
        if p.exists():
            try:
                blob = json.loads(p.read_text(encoding="utf-8"))
                out = dict(DEFAULT_RULES)
                out.update(blob)
                return out
            except Exception:
                pass
        return DEFAULT_RULES

    def _sync_director(self):
        """设置改了，仲裁参数跟着改。"""
        self.director.message_hold_ms = self.message_hold_sec * 1000
        self.director.content_dwell_ms = self.card_dwell_sec * 1000
        self.director.screensaver_after_ms = self.screensaver_after_sec * 1000
        self.director.screensaver_dwell_ms = self.screensaver_dwell_sec * 1000

    def log(self, level, msg):
        self._log_seq += 1
        entry = {"seq": self._log_seq, "ts": time.time(), "level": level, "msg": msg}
        self.logs.append(entry)
        log.log({"error": 40, "warn": 30, "info": 20}.get(level, 20), "%s", msg)
        return entry

    # ---------- gateway ----------
    async def on_sessions(self, rows):
        changed, state, picked = self.engine.update(rows)
        self._sync_confirm_focus()
        if changed:
            self.log("info", "状态 -> " + state)
            await self.push_state(state)
            if state == "done":
                # 干完一次活 —— 功德 +1。
                # 任何一次「变成 done」都算，包括 idle -> done：
                # 轮询可能没赶上干活那一帧，但活确实干完了。
                self._add_merit()
        return state

    def _add_merit(self):
        """功德 +1，并落盘 —— 数值得活过重启。"""
        self.merit.add()
        self.cfg.setdefault("ui", {})["merit"] = self.merit.value
        self._persist_config()
        self.log("info", "功德 +1 -> %d" % self.merit.value)

    async def push_state(self, state):
        s = self.devices.session
        if s is None:
            return
        s.state = state
        await self.devices.send_json({"type": "state", "state": state,
                                      "since": int(self.engine.since),
                                      "text": STATE_SUBTITLE.get(state, "")})

    # ---------- 设备 ----------
    async def on_device_connected(self):
        s = self.devices.session
        if s is None:
            return
        await self.devices.send_json({
            "type": "welcome", "protocol": 1, "session": s.device_id,
            "server": "petd/0.1.0",
            "render": {"width": self.cfg.get("render", {}).get("width", 240),
                       "height": self.cfg.get("render", {}).get("height", 320),
                       "jpegQuality": self.cfg.get("render", {}).get("quality", 85),
                       "subsampling": self.cfg.get("render", {}).get("subsampling", 2),
                       "colorFormat": "rgb565"},
            "density": {"levels": [0, 1, 2], "current": self.density},
            "gestures": {"longPressMs": self.gestures.get("longPressMs", 600),
                         "stepsPerAction": self.gestures.get("stepsPerAction", 4)},
            "frame": {"idleFps": self.cfg.get("frame", {}).get("idleFps", 1),
                      "activeFps": self.cfg.get("frame", {}).get("activeFps", 10)},
        })
        # 启用哪些游戏 —— 单独一条消息，不塞在 welcome 里。
        # welcome 是协议固定字段，塞进去老固件会多出一个没见过的键（无害，
        # 但协议文档要跟着改；单独一条更清楚，老固件直接忽略）。
        #
        # 固件太老就发空列表：老固件装不了游戏包（装了就重启），
        # 给它空列表，它会把本地包裁掉，也不会再要包。
        if fw_supports_packs(s.fw):
            enabled = sorted(self.games_enabled)
        else:
            enabled = []
            self.log("warn", "固件 %s 不支持游戏包，已关闭下发"
                     % (s.fw or "未知"))
        await self.devices.send_json({"type": "games", "enabled": enabled})
        # 已装的包也要重推一遍 —— 设备只按 ID 判重，不比对内容。
        # 服务端改了 pack（比如蛇的速度），设备本地那份还是旧的：
        # 刷了新固件也玩不到新版本。握手时推一遍，设备覆盖写盘。
        await self._push_packs(enabled)
        self.log("info", "设备握手完成: " + s.device_id)
        self._mark_device_seen(s)

    async def on_device_message(self, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            return
        t = msg.get("type")
        if t == "frameAck":
            await self.devices.ack(msg.get("id"))
        elif t == "status":
            s = self.devices.session
            if s:
                s.fw = msg.get("fw", s.fw)
                s.rssi = msg.get("rssi", 0)
                s.decode_ms = msg.get("decodeMs", 0)
                s.last_frame_ms = msg.get("lastFrameMs", 0)
                # ip / provisioned 是给下一版固件留的字段：固件还没上报就不动，
                # 旧固件的报文照样能收。
                if "ip" in msg:
                    s.ip = str(msg.get("ip") or "")
                if "provisioned" in msg:
                    s.provisioned = bool(msg.get("provisioned"))
        elif t == "input":
            # 设备旋钮原始事件先落一行日志 —— 「按了没反应」最怕的就是看不见事件。
            # rot_press 在确认卡在场时是静默忽略的，没这行就查不出它到底来过没有。
            self.log("info", "设备旋钮事件: %s" % json.dumps(msg, ensure_ascii=False))
            await self.on_knob(msg)
        elif t == "otaStatus":
            await self.on_ota_status(msg)
        elif t == "gameMode":
            s = self.devices.session
            if s:
                s.mode = str(msg.get("mode") or "idle")
                self.log("info", "设备模式 -> %s" % s.mode)
        elif t == "packAck":
            pid = str(msg.get("id") or "")
            ok = bool(msg.get("ok"))
            self.log("info" if ok else "error",
                     ("游戏包已安装: " if ok else "游戏包安装失败: ") + pid)
        elif t == "gameRequest":
            await self.send_pack(str(msg.get("id") or ""))
        elif t == "log":
            self.log(msg.get("level", "info"), "device: " + str(msg.get("msg", "")))
        elif t == "error":
            self.log("error", "device: " + str(msg.get("message", msg.get("code", ""))))

    # ---------- 游戏 ----------
    # ---------- OTA ----------

    async def on_ota_status(self, msg):
        """设备报了 OTA 进度 —— 记下来，后台能看见。"""
        s = self.devices.session
        if s is None:
            return
        # 每写完一片设备都会报一次（带 seq）—— 服务端靠它控速。
        seq = msg.get("seq")
        if isinstance(seq, int):
            rnd = msg.get("round")
            self.devices.note_ota_ack(seq, rnd if isinstance(rnd, int) else None)
        state = str(msg.get("state") or "idle")
        s.ota_state = state
        s.ota_version = str(msg.get("version") or "")
        s.ota_percent = int(msg.get("percent") or 0)
        ok = bool(msg.get("ok"))
        s.ota_error = "" if ok else str(msg.get("error") or "失败")
        if not ok:
            self.log("error", "OTA 失败: %s" % (s.ota_error or "未知原因"))
        elif state == "downloading":
            self.log("info", "OTA 下载中 %d%%" % s.ota_percent)
        elif state == "verifying":
            self.log("info", "OTA 校验中")
        elif state == "ready":
            self.log("info", "OTA 写完，准备重启")

    def ota_view(self):
        """后台「固件」页要的东西。

        谁决定升级：**只有人**。这里只是把事实摆出来 ——
        设备当前版本、可用版本、升级进度。
        """
        s = self.devices.session
        dev = {
            "online": bool(s is not None),
            "deviceId": s.device_id if s else "",
            "fw": s.fw if s else "",
            "otaState": s.ota_state if s else "idle",
            "otaVersion": s.ota_version if s else "",
            "otaPercent": s.ota_percent if s else 0,
            "otaError": s.ota_error if s else "",
        }
        versions = ota_mod.list_versions()
        # 登记过的最高版本（后台还可能拿它做别的判断）。
        latest = versions[0]["version"] if versions else ""
        # 刚传上来的那一份 —— 「升级固件」刷的就是它。
        # 按登记时间取最新，不按版本号取 —— 你刚传的是哪份，就刷哪份。
        uploaded = None
        if versions:
            newest = max(versions, key=lambda v: (v.get("addedAt") or 0,
                                                 ota_mod._ver_key(v["version"])))
            uploaded = {"version": newest["version"], "size": newest["size"]}
        # 同版也给刷 —— 设备跑的是这一版但可能刷坏了，重刷一份能救回来。
        # 比设备旧的不给刷 —— 降级不在这个页面的能力范围里。
        available = ""
        if uploaded and s is not None and s.fw:
            target = uploaded["version"]
            if ota_mod.fw_supports_ota(s.fw) and \
                    ota_mod._ver_key(target) >= ota_mod._ver_key(s.fw):
                available = target
        return {
            "device": dev,
            "versions": versions,
            "latest": latest,
            "uploaded": uploaded,
            "available": available,
            "canUpgrade": bool(available),
            "minFw": ".".join(str(p) for p in ota_mod.MIN_OTA_FW),
            "appPartitionSize": ota_mod.APP_PARTITION_SIZE,
        }

    async def start_ota_upgrade(self, version):
        """后台点了「升级」—— 才开始下发。

        设备自己不会升级。这条路是唯一的触发点。
        """
        s = self.devices.session
        if s is None:
            return False, "设备不在线"
        if not ota_mod.fw_supports_ota(s.fw):
            return False, ("固件 %s 不支持 OTA（要 %s 以上）"
                           % (s.fw or "未知",
                              ".".join(str(p) for p in ota_mod.MIN_OTA_FW)))
        data = ota_mod.read_firmware(version)
        if data is None:
            return False, "找不到固件 %s" % version
        total = len(data)
        # 设备端还卡在上一轮没下完的 OTA？
        # 这种状态下从第 0 片重下，新片会接在旧片的偏移上 —— 镜像直接写坏。
        # 0.5.9 起的固件能自己作废上一轮、从头再来；更老的固件不能，
        # 只能让设备断电重启（断电后状态清空，重连时上报 idle）。
        if s.ota_state == "downloading" and s.ota_percent > 0:
            if not ota_mod.fw_can_restart_ota(s.fw):
                return False, ("设备端还卡在上一轮 OTA（%d%%），这一版固件没法中途"
                               "重来 —— 请给设备断电重启后再点升级"
                               % s.ota_percent)
            self.log("info", "设备端卡在上一轮 OTA（%d%%），新固件会自己作废重来"
                     % s.ota_percent)
        self.log("info", "开始下发固件 %s（%d bytes）" % (version, total))
        # 这一轮的编号 —— 设备会回在 otaStatus 里。
        rnd = self.devices.next_ota_round()
        # 确认计数从头来 —— 别让上一次的 seq 把这一轮的等待直接满足掉。
        await self.devices.reset_ota_ack(rnd)
        ok = await self.devices.send_ota_start(version, total, rnd)
        if not ok:
            return False, "下发开始指令失败"
        seq = 0
        for off in range(0, total, ota_mod.CHUNK_SIZE):
            chunk = data[off:off + ota_mod.CHUNK_SIZE]
            if not await self.devices.send_ota_chunk(seq, chunk):
                self.log("error", "OTA 下发中断在第 %d 片" % seq)
                return False, "下发中断在第 %d 片" % seq
            # **等设备确认这一片进了 flash 再发下一片。**
            # 不等就会把 1MB 固件几秒钟全灌过去：设备 OTA 队列只有 4 深，
            # 写 flash 又慢，队列一满，WS 收包任务就被堵死，
            # 连接直接断在半路 —— 真机表现是「下发中断在第 16 片」，
            # 而且每次断的片数都不一样。
            if not await self.devices.wait_ota_ack(seq, ota_mod.OTA_ACK_TIMEOUT):
                self.log("error", "OTA 第 %d 片没等到设备确认" % seq)
                if self.devices.session is None:
                    return False, "第 %d 片没等到设备确认 —— 设备断了" % seq
                return False, "第 %d 片没等到设备确认（设备可能已经断了）" % seq
            # 设备写盘失败会带 ok=false —— 立刻停，别把坏数据继续推。
            cur = self.devices.session
            if cur is not None and cur.ota_error:
                self.log("error", "OTA 设备端报错: %s" % cur.ota_error)
                return False, "设备端报错: %s" % cur.ota_error
            seq += 1
        await self.devices.send_ota_finish()
        self.log("info", "固件 %s 下发完毕（%d 片），等设备重启" % (version, seq))
        return True, ""

    async def send_pack(self, pack_id):
        """把一个游戏包推给设备 —— 一条文本预告 + 一条 binary 本体。

        本体走 binary：设备那边要把它原样写进 SPIFFS，而且 JSON 重新
        序列化会走 newlib 的浮点 printf（%g）—— 装包那条回调栈只有 4KB。
        """
        if not pack_id:
            return False
        s = self.devices.session
        if s is None:
            return False
        if not fw_supports_packs(s.fw):
            self.log("warn", "固件 %s 不支持游戏包，已跳过: %s"
                     % (s.fw or "未知", pack_id))
            return False
        raw = packs_mod.read_pack(pack_id)
        if raw is None:
            self.log("warn", "找不到游戏包: " + pack_id)
            return False
        data = packs_mod.pack_data(pack_id)
        if data is None:
            self.log("error", "游戏包 %s 解析失败" % pack_id)
            return False
        ok = await self.devices.send_pack(pack_id, int(data.get("version", 1)),
                                          raw.encode("utf-8"))
        if ok:
            self.log("info", "游戏包已下发: " + pack_id)
        return bool(ok)

    async def _push_packs(self, ids):
        """把包逐个推给设备，中间留间隔。

        设备那边的接收队列只有 2 深。一次连着推三个包，挤不进去的那个
        会被静默丢掉 —— 设备就留着旧包，服务端这边还看不出异常。
        留一点间隔，让设备先把上一个装完。
        """
        for i, pid in enumerate(ids):
            if i:
                await asyncio.sleep(self.pack_push_gap)
            await self.send_pack(pid)

    async def push_games(self):
        """把启用的游戏列表推给设备。

        设备收到后自己裁剪（多的删掉）+ 主动要缺的 —— 不用服务端逐个推。
        """
        s = self.devices.session
        # 固件太老就别给 —— 老固件装包会重启。
        if s is not None and not fw_supports_packs(s.fw):
            self.log("warn", "固件 %s 不支持游戏包，已关闭下发"
                     % (s.fw or "未知"))
            await self.devices.send_json({"type": "games", "enabled": []})
            return
        enabled = sorted(self.games_enabled)
        await self.devices.send_json({"type": "games", "enabled": enabled})
        # 连已装的也重推 —— 设备只按 ID 判重，不比对内容。
        # 服务端改了 pack，不推过去设备就一直玩旧的那份。
        await self._push_packs(enabled)

    def set_games(self, ids):
        """勾选启用哪些游戏。改完立刻生效，也落盘。"""
        picked = packs_mod.normalize(ids)
        self.games_enabled = picked
        ui = self.cfg.setdefault("ui", {})
        ui["games"] = sorted(picked)
        self._persist_config()
        self.log("info", "可用游戏 -> " + ("、".join(sorted(picked)) or "无"))

    def games_payload(self):
        """后台「游戏」页 —— 所有可用 pack 和开关状态。"""
        items = []
        for d in packs_mod.list_packs():
            items.append({
                "id": d["id"],
                "title": d["title"],
                "hint": d["hint"],
                "order": d["order"],
                "enabled": d["id"] in self.games_enabled,
                "builtin": "/data/" not in d["path"],
            })
        return {"games": items,
                "enabled": sorted(self.games_enabled),
                # 设备现在在哪个模式 —— playing 说明它正在玩，服务端停推帧
                "deviceMode": str(self.devices.status().get("mode") or "idle")}

    # ---------- 旋钮 ----------
    async def on_knob(self, msg):
        """旋钮事件 -> 手势 -> 动作。

        返回这次做了什么 {"gesture","action","result"} —— 后台的模拟按钮走的就是
        这一条路，所以按钮和真设备的行为一定一致。
        """
        gesture_key, magnitude = gestures_mod.classify(msg, self.gestures)
        if gesture_key is None:
            return None
        # 确认卡在场时旋钮归它：转选择 / 短按确认 / 长按取消。
        # 不走动作表 —— 确认卡是临时覆盖层，答完就还回去。
        if self._confirm_active() is not None:
            return await self._confirm_knob(gesture_key, magnitude)
        action = gestures_mod.action_for(gesture_key, self.gestures)
        if not action:
            return None
        self.log("info", "旋钮 %s -> %s (%s)" % (gesture_key, action, magnitude))
        result = await self.run_action(action, magnitude)
        return {"gesture": gesture_key, "action": action, "result": result or "ok"}

    async def _confirm_knob(self, gesture_key, magnitude):
        """确认卡在场时的旋钮语义。

        转 = 选下一项；短按 = 确认；长按 = 取消。
        rot_press（按住+转）在确认卡上不做事 —— 按住时转是噪声。
        """
        if gesture_key == "rot":
            cur = self.confirm.rotate(magnitude)
            if cur is None:
                return {"gesture": gesture_key, "action": "confirm.select",
                        "result": "none"}
            self.log("info", "确认卡 %s 选中: %s"
                     % (cur.id, cur.options[cur.selected]))
            return {"gesture": gesture_key, "action": "confirm.select",
                    "result": cur.options[cur.selected]}
        if gesture_key == "press_short":
            card, err = self.confirm.confirm()
            if card is None:
                return {"gesture": gesture_key, "action": "confirm.answer",
                        "result": err or "none"}
            self.log("info", "确认卡 %s 已答: %s" % (card.id, card.answer))
            return {"gesture": gesture_key, "action": "confirm.answer",
                    "result": card.answer}
        if gesture_key == "press_long":
            card, err = self.confirm.cancel()
            if card is None:
                return {"gesture": gesture_key, "action": "confirm.cancel",
                        "result": err or "none"}
            self.log("info", "确认卡 %s 已取消" % card.id)
            return {"gesture": gesture_key, "action": "confirm.cancel",
                    "result": "cancelled"}
        return {"gesture": gesture_key, "action": "", "result": "ignored"}

    async def simulate_gesture(self, gesture_key="press_short"):
        """后台按钮：模拟一次旋钮手势。

        造一条设备那种原始事件，走 on_knob —— 跟真设备同一条路。
        短按到底干什么，看 gestures.json 的映射；改了映射，这个按钮跟着变。
        那才叫「模拟」，不是在这儿直接调某个动作。
        """
        key = str(gesture_key or "press_short")
        if key not in ("rot", "rot_press", "press_long", "press_short"):
            return {"gesture": key, "action": "", "result": "unknown"}
        raw = {"type": "input", "ev": "press", "ms": 100}
        if key == "press_long":
            raw["ms"] = int(self.gestures.get("longPressMs", 600)) + 10
        elif key == "rot":
            raw = {"type": "input", "ev": "rot", "dir": 1, "steps": 1}
        elif key == "rot_press":
            raw = {"type": "input", "ev": "rot_press", "dir": 1, "steps": 1}
        out = await self.on_knob(raw)
        if out is None:
            self.log("info", "旋钮 %s 没分配动作" % key)
            return {"gesture": key, "action": "", "result": "unassigned"}
        return out

    async def run_action(self, action, magnitude=1):
        """派发一个动作。返回这次的结果 —— 后台的模拟按钮要拿它说话。"""
        if action == "card.next":
            # 手动翻到下一张卡 —— 宠物在忙（消息层）时不翻
            if self.director.next_card():
                self.log("info", "切到下一张卡")
                return "next"
            return "blocked"
        elif action == "density.cycle":
            await self.set_density((self.density + 1) % 3)
            return "ok"
        elif action == "state.refresh":
            await self.refresh()
            await self.devices.send_json({"type": "refresh", "id": self.frame_seq})
            return "ok"
        elif action == "session.next":
            await self.select_next_session(int(magnitude or 1))
            return "ok"
        elif action == "skin.next":
            await self.cycle_skin()
            return "ok"
        elif action == "game.menu":
            return await self.open_game_menu()
        return ""

    # ---------- 能改的设置 ----------
    # 后台设定和旋钮都调这几个方法 —— 同一份状态，改完立刻生效，也落盘。

    def set_features(self, names):
        """勾选参与轮播的 feature。"""
        picked = feature_mod.normalize(names)
        self.features_enabled = picked
        ui = self.cfg.setdefault("ui", {})
        ui["features"] = sorted(picked)
        # 版本要跟着记上 —— 用户自己勾掉的是他的选择，
        # 下次启动不该又被「新版本自动补齐」加回来。
        ui["featuresVersion"] = feature_mod.FEATURES_VERSION
        self._persist_config()
        self.log("info", "空闲显示 -> " + ("、".join(sorted(picked)) or "无"))
        self._wake_poll()

    def set_card_dwell(self, seconds):
        seconds = max(1, int(seconds))
        self.card_dwell_sec = seconds
        self.cfg.setdefault("ui", {})["cardDwellSec"] = seconds
        self._persist_config()
        self._sync_director()
        self.log("info", "每张卡停留 -> %d 秒" % seconds)

    def set_message_hold(self, seconds):
        seconds = max(0, int(seconds))
        self.message_hold_sec = seconds
        self.cfg.setdefault("ui", {})["messageHoldSec"] = seconds
        self._persist_config()
        self._sync_director()
        self.log("info", "工作结束后保留 -> %d 秒" % seconds)

    def set_screensaver_after(self, seconds):
        """忙多久之后上屏保。0 = 关掉。"""
        seconds = max(0, int(seconds))
        self.screensaver_after_sec = seconds
        self.cfg.setdefault("ui", {})["screensaverAfterSec"] = seconds
        self._persist_config()
        self._sync_director()
        self.log("info", "屏保门槛 -> %s"
                 % ("关" if seconds == 0 else "%d 秒" % seconds))

    def set_screensaver_dwell(self, seconds):
        """屏保期间多久换一张照片。"""
        seconds = max(3, int(seconds))
        self.screensaver_dwell_sec = seconds
        self.cfg.setdefault("ui", {})["screensaverDwellSec"] = seconds
        self._persist_config()
        self._sync_director()
        self.log("info", "屏保换图间隔 -> %d 秒" % seconds)

    def set_sleep_window(self, start, end, enabled=None):
        """设置睡觉时段。起止两个钟点 —— 跨午夜也认。"""
        self.sleep_start = str(start or config_mod.DEFAULT_SLEEP_START)
        self.sleep_end = str(end or config_mod.DEFAULT_SLEEP_END)
        if enabled is not None:
            self.sleep_enabled = bool(enabled)
        ui = self.cfg.setdefault("ui", {})
        ui["sleepStart"] = self.sleep_start
        ui["sleepEnd"] = self.sleep_end
        ui["sleepEnabled"] = self.sleep_enabled
        self._persist_config()
        self.log("info", "睡觉时段 -> %s" % (
            ("%s ~ %s" % (self.sleep_start, self.sleep_end))
            if self.sleep_enabled else "不睡"))

    def set_brightness(self, value):
        """屏幕亮度档位。改完下一帧就用新值，也写进配置。"""
        v = str(value or "auto").strip()
        if v != "auto" and v not in render_mod.BRIGHTNESS_FACTORS:
            raise ValueError("未知的亮度档位：%s" % v)
        self.brightness = v
        self.cfg.setdefault("ui", {})["brightness"] = v
        self._persist_config()
        self.log("info", "屏幕亮度 -> %s" % v)

    async def set_density(self, level):
        level = max(0, min(2, int(level)))
        self.density = level
        self.cfg.setdefault("ui", {})["density"] = level
        self._persist_config()
        await self.devices.send_json({"type": "setDensity", "level": level})
        self.log("info", "信息密度 -> %d" % level)

    async def set_background(self, name):
        """换背景。背景和宠物形象是解耦的两件事 —— 换背景不动宠物。"""
        root = self.cfg.get("_repo_root", ".")
        if not bg_mod.has_bg(root, name):
            raise ValueError("没有这个背景")
        self.background = name
        self.cfg.setdefault("ui", {})["background"] = name
        self._persist_config()
        self.log("info", "背景 -> " + name)

    async def set_card_background(self, name):
        """换卡片背景。跟宠物背景是分开的两套 —— 换一边不动另一边。

        空字符串 = 用卡片自己的渐变底（默认）。
        """
        root = self.cfg.get("_repo_root", ".")
        name = str(name or "").strip()
        # 只认卡片背景那一套 —— 宠物背景的图不算数，两套各管各的。
        if name and not bg_mod.has_bg(root, name, bg_mod.KIND_CARD):
            raise ValueError("没有这张卡片背景")
        self.card_background = name
        self.cfg.setdefault("ui", {})["cardBackground"] = name
        self._persist_config()
        self.log("info", "卡片背景 -> " + (name or "卡片自己的渐变"))

    async def set_skin(self, name):
        root = self.cfg.get("_repo_root", ".")
        if name not in skins_mod.list_skins(root):
            raise ValueError("没有这个形象")
        # 六态必须齐 —— 屏上任何一刻都可能是六态中的任意一态，
        # 缺一态就等于那一刻屏上是空的。
        missing = skins_mod.missing_states(root, name)
        if missing:
            raise ValueError("还缺这些状态：%s" % "、".join(missing))
        self.skin = name
        self.cfg.setdefault("ui", {})["skin"] = name
        self._persist_config()
        self.log("info", "形象 -> " + name)

    def set_weather_city(self, city):
        """天气城市。空 = 用默认城市。"""
        city = str(city or "").strip()
        self.cfg.setdefault("ui", {})["weatherCity"] = city
        self._persist_config()
        # 缓存里还有旧城市的数据 —— 扔掉，让它重新取
        for f in feature_mod.all_features():
            reset = getattr(f, "reset", None)
            if callable(reset):
                reset()
        self.log("info", "天气城市 -> " + (city or "默认"))
        self._wake_poll()

    def set_session(self, key):
        """关注某个会话。空 = 自动（跟着最活跃的那个）。

        存的是**实际生效**的 key —— 被排除的会话（第三方通道、后台会话）
        选不上，配置里也不该留下它的 key。
        """
        key = str(key or "")
        actual = self.engine.select(key or None)
        self._sync_confirm_focus()
        self.cfg.setdefault("ui", {})["session"] = actual or ""
        self._persist_config()
        if key and not actual:
            self.log("info", "会话不在可见范围，忽略: " + key)
            return
        self.log("info", "关注会话 -> " + (actual or "自动"))

    async def open_game_menu(self):
        """让设备打开游戏菜单。

        游戏跑在设备上 —— 服务端没有「游戏界面」这回事，
        只能请设备自己打开菜单。设备不在线就说清楚，别装成按了没反应。
        """
        if not self.devices.online:
            self.log("info", "设备不在线，开不了游戏菜单")
            return "offline"
        ok = await self.devices.send_json({"type": "gameCommand", "action": "menu"})
        if ok:
            self.log("info", "已让设备打开游戏菜单")
            return "opened"
        self.log("info", "没能让设备打开游戏菜单")
        return "offline"

    def reload_album(self):
        """照片变了 —— 让相册重新读一遍列表。"""
        if self.album is not None:
            self.album.reload()

    def album_view(self):
        """相册现状 —— 后台要显示照片，也得说清有几张。"""
        items = album_mod.list_items()
        return {
            "items": items,
            "count": len(items),
            "max": album_mod.MAX_PHOTOS,
        }

    def merit_on(self):
        """功德箱功能开没开 —— 关了屏上不出现任何功德字样。"""
        return "merit" in self.features_enabled

    def toys_view(self):
        """屏上玩具的现状 —— 后台要显示它，也得说清现在摇不摇得动。

        玩具不是宠物状态，所以它不在六态语义表里 —— 这一段是它自己的账。
        """
        state = self.engine.state
        busy = state in ("working", "waiting", "error")
        night = self.is_night()
        return {
            "merit": int(self.merit.value),
            "busy": busy,
            "night": night,
            # 短按被映射到哪个动作 —— 页面照它说话，不替用户猜
            "pressAction": gestures_mod.action_for("press_short", self.gestures),
        }

    async def cycle_skin(self):
        """切到下一个形象 —— 旋钮和后台走同一条路。"""
        root = self.cfg.get("_repo_root", ".")
        names = skins_mod.list_skins(root)
        if not names:
            self.log("info", "没有可用形象")
            return
        cur = names.index(self.skin) if self.skin in names else -1
        await self.set_skin(names[(cur + 1) % len(names)])

    def _persist_config(self):
        try:
            config_mod.save({k: v for k, v in self.cfg.items()
                             if not k.startswith("_")})
        except Exception as exc:
            self.log("error", "保存配置失败: %s" % exc)

    async def select_next_session(self, steps=1):
        rows = self.engine.sessions
        if not rows:
            return
        keys = [r.get("key") for r in rows]
        cur = self.engine.selected_key
        idx = keys.index(cur) if cur in keys else -1
        nxt = rows[(idx + steps) % len(rows)]
        self.engine.select(nxt.get("key"))
        self._sync_confirm_focus()

    async def refresh(self):
        if self._gateway is not None:
            await self._gateway.refresh_sessions()

    # ---------- 睡觉 ----------
    @staticmethod
    def _parse_hhmm(text):
        """一天里的分钟数。

        "24:00" 认（= 1440）—— 只有区间终点用得上：睡到午夜。
        """
        parts = str(text or "").split(":")
        try:
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
        except (TypeError, ValueError):
            return None
        if not (0 <= m <= 59):
            return None
        if h == 24 and m == 0:
            return 1440
        if not (0 <= h <= 23):
            return None
        return h * 60 + m

    def is_night(self, when=None):
        """现在是不是睡觉时段。

        睡觉只有一个来源 —— 用户配的时段。没有「空闲多久算睡着」那回事：
        空闲的时候宠物在轮播卡片里，一直醒着。
        """
        if not self.sleep_enabled:
            return False
        start = self._parse_hhmm(self.sleep_start)
        end = self._parse_hhmm(self.sleep_end)
        if start is None or end is None:
            return False
        if start == end:
            return False
        t = time.localtime(when if when is not None else time.time())
        now = t.tm_hour * 60 + t.tm_min
        if start < end:
            return start <= now < end
        # 跨午夜 —— 22:00 ~ 07:00
        return now >= start or now < end

    # ---------- 渲染 ----------
    def _subtitle(self):
        picked = None
        for row in self.engine.sessions:
            if row.get("key") == self.engine.selected_key:
                picked = row
                break
        if picked is None and self.engine.sessions:
            picked = max(self.engine.sessions,
                         key=lambda r: epoch_s(r.get("lastActivityAt")))
        self._picked = picked
        state = self.engine.state
        sub = STATE_SUBTITLE.get(state, "")
        if state == "idle":
            # 空闲时副标题不是状态说明，是宠物自己想说的话。
            # 有事等你时它不插嘴 —— 插嘴就变噪音了。
            line = self.chatter.maybe(time.time(), state)
            if line:
                sub = line
        if state == "waiting" and picked:
            if picked.get("permissionModePending"):
                sub = "等你授权"
            elif picked.get("unread"):
                sub = "有未读消息"
        # 多个会话同时在等 —— 必须说清几个，否则处理完一个才发现还有一个
        n = self.engine.counts.get(state, 0)
        if n > 1:
            sub = "%s ×%d" % (sub, n)
        return sub

    def _session_name(self):
        if not self._picked:
            return ""
        return self._name_of(self._picked)

    @staticmethod
    def _channel_of(row):
        """会话通道 —— gateway 推的行里带 channel（飞书就是 feishu）。

        新版 WebUI 不再显示飞书会话，但 petd 这边照样收得到。
        所以「哪些会话存在」以 gateway 为准，不以 WebUI 为准。
        """
        return state_mod.channel_of(row)

    @staticmethod
    def _name_of(row):
        """会话显示名。拿不到就退回 key 的最后一段。"""
        for k in ("displayName", "label", "title"):
            v = row.get(k)
            if v:
                return str(v)
        return str(row.get("key") or "").split(":")[-1]

    @classmethod
    def _label_of(cls, row):
        """后台显示名 —— 通道会话的 key 末段常是裸 open_id。

        光丢一串 ou_xxx 看不出是哪条通道，带上通道名和缩略 id。
        """
        name = cls._name_of(row)
        ch = cls._channel_of(row)
        if not ch:
            return name
        label = CHANNEL_LABELS.get(ch, ch)
        for k in ("displayName", "label", "title"):
            if row.get(k):
                return "%s · %s" % (label, name)
        tail = str(row.get("key") or "").split(":")[-1]
        if len(tail) > 12:
            tail = tail[:11] + "…"
        return "%s · %s" % (label, tail)

    def public_sessions(self):
        """给后台看的会话列表 —— 只放安全字段。"""
        out = []
        for row in self.engine.sessions:
            key = row.get("key")
            ch = self._channel_of(row)
            out.append({
                "key": key,
                "name": self._label_of(row),
                "channel": ch,
                "channelLabel": CHANNEL_LABELS.get(ch, ch),
                "state": self.engine.session_states.get(key, "idle"),
                "lastActivityAt": epoch_s(row.get("lastActivityAt")),
                "focused": key == self.engine.selected_key,
                "attributed": key == self.engine.attribution,
            })
        return out

    def render_now(self):
        root = self.cfg.get("_repo_root", ".")
        state = self.engine.state
        now = time.time()

        # 防烧屏 —— 只在睡觉时段开。
        # 夜里屏上是一张不动的睡觉图，一挂就是好几个小时；
        # 白天有卡片轮播，内容本来就在变，不需要。
        night = self.is_night(now)
        anti_burn = render_mod.anti_burn_state(now) if night else None
        # 卡片在夜里不会出现（导演先判睡觉），所以只有 render_frame 要接这个参数。

        # 压暗系数 —— 跟着「屏幕亮度」那一项走。"auto" 档夜里压、白天不压。
        dim = render_mod.brightness_factor(self.brightness, night=night)

        # 卡片背景 —— 内容层用的底。跟宠物背景是分开的两套：
        # 读的是卡片背景自己的目录，宠物背景那张图它看不见。
        card_bg_img = None
        if self.card_background:
            card_bg_img = bg_mod.load_image(root, self.card_background,
                                           bg_mod.KIND_CARD)

        # 飘字层 —— 功德 +1 之类，盖在宠物形象上飘过去
        overlay = None
        bubble = self.merit.bubble(now) if self.merit_on() else None
        if bubble:
            remain = float(bubble["until"]) - now
            # 最后 0.8 秒淡出
            alpha = 1.0 if remain > 0.8 else max(0.0, remain / 0.8)
            overlay = render_mod.bubble_overlay(self.cfg, bubble["text"],
                                                bubble["phrase"], alpha)

        # 确认卡 —— 优先级最高：它是专门来要人回答的。
        # 设备在游戏里时不出现（_confirm_active 里判了）。
        ccard = self._confirm_active()
        if ccard is not None:
            pending = len(self.confirm.list_cards())
            jpeg = render_mod.render_confirm_card(
                self.cfg, ccard.snapshot(),
                background_image=card_bg_img, dim=dim,
                pending_count=max(0, pending - 1),
                remaining_sec=int(ccard.remaining()))
            self.last_jpeg = jpeg
            self.last_jpeg_ts = time.time()
            return jpeg

        view = self.director.update(now, state, self._feature_ctx(),
                                    self._features(), night=self.is_night(now),
                                    saver=self.album)
        if view["layer"] == screen_mod.SCREENSAVER_LAYER and view.get("card"):
            # 屏保 —— 整屏相册 + 宠物小窗。小窗放当前状态那张脸，
            # 别让主人以为宠物没了。
            card = view["card"]
            face = str(view.get("face") or state)
            skin_img = skins_mod.load_image(root, self.skin, face)
            jpeg = render_mod.render_screensaver(
                self.cfg, str(card.get("photo") or ""),
                str(card.get("counter") or ""), face=face,
                skin_image=skin_img, dim=dim)
            if jpeg is None:
                # 照片读不出来 —— 退回整屏宠物，别让屏上开天窗
                jpeg = render_mod.render_frame(
                    self.cfg, face, self._subtitle(), self._session_name(),
                    density=self.density, skin_image=skin_img,
                    overlay=overlay,
                    merit=self.merit.value if self.merit_on() else 0,
                    background_image=bg_img, anti_burn=anti_burn, dim=dim)
        elif view["layer"] == screen_mod.CONTENT_LAYER and view.get("card"):
            card = view["card"]
            # 照片卡 —— 整屏一张图，没有宠物形象，也没有飘字。
            # 照片上飘一行字太乱，压住。
            photo = str(card.get("photo") or "")
            if photo:
                jpeg = render_mod.render_photo_card(
                    self.cfg, photo, str(card.get("counter") or ""), dim=dim)
                if jpeg is None:
                    # 照片读不出来 —— 退回普通卡片，别让屏上开天窗
                    jpeg = render_mod.render_card(self.cfg, card,
                                                  background_image=card_bg_img, dim=dim)
            else:
                cstate = str(card.get("state") or state)
                skin_img = skins_mod.load_image(root, self.skin, cstate)
                jpeg = render_mod.render_card(self.cfg, card, skin_image=skin_img,
                                              overlay=overlay,
                                              background_image=card_bg_img, dim=dim)
        else:
            face = str(view.get("face") or state)
            sub = self._subtitle()
            name = self._session_name()
            skin_img = skins_mod.load_image(root, self.skin, face)
            bg_img = bg_mod.load_image(root, self.background)
            jpeg = render_mod.render_frame(self.cfg, face, sub, name,
                                           density=self.density, skin_image=skin_img,
                                           overlay=overlay,
                                           merit=self.merit.value if self.merit_on() else 0,
                                           background_image=bg_img,
                                           anti_burn=anti_burn, dim=dim)
        self.last_jpeg = jpeg
        self.last_jpeg_ts = time.time()
        return jpeg

    # ---------- 确认卡 ----------

    def _confirm_active(self):
        """当前该显示的确认卡。没有就是 None。

        设备在游戏里时不弹 —— 设备本地接管了屏幕，服务端抢不动，
        硬推只是把游戏画面顶掉。卡留在队列里，退出游戏再显示。
        """
        card = self.confirm.current()
        if card is None:
            return None
        s = self.devices.session
        if s is not None and s.mode != "idle":
            return None
        return card

    def confirm_view(self):
        """后台看的确认卡现状。"""
        cards = self.confirm.list_cards()
        current = self.confirm.current()
        return {
            "current": current.snapshot() if current else None,
            "pending": len(cards),
            "queue": cards,
            "focusSession": self.confirm.focus_session,
        }

    def push_confirm(self, question, options, session_key="", source="",
                     timeout_sec=0):
        # 不指定会话就用宠物正在反映的那个 —— 答案得回对人那儿。
        session_key = str(session_key or self.engine.selected_key
                          or self.engine.attribution or "")
        """发起一张确认卡。返回 (卡快照, 错误信息)。"""
        try:
            card, _ = self.confirm.push(question, options,
                                        session_key=session_key,
                                        source=source, timeout_sec=timeout_sec)
        except confirm_mod.ConfirmError as exc:
            return None, str(exc)
        self.log("info", "确认卡已发起: %s %s" % (card.id, card.question))
        return card.snapshot(), ""

    def _sync_confirm_focus(self):
        """确认卡的焦点会话跟着宠物正在反映的会话走。

        屏上优先显示焦点会话自己的卡 —— 别的会话的卡不能因为排队饿死。

        焦点必须落在**可见**的会话上。三方通道的会话看不见，
        焦点指向它等于把答案往那儿送。
        """
        key = self.engine.selected_key or self.engine.attribution or ""
        if key and not self._session_visible(key):
            key = ""
        self.confirm.set_focus(key)

    def _session_visible(self, key):
        """这个会话在宠物的视野里吗。"""
        for row in self.engine.sessions:
            if row.get("key") == key:
                return True
        return False

    def _on_confirm_answer(self, card, answer):
        """确认卡有了结果 —— 排进待发队列。

        这一步不能是 async：ConfirmManager 的回调在同步上下文里跑
        （测试直接调 confirm()）。所以只入队，真正发给 gateway 由
        帧循环去做 —— 那样不管从哪儿触发都能发出去。
        """
        self._confirm_outbox.append((card, answer))
        self._confirm_fallback_write(card, answer)
        # 有事件循环就立刻发 —— 不用等下一帧（idle 帧只有 1fps，慢）。
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(self._flush_confirm_outbox())

    def _confirm_fallback_write(self, card, answer):
        """本机兜底 —— 网关断了也不能把答案弄丢。"""
        try:
            path = config_mod.DATA_DIR / "confirm_answers.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "id": card.id,
                    "question": card.question,
                    "status": card.status,
                    "answer": answer,
                    "sessionKey": card.session_key,
                    "at": int(time.time()),
                }, ensure_ascii=False) + "\n")
        except Exception:
            log.warning("确认卡答案落盘失败", exc_info=True)
    async def _flush_confirm_outbox(self):
        """把答案注回发起方会话。"""
        if not self._confirm_outbox:
            return
        if self._gateway is None or not self._gateway.connected:
            return
        pending, self._confirm_outbox = self._confirm_outbox, []
        for card, answer in pending:
            if not card.session_key:
                self.log("info", "确认卡 %s 没有会话可回，落盘兜底" % card.id)
                continue
            text = self._confirm_reply_text(card, answer)
            try:
                await self._gateway.send_chat(card.session_key, text)
                self.log("info", "确认卡 %s 的结果已注回 %s"
                         % (card.id, card.session_key))
            except Exception as exc:
                self.log("warning", "确认卡 %s 回程失败: %s" % (card.id, exc))
                # 回不去就放回队首，等 gateway 恢复。
                self._confirm_outbox.insert(0, (card, answer))

    @staticmethod
    def _confirm_reply_text(card, answer):
        """回给 AI 的话 —— AI 下一次读上下文就能看到这张卡的结果。

        卡 id 放在标题里：多张卡并行时，AI 得知道回的是哪一张。
        四种结束态各一句 —— 选了哪项、用户主动取消（别再问）、
        没人应答（按默认选项继续）、被新问题取代。
        """
        head = "[确认卡 %s] %s" % (card.id, card.question)
        if card.status == confirm_mod.STATUS_ANSWERED:
            return "%s\n用户选择了：**%s**" % (head, answer)
        if card.status == confirm_mod.STATUS_CANCELLED:
            return "%s\n用户主动取消了这个问题，不必重复询问。" % head
        if card.status == confirm_mod.STATUS_SUPERSEDED:
            return "%s\n这个问题已被另一个新问题取代。" % head
        if card.status == confirm_mod.STATUS_EXPIRED:
            return "%s\n无人应答，这张卡已超时，按默认选项继续。" % head
        return "%s\n这张卡没有结果。" % head

    def _features(self):
        """参与轮播的 feature —— 按注册顺序。"""
        if not self.features_enabled:
            return []
        allf = feature_mod.all_features()
        return [f for f in allf if f.name in self.features_enabled]

    def _feature_ctx(self):
        """给 feature 的上下文。纯数据 —— feature 不许自己连 gateway。"""
        return {
            "now": time.time(),
            "state": self.engine.state,
            "sessions": self._feature_sessions(),
            "skin": self.skin,
            "focused": self.engine.selected_key,
            "device": self.devices.status(),
            "weatherCity": str(self.cfg.get("ui", {}).get("weatherCity") or ""),
            # 功德 —— 它也是 feature，卡片内容从这儿拿
            "merit": int(self.merit.value),
            "meritPhrase": self.merit.last_phrase(),
        }

    def _feature_sessions(self):
        """给 feature 看的会话列表（脱敏：只有名字、状态、时间）。"""
        out = []
        for row in self.engine.sessions:
            out.append({
                "key": row.get("key"),
                "name": self._name_of(row),
                "status": str(row.get("status") or ""),
                "state": self.engine.session_states.get(row.get("key"), "idle"),
                "lastActivityAt": epoch_s(row.get("lastActivityAt")),
                "unread": bool(row.get("unread")),
                "pending": bool(row.get("permissionModePending")),
            })
        return out

    # ---------- 后台取数 ----------
    def _wake_poll(self):
        """设置变了 —— 让后台取数线程尽快重跑一遍。"""
        ev = getattr(self, "_poll_event", None)
        if ev is not None:
            ev.set()

    def _poll_loop(self):
        """后台线程：feature 要联网的数据在这里取，不阻塞渲染。

        只给「用户勾上了」的 feature 取数 —— 没勾的别去碰网络。
        """
        while not self._stop:
            try:
                ctx = self._feature_ctx()
                for f in feature_mod.all_features():
                    if f.name not in self.features_enabled:
                        continue
                    try:
                        f.poll(ctx)
                    except Exception:
                        log.warning("feature %s 取数失败",
                                    getattr(f, "name", "?"), exc_info=True)
            except Exception:
                log.warning("后台取数失败", exc_info=True)
            # 等到下一次取数，或者被叫醒，或者要退出。
            # stop() 会 set 这个事件 —— 不然线程会一直睡满一个周期，
            # 测试收尾时 executor 等它，套件就挂住了。
            self._poll_event.wait(POLL_INTERVAL_SEC)
            self._poll_event.clear()

    async def _frame_loop(self):
        while not self._stop:
            state = self.engine.state
            fps = (self.cfg.get("frame", {}).get("activeFps", 10)
                   if state in ACTIVE_STATES
                   else self.cfg.get("frame", {}).get("idleFps", 1))
            interval = 1.0 / max(0.2, float(fps))
            t0 = time.time()
            try:
                await self._flush_confirm_outbox()
            except Exception:
                log.warning("确认卡回程发送失败", exc_info=True)
            try:
                jpeg = self.render_now()
            except Exception as exc:
                self.log("error", "渲染失败: %s" % exc)
                await asyncio.sleep(1)
                continue
            # 设备在游戏里 —— 别推帧抢屏。设备端也挡一层，这里是省带宽。
            s = self.devices.session
            if s is not None and s.mode != "idle":
                await asyncio.sleep(0.2)
                continue
            # OTA 期间也别推帧：设备正忙着写 flash，屏上自己画进度。
            # 抢带宽只会让固件片更容易挤爆设备的收包队列。
            if s is not None and s.ota_state == "downloading":
                await asyncio.sleep(0.2)
                continue
            if self.devices.online:
                self.frame_seq += 1
                await self.devices.push_frame(jpeg, self.frame_seq)
            await asyncio.sleep(max(0.0, interval - (time.time() - t0)))

    # ---------- 生命周期 ----------
    async def start(self, gateway=None):
        self._gateway = gateway
        self._task = asyncio.create_task(self._frame_loop())
        # 守护线程 —— 进程退出时不等它。
        # 不能用 run_in_executor：线程池的 worker 不是守护线程，
        # 进程收尾会 join 它，而它正睡在下一次取数的间隔里。
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        self.log("info", "petd 启动")

    async def stop(self):
        self._stop = True
        self._poll_event.set()
        if self._task:
            self._task.cancel()
        if self._gateway:
            self._gateway.stop()

    # ---------- 后台页数据 ----------
    def _gesture_view(self):
        """旋钮手势的当前映射 —— 页面要显示用户现在配的是什么。

        只读。改它得动 petd/data/gestures.json 并重启 petd。
        """
        acts = self.gestures.get("actions", {}) or {}
        return {
            "longPressMs": int(self.gestures.get("longPressMs", 600)),
            "stepsPerAction": int(self.gestures.get("stepsPerAction", 4)),
            "items": [{"key": k, "action": acts.get(k, "") or ""}
                      for k in ("rot", "rot_press", "press_long", "press_short")],
        }

    def snapshot(self):
        return {
            "gateway": {"connected": bool(self._gateway and self._gateway.connected),
                        "error": self._gateway.last_error if self._gateway else ""},
            "device": self.devices.status(),
            "pet": {"state": self.engine.state, "since": int(self.engine.since),
                    "stateCn": state_mod.STATE_CN.get(self.engine.state, self.engine.state),
                    "density": self.density, "skin": self.skin,
                    "background": self.background,
                    "cardBackground": self.card_background,
                    "sessions": len(self.engine.sessions),
                    "selected": self.engine.selected_key,
                    "attribution": self.engine.attribution,
                    "counts": self.engine.counts,
                    "layer": self.director.layer,
                    "feature": self.director.snapshot().get("title") or "",
                    "night": self.is_night(),
                    # 玩具折在这里，不新开顶层段 —— status 的顶层结构是契约
                    "toys": self.toys_view()},
            "frames": {"seq": self.frame_seq,
                       "lastBytes": len(self.last_jpeg) if self.last_jpeg else 0,
                       "lastTs": int(self.last_jpeg_ts)},
            "gestures": self._gesture_view(),
        }

    # ---------- 宠物设定 ----------
    def settings_payload(self):
        """后台「宠物设定」—— 每一项都对应上面某个 setter。"""
        return settings_mod.build(self)

    # ---------- 首次使用指引 ----------
    def _load_setup_state(self):
        """读落盘的状态。读不了就当没有 —— 引导页不该因为一个文件挂掉。"""
        try:
            blob = json.loads(_setup_state_path().read_text(encoding="utf-8"))
        except Exception:
            return {}
        return blob if isinstance(blob, dict) else {}

    def _save_setup_state(self, blob):
        path = _setup_state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(blob, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        except Exception as exc:
            self.log("error", "保存引导状态失败: %s" % exc)

    def _mark_device_seen(self, session):
        """记下「设备连过」—— 断开后后台不该把这一项退回未开始。"""
        state = self._load_setup_state()
        state["everConnected"] = True
        if session is not None and session.device_id:
            state["deviceId"] = session.device_id
        state["maxFrames"] = max(int(state.get("maxFrames") or 0),
                                 int(session.frame_count) if session else 0)
        self._save_setup_state(state)

    def on_device_disconnected(self, session):
        """设备走了，把帧数落盘。"""
        state = self._load_setup_state()
        state["everConnected"] = True
        state["maxFrames"] = max(int(state.get("maxFrames") or 0),
                                 int(session.frame_count) if session else 0)
        self._save_setup_state(state)

    def _mdns_view(self):
        """mDNS 广播现状。

        addresses 始终来自本机真实网卡 —— 广播器没起来也要给地址，
        因为设备配网要填的是 IP。
        """
        adv = self.mdns
        cfg_mdns = self.cfg.get("mdns", {}) or {}
        addresses = []
        if adv is not None and adv.running:
            addresses = adv.addresses()
        if not addresses:
            addresses = local_ipv4_addresses()
        return {
            "enabled": bool(cfg_mdns.get("enabled", True)),
            "hostname": (adv.hostname if adv is not None
                         else str(cfg_mdns.get("hostname") or "petd.local")),
            "addresses": addresses,
            "port": self.listen_port,
        }

    def _server_view(self):
        """设备该连到哪 —— 配网页面里让用户填的地址。

        只给真实局域网 IP。hostname（petd.local）在很多网络里解析不了，
        让用户填一个连不上的名字比不给更糟 —— 所以不推荐它。
        """
        return {
            "addresses": local_ipv4_addresses(),
            "port": self.listen_port,
        }

    def _manual_view(self):
        """使用说明页要显示的东西。

        全部来自当前真在用的配置 —— 手势映射、密度档位、内容卡清单。
        写死一份的话，用户改了配置之后说明页就成了骗人的。
        """
        acts = self.gestures.get("actions", {}) or {}
        return {
            "gestures": {
                "items": [{"key": k, "action": acts.get(k, "") or ""}
                          for k in ("rot", "rot_press", "press_long", "press_short")],
            },
            "density": [{"label": settings_mod.DENSITY_LABELS.get(d, str(d)),
                          "desc": settings_mod.DENSITY_DESCS.get(d, "")}
                         for d in (0, 1, 2)],
            # catalog 给的是 name/title/tip —— 说明页要的是 label/desc 两列
            "features": [{"label": f["title"], "desc": f["tip"]}
                         for f in feature_mod.catalog()],
        }

    def setup_payload(self):
        """后台「第一次用」的引导数据。

        字段名是前后端契约 —— 前端按这些键渲染，改名就白屏。
        """
        state = self._load_setup_state()
        ever = bool(state.get("everConnected"))
        session = self.devices.session
        online = self.devices.online

        device_done = bool(online or ever)
        device_detail = ""
        if session is not None and session.device_id:
            device_detail = session.device_id
        elif state.get("deviceId"):
            device_detail = str(state.get("deviceId"))

        frames = int(session.frame_count) if session is not None else 0
        frames = max(frames, int(state.get("maxFrames") or 0))
        frames_done = device_done and frames > 0

        # 宠物这一步是「设备上真的跑起来了」，光有 gateway 会话不算 ——
        # 那是电脑上的对话，跟屏幕上的宠物无关。设备没连上就不能打勾，
        # 否则四步指引会出现「第一、二步还没完成、第四步已经好了」。
        sessions = len(self.engine.sessions)
        pet_done = device_done and sessions > 0

        steps = [
            {"id": "admin", "label": "后台已就绪", "done": True,
             "detail": "petd 正在运行", "hint": ""},
            {"id": "device", "label": "设备已连接", "done": device_done,
             "detail": device_detail,
             "hint": "" if device_done else "设备刷好固件后会自己连上来"},
            {"id": "frames", "label": "屏幕已出画面", "done": frames_done,
             "detail": ("已推送 %d 帧" % frames) if frames_done else "", "hint": ""},
            {"id": "pet", "label": "宠物已上线", "done": pet_done,
             "detail": ("%d 个会话" % sessions) if pet_done else "",
             "hint": "" if pet_done else (
                 "设备连上后，宠物需要至少一个会话才能醒" if device_done
                 else "先等设备连上来")},
        ]
        return {
            "steps": steps,
            "manual": self._manual_view(),
            "mdns": self._mdns_view(),
            "servers": self._server_view(),
            "provisioning": self._provisioning_view(),
        }

    def _provisioning_view(self):
        """配网能力说明。等固件 v0.4.0 落地后，supported 改由固件 hello/status
        报文里的字段决定（petd 侧已经预留了 provisioned）。"""
        return {
            "supported": True,
            "apSsidPattern": "petd-setup-XXXX",
            "apUrl": "http://192.168.4.1",
            "note": "密码显示在设备屏幕上",
        }

    def setup_public_payload(self):
        """没登录也能看的那部分引导。

        只有「设备该连到哪」和「怎么配网」—— 设备编号、会话数、帧数一律不给，
        那些是登录之后才该看到的东西。
        """
        return {
            "mdns": self._mdns_view(),
            "servers": self._server_view(),
            "provisioning": self._provisioning_view(),
        }
