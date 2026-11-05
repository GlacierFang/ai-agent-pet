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
from . import config as config_mod
from . import album as album_mod
from . import features as feature_mod
from . import backgrounds as bg_mod
from . import gestures as gestures_mod
from . import render as render_mod
from . import screen as screen_mod
from . import settings as settings_mod
from . import skins as skins_mod
from . import state as state_mod
from . import toys as toys_mod
from .device import DeviceManager
from .state import DEFAULT_RULES, StateEngine, epoch_s

log = logging.getLogger("petd.app")

ACTIVE_STATES = ("working", "waiting", "error", "done")

# 「设备连过没有」这类跨重启的事实要落在盘上，否则重启一次后台就退回未开始。
# 放 data/ 下 —— 那里已经在 systemd unit 的 ReadWritePaths 里。
SETUP_STATE_PATH = config_mod.DATA_DIR / "setup_state.json"

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
        self.density = int(cfg.get("ui", {}).get("density", 1))
        self.skin = cfg.get("ui", {}).get("skin", "default")
        # 背景 —— 和宠物形象解耦。换宠物不动背景，换背景不动宠物。
        self.background = str(cfg.get("ui", {}).get("background") or "default")
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
        # 屏上仲裁：宠物脸 ↔ feature 卡片
        self.director = screen_mod.ScreenDirector(self.rules)
        self.chatter = chatter_mod.Chatter()
        # 屏上的玩具 —— 骰子（一次性覆盖层）和功德计数器。
        # 它们不是宠物状态，不进六态语义表；状态机一个字节都没动。
        self.dice = toys_mod.Dice()
        self.merit = toys_mod.Merit(cfg.get("ui", {}).get("merit", 0))
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
            if state in ("working", "waiting", "error"):
                # 有活来了 —— 骰子让路
                self.dice.dismiss()
            elif state == "done":
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
        """旋钮事件 -> 手势 -> 动作。

        返回这次做了什么 {"gesture","action","result"} —— 后台的模拟按钮走的就是
        这一条路，所以按钮和真设备的行为一定一致。
        """
        gesture_key, magnitude = gestures_mod.classify(msg, self.gestures)
        if gesture_key is None:
            return None
        action = gestures_mod.action_for(gesture_key, self.gestures)
        if not action:
            return None
        self.log("info", "旋钮 %s -> %s (%s)" % (gesture_key, action, magnitude))
        result = await self.run_action(action, magnitude)
        return {"gesture": gesture_key, "action": action, "result": result or "ok"}

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
        elif action == "dice.roll":
            return self.roll_dice()
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
        # 缓存里还���旧城市的数据 —— 扔掉，让它重新取
        for f in feature_mod.all_features():
            reset = getattr(f, "reset", None)
            if callable(reset):
                reset()
        self.log("info", "天气城市 -> " + (city or "默认"))
        self._wake_poll()

    def set_session(self, key):
        """关注某个会话。空 = 自动（跟着最活跃的那个）。"""
        key = str(key or "")
        self.engine.select(key or None)
        self.cfg.setdefault("ui", {})["session"] = key
        self._persist_config()
        self.log("info", "关注会话 -> " + (key or "自动"))

    def roll_dice(self):
        """摇骰子 —— 按一下开，再按一下收。

        返回这次的结果：opened / closed / busy / night。
        只在宠物闲着的时候弹：
          · 睡着不弹 —— 吵醒它要改状态机，那是最贵的一条路
          · 忙着不弹 —— 有活先干活，骰子让路
        """
        if self.dice.active:
            self.dice.dismiss()
            self.log("info", "收起骰子")
            return "closed"
        if not self.dice_on():
            # 骰子功能没勾 —— 按旋钮不弹骰子
            self.log("info", "骰子没开")
            return "off"
        state = self.engine.state
        if state in ("working", "waiting", "error"):
            self.log("info", "有活，先干活")
            return "busy"
        if self.is_night():
            # 睡着的判断看时段，不看引擎状态 —— 引擎里没有 sleeping 这一态
            self.log("info", "睡着了，不摇骰子")
            return "night"
        self.dice.press()
        self.log("info", "摇骰子")
        return "opened"

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

    def dice_on(self):
        """赛博骰子功能开没开 —— 关了短按旋钮不弹骰子。"""
        return "dice" in self.features_enabled

    def toys_view(self):
        """屏上玩具的现状 —— 后台要显示它，也得说清现在摇不摇得动。

        玩具不是宠物状态，所以它不在六态语义表里 —— 这一段是它自己的账。
        """
        state = self.engine.state
        busy = state in ("working", "waiting", "error")
        night = self.is_night()
        return {
            "merit": int(self.merit.value),
            "dice": {
                "active": bool(self.dice.active),
                "rolling": bool(self.dice.rolling),
                "value": int(self.dice.value),
                "rolled": bool(self.dice.rolled),
            },
            "busy": busy,
            "night": night,
            # 现在按旋钮会不会弹骰子
            "canRoll": not busy and not night,
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
        root = self.cfg.get("_repo_root", ".")
        state = self.engine.state
        now = time.time()

        # 骰子占屏 —— 一次性覆盖层。这时没有宠物脸。
        if not self.dice_on():
            # 功能被关掉了 —— 屏上不该还有骰子
            self.dice.dismiss()
        dice_on, dice_face, dice_rolling = self.dice.update(now)
        if dice_on:
            jpeg = render_mod.render_dice(self.cfg, value=dice_face,
                                          rolling=dice_rolling)
            self.last_jpeg = jpeg
            self.last_jpeg_ts = time.time()
            return jpeg

        # 飘字层 —— 功德 +1 之类，盖在宠物脸上飘过去
        overlay = None
        bubble = self.merit.bubble(now) if self.merit_on() else None
        if bubble:
            remain = float(bubble["until"]) - now
            # 最后 0.8 秒淡出
            alpha = 1.0 if remain > 0.8 else max(0.0, remain / 0.8)
            overlay = render_mod.bubble_overlay(self.cfg, bubble["text"],
                                                bubble["phrase"], alpha)

        view = self.director.update(now, state, self._feature_ctx(),
                                    self._features(), night=self.is_night(now))
        if view["layer"] == screen_mod.CONTENT_LAYER and view.get("card"):
            card = view["card"]
            # 照片卡 —— 整屏一张图，没有宠物脸，也没有飘字。
            # 照片上飘一行字太乱，压住。
            photo = str(card.get("photo") or "")
            if photo:
                jpeg = render_mod.render_photo_card(
                    self.cfg, photo, str(card.get("counter") or ""))
                if jpeg is None:
                    # 照片读不出来 —— 退回普通卡片，别让屏上开天窗
                    jpeg = render_mod.render_card(self.cfg, card)
            else:
                cstate = str(card.get("state") or state)
                skin_img = skins_mod.load_image(root, self.skin, cstate)
                jpeg = render_mod.render_card(self.cfg, card, skin_image=skin_img,
                                              overlay=overlay)
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
                                           background_image=bg_img)
        self.last_jpeg = jpeg
        self.last_jpeg_ts = time.time()
        return jpeg

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
            # 功德和骰子 —— 它们也是 feature，卡片内容从这儿拿
            "merit": int(self.merit.value),
            "meritPhrase": self.merit.last_phrase(),
            "dice": {"active": bool(self.dice.active),
                     "rolling": bool(self.dice.rolling),
                     "value": int(self.dice.value),
                     "rolled": bool(self.dice.rolled)},
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
            # 骰子在滚的时候必须高帧率 —— 闲置档 1fps 只能看到一两帧，等于没滚
            fps = (self.cfg.get("frame", {}).get("activeFps", 10)
                   if state in ACTIVE_STATES or self.dice.active
                   else self.cfg.get("frame", {}).get("idleFps", 1))
            interval = 1.0 / max(0.2, float(fps))
            t0 = time.time()
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
            "provisioning": self._provisioning_view(),
        }

    def _provisioning_view(self):
        """配网能力说明。等固件 v0.2.0 落地后，supported 改由固件 hello/status
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
            "provisioning": self._provisioning_view(),
        }
