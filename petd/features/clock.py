"""「时间」—— 大字钟。"""
import datetime

from .base import Feature

WEEK_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


class Clock(Feature):
    name = "clock"
    title = "时间"
    tip = "当前时间和日期"
    priority = 5

    def wants(self, state):
        return True

    def context(self, ctx):
        now = float(ctx.get("now") or 0)
        if not now:
            return None
        dt = datetime.datetime.fromtimestamp(now)
        return {
            "title": "",
            "big": dt.strftime("%H:%M"),
            "body": ["%d月%d日 %s" % (dt.month, dt.day, WEEK_CN[dt.weekday()])],
            "state": "idle",
            "source": "本地时间",
        }
