"""feature 注册表。

屏上「内容层」的来源。注册表只管「有哪些内容来源」，不管「什么时候上屏」
—— 那是屏上仲裁的事，见 petd/screen.py。

顺序就是轮播顺序：列表里排在前面的先上屏。不做用户自建，也不做排序 ——
要加内容就往 BUILTIN 里加一行。
"""
from .base import Feature
from . import album, clock, host, merit, notify, recent_done, sessions, weather

# 注册顺序 = 轮播顺序
BUILTIN = [
    sessions.Sessions(),
    notify.Notify(),
    recent_done.RecentDone(),
    merit.Merit(),
    clock.Clock(),
    host.HostStatus(),
    weather.Weather(),
    album.Album(),
]

# 功能清单的版本。新增功能时 +1，并把新加的名字记进 FEATURE_INTRO。
#
# 老用户的 config 里没有新功能的名字 —— 直接 normalize 会把它们悄悄关掉
# （骰子会直接失灵）。所以配置里记着「用户看过第几版」，
# 老配置升上来时把这一版新增的功能补上，补完记下版本。
# 之后用户自己勾掉，就真的是他的选择了，不会再被加回来。
FEATURES_VERSION = 4

FEATURE_INTRO = {
    1: ["sessions", "notify", "recent_done", "clock", "host"],
    2: ["merit", "dice"],
    3: ["album"],
    4: [],   # 第 4 版没有新增 —— 骰子搬去设备端了
}

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


def get(name):
    """按名字取 feature。找不到就是 None。

    按下标取会随注册表增减移位 —— 加一个功能就崩一片。按名字不会。
    """
    for f in BUILTIN:
        if f.name == name:
            return f
    return None


def reconcile(names, version):
    """把老配置补到当前版本。返回 (功能名单, 版本)。

    用户自己勾掉的不会被加回来 —— 版本记上了就说明他看过这一版。
    """
    out = set(normalize(names))
    try:
        ver = int(version)
    except (TypeError, ValueError):
        ver = 1
    # 版本 0 = 没记过版本的老配置 —— 按「看过第 1 版」算。
    # 第 1 版那批功能用户可能自己勾掉过，别全加回来。
    if ver < 1:
        ver = 1
    known = {f.name for f in BUILTIN}
    for v in range(ver + 1, FEATURES_VERSION + 1):
        for n in FEATURE_INTRO.get(v, []):
            if n in known:
                out.add(n)
    return out, FEATURES_VERSION


def catalog():
    """给后台「宠物设定」的功能段用 —— 加一个 feature 这里自动多一项。"""
    return [{"name": f.name, "title": f.title, "tip": f.tip} for f in BUILTIN]
