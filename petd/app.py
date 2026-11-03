"""petd 主控：状态 → 渲染 → 推帧。

渲染循环按状态限帧：idle 1fps，working/waiting/error 10fps。
"""
import asyncio
import json
import logging
import time
from collections import deque

from . import config as config_mod
from . import gestures as gestures_mod
from . import render as render_mod
from . import skins as skins_mod
from . import state as state_mod
from .device import DeviceManager
from .state import DEFAULT_RULES, StateEngine, epoch_s

log = logging.getLogger("petd.app")

ACTIVE_STATES = ("working", "waiting", "error", "done")
PAGES = ("face", "session", "notify")

# 「设备连过没有」这类跨重启的事实要落在盘上，否则重启一次后台就退回未开始。
# 放 data/ 下 —— 那里已经在 systemd unit 的 ReadWritePaths 里。
SETUP_STATE_PATH = config_mod.DATA_DIR / "setup_state.json"

STATE_SUBTITLE = {
    "idle": "", "working": "正在处理", "waiting": "等你确认",
    "done": "已完成", "error": "出错了", "sleeping": "zZ",
}


class PetApp:
    def __init__(self, cfg):
        self.cfg = cfg
        self.rules = self._load_rules()
        self.engine = StateEngine(self.rules, cfg.get("state", {}).get("sleepAfterMin", 10))
        self.devices = DeviceManager()
        self.gestures = gestures_mod.load()
        self.page = cfg.get("ui", {}).get("page", "face")
        self.density = int(cfg.get("ui", {}).get("density", 1))
        self.skin = cfg.get("ui", {}).get("skin", "default")
        self.frame_seq = 0
        self.last_jpeg = None
        self.last_jpeg_ts = 0
        self.logs = deque(maxlen=300)
        self._log_seq = 0
        self._stop = False
        self._task = None
        self._gateway = None
        self._phase = 0.0
        self._picked = None
        self.mdns = None          # server 生命周期里塞进来的 MdnsAdvertiser
        # 实际在听的端口。命令行 --port 会盖过配置，但不该被写回配置文件 ——
        # 那是「这次跑在哪个端口」，不是「以后都跑哪个端口」。
        self.listen_port = int((cfg.get("server", {}) or {}).get("port", 18860))

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

    def log(self, level, msg):
        self._log_seq += 1
        entry = {"seq": self._log_seq, "ts": time.time(), "level": level, "msg": msg}
        self.logs.append(entry)
        log.log({"error": 40, "warn": 30, "info": 20}.get(level, 20), "%s", msg)
        return entry

    # ---------- gateway ----------
    async def on_sessions(self, rows):
        changed, state, picked = self.engine.update(rows)
        if changed:
            self.log("info", "状态 -> " + state)
            await self.push_state(state)
        return state

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
            "pages": list(PAGES),
            "density": {"levels": [0, 1, 2], "current": self.density},
            "gestures": {"longPressMs": self.gestures.get("longPressMs", 600),
                         "stepsPerAction": self.gestures.get("stepsPerAction", 4)},
            "frame": {"idleFps": self.cfg.get("frame", {}).get("idleFps", 1),
                      "activeFps": self.cfg.get("frame", {}).get("activeFps", 10)},
        })
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
            await self.on_knob(msg)
        elif t == "log":
            self.log(msg.get("level", "info"), "device: " + str(msg.get("msg", "")))
        elif t == "error":
            self.log("error", "device: " + str(msg.get("message", msg.get("code", ""))))

    # ---------- 旋钮 ----------
    async def on_knob(self, msg):
        gesture_key, magnitude = gestures_mod.classify(msg, self.gestures)
        if gesture_key is None:
            return
        action = gestures_mod.action_for(self.page, gesture_key, self.gestures)
        if not action:
            return
        self.log("info", "旋钮 %s -> %s (%s)" % (gesture_key, action, magnitude))
        await self.run_action(action, magnitude)

    async def run_action(self, action, magnitude=1):
        if action == "page.next":
            idx = PAGES.index(self.page) if self.page in PAGES else -1
            self.page = PAGES[(idx + 1) % len(PAGES)]
            await self.devices.send_json({"type": "setPage", "page": self.page})
        elif action == "page.prev":
            idx = PAGES.index(self.page) if self.page in PAGES else 0
            self.page = PAGES[(idx - 1) % len(PAGES)]
            await self.devices.send_json({"type": "setPage", "page": self.page})
        elif action == "density.cycle":
            self.density = (self.density + 1) % 3
            await self.devices.send_json({"type": "setDensity", "level": self.density})
        elif action == "state.refresh":
            await self.refresh()
            await self.devices.send_json({"type": "refresh", "id": self.frame_seq})
        elif action == "session.next":
            await self.select_next_session(int(magnitude or 1))
        elif action == "skin.next":
            await self.cycle_skin()

    async def cycle_skin(self):
        """切到下一个形象 —— 旋钮和后台走同一条路。"""
        root = self.cfg.get("_repo_root", ".")
        names = skins_mod.list_skins(root)
        if not names:
            self.log("info", "没有可用形象")
            return
        cur = names.index(self.skin) if self.skin in names else -1
        self.skin = names[(cur + 1) % len(names)]
        self._persist_ui()
        self.log("info", "形象 -> " + self.skin)

    def _persist_ui(self):
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

    async def refresh(self):
        if self._gateway is not None:
            await self._gateway.refresh_sessions()

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
    def _name_of(row):
        """会话显示名。拿不到就退回 key 的最后一段。"""
        for k in ("displayName", "label", "title"):
            v = row.get(k)
            if v:
                return str(v)
        return str(row.get("key") or "").split(":")[-1]

    def public_sessions(self):
        """给后台看的会话列表 —— 只放安全字段。"""
        out = []
        for row in self.engine.sessions:
            key = row.get("key")
            out.append({
                "key": key,
                "name": self._name_of(row),
                "state": self.engine.session_states.get(key, "idle"),
                "lastActivityAt": epoch_s(row.get("lastActivityAt")),
                "focused": key == self.engine.selected_key,
                "attributed": key == self.engine.attribution,
            })
        return out

    def render_now(self):
        sub = self._subtitle()
        name = self._session_name()
        root = self.cfg.get("_repo_root", ".")
        frames = skins_mod.load_frames(root, self.skin, self.engine.state)
        jpeg = render_mod.render_frame(self.cfg, self.engine.state, sub, name,
                                      density=self.density, phase=self._phase,
                                      skin_frames=frames)
        self.last_jpeg = jpeg
        self.last_jpeg_ts = time.time()
        return jpeg

    async def _frame_loop(self):
        while not self._stop:
            state = self.engine.state
            fps = (self.cfg.get("frame", {}).get("activeFps", 10) if state in ACTIVE_STATES
                   else self.cfg.get("frame", {}).get("idleFps", 1))
            interval = 1.0 / max(0.2, float(fps))
            t0 = time.time()
            self._phase = (self._phase + interval) % 1000.0
            try:
                jpeg = self.render_now()
            except Exception as exc:
                self.log("error", "渲染失败: %s" % exc)
                await asyncio.sleep(1)
                continue
            if self.devices.online:
                self.frame_seq += 1
                await self.devices.push_frame(jpeg, self.frame_seq)
            await asyncio.sleep(max(0.0, interval - (time.time() - t0)))

    # ---------- 生命周期 ----------
    async def start(self, gateway=None):
        self._gateway = gateway
        self._task = asyncio.create_task(self._frame_loop())
        self.log("info", "petd 启动")

    async def stop(self):
        self._stop = True
        if self._task:
            self._task.cancel()
        if self._gateway:
            self._gateway.stop()

    # ---------- 后台页数据 ----------
    def snapshot(self):
        return {
            "gateway": {"connected": bool(self._gateway and self._gateway.connected),
                        "error": self._gateway.last_error if self._gateway else ""},
            "device": self.devices.status(),
            "pet": {"state": self.engine.state, "since": int(self.engine.since),
                    "stateCn": state_mod.STATE_CN.get(self.engine.state, self.engine.state),
                    "page": self.page, "density": self.density, "skin": self.skin,
                    "sessions": len(self.engine.sessions),
                    "selected": self.engine.selected_key,
                    "attribution": self.engine.attribution,
                    "counts": self.engine.counts},
            "frames": {"seq": self.frame_seq,
                       "lastBytes": len(self.last_jpeg) if self.last_jpeg else 0,
                       "lastTs": int(self.last_jpeg_ts)},
        }

    # ---------- 首次使用指引 ----------
    def _load_setup_state(self):
        """读落盘的状态。读不了就当没有 —— 引导页不该因为一个文件挂掉。"""
        try:
            blob = json.loads(SETUP_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return blob if isinstance(blob, dict) else {}

    def _save_setup_state(self, blob):
        try:
            SETUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            SETUP_STATE_PATH.write_text(json.dumps(blob, ensure_ascii=False, indent=2),
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

        enabled 取配置（用户关了就是 false）；addresses 取广播器实际广播的地址 ——
        广播器没起来时是空列表，页面据此告诉用户「设备还连不上」。
        """
        adv = self.mdns
        cfg_mdns = self.cfg.get("mdns", {}) or {}
        addresses = []
        if adv is not None and adv.running:
            addresses = adv.addresses()
        return {
            "enabled": bool(cfg_mdns.get("enabled", True)),
            "hostname": (adv.hostname if adv is not None
                         else str(cfg_mdns.get("hostname") or "petd.local")),
            "addresses": addresses,
            "port": self.listen_port,
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

        sessions = len(self.engine.sessions)
        pet_done = sessions > 0

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
             "hint": "" if pet_done else "宠物需要至少一个会话才能醒"},
        ]
        return {
            "steps": steps,
            "mdns": self._mdns_view(),
            # 配网能力说明。等固件 v0.2.0 落地后，supported 改由固件 hello/status
            # 报文里的字段决定（petd 侧已经预留了 provisioned）。
            "provisioning": {
                "supported": True,
                "apSsidPattern": "petd-setup-XXXX",
                "apUrl": "http://192.168.4.1",
                "note": "密码显示在设备屏幕上",
            },
        }

