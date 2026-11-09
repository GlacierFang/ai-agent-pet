"""屏上的玩具：功德计数器。

玩具**不是宠物状态**。宠物有六态（idle/working/waiting/done/error/sleeping），
语义在 docs/状态语义.md 里定死了。玩具不进那套语义：

  · 功德 +1 是飘过屏上的一行字 —— 它不改变宠物在干什么

好处：状态机一个字节不动，状态优先级也不用重排
（状态优先级曾经写反过一次 —— 玩具不进那套语义，不动它是省事，不是偷懒）。
"""

import random
import time

# 功德飘字停留时长（毫秒）
MERIT_BUBBLE_MS = 2600

# 程序员玄学短句 —— 功德 +1 时飘一句。本地文案，不联网。
MYSTIC_PHRASES = (
    "阿弥陀佛",
    "佛祖保佑",
    "玄学护体",
    "码到功成",
    "一行不改",
    "心诚则灵",
    "随缘过了",
    "编译通过",
    "积少成多",
    "稳了",
    "香火不断",
    "离大谱了",
)


class Merit:
    """功德计数器 —— agent 干完一次活 +1。

    数值要活过重启，所以落盘（config.json 的 merit 字段）。
    """

    def __init__(self, value=0, rng=None):
        self.value = max(0, int(value or 0))
        self._rng = rng if rng is not None else random.Random()
        self._last_phrase = ""
        self._bubble = None

    def add(self, now=None):
        """+1。返回这次的飘字内容。"""
        now = time.time() if now is None else now
        self.value += 1
        phrase = self._pick_phrase()
        self._bubble = {
            "text": "功德 +1",
            "phrase": phrase,
            "born": now,
            "until": now + MERIT_BUBBLE_MS / 1000.0,
        }
        return self._bubble

    def _pick_phrase(self):
        # 别连着两句一样 —— 连着两次「阿弥陀佛」看着像卡了。
        phrase = self._last_phrase
        for _ in range(8):
            phrase = self._rng.choice(MYSTIC_PHRASES)
            if phrase != self._last_phrase:
                break
        self._last_phrase = phrase
        return phrase

    def last_phrase(self):
        """上一句玄学 —— 屏上那张功德卡要显示它。"""
        return self._last_phrase

    def bubble(self, now=None):
        """当前飘字；没有或者过期了返回 None。"""
        now = time.time() if now is None else now
        b = self._bubble
        if not b:
            return None
        if now >= b["until"]:
            self._bubble = None
            return None
        return b
