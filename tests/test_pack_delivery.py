"""游戏包下发链路的测试。

背景：fw-v0.5.0 的设备在 WebSocket 回调栈里装游戏包 —— 回调栈只有 4KB，
解析 + 写 SPIFFS 撑爆栈，设备 panic 重启。重启后它报「本地没装这些包」，
后台又推一遍，于是设备在 CONNECTING 和宠物卡之间无限刷屏。

这两条防线要守住：
  1. 固件版本低于 0.5.1 的设备，一根 pack 都不下发。
  2. pack 本体走 binary —— 字节与文件里的一模一样，设备原样写盘，
     不在设备上重新序列化 JSON。
"""

import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config as config_mod  # noqa: E402
from petd import device as device_mod  # noqa: E402
from petd import packs as packs_mod  # noqa: E402
from petd.app import PetApp  # noqa: E402


class _FakeWs:
    """记录发了什么的假 WebSocket。"""

    def __init__(self):
        self.texts = []
        self.binaries = []

    async def send_text(self, s):
        self.texts.append(s)

    async def send_bytes(self, b):
        self.binaries.append(b)

    def json_texts(self):
        return [json.loads(t) for t in self.texts]


def _session(fw):
    ws = _FakeWs()
    return ws, device_mod.DeviceSession(ws, {"fw": fw, "deviceId": "esp32s3-test"})


# --------------------------------------------------------------------------
# 版本闸门
# --------------------------------------------------------------------------

def test_old_firmware_does_not_support_packs():
    """0.5.0 装包会重启 —— 必须判定为不支持。"""
    assert device_mod.fw_supports_packs("0.5.0") is False
    assert device_mod.fw_supports_packs("0.4.9") is False
    assert device_mod.fw_supports_packs("") is False
    assert device_mod.fw_supports_packs(None) is False


def test_new_firmware_supports_packs():
    assert device_mod.fw_supports_packs("0.5.1") is True
    assert device_mod.fw_supports_packs("0.6.0") is True
    assert device_mod.fw_supports_packs("1.0.0") is True


def test_version_parsing_is_robust():
    assert device_mod.fw_tuple("0.5.1") == (0, 5, 1)
    assert device_mod.fw_tuple("1.2") == (1, 2)
    assert device_mod.fw_tuple("garbage") == (0,)


# --------------------------------------------------------------------------
# pack 本体走 binary
# --------------------------------------------------------------------------

def test_pack_body_is_binary_and_byte_identical():
    """设备把 pack 原样写盘 —— 发过去的字节必须和文件里的一模一样。"""
    ws, session = _session("0.5.1")

    raw = packs_mod.read_pack("dice")
    assert raw, "仓库里应该有 dice pack"
    raw_bytes = raw.encode("utf-8")

    asyncio.run(session.send_pack("dice", 1, raw_bytes))

    preview = session.ws.json_texts()
    assert len(preview) == 1, preview
    assert preview[0]["type"] == "pack"
    assert preview[0]["id"] == "dice"
    assert preview[0]["bytes"] == len(raw_bytes)

    assert len(ws.binaries) == 1, ws.binaries
    assert ws.binaries[0] == raw_bytes, "pack 字节跟文件里的不一致"


def test_preview_and_body_are_adjacent():
    """预告和本体必须挨着 —— 设备靠预告判断下一条 binary 是 pack。"""
    ws, session = _session("0.5.1")
    asyncio.run(session.send_pack("dice", 1, b'{"id":"dice"}'))
    assert len(ws.texts) == 1
    assert len(ws.binaries) == 1


def test_frame_and_pack_do_not_interleave():
    """推帧和发包共用一把锁 —— 中间插一条别的 binary 设备就串包了。"""
    ws, session = _session("0.5.1")

    async def both():
        await session.send_frame(b"\xff\xd8jpegbytes", 1)
        await session.send_pack("dice", 1, b'{"id":"dice"}')

    asyncio.run(both())

    order = []
    for t in ws.texts:
        order.append(json.loads(t)["type"])
    # 两条预告的顺序是 frame -> pack，中间没有别的 binary
    assert order == ["frame", "pack"], order
    assert len(ws.binaries) == 2


# --------------------------------------------------------------------------
# 后台不下发给老固件
# --------------------------------------------------------------------------

def test_app_sends_no_pack_to_old_firmware():
    """老固件一根 pack 都不收 —— 这是防刷屏的第一道闸。"""
    app = PetApp(config_mod.defaults())
    ws, session = _session("0.5.0")
    app.devices.session = session

    ok = asyncio.run(app.send_pack("dice"))

    assert ok is False
    assert ws.binaries == [], "给老固件发了 pack —— 设备会重启"


def test_app_sends_pack_to_new_firmware():
    app = PetApp(config_mod.defaults())
    ws, session = _session("0.5.1")
    app.devices.session = session

    ok = asyncio.run(app.send_pack("dice"))

    assert ok is True
    assert len(ws.binaries) == 1
    assert ws.binaries[0] == packs_mod.read_pack("dice").encode("utf-8")


def test_handshake_gives_old_firmware_empty_game_list():
    """握手时给老固件空列表 —— 它就不会再要包。"""
    app = PetApp(config_mod.defaults())
    ws, session = _session("0.5.0")
    app.devices.session = session

    asyncio.run(app.on_device_connected())

    games = [m for m in ws.json_texts() if m.get("type") == "games"]
    assert games, ws.texts
    assert games[0]["enabled"] == [], games[0]


def test_handshake_gives_new_firmware_enabled_list():
    app = PetApp(config_mod.defaults())
    ws, session = _session("0.5.1")
    app.devices.session = session
    app.games_enabled = ["dice"]

    asyncio.run(app.on_device_connected())

    games = [m for m in ws.json_texts() if m.get("type") == "games"]
    assert games[0]["enabled"] == ["dice"], games[0]
