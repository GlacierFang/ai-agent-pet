"""「最近完成的事」—— 第一张真卡片。

零配置：不需要 API key，数据 petd 本来就有（网关给的会话列表）。

它同时是契约的活体测试：注册 → 有话说 → 上屏 → 没话说就下屏。
"""
import time

from .base import Feature

# 超过这个时间的「完成」就不值得占屏了 —— 屏上该有新鲜的事。
RECENT_WINDOW_MIN = 30


class RecentDone(Feature):
    name = "recent_done"
    title = "最近完成"
    tip = "刚做完的事"
    priority = 10

    def context(self, ctx):
        now = float(ctx.get("now") or time.time())
        sessions = ctx.get("sessions") or []
        best = None
        for row in sessions:
            # state 是 petd 判出来的宠物状态（done = 跑完了），
            # 不是上游的 status —— 上游没有「完成」这个概念。
            if row.get("state") != "done":
                continue
            ts = float(row.get("lastActivityAt") or 0)
            if not ts:
                continue
            if (now - ts) / 60.0 > RECENT_WINDOW_MIN:
                continue
            if best is None or ts > best[0]:
                best = (ts, row)
        if best is None:
            return None
        ts, row = best
        return {
            "title": str(row.get("name") or row.get("key") or ""),
            "body": ["刚刚做完", _ago(now - ts)],
            "state": "done",
            "source": self.title,
        }


def _ago(seconds):
    """多久之前。"""
    s = max(0, int(seconds))
    if s < 60:
        return "不到一分钟"
    if s < 3600:
        return "%d 分钟前" % (s // 60)
    if s < 86400:
        return "%d 小时前" % (s // 3600)
    return "%d 天前" % (s // 86400)
