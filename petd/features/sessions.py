"""「会话」—— 屏上正在跑什么。"""
from .base import Feature

STATE_CN = {
    "working": "在忙", "waiting": "等你", "done": "刚完成",
    "error": "出错", "idle": "闲着", "sleeping": "睡着",
}

# 急的排前面
ORDER = {"waiting": 0, "error": 1, "working": 2, "done": 3, "idle": 4}


class Sessions(Feature):
    name = "sessions"
    title = "会话"
    tip = "正在跑的会话和它们的状态"
    priority = 10

    def wants(self, state):
        return True

    def context(self, ctx):
        rows = list(ctx.get("sessions") or [])
        if not rows:
            return None
        focused = ctx.get("focused")
        rows.sort(key=lambda r: (0 if r.get("key") == focused else 1,
                                 ORDER.get(str(r.get("state") or "idle"), 9)))
        out = []
        for r in rows[:4]:
            out.append({
                "left": str(r.get("name") or r.get("key") or ""),
                "right": STATE_CN.get(str(r.get("state") or "idle"), "闲着"),
                "accent": str(r.get("state") or "idle"),
            })
        return {"title": "会话", "rows": out, "state": "idle",
                "source": "共 %d 个" % len(rows)}
