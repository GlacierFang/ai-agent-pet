"""OTA 下发的流控测试。

真机现象：「OTA 下发中断在第 16 片」，而且每次断的片数都不一样
（实测 16 / 20 / 26 / 29 片）。

根因是服务端没有流控：3.2 秒把 1MB 固件全灌过去，设备的 OTA 收包队列
只有 4 深，写 flash 又慢 —— 队列一满，WS 收包任务就被堵死，连接断掉。

这里钉住两件事：
  1. 服务端必须**等设备确认**这一片进了 flash，才发下一片。
  2. 确认必须是 0..N **连续**的 —— 上一轮迟到的确认不能填掉中间的空缺，
     否则看起来像连续，镜像就写坏了。
"""
import asyncio
import pathlib
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import device as device_mod  # noqa: E402
from petd import ota as ota_mod  # noqa: E402


class _FakeWs:
    def __init__(self):
        self.texts = []
        self.binaries = []

    async def send_text(self, s):
        self.texts.append(s)

    async def send_bytes(self, b):
        self.binaries.append(b)


# --------------------------------------------------------------------------
# 确认语义
# --------------------------------------------------------------------------

def test_ack_marks_chunk_received():
    sess = device_mod.DeviceSession(_FakeWs(), {})
    sess.note_ota_ack(0)
    assert sess.ota_ack_ready(0) is True
    assert sess.ota_ack_ready(1) is False


def test_ack_must_be_contiguous():
    """只确认了第 2 片、第 1 片没确认 —— 不算连续，不能放行。

    上一轮迟到的确认会把中间的空缺填上，看起来像连续，
    服务端就以为中间那片也写进 flash 了 —— 镜像直接写坏。
    """
    sess = device_mod.DeviceSession(_FakeWs(), {})
    sess.note_ota_ack(0)
    sess.note_ota_ack(2)
    assert sess.ota_ack_ready(1) is False
    assert sess.ota_ack_ready(2) is False


def test_ack_from_other_round_is_ignored():
    """上一轮 OTA 迟到的确认不能算数。"""
    sess = device_mod.DeviceSession(_FakeWs(), {})
    sess.reset_ota_ack(round=2)
    sess.note_ota_ack(5, round=1)
    assert sess.ota_ack_ready(5) is False
    sess.note_ota_ack(5, round=2)
    assert sess.ota_ack_ready(5) is False   # 中间 0..4 没确认


def test_wait_ack_returns_true_when_acked():
    sess = device_mod.DeviceSession(_FakeWs(), {})

    async def go():
        sess.note_ota_ack(0)
        return await sess.wait_ota_ack(0, timeout=1)

    assert asyncio.run(go()) is True


def test_wait_ack_times_out_without_ack():
    sess = device_mod.DeviceSession(_FakeWs(), {})

    async def go():
        return await sess.wait_ota_ack(0, timeout=0.05)

    assert asyncio.run(go()) is False


def test_wait_ack_fails_fast_after_disconnect():
    """设备断了就别再傻等 —— 立刻返回 False。"""
    sess = device_mod.DeviceSession(_FakeWs(), {})

    async def go():
        sess.note_closed()
        return await sess.wait_ota_ack(0, timeout=30)

    assert asyncio.run(go()) is False


def test_wait_ack_gives_up_quickly_when_device_drops_mid_transfer():
    """传输中途断开 —— 别白等满 30 秒。

    设备掉线时服务端的 detach 会给 session 打 note_closed；
    等确认的循环必须立刻退出，不然每片都要等满超时。
    """
    sess = device_mod.DeviceSession(_FakeWs(), {})

    async def go():
        async def drop():
            await asyncio.sleep(0.05)
            sess.note_closed()
        asyncio.ensure_future(drop())
        t0 = time.monotonic()
        ok = await sess.wait_ota_ack(0, timeout=30)
        return ok, time.monotonic() - t0

    ok, elapsed = asyncio.run(go())
    assert ok is False
    assert elapsed < 2.0, "断开后不该再等满 30 秒"


# --------------------------------------------------------------------------
# 下发流程：必须等确认
# --------------------------------------------------------------------------

class _FakeDevices:
    """记下每次发片的时刻，以及「发之前设备确认到哪了」。"""

    def __init__(self, ack_delay=0.0, device_fw="0.5.7", device_state="idle"):
        self.sent = []
        self.acked_upto = -1
        self.round = 0
        self.ack_delay = ack_delay
        self.session = device_mod.DeviceSession(_FakeWs(), {})
        self.session.fw = device_fw
        self.session.ota_state = device_state

    def next_ota_round(self):
        self.round += 1
        return self.round

    async def reset_ota_ack(self, rnd=None):
        self.acked_upto = -1
        self.session.reset_ota_ack(rnd)

    async def send_ota_start(self, version, size, rnd=None):
        self.session.ota_round = rnd if rnd is not None else 0
        return True

    async def send_ota_chunk(self, seq, data):
        self.sent.append((seq, self.acked_upto))
        return True

    async def wait_ota_ack(self, seq, timeout):
        # 模拟设备写完 flash 才确认
        await asyncio.sleep(self.ack_delay)
        self.acked_upto = seq
        self.session.note_ota_ack(seq, self.session.ota_round)
        return True

    async def send_ota_finish(self):
        return True


def _app_with(devices, firmware=b"x" * 4096):
    from petd.app import PetApp
    from petd import config as config_mod
    app = PetApp(config_mod.defaults())
    app.devices = devices
    return app, firmware


def test_upgrade_waits_for_ack_before_next_chunk(monkeypatch):
    """发第 N+1 片之前，第 N 片必须已经被设备确认。"""
    devices = _FakeDevices()
    app, firmware = _app_with(devices)
    monkeypatch.setattr(ota_mod, "read_firmware", lambda v: firmware)

    ok, err = asyncio.run(app.start_ota_upgrade("0.5.8"))
    assert ok is True, err

    # 每一片发出去时，设备确认到的最大 seq 必须正好是上一片
    for idx, (seq, acked) in enumerate(devices.sent):
        if idx == 0:
            assert acked == -1
        else:
            assert acked == seq - 1, f"第 {seq} 片发出时只确认到 {acked}"


def test_upgrade_sends_every_chunk(monkeypatch):
    devices = _FakeDevices()
    app, firmware = _app_with(devices)
    monkeypatch.setattr(ota_mod, "read_firmware", lambda v: firmware)

    ok, err = asyncio.run(app.start_ota_upgrade("0.5.8"))
    assert ok is True, err
    expected = (len(firmware) + ota_mod.CHUNK_SIZE - 1) // ota_mod.CHUNK_SIZE
    assert len(devices.sent) == expected
    assert [s for s, _ in devices.sent] == list(range(expected))


def test_upgrade_stops_when_device_reports_error(monkeypatch):
    """设备报 ok=false 就得停 —— 别把坏数据继续推。"""

    class _FailDevices(_FakeDevices):
        async def wait_ota_ack(self, seq, timeout):
            self.acked_upto = seq
            self.session.note_ota_ack(seq, self.session.ota_round)
            if seq == 0:
                self.session.ota_error = "写入失败"
            return True

    devices = _FailDevices()
    app, firmware = _app_with(devices)
    monkeypatch.setattr(ota_mod, "read_firmware", lambda v: firmware)

    ok, err = asyncio.run(app.start_ota_upgrade("0.5.8"))
    assert ok is False
    assert "写入失败" in err
    assert len(devices.sent) == 1


def test_upgrade_refuses_when_device_stuck_on_old_firmware(monkeypatch):
    """设备卡在上一轮 OTA，而固件又不会中途重来 —— 说清楚要断电重启。"""
    devices = _FakeDevices(device_fw="0.5.7", device_state="downloading")
    devices.session.ota_percent = 24
    app, firmware = _app_with(devices)
    monkeypatch.setattr(ota_mod, "read_firmware", lambda v: firmware)

    ok, err = asyncio.run(app.start_ota_upgrade("0.5.8"))
    assert ok is False
    assert "断电重启" in err


def test_upgrade_allowed_when_device_can_restart_ota(monkeypatch):
    """新固件会自己作废上一轮 —— 那就能直接重来。"""
    devices = _FakeDevices(device_fw="0.5.9", device_state="downloading")
    devices.session.ota_percent = 24
    app, firmware = _app_with(devices)
    monkeypatch.setattr(ota_mod, "read_firmware", lambda v: firmware)

    ok, err = asyncio.run(app.start_ota_upgrade("0.5.10"))
    assert ok is True, err
    assert len(devices.sent) >= 1


# --------------------------------------------------------------------------
# 版本门槛
# --------------------------------------------------------------------------

def test_restart_ota_gate():
    assert ota_mod.fw_can_restart_ota("0.5.7") is False
    assert ota_mod.fw_can_restart_ota("0.5.8") is False
    assert ota_mod.fw_can_restart_ota("0.5.9") is True
    assert ota_mod.fw_can_restart_ota("0.6.0") is True
    assert ota_mod.fw_can_restart_ota("") is False

