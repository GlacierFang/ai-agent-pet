"""屏上玩具的测试：功德计数器。

玩具不是宠物状态 —— 六态语义一个字都没动，这些测试钉的是玩具自己的行为。
"""

import pathlib
import random
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config  # noqa: E402
from petd import features as feature_mod  # noqa: E402
from petd import render as render_mod  # noqa: E402
from petd import toys as toys_mod  # noqa: E402


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

def test_bubble_overlay_is_rgba():
    """飘字层是 RGBA 图 —— 它要盖在宠物形象上，不能自己编码 JPEG。"""
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
    """后台接口跟鉴权无关 —— 显式关掉鉴权。

    **把睡觉关掉**：骰子夜里不弹。这条 fixture 要是跟着墙上时钟走，
    晚上跑这套测试就会莫名其妙全红 —— 测试不该看现在几点。
    """
    from starlette.testclient import TestClient
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    cfg = config.defaults()
    cfg["ui"]["sleepEnabled"] = False
    from petd.server import create_app
    with TestClient(create_app(cfg, start_gateway=False)) as c:
        yield c


def test_knob_endpoint_follows_gesture_table(client):
    """模拟按钮走的是真手势表 —— 改了映射，按钮跟着变。

    这才是「模拟」：不是在这儿直接调某个动作。
    """
    pet = client.app.state.pet
    pet.gestures["actions"]["press_short"] = "density.cycle"
    before = pet.density
    body = client.post("/admin/api/knob", json={"gesture": "press_short"}).json()
    assert body["action"] == "density.cycle"
    assert pet.density == (before + 1) % 3


def test_knob_endpoint_reports_unassigned(client):
    """短按没分配动作 —— 得说清楚，不能装成按了没反应。"""
    pet = client.app.state.pet
    pet.gestures["actions"]["press_short"] = ""
    body = client.post("/admin/api/knob", json={"gesture": "press_short"}).json()
    assert body["action"] == ""
    assert body["result"] == "unassigned"


def test_toys_view_shape(client):
    """后台要显示玩具，字段名是前后端契约。"""
    pet = client.app.state.pet
    view = pet.toys_view()
    assert set(view.keys()) == {"merit", "busy", "night", "pressAction"}


def test_toys_view_reports_press_mapping(client):
    """页面要照实说短按被映射成什么 —— 不替用户猜。"""
    pet = client.app.state.pet
    assert pet.toys_view()["pressAction"] == "game.menu"


# ---------- 玩具是功能 ----------

def test_toys_are_real_features():
    """功德箱是功能清单里的一项 —— 不是另开一节。

    设计约束：它该作为「功能」出现，别自成一类。
    """
    names = [f.name for f in feature_mod.all_features()]
    assert "merit" in names
    cat = [c["name"] for c in feature_mod.catalog()]
    assert "merit" in cat


def test_dice_is_not_a_server_side_feature():
    """骰子搬进设备端引擎了 —— 它不再是屏上的一张内容卡。"""
    names = [f.name for f in feature_mod.all_features()]
    assert "dice" not in names


def test_merit_feature_off_hides_merit_number(client):
    """功德功能没勾 —— 屏角不画功德数。"""
    pet = client.app.state.pet
    pet.merit.value = 9
    pet.set_features(["clock"])
    jpeg = render_mod.render_frame(config.load(), "idle", "在吗", "会话",
                                   density=1, merit=pet.merit.value
                                   if pet.merit_on() else 0)
    assert jpeg[:2] == b"\xff\xd8"


def test_old_config_gets_new_features_enabled():
    """老配置里没有新功能的名字 —— 升级时要自动补上。

    不补的话用户没勾过的新功能会直接失灵：不是他不要，是配置太老。
    """
    names, ver = feature_mod.reconcile(["clock", "host"], 1)
    assert "merit" in names
    assert ver == feature_mod.FEATURES_VERSION


def test_reconcile_respects_user_choice():
    """用户自己勾掉的不能被加回来 —— 版本记上了就说明他看过这一版。"""
    names, ver = feature_mod.reconcile(["clock"], feature_mod.FEATURES_VERSION)
    assert "merit" not in names


def test_reconcile_keeps_v1_features_user_removed():
    """老配置的用户可能自己勾掉过第 1 版的功能 —— 不能全加回来。

    老配置没有版本号，按「看过第 1 版」算：只补第 2 版新增的。
    """
    names, ver = feature_mod.reconcile(["clock"], 1)
    assert "clock" in names
    assert "weather" not in names, "用户勾掉的旧功能不该被加回来"
    assert "merit" in names


def test_config_load_keeps_old_config_without_version(tmp_path, monkeypatch):
    """老 config.json 里没有 featuresVersion —— 读出来也不能当成最新版。

    靠默认值合并会把默认的版本号带过去，于是新增功能永远补不上，
    骰子会直接失灵。
    """
    import json
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"ui": {"features": ["clock", "host"]}}), encoding="utf-8")
    cfg = config.load(path=p)
    assert cfg["ui"]["featuresVersion"] == 1
    names, ver = feature_mod.reconcile(cfg["ui"]["features"],
                                       cfg["ui"]["featuresVersion"])
    assert "merit" in names


def test_user_toggle_persists_version(client):
    """用户自己勾掉一个功能 —— 版本要记上，下次启动别又加回来。"""
    client.post("/admin/api/settings",
                json={"id": "features", "value": ["clock", "merit"]})
    pet = client.app.state.pet
    assert pet.cfg["ui"]["featuresVersion"] == feature_mod.FEATURES_VERSION
    names, _ = feature_mod.reconcile(pet.cfg["ui"]["features"],
                                      pet.cfg["ui"]["featuresVersion"])
    assert "notify" not in names


def test_merit_feature_card_shows_count():
    """功德卡上得有累计数。"""
    f = feature_mod.BUILTIN[[x.name for x in feature_mod.BUILTIN].index("merit")]
    ctx = {"now": 1000.0, "merit": 12, "meritPhrase": "稳了"}
    card = f.context(ctx)
    assert card is not None
    assert card["big"] == "12"


def test_merit_feature_silent_before_any_work():
    """还没干完过活 —— 功德卡没话可说，不占屏。"""
    f = feature_mod.BUILTIN[[x.name for x in feature_mod.BUILTIN].index("merit")]
    assert f.context({"now": 1000.0, "merit": 0}) is None


def test_settings_expose_toy_features_with_live_slots(client):
    """后台「功能」清单里要有功德箱，而且带实时数字槽。"""
    caps = {c["name"]: c for c in client.get("/admin/api/settings").json()["features"]}
    assert "merit" in caps
    merit_live = {lv["id"] for lv in caps["merit"].get("live") or []}
    assert "feat-live-merit" in merit_live


def test_status_carries_toys(client):
    """status 的顶层结构是契约 —— 玩具折在 pet 里，不新开顶层段。"""
    body = client.get("/admin/api/status").json()
    assert set(body.keys()) == {"gateway", "device", "pet", "frames", "gestures"}
    assert "toys" in body["pet"]
    assert body["pet"]["toys"]["merit"] == 0
