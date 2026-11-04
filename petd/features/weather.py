"""「天气」—— 后台取数，渲染时只读缓存。

数据源 wttr.in：免费、不用密钥，首次调用按来源 IP 定位城市。
要指定城市就在后台「宠物设定」里填 —— 填中文城市名也行。

渲染循环不碰网络 —— poll() 在后台线程里取数，context() 只读缓存。
"""
import json
import logging
import threading
import time
import urllib.parse
import urllib.request

from .base import Feature

log = logging.getLogger("petd.features.weather")

TTL_SEC = 900
URL_WITH_CITY = "https://wttr.in/{city}?format=j1"
URL_AUTO = "https://wttr.in/?format=j1"

# wttr.in 只给英文描述，屏上全是中文 —— 在这里翻。
# 键是 wttr.in 的描述原文（小写匹配）。
DESC_CN = {
    "clear": "晴",
    "sunny": "晴",
    "partly cloudy": "多云转晴",
    "cloudy": "多云",
    "overcast": "阴",
    "mist": "薄雾",
    "fog": "雾",
    "patchy rain nearby": "局部有雨",
    "patchy snow nearby": "局部有雪",
    "patchy sleet nearby": "局部有雨夹雪",
    "patchy freezing drizzle nearby": "局部有冻毛毛雨",
    "patchy freezing rain nearby": "局部有冻雨",
    "patchy heavy snow nearby": "局部有大雪",
    "patchy heavy rain nearby": "局部有大雨",
    "patchy rain showers nearby": "局部有阵雨",
    "patchy light rain with thunder": "局部有雷阵雨",
    "patchy snow with thunder": "局部有雷雪",
    "light rain": "小雨",
    "light rain shower": "小阵雨",
    "light drizzle": "小毛毛雨",
    "light freezing drizzle": "轻微冻毛毛雨",
    "light sleet": "小雨夹雪",
    "light snow": "小雪",
    "light snow shower": "小阵雪",
    "moderate rain at times": "间歇性中雨",
    "moderate rain": "中雨",
    "moderate rain shower": "中阵雨",
    "moderate drizzle": "中毛毛雨",
    "moderate freezing drizzle": "中度冻毛毛雨",
    "moderate sleet": "中雨夹雪",
    "moderate snow at times": "间歇性中雪",
    "moderate snow": "中雪",
    "moderate snow shower": "中阵雪",
    "moderate or heavy snow showers": "中到大阵雪",
    "moderate or heavy snow with showers": "中到大雨夹雪",
    "dense drizzle": "密集毛毛雨",
    "dense freezing drizzle": "密集冻毛毛雨",
    "heavy rain at times": "间歇性大雨",
    "heavy rain": "大雨",
    "heavy rain shower": "大阵雨",
    "heavy freezing drizzle": "强冻毛毛雨",
    "heavy freezing rain": "强冻雨",
    "heavy sleet": "大雨夹雪",
    "heavy snow": "大雪",
    "heavy snow shower": "大阵雪",
    "freezing drizzle": "冻毛毛雨",
    "freezing rain": "冻雨",
    "blowing snow": "风雪",
    "blizzard": "暴风雪",
    "light rain with thunder": "雷阵雨",
    "heavy rain with thunder": "雷暴大雨",
    "light snow with thunder": "雷雪",
    "heavy snow with thunder": "雷暴大雪",
    "light sleet with thunder": "雷雨夹雪",
    "heavy sleet with thunder": "强雷雨夹雪",
    "moderate rain with thunder": "雷雨",
    "moderate snow with thunder": "雷雪",
    "patchy light rain with thunder nearby": "局部有雷阵雨",
    "thundery outbreaks possible": "可能有雷暴",
    "light showers of ice pellets": "轻微冰粒阵雨",
    "moderate or heavy showers of ice pellets": "中到大冰粒阵雨",
    "light snow grains": "小米粒",
    "moderate snow grains": "中米粒",
    "heavy snow grains": "大米粒",
    "light ice pellets": "小冰粒",
    "moderate ice pellets": "中冰粒",
    "heavy ice pellets": "大冰粒",
}

# 描述表里没有的，按关键词兜底。顺序有讲究 —— 先具体后笼统。
DESC_KEYWORDS = (
    ("thunder", "雷雨"),
    ("sleet", "雨夹雪"),
    ("hail", "冰雹"),
    ("ice pellets", "冰粒"),
    ("blizzard", "暴风雪"),
    ("blowing snow", "风雪"),
    ("snow", "雪"),
    ("drizzle", "毛毛雨"),
    ("freezing", "冻"),
    ("shower", "阵雨"),
    ("rain", "雨"),
    ("fog", "雾"),
    ("mist", "薄雾"),
    ("cloud", "多云"),
    ("clear", "晴"),
    ("sun", "晴"),
)

_cache = {"at": 0.0, "data": None}
_lock = threading.Lock()


def _pick(payload, *path):
    """按路径取值。

    wttr.in 的结构里 list 和 dict 混着长：nearest_area 是 list，
    里面那层是 dict，再里面又是 list。以前这份只认 dict，碰到 list
    直接返回空 —— 天气卡上什么都是空的。
    """
    cur = payload
    for key in path:
        if isinstance(cur, list):
            cur = cur[0] if cur else None
        if not isinstance(cur, dict) or key not in cur:
            return ""
        cur = cur[key]
    if isinstance(cur, list):
        cur = cur[0] if cur else ""
    if isinstance(cur, dict):
        cur = cur.get("value") or ""
    return str(cur or "")


def _desc_cn(en):
    """英文天气描述 -> 中文。"""
    low = str(en or "").strip().lower()
    if not low:
        return ""
    if low in DESC_CN:
        return DESC_CN[low]
    for kw, label in DESC_KEYWORDS:
        if kw in low:
            return label
    return ""


def _parse(payload):
    """wttr.in 的 j1 报文 -> 天气卡要用的几项。"""
    en = _pick(payload, "current_condition", "weatherDesc")
    return {
        "city": _pick(payload, "nearest_area", "areaName"),
        "desc": _desc_cn(en),
        "temp": _pick(payload, "current_condition", "temp_C"),
        "feels": _pick(payload, "current_condition", "FeelsLikeC"),
        "hum": _pick(payload, "current_condition", "humidity"),
    }


def _fetch(city=""):
    city = str(city or "").strip()
    if city:
        # 城市名可能是中文 —— 得编码，不然 urlopen 直接报错。
        url = URL_WITH_CITY.format(city=urllib.parse.quote(city))
    else:
        url = URL_AUTO
    req = urllib.request.Request(url, headers={"User-Agent": "petd/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    return _parse(payload)


class Weather(Feature):
    name = "weather"
    title = "天气"
    tip = "当前天气和温度"
    priority = 5

    def wants(self, state):
        return True

    def reset(self):
        """城市改了 —— 旧数据作废，重新取。"""
        with _lock:
            _cache["at"] = 0.0
            _cache["data"] = None

    def poll(self, ctx=None):
        """后台线程里调 —— 网络慢也不拖住渲染。"""
        with _lock:
            if _cache["data"] and (time.time() - _cache["at"]) < TTL_SEC / 2:
                return _cache["data"]
        city = ""
        if ctx:
            city = str(ctx.get("weatherCity") or "")
        try:
            data = _fetch(city)
        except Exception as exc:
            log.warning("天气取数失败: %s", exc)
            return None
        with _lock:
            _cache["at"] = time.time()
            _cache["data"] = data
        return data

    def context(self, ctx):
        with _lock:
            data = _cache["data"]
            at = _cache["at"]
        if not data or not at:
            return None
        if time.time() - at > TTL_SEC:
            return None
        rows = []
        if data.get("feels"):
            rows.append({"left": "体感", "right": data["feels"] + "°", "accent": "idle"})
        if data.get("hum"):
            rows.append({"left": "湿度", "right": data["hum"] + "%", "accent": "idle"})
        body = [data.get("desc") or ""] if data.get("desc") else []
        return {
            "title": data.get("city") or "天气",
            "big": (data.get("temp") or "") + "°" if data.get("temp") else "",
            "body": body,
            "rows": rows,
            "state": "idle",
            "source": "wttr.in",
        }
