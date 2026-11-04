"""屏上分层：消息层 / 内容层。

屏上永远只有一样东西 —— 不是上下分区，是整屏切换：

    消息层   宠物本体 + 状态（+ 一句话）。等你确认、出错了，立刻占屏。
    内容层   某张 feature 卡片，整屏。

没消息、也没内容可显示时，回消息层挂着宠物的脸 —— 屏上永远有它。

切层规则：

  · waiting / error 立刻抢占内容层（你在等它，不能被卡片盖住）
  · 消息结束后再留 holdMs 才让位（防状态抖动闪屏）
  · 内容层换卡片至少住 dwellMs（防卡片来回闪）

参数在 petd/data/state_rules.json 的 "screen" 段里。
"""
import logging
import time

log = logging.getLogger("petd.screen")

MESSAGE_LAYER = "message"
CONTENT_LAYER = "content"

DEFAULT_MESSAGE_STATES = ("waiting", "error")
DEFAULT_MESSAGE_HOLD_MS = 3000
DEFAULT_CONTENT_DWELL_MS = 8000


class ScreenDirector:
    """决定这一帧屏上显示什么。"""

    def __init__(self, rules=None):
        screen = (rules or {}).get("screen", {}) or {}
        self.message_states = tuple(screen.get("messageStates")
                                    or DEFAULT_MESSAGE_STATES)
        self.message_hold_ms = int(screen.get("messageHoldMs",
                                              DEFAULT_MESSAGE_HOLD_MS))
        self.content_dwell_ms = int(screen.get("contentDwellMs",
                                               DEFAULT_CONTENT_DWELL_MS))
        self.layer = MESSAGE_LAYER
        self.feature = None
        self._layer_since = time.time()
        self._message_until = 0.0

    def snapshot(self):
        """给后台看的：现在屏上是哪一层、谁在上。"""
        return {
            "layer": self.layer,
            "feature": getattr(self.feature, "name", "") if self.feature else "",
            "title": getattr(self.feature, "title", "") if self.feature else "",
        }

    # ---------- 对外 ----------
    def update(self, now, state, ctx, features=None):
        """决定这一帧显示什么。返回 {layer, feature, card}。"""
        if state in self.message_states:
            # 等你的事 —— 立刻抢屏，不能被卡片盖住
            self.layer = MESSAGE_LAYER
            self.feature = None
            self._layer_since = now
            self._message_until = now + self.message_hold_ms / 1000.0
            return {"layer": MESSAGE_LAYER, "feature": None, "card": None}

        if self.layer == MESSAGE_LAYER and now < self._message_until:
            # 消息刚结束 —— 留一会儿再让位
            return {"layer": MESSAGE_LAYER, "feature": None, "card": None}

        card, feature = self._pick(now, state, ctx, features)
        if card is None:
            # 没内容 —— 回消息层挂着宠物的脸
            self.layer = MESSAGE_LAYER
            self.feature = None
            self._layer_since = now
            self._message_until = 0.0
            return {"layer": MESSAGE_LAYER, "feature": None, "card": None}

        if self.layer != CONTENT_LAYER:
            self.layer = CONTENT_LAYER
            self._layer_since = now
        elif feature is not self.feature:
            # 换卡片了 —— 重新起算停留时间
            self._layer_since = now
        self.feature = feature
        return {"layer": CONTENT_LAYER, "feature": feature, "card": card}

    # ---------- 内部 ----------
    def _pick(self, now, state, ctx, features):
        """挑一个 feature。返回 (card, feature)；没有就 (None, None)。"""
        best = None
        current = None
        for f in (features or []):
            try:
                if not f.wants(state):
                    continue
                card = f.context(ctx)
            except Exception:
                log.warning("feature %s 出错，跳过", getattr(f, "name", "?"),
                            exc_info=True)
                continue
            if not card:
                continue
            if f is self.feature:
                current = (card, f)
            if best is None or int(getattr(f, "priority", 0)) > int(
                    getattr(best[1], "priority", 0)):
                best = (card, f)
        if current is not None and self.layer == CONTENT_LAYER:
            # 当前这张还在说话 —— 不到 dwell 不换
            if now - self._layer_since < self.content_dwell_ms / 1000.0:
                return current
            return best or current
        return best or (None, None)
