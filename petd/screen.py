"""屏上仲裁：宠物形象 ↔ feature 卡片。

屏上永远只有一样东西 —— 不是上下分区，是整屏切换。

一条时间线：

    OpenClaw 在干活（working / waiting / error）
        → 宠物形象整屏接管，直接打断当前 feature 卡
    工作结束（done / idle）
        → 保留 N 秒（用户可调）宠物形象还在
        → feature 卡片接管，轮播，每张住 M 秒（用户可调）
        → 所有 feature 都没话说 → 回宠物形象挂着
    夜间时段
        → 到了睡觉时段就睡；OpenClaw 干活就醒着干活，干完再睡

睡眠只有一个来源 —— 用户配的时段。没有「空闲多久算睡着」那回事：
空闲的时候宠物在轮播卡片里，一直醒着。

还有一层：忙了很久（默认 60 秒）之后，屏上换成相册轮播 + 宠物小窗 ——
宠物还在干活，但屏上不该一张图挂几个小时。门槛后台可调，0 = 关掉。
"""
import logging
import time

log = logging.getLogger("petd.screen")

MESSAGE_LAYER = "message"
CONTENT_LAYER = "content"
# 屏保 —— 忙了很久之后顶上来的画面：整屏相册 + 宠物小窗。
SCREENSAVER_LAYER = "screensaver"

DEFAULT_BUSY_STATES = ("working", "waiting", "error")
DEFAULT_MESSAGE_HOLD_MS = 3000
DEFAULT_CONTENT_DWELL_MS = 8000
# 忙多久之后上屏保。0 = 不上。
DEFAULT_SCREENSAVER_AFTER_MS = 60000
# 屏保期间多久换一张照片。
DEFAULT_SCREENSAVER_DWELL_MS = 15000


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
        # 屏保：门槛、翻页间隔，以及「现在正在忙」的起点。
        self.screensaver_after_ms = int(
            screen.get("screensaverAfterMs", DEFAULT_SCREENSAVER_AFTER_MS))
        self.screensaver_dwell_ms = int(
            screen.get("screensaverDwellMs", DEFAULT_SCREENSAVER_DWELL_MS))
        self._busy_since = 0.0
        self._saver_since = 0.0
        self._saver_feature = None
        self._saver_ctx = None

    def snapshot(self):
        """给后台看的：现在屏上是哪一层、谁在上。"""
        return {
            "layer": self.layer,
            "feature": getattr(self.feature, "name", "") if self.feature else "",
            "title": getattr(self.feature, "title", "") if self.feature else "",
        }

    # ---------- 对外 ----------
    def next_card(self):
        """手动切到下一张卡。宠物在忙（消息层）时不切 —— 它没空翻卡。

        屏保里例外 —— 转旋钮换下一张照片，那是屏上唯一能动的事。
        """
        if self.layer == SCREENSAVER_LAYER:
            return self._saver_photo_next()
        if self.layer != CONTENT_LAYER:
            return False
        self._force_next = True
        self._layer_since = 0.0
        return True

    def update(self, now, state, ctx, features=None, night=False, saver=None):
        """决定这一帧显示什么。返回 {layer, feature, card, face}。"""
        busy = state in self.busy_states
        prev = self._state
        self._state = state

        if busy:
            if prev not in self.busy_states:
                # 刚开始忙 —— 记住起点，屏保要拿它算「忙了多久」
                self._busy_since = now
            # 忙了很久 —— 上屏保：整屏相册，宠物缩到小窗里。
            card, feature = self._saver_pick(now, ctx, features, saver)
            if card is not None:
                self.layer = SCREENSAVER_LAYER
                self.feature = feature
                self._face = state
                self._layer_since = now
                self._hold_until = 0.0
                return {"layer": SCREENSAVER_LAYER, "feature": feature,
                        "card": card, "face": state}
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
            self._busy_since = 0.0
            self._saver_since = 0.0
            self._saver_feature = None

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
            # 没内容 —— 回消息层挂着宠物形象
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

    def _saver_pick(self, now, ctx, features, saver):
        """忙了很久 —— 该上屏保了。

        返回 (card, feature)；不该上就返回 (None, None)。

        三条底线：
        - 门槛 0 = 关掉
        - 相册没照片 = 不上（屏上不能开天窗）
        - 设备在游戏里 = 不上（游戏画面更该留在屏上）
        """
        if self.screensaver_after_ms <= 0:
            return None, None
        if (now - self._busy_since) * 1000.0 < self.screensaver_after_ms:
            return None, None
        dev = (ctx or {}).get("device") or {}
        if str(dev.get("mode") or "idle") != "idle":
            return None, None
        if saver is None:
            return None, None
        try:
            card = saver.context(ctx)
        except Exception:
            log.warning("屏保取相册内容出错", exc_info=True)
            return None, None
        if not card or not card.get("photo"):
            return None, None
        self._saver_feature = saver
        self._saver_ctx = ctx
        if self.layer != SCREENSAVER_LAYER:
            # 刚上屏保 —— 先站住，住够时间再换下一张
            self._saver_since = now
            return card, saver
        if (now - self._saver_since) * 1000.0 >= self.screensaver_dwell_ms:
            try:
                saver.on_show(ctx)
                card = saver.context(ctx) or card
            except Exception:
                log.warning("屏保换照片出错", exc_info=True)
            self._saver_since = now
        return card, saver

    def _saver_photo_next(self):
        """屏保里转旋钮 —— 换下一张照片。"""
        f = self._saver_feature
        if f is None:
            return False
        try:
            f.on_show(self._saver_ctx)
        except Exception:
            log.warning("屏保换照片出错", exc_info=True)
            return False
        self._saver_since = time.time()
        return True

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
            # 换了一张卡 —— 住的时间重新算
            self._layer_since = now
            self._force_next = False
            card = self._reshow(f, ctx, name)
            if card:
                return card, f
        return None, None

    def _reshow(self, feature, ctx, name):
        """新的一段显示开始 —— 先让它准备，再取它的内容。

        on_show 是通用钩子：轮播切到它、或者同一张卡住够了一轮，
        都算「轮到它」。相册靠这个换下一张照片。

        内容要重新取一遍 —— 准备过程可能改了内容（相册换了图）。
        """
        try:
            on_show = getattr(feature, "on_show", None)
            if callable(on_show):
                on_show(ctx)
            return feature.context(ctx)
        except Exception:
            log.warning("feature %s 出错，跳过", name, exc_info=True)
            return None
