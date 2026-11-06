"""「赛博骰子」—— 短按旋钮摇一次。

骰子本体是屏上的一次性覆盖层（整屏是骰子，没有宠物形象），
这个 feature 管的是「要不要有骰子这回事」：勾上它，短按旋钮才弹骰子。
"""

from .base import Feature


class Dice(Feature):
    name = "dice"
    title = "赛博骰子"
    tip = "短按旋钮摇一次，整屏变骰子，滚 1.5 秒出结果"
    priority = 21

    def context(self, ctx):
        dice = ctx.get("dice") or {}
        if not dice.get("rolled"):
            return {
                "body": ["短按旋钮摇一次"],
                "state": "idle",
                "source": self.title,
            }
        return {
            "big": str(int(dice.get("value") or 0)),
            "body": ["上次摇出的点数"],
            "state": "idle",
            "source": self.title,
        }
