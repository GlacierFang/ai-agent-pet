"""会话列表 → 宠物状态。

规则见 docs/状态语义.md。判定只用最小字段集：
status / hasActiveRun / unread / permissionModePending / isBackground。
上游加字段不影响这里；上游改字段也只改 data/state_rules.json。

宠物反应的是「全部会话」：每个会话各自判状态，取最急的那个当宠物状态，
并带上归因（是哪个会话在起作用）和计数（各有几个在等）。
"""

import time

# 优先级从急到缓。等你批准最急 —— 那是唯一会挡住人的事。
PRIORITY = ["waiting", "error", "working", "done", "idle"]

DEFAULT_RULES = {
    "version": 1,
    "priority": PRIORITY,
    "stability": {
        "idleAfterMs": 3000,
        "idleGraceMs": 30000,
        "eventDebounceMs": 200,
        # done 衰减：多久没动静就不再算「刚完成」。
        # 不衰减的话，几天前跑完的会话会把宠物永远钉在「刚完成」。
        "doneDecayMs": 180000,
    },
    "exclude": {"isBackground": True},
    "rules": {
        "error": {"all": [{"status": "error"}]},
        "waiting": {"any": [{"permissionModePending": True}, {"unread": True}]},
        "working": {"all": [{"status": "running"}, {"hasActiveRun": True}]},
        "done": {"all": [{"status": "done"}]},
        "idle": {"none": [{"status": "running", "hasActiveRun": True}]},
    },
}

BACKGROUND = "background"


def epoch_s(value):
    """把上游的时间戳统一成秒。

    gateway 给的 lastActivityAt 是**毫秒**。之前按秒算，两个后果：
      · 前端「几分钟前」全显示成「刚刚」
      · done 衰减永远不触发（秒减毫秒是负数），
        几天前跑完的会话会一直让宠物停在「刚完成」

    量级判断：现在的秒级时间戳约 1.8e9，毫秒级约 1.8e12。
    """
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0:
        return 0.0
    if v > 1e11:
        return v / 1000.0
    return v

STATE_CN = {
    "idle": "闲",
    "working": "在忙",
    "waiting": "等你",
    "done": "刚完成",
    "error": "出错",
    "sleeping": "睡着了",
}


def _cond(row, cond):
    return all(row.get(k) == v for k, v in cond.items())


def _rule(row, rule):
    if not rule:
        return False
    if "all" in rule:
        return all(_cond(row, cond) for cond in rule["all"])
    if "any" in rule:
        return any(_cond(row, cond) for cond in rule["any"])
    if "none" in rule:
        return not any(_cond(row, cond) for cond in rule["none"])
    return False


def classify(row, rules):
    for name in rules.get("priority", PRIORITY):
        if _rule(row, rules.get("rules", {}).get(name)):
            return name
    return "idle"


class StateEngine:
    """维护会话快照，算出宠物当前状态。

    稳态窗只作用于「退回 idle」：进入 working/waiting/error 立即生效。
    """

    def __init__(self, rules=None):
        self.rules = rules or DEFAULT_RULES
        self.sessions = []
        self.selected_key = None
        self.state = "idle"
        self.since = time.time()
        self._idle_candidate_since = None
        self._last_activity = time.time()
        # 归因与计数：宠物反应全部会话，这两块回答「为什么」和「几个」
        self.attribution = None
        self.counts = {}
        self.session_states = {}

    # -- 内部 --
    def _visible(self, rows):
        exclude = self.rules.get("exclude", {})
        out = []
        for row in rows or []:
            skip = False
            for key, val in exclude.items():
                if row.get(key) == val:
                    skip = True
                    break
            if not skip:
                out.append(row)
        return out

    def rank(self, state):
        """状态有多急 —— 数字越小越急。"""
        prio = self.rules.get("priority", PRIORITY)
        return prio.index(state) if state in prio else len(prio)

    def _decay(self, row, state, now):
        """done 太久远就当 idle。"""
        if state != "done":
            return state
        ms = self.rules.get("stability", {}).get("doneDecayMs", 180000)
        if not ms or ms <= 0:
            return state
        last = epoch_s(row.get("lastActivityAt"))
        if last and (now - last) * 1000 > ms:
            return "idle"
        return state

    def _classify_all(self, rows, now):
        states = {}
        counts = {}
        for row in rows:
            st = self._decay(row, classify(row, self.rules), now)
            key = row.get("key")
            states[key] = st
            counts[st] = counts.get(st, 0) + 1
        return states, counts

    def _pick(self, rows, states):
        """最急的会话；同级取最近活动的。

        宠物反映全部会话 —— 焦点（selected_key）不改变宠物状态，
        只决定会话卡片显示哪一条。
        """
        if not rows:
            return None
        return max(rows, key=lambda r: (
            -self.rank(states.get(r.get("key"), "idle")),
            epoch_s(r.get("lastActivityAt")),
        ))

    # -- 对外 --
    def update(self, rows, selected_key=None):
        if selected_key is not None:
            self.selected_key = selected_key
        visible = self._visible(rows)
        self.sessions = visible

        now = time.time()
        states, counts = self._classify_all(visible, now)
        self.session_states = states
        self.counts = counts

        picked = self._pick(visible, states)
        raw = states.get(picked.get("key"), "idle") if picked is not None else "idle"

        # done 表示一次跑完了 —— 不是「还在活动」，不该一直挡住睡觉
        if raw in ("working", "waiting", "error"):
            self._last_activity = now

        ACTIVE = ("working", "waiting", "error", "done")
        target = raw
        if raw == "idle":
            if self.state in ACTIVE:
                # 稳态窗：退回 idle 必须连续 idleAfterMs 都判为非活跃，
                # 否则多会话并发时会 idle/working 抽搐。
                grace = self.rules.get("stability", {}).get("idleAfterMs", 3000)
                if self._idle_candidate_since is None:
                    self._idle_candidate_since = now
                if (now - self._idle_candidate_since) * 1000 >= grace:
                    target = "idle"
                    self._idle_candidate_since = None
                else:
                    target = self.state
            else:
                # idle / sleeping 之间不套稳态窗 —— 否则每 3 秒抖一次
                target = "idle"
                self._idle_candidate_since = None
        else:
            self._idle_candidate_since = None

        changed = target != self.state
        if changed:
            self.state = target
            self.since = now

        # 归因跟着当前状态走 —— 空闲时没有归因可言
        self.attribution = (picked.get("key")
                            if picked is not None and raw != "idle" else None)
        return changed, target, picked

    def select(self, key):
        self.selected_key = key
        return self.selected_key

    def focused(self):
        """用户当前聚焦的会话行（没有就 None）。"""
        for row in self.sessions:
            if row.get("key") == self.selected_key:
                return row
        return None
