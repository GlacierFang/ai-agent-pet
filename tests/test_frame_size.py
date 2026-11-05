"""单帧大小护栏的测试。

设备端的接收缓冲是 32KB（firmware/main/proto.h 的 PETD_MAX_JPEG_BYTES）。
一帧超了，设备会丢帧，而且**不回 frameAck** —— 服务端的 inflight 永远减不回来，
之后再也不推帧，整台设备卡在上一帧。

所以这条护栏有两侧：渲染时别产出超限帧，推帧前也别放超限帧过去。
这两个断言都要能推翻「护栏真的挡住了」这个假设。
"""

import asyncio
import io
import pathlib
import sys

import pytest
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config as config_mod  # noqa: E402
from petd import device as device_mod  # noqa: E402
from petd import render  # noqa: E402


def _cfg():
    return config_mod.defaults()


class _FakeWs:
    """记录发了什么的假 WebSocket。"""

    def __init__(self):
        self.texts = []
        self.binaries = []

    async def send_text(self, s):
        self.texts.append(s)

    async def send_bytes(self, b):
        self.binaries.append(b)


# ---------- 渲染侧：别产出超限帧 ----------


def test_render_paths_stay_within_frame_limit():
    """所有渲染路径的输出都必须进得了设备缓冲区。

    这条能推翻「质量阶梯对每条路径都生效」—— 比如某条路径忘了走 _encode_jpeg。
    """
    cfg = _cfg()

    # 宠物帧
    jpeg = render.render_frame(cfg, "sleeping", "晚上好", "会话", 2)
    assert len(jpeg) <= render.MAX_FRAME_BYTES, (
        "宠物帧 %d 字节，超了 %d" % (len(jpeg), render.MAX_FRAME_BYTES))

    # 内容卡
    card = {"title": "标题", "big": "大字", "body": ["一", "二", "三"],
            "rows": [{"left": "左", "right": "右"}], "state": "idle",
            "source": "来源"}
    jpeg = render.render_card(cfg, card)
    assert len(jpeg) <= render.MAX_FRAME_BYTES, (
        "内容卡 %d 字节，超了 %d" % (len(jpeg), render.MAX_FRAME_BYTES))

    # 骰子
    jpeg = render.render_dice(cfg, value=6)
    assert len(jpeg) <= render.MAX_FRAME_BYTES, (
        "骰子 %d 字节，超了 %d" % (len(jpeg), render.MAX_FRAME_BYTES))


def test_photo_card_is_downscaled_when_too_big():
    """一张噪点照片 —— 未压缩时远超 32KB。

    噪点是 JPEG 最难压的输入：随机像素。如果这里还是超限，说明质量阶梯没起作用。
    """
    cfg = _cfg()

    # 造一张细节极多的图：RGB 噪点。
    import random
    rnd = random.Random(20261105)
    noisy = Image.new("RGB", (240, 320))
    noisy.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                   for _ in range(240 * 320)])

    path = pathlib.Path(config_mod.DATA_DIR) / "noisy.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    noisy.save(str(path))

    jpeg = render.render_photo_card(cfg, str(path), "1 / 1")
    assert jpeg is not None
    assert len(jpeg) <= render.MAX_FRAME_BYTES, (
        "噪点照片 %d 字节，超了 %d" % (len(jpeg), render.MAX_FRAME_BYTES))


def test_quality_drops_only_when_needed():
    """普通帧不该被无谓地降质量 —— 只有超限才降。

    这条能推翻「质量阶梯是不是把每一帧都压了一遍」。
    """
    cfg = _cfg()
    jpeg = render.render_frame(cfg, "idle")
    # 宠物帧在 q=85 下远小于上限。
    assert len(jpeg) < render.MAX_FRAME_BYTES * 0.7, (
        "普通帧 %d 字节被压得太狠了" % len(jpeg))


# ---------- 推送侧：超限的帧不许发出去 ----------


def test_oversized_frame_is_not_sent():
    """超限帧必须被拦在发送之前。

    这条是死锁的直接防线：发出去 = 设备丢帧不回 ACK = inflight 永远不减
    = 之后再也不推帧。
    """
    ws = _FakeWs()
    session = device_mod.DeviceSession(ws, {})

    oversized = b"\x00" * (render.MAX_FRAME_BYTES + 1)
    ok = asyncio.run(session.send_frame(oversized, 7))

    assert ok is False, "超限帧被发出去了"
    assert ws.binaries == [], "超限帧真的发到设备上了"
    assert ws.texts == [], "超限帧连预告都发了"
    # 关键：inflight 不能涨 —— 涨了服务端就会卡住
    assert session.inflight == 0, (
        "inflight 涨到 %d，服务端会永久停推" % session.inflight)


def test_normal_frame_is_sent_and_counted():
    """正常帧照发照计数 —— 拦过头也是 bug。

    这条能推翻「护栏是不是把正常帧也挡了」。
    """
    ws = _FakeWs()
    session = device_mod.DeviceSession(ws, {})

    jpeg = render.render_frame(_cfg(), "idle")
    ok = asyncio.run(session.send_frame(jpeg, 3))

    assert ok is True
    assert len(ws.binaries) == 1
    assert session.inflight == 1
    assert 3 in session.pending

    # ACK 回来之后 inflight 要减回去
    asyncio.run(session.ack(3))
    assert session.inflight == 0
    assert 3 not in session.pending


def test_limit_matches_device_buffer():
    """服务端的帧上限必须跟设备端的缓冲区一致。

    设备端是 firmware/main/proto.h 的 PETD_MAX_JPEG_BYTES。
    两边不一样的话，要么白降质量，要么还是超限。
    """
    proto = (ROOT / "firmware" / "main" / "proto.h").read_text(encoding="utf-8")
    assert "PETD_MAX_JPEG_BYTES" in proto, "proto.h 里找不到 PETD_MAX_JPEG_BYTES"
    line = [ln for ln in proto.splitlines() if "PETD_MAX_JPEG_BYTES" in ln
             and "define" in ln][0]
    assert "32 * 1024" in line, (
        "设备端帧上限变了：%s —— 服务端的 %d 要跟着改"
        % (line.strip(), render.MAX_FRAME_BYTES))
    assert render.MAX_FRAME_BYTES == 32 * 1024
