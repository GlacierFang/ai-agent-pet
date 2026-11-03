"""会话列表 → 宠物状态。

规则见 docs/状态语义.md。判定只用最小字段集：
status / hasActiveRun / unread / permissionModePending / isBackground。
上游加字段不影响这里；上游改字段也只改 data/state_rules.json。
"""
import time

PRIORITY = ["error", "waiting", "working", "done", "idle"]

DEFAULT_RULES = {
    "version": 1,
    "priority": PRIORITY,
    "stability": {
        "idleAfterMs": 3000,
        "idleGraceMs": 30000,
        "eventDebounceMs": 200,
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

    def __init__(self, rules=None, sleep_after_min=10):
        self.rules = rules or DEFAULT_RULES
        self.sleep_after_min = sleep_after_min
        self.sessions = []
        self.selected_key = None
        self.state = "idle"
        self.since = time.time()
        self._idle_candidate_since = None
        self._last_activity = time.time()

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

    def _pick(self, rows):
        if self.selected_key:
            for row in rows:
                if row.get("key") == self.selected_key:
                    return row
        if not rows:
            return None
        return max(rows, key=lambda r: r.get("lastActivityAt") or 0)

    # -- 对外 --
    def update(self, rows, selected_key=None):
        if selected_key is not None:
            self.selected_key = selected_key
        visible = self._visible(rows)
        self.sessions = visible
        picked = self._pick(visible)
        raw = "idle"
        if picked is not None:
            raw = classify(picked, self.rules)

        now = time.time()
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

        # 长期无活动 → sleeping（只在已经 idle 的基础上判定）
        if target == "idle":
            idle_min = self.sleep_after_min
            if idle_min > 0 and (now - self._last_activity) > idle_min * 60:
                target = "sleeping"

        changed = target != self.state
        if changed:
            self.state = target
            self.since = now
        return changed, target, picked

    def select(self, key):
        self.selected_key = key
        return self.selected_key
