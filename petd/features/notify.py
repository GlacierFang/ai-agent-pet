"""「通知」—— 未读消息和等你授权的事。"""
from .base import Feature


class Notify(Feature):
    name = "notify"
    title = "通知"
    tip = "未读消息和等你授权的事"
    priority = 20

    def wants(self, state):
        return True

    def context(self, ctx):
        rows = list(ctx.get("sessions") or [])
        items = []
        for r in rows:
            if r.get("pending"):
                items.append((r, "等你授权"))
            elif r.get("unread"):
                items.append((r, "有未读"))
        if not items:
            return None
        out = []
        for r, tag in items[:4]:
            out.append({"left": str(r.get("name") or r.get("key") or ""),
                        "right": tag, "accent": "waiting"})
        return {"title": "通知", "rows": out, "state": "waiting",
                "source": "%d 条" % len(items)}
