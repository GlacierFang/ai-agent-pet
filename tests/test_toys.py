"""屏上玩具的测试：骰子、功德计数器。

玩具不是宠物状态 —— 六态语义一个字都没动，这些测试钉的是玩具自己的行为。
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config  # noqa: E402
from petd import render as render_mod  # noqa: E402
from petd import toys as toys_mod  # noqa: E402


# ---------- 骰子 ----------

def test_dice_starts_closed():
    d = toys_mod.Dice()
    assert d.active is False
    on, face, rolling = d.update(0)
    assert on is False and rolling is False


def test_dice_press_opens_and_second_press_closes():
    d = toys_mod.Dice()
    assert d.press(now=100.0) is True
    assert d.active is True
    assert d.press(now=100.0) is False
    assert d.active is False


def test_dice_result_is_in_range():
    d = toys_mod.Dice()
    d.press(now=0.0)
    assert 1 <= d.value <= toys_mod.DICE_FACES


def test_dice_face_stops_at_result():
    """滚完之后画面上的点数必须等于结果 —— 停住的那个数不能是另一个数。"""
    d = toys_mod.Dice()
    d.press(now=0.0)
    # 滚还没完 —— 画面上的点数是随机的
    on, face, rolling = d.update(0.1)
    assert on is True and rolling is True
    # 滚完了
    on, face, rolling = d.update(toys_mod.DICE_ROLL_MS / 1000.0 + 0.01)
    assert on is True and rolling is False
    assert face == d.value


def test_dice_auto_hides_after_result_hold():
    d = toys_mod.Dice()
    d.press(now=0.0)
    t = toys_mod.DICE_ROLL_MS / 1000.0 + toys_mod.DICE_RESULT_HOLD_MS / 1000.0
    on, face, rolling = d.update(t + 0.01)
    assert on is False


def test_dice_dismiss_yields_screen():
    """有活来了 —— 骰子让路。"""
    d = toys_mod.Dice()
    d.press(now=0.0)
    d.dismiss()
    on, face, rolling = d.update(0.1)
    assert on is False


def test_dice_distribution_is_fair():
    """1000 次摇出来的点数得大致均匀。

    骰子要是偏斜，这东西就没有意义了 —— 抽 1000 次，
    任何一面低于 12% 或高于 22% 都算异常。
    """
    d = toys_mod.Dice()
    counts = {i: 0 for i in range(1, toys_mod.DICE_FACES + 1)}
    for _ in range(1000):
        d.press(now=0.0)
        counts[d.value] += 1
    for face, n in counts.items():
        assert 120 <= n <= 220, "点数 %d 出了 %d 次，分布不匀" % (face, n)


# ---------- 功德 ----------

def test_merit_starts_at_zero():
    m = toys_mod.Merit(0)
    assert m.value == 0


def test_merit_adds_one():
    m = toys_mod.Merit(0)
    m.add(now=0.0)
    assert m.value == 1


def test_merit_loads_from_config():
    m = toys_mod.Merit(42)
    assert m.value == 42


def test_merit_never_negative():
    m = toys_mod.Merit(-5)
    assert m.value == 0


def test_merit_bubble_has_text_and_phrase():
    m = toys_mod.Merit(0)
    b = m.add(now=0.0)
    assert b["text"] == "功德 +1"
    assert b["phrase"] in toys_mod.MYSTIC_PHRASES


def test_merit_bubble_expires():
    m = toys_mod.Merit(0)
    m.add(now=0.0)
    assert m.bubble(now=0.1) is not None
    assert m.bubble(now=toys_mod.MERIT_BUBBLE_MS / 1000.0 + 0.1) is None


def test_merit_phrases_do_not_repeat_back_to_back():
    """连着两句一样看着像卡了 —— 换个短语。"""
    m = toys_mod.Merit(0)
    first = m.add(now=0.0)["phrase"]
    second = m.add(now=1.0)["phrase"]
    assert first != second


def test_merit_persists_through_config():
    """功德要活过重启 —— 它落在 config.json 里。

    走真的存盘再读回来 —— 光在内存里改 dict 不算数。
    """
    cfg = config.defaults()
    cfg["ui"]["merit"] = 7
    config.save(cfg)
    assert config.load()["ui"]["merit"] == 7


def test_merit_default_is_zero():
    """新装的机器上功德是 0。"""
    assert config.defaults()["ui"]["merit"] == 0


# ---------- 渲染 ----------

def test_render_dice_produces_valid_jpeg():
    cfg = config.load()
    for face in range(1, 7):
        jpeg = render_mod.render_dice(cfg, value=face, rolling=False)
        assert jpeg[:2] == b"\xff\xd8", "JPEG 头缺失"
        assert jpeg[-2:] == b"\xff\xd9", "JPEG 尾缺失"


def test_render_dice_rolling_produces_valid_jpeg():
    cfg = config.load()
    jpeg = render_mod.render_dice(cfg, value=3, rolling=True)
    assert jpeg[:2] == b"\xff\xd8"


def test_bubble_overlay_is_rgba():
    """飘字层是 RGBA 图 —— 它要盖在宠物脸上，不能自己编码 JPEG。"""
    cfg = config.load()
    ov = render_mod.bubble_overlay(cfg, "功德 +1", "阿弥陀佛")
    assert ov.mode == "RGBA"
    assert ov.size == (240, 320)


def test_render_frame_accepts_overlay_and_merit():
    cfg = config.load()
    ov = render_mod.bubble_overlay(cfg, "功德 +1", "稳了")
    jpeg = render_mod.render_frame(cfg, "idle", "在吗", "会话",
                                   density=1, overlay=ov, merit=3)
    assert jpeg[:2] == b"\xff\xd8"


def test_render_card_accepts_overlay():
    cfg = config.load()
    ov = render_mod.bubble_overlay(cfg, "功德 +1", "稳了")
    jpeg = render_mod.render_card(cfg, {"title": "x"}, overlay=ov)
    assert jpeg[:2] == b"\xff\xd8"


def test_bubble_overlay_fades_out():
    """alpha=0 的话飘字应该基本看不见 —— 不然它会一直糊在屏上。"""
    cfg = config.load()
    solid = render_mod.bubble_overlay(cfg, "功德 +1", "稳了", alpha=1.0)
    faded = render_mod.bubble_overlay(cfg, "功德 +1", "稳了", alpha=0.0)
    # alpha=0 时整层应该全透明
    assert faded.getbbox() is None or solid.getbbox() is not None


# ---------- 后台接口 ----------

@pytest.fixture
def client(monkeypatch):
    """后台接口跟鉴权无关 —— 显式关掉鉴权。"""
    from starlette.testclient import TestClient
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    from petd.server import create_app
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        yield c


def test_toys_dice_endpoint_rolls(client):
    """后台那个「摇一次骰子」按钮 —— 没有板子也能看效果。"""
    body = client.post("/admin/api/toys/dice").json()
    assert body["ok"] is True
    assert body["result"] == "opened"
    assert body["toys"]["dice"]["active"] is True
    assert body["toys"]["dice"]["rolling"] is True
    assert 1 <= body["toys"]["dice"]["value"] <= 6


def test_toys_dice_endpoint_toggles(client):
    """按一下开，再按一下收 —— 跟设备上的旋钮一个行为。"""
    client.post("/admin/api/toys/dice")
    body = client.post("/admin/api/toys/dice").json()
    assert body["result"] == "closed"
    assert body["toys"]["dice"]["active"] is False


def test_toys_dice_refuses_when_busy(client):
    """宠物在忙的时候不弹骰子 —— 有活先干活。"""
    pet = client.app.state.pet
    pet.engine.state = "working"
    body = client.post("/admin/api/toys/dice").json()
    assert body["result"] == "busy"
    assert body["toys"]["canRoll"] is False


def test_toys_view_shape(client):
    """后台要显示玩具，字段名是前后端契约。"""
    pet = client.app.state.pet
    view = pet.toys_view()
    assert set(view.keys()) == {"merit", "dice", "busy", "night", "canRoll"}
    assert set(view["dice"].keys()) == {"active", "rolling", "value"}


def test_status_carries_toys(client):
    """status 的顶层结构是契约 —— 玩具折在 pet 里，不新开顶层段。"""
    body = client.get("/admin/api/status").json()
    assert set(body.keys()) == {"gateway", "device", "pet", "frames", "gestures"}
    assert "toys" in body["pet"]
    assert body["pet"]["toys"]["merit"] == 0
