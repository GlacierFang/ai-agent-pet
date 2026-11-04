"""屏上仲裁：宠物脸 ↔ feature 卡片。

屏上永远只有一样东西 —— 不是上下分区，是整屏切换。

一条时间线：

    OpenClaw 在干活（working / waiting / error）
        → 宠物脸整屏接管，直接打断当前 feature 卡
    工作结束（done / idle）
        → 保留 N 秒（用户可调）宠物脸还在
        → feature 卡片接管，轮播，每张住 M 秒（用户可调）
        → 所有 feature 都没话说 → 回宠物脸挂着
    夜间时段
        → 没事干就睡脸；OpenClaw 干活就醒着干活，干完再睡

睡眠只有一个来源 —— 用户配的时段。没有「空闲多久算睡着」那回事：
空闲的时候宠物在轮播卡片里，一直醒着。
"""
import logging
import time

log = logging.getLogger("petd.screen")

MESSAGE_LAYER = "message"
CONTENT_LAYER = "content"

DEFAULT_BUSY_STATES = ("working", "waiting", "error")
DEFAULT_MESSAGE_HOLD_MS = 3000
DEFAULT_CONTENT_DWELL_MS = 8000


class ScreenDirector:
    """决定这一帧屏上显示什么。"""

    def __init__(self, rules=None, hold_ms=None, dwell_ms=None):
        screen = (rules or {}).get("screen", {}) or {}
        self.busy_states = tuple(screen.get("busyStates")
                                 or DEFAULT_BUSY_STATES)
        self.message_hold_ms = int(
            hold_ms if hold_ms is not None
            else screen.get("messageHoldMs", DEFAULT_MESSAGE_HOLD_MS))
        self.content_dwell_ms = int(
            dwell_ms if dwell_ms is not None
            else screen.get("contentDwellMs", DEFAULT_CONTENT_DWELL_MS))
        self.layer = MESSAGE_LAYER
        self.feature = None
        self._face = "idle"
        self._layer_since = time.time()
        self._hold_until = 0.0
        self._state = None
        self._force_next = False

    def snapshot(self):
        """给后台看的：现在屏上是哪一层、谁在上。"""
        return {
            "layer": self.layer,
            "feature": getattr(self.feature, "name", "") if self.feature else "",
            "title": getattr(self.feature, "title", "") if self.feature else "",
        }

    # ---------- 对外 ----------
    def next_card(self):
        """手动切到下一张卡。宠物在忙（消息层）时不切 —— 它没空翻卡。"""
        if self.layer != CONTENT_LAYER:
            return False
        self._force_next = True
        self._layer_since = 0.0
        return True

    def update(self, now, state, ctx, features=None, night=False):
        """决定这一帧显示什么。返回 {layer, feature, card, face}。"""
        busy = state in self.busy_states
        prev = self._state
        self._state = state

        if busy:
            # OpenClaw 在干活 —— 宠物整屏接管，直接打断当前卡片
            self.layer = MESSAGE_LAYER
            self.feature = None
            self._face = state
            self._layer_since = now
            self._hold_until = 0.0
            return self._view(state)

        # 刚忙完 —— 给它留一会儿（用户可调的秒数）
        if prev in self.busy_states:
            self._hold_until = now + self.message_hold_ms / 1000.0

        if now < self._hold_until:
            face = "done" if state == "done" else "idle"
            self.layer = MESSAGE_LAYER
            self.feature = None
            self._face = face
            self._layer_since = now
            return self._view(face)

        if night:
            # 夜里没事干 —— 睡觉
            self.layer = MESSAGE_LAYER
            self.feature = None
            self._face = "sleeping"
            self._layer_since = now
            return self._view("sleeping")

        card, feature = self._pick(now, state, ctx, features)
        if card is None:
            # 没内容 —— 回消息层挂着宠物的脸
            self.layer = MESSAGE_LAYER
            self.feature = None
            self._face = "idle"
            self._layer_since = now
            return self._view("idle")

        if self.layer != CONTENT_LAYER:
            self.layer = CONTENT_LAYER
            self._layer_since = now
        self.feature = feature
        self._face = str(card.get("state") or "idle")
        return {"layer": CONTENT_LAYER, "feature": feature, "card": card,
                "face": self._face}

    # ---------- 内部 ----------
    def _view(self, face):
        return {"layer": self.layer, "feature": self.feature, "card": None,
                "face": face}

    def _pick(self, now, state, ctx, features):
        """挑一张卡片。返回 (card, feature)；没有就 (None, None)。

        轮播 —— 按注册顺序转，转到没话说的就跳过它。
        """
        feats = list(features or [])
        by_name = {}
        cards = {}
        for f in feats:
            by_name[f.name] = f
            try:
                if not f.wants(state):
                    continue
                card = f.context(ctx)
            except Exception:
                log.warning("feature %s 出错，跳过",
                            getattr(f, "name", "?"), exc_info=True)
                continue
            if card:
                cards[f.name] = card
        if not cards:
            return None, None

        names = [f.name for f in feats]
        cur = self.feature.name if self.feature is not None else ""
        dwelled = (now - self._layer_since) >= self.content_dwell_ms / 1000.0

        if cur in cards and not self._force_next and not dwelled:
            return cards[cur], by_name[cur]

        # 轮转到下一张有话说的
        start = (names.index(cur) + 1) if cur in names else 0
        for i in range(len(names)):
            name = names[(start + i) % len(names)]
            if name not in cards:
                continue
            f = by_name[name]
            if f is not self.feature:
                self._layer_since = now
            self._force_next = False
            return cards[name], f
        return None, None
