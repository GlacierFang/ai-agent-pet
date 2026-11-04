"""「设备」—— 这块屏自己的状态。"""
from .base import Feature


def _dur(seconds):
    s = max(0, int(seconds))
    if s < 60:
        return "%d 秒" % s
    if s < 3600:
        return "%d 分钟" % (s // 60)
    if s < 86400:
        return "%d 小时" % (s // 3600)
    return "%d 天" % (s // 86400)


class DeviceStatus(Feature):
    name = "device"
    title = "设备"
    tip = "连接状态、信号和在线时长"
    priority = 5

    def wants(self, state):
        return True

    def context(self, ctx):
        dev = ctx.get("device") or {}
        if not dev.get("online"):
            return None
        rows = []
        fw = str(dev.get("fw") or "")
        if fw:
            rows.append({"left": "固件", "right": fw, "accent": "idle"})
        rssi = dev.get("rssi")
        if rssi:
            rows.append({"left": "信号", "right": "%d dBm" % int(rssi), "accent": "idle"})
        up = int(dev.get("uptime") or 0)
        if up:
            rows.append({"left": "在线", "right": _dur(up), "accent": "idle"})
        if not rows:
            return None
        return {"title": "设备", "rows": rows, "state": "idle", "source": "petd"}
