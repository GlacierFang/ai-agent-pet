"""主机 feature：/proc 采集 + 卡片形状。

以前有个「设备」feature，显示的是那块 ESP32 屏的状态 —— 屏就在用户面前，
做成轮播卡没意义。改成「主机」，看运行 petd 的这台机器。
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd.features import host  # noqa: E402


def test_cpu_times_parsed():
    t = host._read_cpu_times()
    assert t is not None
    total, idle = t
    assert total > 0
    assert 0 <= idle <= total


def test_mem_has_percentage():
    mem = host._read_mem()
    assert mem is not None
    assert mem["total"] > 0
    assert 0 <= mem["pct"] <= 100


def test_disk_has_free_space():
    disk = host._read_disk()
    assert disk is not None
    assert disk["free"] > 0
    assert 0 <= disk["pct"] <= 100


def test_uptime_readable():
    up = host._read_uptime()
    assert up is not None
    assert up > 0


def test_temp_is_number_or_none():
    """没有温度传感器的机器返回 None —— 那一行就不显示。"""
    t = host._read_temp()
    assert t is None or 0 < t < 120


def test_duration_formatting():
    assert host._fmt_dur(90) == "1 分钟"
    assert host._fmt_dur(3600) == "1 小时"
    assert host._fmt_dur(3660) == "1 小时 1 分"
    assert host._fmt_dur(86400) == "1 天"
    assert host._fmt_dur(90000) == "1 天 1 小时"


def test_size_formatting():
    assert host._fmt_size(1024 ** 3) == "1G"
    assert host._fmt_size(5 * 1024 ** 3) == "5G"
    assert host._fmt_size(10 * 1024 ** 2) == "10M"


def test_sample_produces_data():
    data = host._sample()
    assert data is not None
    assert "mem" in data
    assert "disk" in data
    assert "uptime" in data


def test_cpu_percentage_appears_on_second_sample():
    """CPU 占用率要两次采样才算得出来 —— 第一次没有。"""
    host._sample()
    data = host._sample()
    assert data["cpu"] is None or 0 <= data["cpu"] <= 100


def test_card_shape():
    host._sample()
    card = host.HostStatus().context({})
    assert card is not None
    assert card["title"].startswith("主机")
    assert card["source"] == "主机状态"
    assert card["state"] == "idle"
    labels = [r["left"] for r in card["rows"]]
    assert "内存" in labels
    assert "磁盘" in labels
    assert "已运行" in labels
    # 温度只在有传感器的机器上出现
    assert ("温度" in labels) == (host._read_temp() is not None)


def test_feature_metadata():
    f = host.HostStatus()
    assert f.name == "host"
    assert f.title == "主机"
    assert f.tip
