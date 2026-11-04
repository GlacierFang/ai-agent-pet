"""屏上的玩具：骰子、功德计数器。

玩具**不是宠物状态**。宠物有六态（idle/working/waiting/done/error/sleeping），
语义在 docs/状态语义.md 里定死了。玩具不进那套语义：

  · 骰子出现时整屏是骰子，宠物脸不画 —— 它是一次性覆盖层，不是第七态
  · 功德 +1 是飘过屏上的一行字 —— 它不改变宠物在干什么

好处：状态机一个字节不动，状态优先级也不用重排
（上一轮刚修过一次优先级写反的 bug —— 不动它是省事，不是偷懒）。
"""

import random
import time

# 骰子滚动时长（毫秒）—— 滚完就停，出结果。
DICE_ROLL_MS = 1500
# 出结果后停多久 —— 到点自动收起。再按一次旋钮也能立刻收起。
DICE_RESULT_HOLD_MS = 4000
# 功德飘字停留时长（毫秒）
MERIT_BUBBLE_MS = 2600

DICE_FACES = 6

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


class Dice:
    """骰子 —— 一次性覆盖层。

    按一下开，再按一下收；有活来了自动收。
    结果在摇定的那一刻就抽好了 —— 滚动中换的只是画面。
    """

    def __init__(self, rng=None):
        self._rng = rng if rng is not None else random.Random()
        self.active = False
        self.rolling = False
        self.value = 1
        self._face = 1
        # 两个截止时刻都在按下的那一刻定好 —— 不随观察到的帧往后挪。
        # 否则单帧落在两个截止点之间时，骰子会多显示一整个 HOLD。
        self._roll_until = 0.0
        self._hide_until = 0.0

    def press(self, now=None):
        """按一下旋钮。第一次开骰子，再按收起。返回 True = 现在占着屏。"""
        now = time.time() if now is None else now
        if self.active:
            self.active = False
            self.rolling = False
            return False
        self.active = True
        self.rolling = True
        self.value = self._rng.randint(1, DICE_FACES)
        self._face = self._rng.randint(1, DICE_FACES)
        self._roll_until = now + DICE_ROLL_MS / 1000.0
        self._hide_until = self._roll_until + DICE_RESULT_HOLD_MS / 1000.0
        return True

    def dismiss(self):
        """有活来了 —— 骰子让路。"""
        self.active = False
        self.rolling = False

    def update(self, now=None):
        """推进到当前时刻。返回 (占屏中, 显示的点数, 还在滚)。"""
        now = time.time() if now is None else now
        if not self.active:
            return False, 0, False
        if now >= self._hide_until:
            self.active = False
            self.rolling = False
            return False, 0, False
        if now < self._roll_until:
            self._face = self._rng.randint(1, DICE_FACES)
            return True, self._face, True
        return True, self.value, False


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
