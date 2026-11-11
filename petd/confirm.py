"""确认卡 —— 开发中的选择题回到屏上。

场景：AI 在改代码时遇到岔路，需要人拍板。以前这件事只有一条路 ——
回聊天窗口打字。现在可以把这道题推到桌上那块屏，人转旋钮选一下。

一张卡：
    问题（一句话）+ 2~4 个选项 + 超时

手势（服务端定义，不用刷固件）：
    旋转 → 切换选项
    短按 → 确认
    长按 → 取消

回程：
    答完之后答案交给 on_answer 回调 —— 默认注回发起方的 gateway 会话，
    AI 下一次读上下文就能看到「用户选了 B」，不用人再打字说一遍。

边界（第一版）：
    - 只支持选项，不支持自由文本输入（旋钮打字太痛苦）
    - 确认卡只回答问题，不直接触发破坏性动作
    - 最多同时挂 3 张（最多 3 个会话各 1 张），超了顶掉最旧的
    - 同一个会话只留最新的一张：再问新问题就顶掉自己的旧问题
    - 屏上显示当前会话的卡；当前会话没有卡时才回退到别的会话的卡
"""
import logging
import time
import uuid

log = logging.getLogger("petd.confirm")

# 超时：5 分钟。开发中的人可能走开了，卡不能一直占着屏。
DEFAULT_TIMEOUT_SEC = 300
# 队列上限：顶掉最旧的。人一次最多能同时想清楚几件事？
MAX_QUEUE = 3
# 选项上限：旋钮一屏放不下更多。
MAX_OPTIONS = 4
MIN_OPTIONS = 2
# 文字上限：屏只有 240x320。
MAX_QUESTION_LEN = 60
MAX_OPTION_LEN = 24

STATUS_PENDING = "pending"
STATUS_ANSWERED = "answered"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"
STATUS_SUPERSEDED = "superseded"


class ConfirmError(Exception):
    """发起确认失败 —— 带上能给人看的原因。"""


class ConfirmCard:
    """一张待答的卡。"""

    def __init__(self, question, options, session_key="", timeout_sec=0,
                 card_id=None, source=""):
        self.id = card_id or uuid.uuid4().hex[:12]
        self.question = question
        self.options = list(options)
        self.session_key = session_key or ""
        self.source = source or ""
        self.timeout_sec = int(timeout_sec) or DEFAULT_TIMEOUT_SEC
        self.created_at = time.time()
        self.deadline = self.created_at + self.timeout_sec
        self.selected = 0
        self.status = STATUS_PENDING
        self.answer = ""
        self.answered_at = 0.0

    def expired(self, now=None):
        if self.status != STATUS_PENDING:
            return False
        return (now or time.time()) >= self.deadline

    def remaining(self, now=None):
        return max(0.0, self.deadline - (now or time.time()))

    def snapshot(self):
        return {
            "id": self.id,
            "question": self.question,
            "options": list(self.options),
            "selected": self.selected,
            "status": self.status,
            "answer": self.answer,
            "sessionKey": self.session_key,
            "source": self.source,
            "timeoutSec": self.timeout_sec,
            "remainingSec": int(self.remaining()),
            "createdAt": int(self.created_at),
        }


class ConfirmManager:
    """确认卡的队列 + 状态机。

    屏上永远只显示队首那张。答完（确认/取消）才轮到下一张。
    """

    def __init__(self, on_answer=None, timeout_sec=0, max_queue=0):
        self.on_answer = on_answer
        self.timeout_sec = int(timeout_sec) or DEFAULT_TIMEOUT_SEC
        self.max_queue = int(max_queue) or MAX_QUEUE
        # 焦点会话 —— 屏上优先显示它自己的卡。宠物跟着你正在聊的会话走。
        self.focus_session = ""
        self._cards = []

    def set_focus(self, session_key):
        """当前用户正在看的会话。切会话时跟着切。"""
        self.focus_session = str(session_key or "")

    # ---------- 发起 ----------
    def push(self, question, options, session_key="", timeout_sec=0,
             source="", card_id=None):
        """加一张卡。返回 (card, "")。出错抛 ConfirmError。"""
        q = str(question or "").strip()
        if not q:
            raise ConfirmError("问题不能为空")
        if len(q) > MAX_QUESTION_LEN:
            q = q[:MAX_QUESTION_LEN - 1] + "…"
        opts = []
        for o in (options or []):
            s = str(o or "").strip()
            if not s:
                continue
            if len(s) > MAX_OPTION_LEN:
                s = s[:MAX_OPTION_LEN - 1] + "…"
            opts.append(s)
        if len(opts) < MIN_OPTIONS:
            raise ConfirmError("至少要 %d 个选项" % MIN_OPTIONS)
        if len(opts) > MAX_OPTIONS:
            opts = opts[:MAX_OPTIONS]

        # 同一个会话再问新的 —— 顶掉它自己的旧问题。
        # 开发中一个人在一个会话里可能连问三道岔路，三张卡全占着屏，
        # 别的会话的卡就永远轮不到。同一会话只留最新那张。
        if session_key:
            for old in list(self._cards):
                if old.session_key == session_key:
                    log.info("确认卡 %s 被同会话的新问题取代", old.id)
                    self._finish(old, STATUS_SUPERSEDED, "")
                    self._notify(old, "")

        # 顶掉最旧的：人不可能一直不管。
        self.expire_due()
        while len(self._cards) >= self.max_queue:
            old = self._cards.pop(0)
            log.info("确认卡队列满了，顶掉最旧的一张: %s", old.id)
            self._finish(old, STATUS_EXPIRED, "")

        card = ConfirmCard(q, opts, session_key=session_key,
                           timeout_sec=timeout_sec, card_id=card_id,
                           source=source)
        self._cards.append(card)
        log.info("确认卡已发起: %s %s", card.id, q)
        return card, ""

    # ---------- 屏上操作 ----------
    def current(self):
        """当前该显示哪张卡。

        优先焦点会话自己的卡；没有的话回退到队首 ——
        别的会话的卡不能因为排队就饿死。
        """
        self.expire_due()
        if not self._cards:
            return None
        if self.focus_session:
            for c in self._cards:
                if c.session_key == self.focus_session:
                    return c
        return self._cards[0]

    def rotate(self, steps):
        """转旋钮 —— 切换选项。返回当前卡，没有卡返回 None。"""
        card = self.current()
        if card is None:
            return None
        if not steps:
            return card
        n = len(card.options)
        card.selected = (card.selected + int(steps)) % n
        log.info("确认卡 %s 选中第 %d 项: %s",
                 card.id, card.selected, card.options[card.selected])
        return card

    def confirm(self):
        """短按 —— 确认当前选项。返回 (card, "")。"""
        card = self.current()
        if card is None:
            return None, "没有待答的确认卡"
        pick = card.options[card.selected]
        self._finish(card, STATUS_ANSWERED, pick)
        self._notify(card, pick)
        return card, ""

    def cancel(self):
        """长按 —— 取消当前卡。返回 (card, "")。"""
        card = self.current()
        if card is None:
            return None, "没有待答的确认卡"
        self._finish(card, STATUS_CANCELLED, "")
        self._notify(card, "")
        return card, ""

    def answer_card(self, card_id, answer_text=None):
        """指定回答某一张卡（后台/远程用）。返回 (卡, 错误信息)。

        answer_text 为空 = 用当前选中的那项。
        """
        card = self.find(card_id)
        if card is None:
            return None, "没有这张卡"
        if card.status != STATUS_PENDING:
            return card, "这张卡已经结束了"
        if answer_text is None:
            pick = card.options[card.selected]
        else:
            pick = str(answer_text)
            if pick not in card.options:
                return None, "这个答案不在选项里"
        self._finish(card, STATUS_ANSWERED, pick)
        self._notify(card, pick)
        return card, ""

    def cancel_card(self, card_id):
        """取消指定的一张卡。返回 (卡, 错误信息)。"""
        card = self.find(card_id)
        if card is None:
            return None, "没有这张卡"
        if card.status != STATUS_PENDING:
            return card, "这张卡已经结束了"
        self._finish(card, STATUS_CANCELLED, "")
        self._notify(card, "")
        return card, ""

    # ---------- 队列 ----------
    def expire_due(self):
        """把过期的标成 expired 并移出队列。返回被过期掉的卡。"""
        now = time.time()
        dead = [c for c in self._cards if c.expired(now)]
        if not dead:
            return []
        self._cards = [c for c in self._cards if not c.expired(now)]
        for c in dead:
            log.info("确认卡超时未答: %s %s", c.id, c.question)
            self._finish(c, STATUS_EXPIRED, "")
            self._notify(c, "")
        return dead

    def list_cards(self):
        return [c.snapshot() for c in self._cards]

    def find(self, card_id):
        for c in self._cards:
            if c.id == card_id:
                return c
        return None

    # ---------- 内部 ----------
    def _finish(self, card, status, answer):
        card.status = status
        card.answer = answer
        card.answered_at = time.time()
        if card in self._cards:
            self._cards.remove(card)

    def _notify(self, card, answer):
        """把结果交给回调（默认注回发起方会话）。回调失败不影响状态机。"""
        if not self.on_answer:
            return
        try:
            self.on_answer(card, answer)
        except Exception:
            log.exception("确认卡回程失败: %s", card.id)
