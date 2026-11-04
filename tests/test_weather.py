"""天气 feature：Open-Meteo 取数 + 城市解析。

以前这个 feature 用 wttr.in，解析器只认 dict，wttr.in 的报文里
nearest_area / current_condition 都是 list —— 解析出来全是空。
现在换成 Open-Meteo（和 inksight 同一套）：城市名 -> 经纬度 -> 天气。
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd.features import weather  # noqa: E402

SAMPLE = {
    "current": {
        "time": "2026-11-04T16:00",
        "temperature_2m": 15.2,
        "apparent_temperature": 14.2,
        "relative_humidity_2m": 68,
        "weather_code": 2,
    },
}


def test_num_rounds_and_tolerates_garbage():
    assert weather._num(15.2) == "15"
    assert weather._num("18.6") == "19"
    assert weather._num(None) == ""
    assert weather._num("abc") == ""


def test_builtin_city_table_resolves():
    lat, lon, label = weather._resolve("杭州")
    assert label == "杭州"
    assert 30 < lat < 31
    assert 120 < lon < 121


def test_city_suffix_is_stripped():
    lat, lon, label = weather._resolve("杭州市")
    assert label == "杭州"
    assert (lat, lon) == weather.CITY_COORDINATES["杭州"]


def test_blank_city_uses_default():
    lat, lon, label = weather._resolve("")
    assert label == weather.DEFAULT_CITY
    assert (lat, lon) == weather.CITY_COORDINATES[weather.DEFAULT_CITY]


def test_wmo_codes_all_have_chinese():
    """每一个 WMO 码都要有中文 —— 屏上不能出现 Unknown。"""
    for code in (0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67,
                 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99):
        cn = weather.WMO_CN.get(code)
        assert cn, code
        assert not any("a" <= ch.lower() <= "z" for ch in cn), (code, cn)


def test_city_table_covers_major_cities():
    for city in ("北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安"):
        assert city in weather.CITY_COORDINATES


def test_fetch_reads_payload(monkeypatch):
    """_fetch 拿到 Open-Meteo 的报文要解析出温度/体感/湿度/天气码。"""
    monkeypatch.setattr(weather, "_get_json", lambda url, params=None, timeout=8: SAMPLE)
    out = weather._fetch(30.27, 120.15)
    assert out["temp"] == "15"
    assert out["feels"] == "14"
    assert out["hum"] == "68"
    assert out["code"] == 2


def test_context_card_shape(monkeypatch):
    """天气卡长什么样 —— 有城市名、有大字温度、有中文描述。"""
    monkeypatch.setattr(weather, "_get_json", lambda url, params=None, timeout=8: SAMPLE)
    monkeypatch.setattr(weather, "_resolve", lambda city: (30.27, 120.15, "杭州"))
    f = weather.Weather()
    f.poll({"weatherCity": "杭州"})
    card = f.context({})
    assert card["title"] == "杭州"
    assert card["big"] == "15°"
    assert card["body"] == ["局部多云"]
    assert card["source"] == "Open-Meteo"
    assert [r["left"] for r in card["rows"]] == ["体感", "湿度"]
