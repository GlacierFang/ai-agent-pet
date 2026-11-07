"""设备消息处理不能掐断连接的测试。

设备回第一帧 frameAck 时，服务端会调 devices.ack()。这条路径以前抛过
AttributeError —— ack 只挂在 DeviceSession 上，manager 上没有，异常一路传到
WS 处理循环，把连接整个掐掉。设备 5 秒后重连、再收一帧、再被掐断。

后果：屏上偶尔更新，但旋钮事件刚发出去连接就断了，全被丢掉。
用户看到的现象是「旋钮不工作」，根因在服务端。

这两条断言都要能推翻「连接不会再被掐断」这个假设。
"""
import asyncio
import json
import pathlib
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config as config_mod  # noqa: E402
from petd import device as device_mod  # noqa: E402
from petd import render  # noqa: E402
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


def _jpeg():
    return render.render_frame(config_mod.defaults(), "idle")


def test_manager_ack_releases_inflight():
    """manager 上必须有 ack —— 生产代码调的就是它。

    以前 ack 只在 DeviceSession 上，app 拿的是 manager，
    设备回第一个 frameAck 就抛 AttributeError，连接被掐断。
    """
    ws = _FakeWs()
    session = device_mod.DeviceSession(ws, {})
    mgr = device_mod.DeviceManager()
    mgr.session = session

    asyncio.run(session.send_frame(_jpeg(), 1))
    assert session.inflight == 1

    asyncio.run(mgr.ack(1))
    assert session.inflight == 0, (
        "ACK 没把 inflight 减回去 —— 之后再也不推帧")
    assert 1 not in session.pending


def test_app_frame_ack_path_does_not_raise():
    """生产路径：app.on_device_message(frameAck) 不能抛。"""
    app = PetApp(config_mod.defaults())
    ws = _FakeWs()
    session = device_mod.DeviceSession(ws, {})
    app.devices.session = session

    asyncio.run(session.send_frame(_jpeg(), 5))
    asyncio.run(app.on_device_message(json.dumps({"type": "frameAck", "id": 5})))

    assert session.inflight == 0


def test_bad_device_message_does_not_drop_connection():
    """一条消息处理不了，不能连累整条连接。

    连接一断，旋钮事件就全被丢掉 —— 用户只看到「旋钮不工作」，
    却查不出是哪一条消息出的问题。
    """
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient

    from petd.server import create_app

    cfg = config_mod.defaults()
    cfg["_repo_root"] = str(ROOT)
    cfg["mdns"] = {"enabled": False}
    application = create_app(cfg, start_gateway=False, port=18877)

    with TestClient(application) as client:
        pet = application.state.pet
        seen = []

        async def flaky(raw):
            seen.append(raw)
            if len(seen) == 1:
                raise RuntimeError("故意炸一条")

        pet.on_device_message = flaky

        with client.websocket_connect("/device") as ws:
            ws.send_json({"type": "hello", "protocol": 1, "deviceId": "esp32s3-test"})
            hello = ws.receive_json()
            assert hello["type"] == "welcome"

            ws.send_json({"type": "frameAck", "id": 1})

            deadline = time.time() + 5
            while time.time() < deadline and not any(
                    "设备消息处理失败" in (e.get("msg") or "") for e in pet.logs):
                time.sleep(0.05)

            assert any("设备消息处理失败" in (e.get("msg") or "") for e in pet.logs), (
                "坏消息没被就地记下 —— 排查时会瞎猜")
            assert pet.devices.session is not None, (
                "一条消息处理不了就把连接掐断了 —— 旋钮事件会全被丢掉")
