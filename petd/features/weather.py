"""「天气」—— 后台取数，渲染时只读缓存。

数据源 wttr.in：免费、不用密钥，首次调用按来源 IP 定位城市。
要指定城市就在 petd/data/config.json 的 ui.weatherCity 里写城市名。

渲染循环不碰网络 —— poll() 在后台线程里取数，context() 只读缓存。
"""
import json
import logging
import threading
import time
import urllib.request

from .base import Feature

log = logging.getLogger("petd.features.weather")

TTL_SEC = 900
URL_WITH_CITY = "https://wttr.in/{city}?format=j1"
URL_AUTO = "https://wttr.in/?format=j1"

_cache = {"at": 0.0, "data": None}
_lock = threading.Lock()


def _pick(payload, *path):
    cur = payload
    for key in path:
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(key)
    if isinstance(cur, list):
        cur = cur[0] if cur else ""
    if isinstance(cur, dict):
        cur = cur.get("value") or ""
    return str(cur or "")


def _fetch(city=""):
    url = URL_WITH_CITY.format(city=city) if city else URL_AUTO
    req = urllib.request.Request(url, headers={"User-Agent": "petd/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    return {
        "city": _pick(payload, "nearest_area", "areaName"),
        "desc": _pick(payload, "current_condition", "weatherDesc"),
        "temp": _pick(payload, "current_condition", "temp_C"),
        "feels": _pick(payload, "current_condition", "FeelsLikeC"),
        "hum": _pick(payload, "current_condition", "humidity"),
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
