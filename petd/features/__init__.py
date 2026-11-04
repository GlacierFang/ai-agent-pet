"""feature 注册表。

屏上「内容层」的来源。注册表只管「有哪些内容来源」，不管「什么时候上屏」
—— 那是屏上仲裁的事，见 petd/screen.py。

顺序就是轮播顺序：列表里排在前面的先上屏。不做用户自建，也不做排序 ——
要加内容就往 BUILTIN 里加一行。
"""
from .base import Feature
from . import clock, device, notify, recent_done, sessions, weather

# 注册顺序 = 轮播顺序
BUILTIN = [
    sessions.Sessions(),
    notify.Notify(),
    recent_done.RecentDone(),
    clock.Clock(),
    device.DeviceStatus(),
    weather.Weather(),
]


def all_features():
    """所有 feature。"""
    return list(BUILTIN)


def catalog():
    """给后台「空闲时显示什么」用的清单 —— 加一个 feature 这里自动多一项。"""
    return [{"name": f.name, "title": f.title, "tip": f.tip} for f in BUILTIN]
