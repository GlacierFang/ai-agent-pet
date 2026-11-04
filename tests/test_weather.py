"""天气 feature 的解析。

以前 _pick() 只认 dict，wttr.in 的报文里 nearest_area / current_condition
都是 list —— 解析出来全是空，天气卡上什么都是空的。
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd.features import weather  # noqa: E402

SAMPLE = {
    "current_condition": [{
        "temp_C": "18",
        "FeelsLikeC": "17",
        "humidity": "60",
        "weatherCode": "353",
        "weatherDesc": [{"value": "Light drizzle"}],
    }],
    "nearest_area": [{
        "areaName": [{"value": "Hangzhou"}],
        "country": [{"value": "China"}],
    }],
}


def test_pick_walks_lists_and_dicts():
    assert weather._pick(SAMPLE, "current_condition", "temp_C") == "18"
    assert weather._pick(SAMPLE, "current_condition", "weatherDesc") == "Light drizzle"
    assert weather._pick(SAMPLE, "nearest_area", "areaName") == "Hangzhou"


def test_pick_missing_path_returns_empty():
    assert weather._pick({}, "current_condition", "temp_C") == ""
    assert weather._pick({"a": []}, "a", "b") == ""
    assert weather._pick(SAMPLE, "current_condition", "nope") == ""


def test_parse_extracts_every_field():
    out = weather._parse(SAMPLE)
    assert out["city"] == "Hangzhou"
    assert out["temp"] == "18"
    assert out["feels"] == "17"
    assert out["hum"] == "60"


def test_desc_is_chinese():
    assert weather._desc_cn("Clear") == "晴"
    assert weather._desc_cn("Light drizzle") == "小毛毛雨"
    assert weather._desc_cn("Patchy rain nearby") == "局部有雨"
    assert weather._desc_cn("") == ""


def test_desc_never_leaks_english():
    """屏上不能出现英文描述 —— 查一遍常用描述。"""
    for en in ("Clear", "Partly cloudy", "Cloudy", "Light rain",
               "Moderate rain", "Heavy rain", "Light snow", "Heavy snow",
               "Patchy rain nearby", "Thundery outbreaks possible"):
        cn = weather._desc_cn(en)
        assert cn, en
        assert not any("a" <= ch.lower() <= "z" for ch in cn), (en, cn)


def test_chinese_city_is_url_encoded():
    """中文城市名不能直接拼进 URL —— urlopen 会报 UnicodeEncodeError。"""
    import urllib.parse
    assert urllib.parse.quote("杭州") == "%E6%9D%AD%E5%B7%9E"
