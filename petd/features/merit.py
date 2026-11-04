"""「功德箱」—— agent 真把活干完一次 +1。

它是一个 feature：勾上它，屏上会显示功德计数。
累计值落在 config.json 的 ui.merit，重启不清零。

没干完过活就没什么好显示 —— 那时候这张卡不上屏。
"""

from .base import Feature


class Merit(Feature):
    name = "merit"
    title = "功德箱"
    tip = "agent 每次真把活干完 +1，屏上飘一句程序员玄学"
    priority = 20

    def context(self, ctx):
        merit = int(ctx.get("merit") or 0)
        if merit <= 0:
            # 还没干完过活 —— 没话可说，不占屏
            return None
        body = ["累计功德"]
        phrase = str(ctx.get("meritPhrase") or "")
        if phrase:
            body.append(phrase)
        return {
            "big": str(merit),
            "body": body,
            "state": "done",
            "source": self.title,
        }
