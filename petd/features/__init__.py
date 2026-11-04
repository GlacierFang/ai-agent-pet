"""feature 注册表。

屏上「内容层」的来源。注册表只管「有哪些内容来源」，不管「什么时候上屏」
—— 那是屏上仲裁的事，见 petd/screen.py。

顺序就是轮播顺序：列表里排在前面的先上屏。不做用户自建，也不做排序 ——
要加内容就往 BUILTIN 里加一行。
"""
from .base import Feature
from . import clock, host, notify, recent_done, sessions, weather

# 注册顺序 = 轮播顺序
BUILTIN = [
    sessions.Sessions(),
    notify.Notify(),
    recent_done.RecentDone(),
    clock.Clock(),
    host.HostStatus(),
    weather.Weather(),
]

# 老名字 -> 新名字。
# 「device」以前指的是那块 ESP32 屏（信号、固件、在线时长）—— 屏就在用户
# 面前，做成轮播卡没意义。现在改成「host」，看运行 petd 的这台机器。
ALIASES = {"device": "host"}


def normalize(names):
    """把老名字换成新名字，并去掉不认识的。"""
    known = {f.name for f in BUILTIN}
    out = set()
    for n in names or []:
        n = str(n).strip()
        n = ALIASES.get(n, n)
        if n in known:
            out.add(n)
    return out


def all_features():
    """所有 feature。"""
    return list(BUILTIN)


def catalog():
    """给后台「宠物设定」的功能段用 —— 加一个 feature 这里自动多一项。"""
    return [{"name": f.name, "title": f.title, "tip": f.tip} for f in BUILTIN]
