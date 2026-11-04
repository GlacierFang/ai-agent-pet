"""「天气」—— 后台取数，渲染时只读缓存。

数据源 Open-Meteo：免费、不用密钥，按经纬度取。
城市名先查内置城市表，查不到再拿 Open-Meteo 的地理编码接口解析。

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

TTL_SEC = 1800          # 天气 30 分钟不变 —— 不用每次都问
GEO_TTL_SEC = 86400     # 城市名 -> 坐标，一天内不重复查

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

# 天气城市。地理编码只认地级市（「杭州市西湖区」查不到），
# 所以常见城市直接内置，省一次请求也省一次猜错。
CITY_COORDINATES = {
    "北京": (39.90, 116.40),
    "上海": (31.23, 121.47),
    "广州": (23.13, 113.26),
    "深圳": (22.54, 114.06),
    "杭州": (30.27, 120.15),
    "南京": (32.06, 118.80),
    "成都": (30.57, 104.07),
    "重庆": (29.56, 106.55),
    "武汉": (30.59, 114.31),
    "西安": (34.26, 108.94),
    "苏州": (31.30, 120.62),
    "天津": (39.13, 117.20),
    "长沙": (28.23, 112.94),
    "郑州": (34.75, 113.65),
    "青岛": (36.07, 120.38),
    "大连": (38.91, 121.60),
    "厦门": (24.48, 118.09),
    "昆明": (25.04, 102.68),
    "合肥": (31.82, 117.23),
    "福州": (26.07, 119.30),
    "哈尔滨": (45.75, 126.65),
    "沈阳": (41.80, 123.43),
    "济南": (36.65, 116.99),
    "石家庄": (38.04, 114.51),
    "长春": (43.88, 125.32),
    "南昌": (28.68, 115.86),
    "贵阳": (26.65, 106.63),
    "南宁": (22.82, 108.32),
    "太原": (37.87, 112.55),
    "兰州": (36.06, 103.83),
    "海口": (20.04, 110.35),
    "银川": (38.49, 106.23),
    "西宁": (36.62, 101.78),
    "呼和浩特": (40.84, 111.75),
    "乌鲁木齐": (43.83, 87.62),
    "拉萨": (29.65, 91.13),
    "香港": (22.32, 114.17),
    "澳门": (22.20, 113.55),
    "台北": (25.03, 121.57),
    "东京": (35.68, 139.69),
    "首尔": (37.57, 126.98),
    "新加坡": (1.35, 103.82),
    "纽约": (40.71, -74.01),
    "伦敦": (51.51, -0.13),
    "巴黎": (48.86, 2.35),
    "悉尼": (-33.87, 151.21),
    "温哥华": (49.28, -123.12),
    "旧金山": (37.77, -122.42),
}

DEFAULT_CITY = "上海"

# WMO 天气码 -> 中文。Open-Meteo 给的是码，不是描述。
WMO_CN = {
    0: "晴",
    1: "大致晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    56: "轻冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "轻冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米粒雪",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "大阵雪",
    95: "雷阵雨",
    96: "雷阵雨伴冰雹",
    99: "强雷阵雨伴冰雹",
}

_cache = {"at": 0.0, "data": None}
_geo_cache = {}
_lock = threading.Lock()


def _num(value):
    """取个整数出来。取不到就空字符串 —— 屏上不显示 0 度的假数据。"""
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return ""


def _get_json(url, params=None, timeout=8):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "petd/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _geocode(name):
    """城市名 -> (lat, lon, 显示名)。先查国内，再查全球。"""
    for extra in ({"countryCode": "CN"}, {}):
        params = {"name": name, "count": 1, "language": "zh", "format": "json"}
        params.update(extra)
        data = _get_json(GEOCODING_URL, params)
        results = data.get("results") or []
        if results:
            r = results[0]
            return float(r["latitude"]), float(r["longitude"]), str(r.get("name") or name)
    return None


def _resolve(city):
    """城市名 -> (lat, lon, 显示名)。查不到就用默认城市。"""
    name = str(city or "").strip()
    if not name:
        return CITY_COORDINATES[DEFAULT_CITY][0], CITY_COORDINATES[DEFAULT_CITY][1], DEFAULT_CITY
    if name in CITY_COORDINATES:
        lat, lon = CITY_COORDINATES[name]
        return lat, lon, name
    # 「杭州市」这种带后缀的，剥掉再试
    simple = name[:-1] if name.endswith("市") else name
    if simple in CITY_COORDINATES:
        lat, lon = CITY_COORDINATES[simple]
        return lat, lon, simple
    hit = _geo_cache.get(name)
    if hit and time.time() - hit[2] < GEO_TTL_SEC:
        return hit[0], hit[1], hit[3]
    try:
        found = _geocode(name)
    except Exception as exc:
        log.warning("城市「%s」查不到坐标: %s", name, exc)
        found = None
    if not found:
        return (CITY_COORDINATES[DEFAULT_CITY][0],
                CITY_COORDINATES[DEFAULT_CITY][1], DEFAULT_CITY)
    lat, lon, label = found
    _geo_cache[name] = (lat, lon, time.time(), label)
    return lat, lon, label


def _fetch(lat, lon):
    """Open-Meteo 的当前天气。"""
    data = _get_json(FORECAST_URL, {
        "latitude": round(float(lat), 4),
        "longitude": round(float(lon), 4),
        "current": "temperature_2m,apparent_temperature,"
                   "relative_humidity_2m,weather_code",
        "timezone": "auto",
    })
    cur = data.get("current") or {}
    try:
        code = int(cur.get("weather_code"))
    except (TypeError, ValueError):
        code = -1
    return {
        "temp": _num(cur.get("temperature_2m")),
        "feels": _num(cur.get("apparent_temperature")),
        "hum": _num(cur.get("relative_humidity_2m")),
        "code": code,
    }


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
            lat, lon, label = _resolve(city)
            data = _fetch(lat, lon)
        except Exception as exc:
            log.warning("天气取数失败: %s", exc)
            return None
        data["city"] = label
        data["desc"] = WMO_CN.get(data["code"], "未知")
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
            "source": "Open-Meteo",
        }
