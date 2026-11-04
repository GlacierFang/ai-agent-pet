"""宠物自己冒出来的一句话。

只在空闲时出现 —— 有事等你确认时它不该插嘴。频次有上限：话痨会变成噪音，
用户三秒后就想把它关掉。

台词是本地的，不依赖 gateway —— 设备脱网也得活着。
"""
import random
import time

LINES = (
    "今天也挺好的。",
    "我在。",
    "有事随时叫我。",
    "要不要歇会儿？",
    "就待着挺好。",
    "外面怎么样？",
    "刚忙完一阵。",
)

MIN_INTERVAL_S = 600
MAX_INTERVAL_S = 1800


class Chatter:
    """闲话调度器。"""

    def __init__(self, lines=None, min_interval=MIN_INTERVAL_S,
                 max_interval=MAX_INTERVAL_S, rng=None, started=None):
        self.lines = list(lines or LINES)
        self.min_interval = int(min_interval)
        self.max_interval = max(max_interval, self.min_interval)
        self.rng = rng or random.Random()
        self._started = float(started) if started is not None else time.time()
        self._next_at = self._started + self.min_interval
        self._last_line = ""

    def maybe(self, now=None, state="idle"):
        """该说一句就返回一句，否则 None。"""
        if state != "idle":
            return None
        now = float(now if now is not None else time.time())
        if now < self._next_at:
            return None
        pool = [l for l in self.lines if l != self._last_line] or list(self.lines)
        line = self.rng.choice(pool)
        self._last_line = line
        self._next_at = now + self.rng.randint(self.min_interval, self.max_interval)
        return line
