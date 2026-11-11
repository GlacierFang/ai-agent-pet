"""宠物设定接口（/admin/api/settings）的单测。

设定页列的每一项都必须**真的能改** —— 这是它和以前那份
capabilities.json 最大的区别。那份的 enabled 字段全仓没有任何地方读，
勾掉了什么也不会发生；这里每一项都对应服务端一个 setter。
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config  # noqa: E402
from petd.server import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """功能清单跟鉴权无关 —— 显式关掉鉴权，省得每个用例都先登录。"""
    from starlette.testclient import TestClient
    cfg = config.defaults()
    cfg["_repo_root"] = str(tmp_path)
    monkeypatch.setattr("petd.config.DATA_DIR", tmp_path)
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    with TestClient(create_app(cfg, start_gateway=False)) as c:
        yield c


def test_features_requires_auth_when_password_set(monkeypatch):
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", "ceshi-mima-abc123")
    from starlette.testclient import TestClient
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        assert c.get("/admin/api/settings").status_code == 401
        c.post("/admin/api/login", json={"password": "ceshi-mima-abc123"})
        assert c.get("/admin/api/settings").status_code == 200


def test_settings_shape(client):
    body = client.get("/admin/api/settings").json()
    assert set(body.keys()) == {"features", "settings"}
    names = [c["name"] for c in body["features"]]
    assert "sessions" in names
    assert "clock" in names
    assert "weather" in names
    ids = [s["id"] for s in body["settings"]]
    assert ids == ["dwell", "hold", "screensaver", "density", "brightness", "sleep"]


def test_feature_has_checkbox_and_tip(client):
    """能力 = 勾选框 + 一句说明 + 它自己的设定项。"""
    for c in client.get("/admin/api/settings").json()["features"]:
        assert set(c.keys()) >= {"name", "title", "tip", "enabled", "options"}
        assert c["title"]
        assert c["tip"], "每项能力都要说清它是干什么的"
        assert isinstance(c["enabled"], bool)


def test_each_setting_has_a_control_type(client):
    """每一项都该说清自己用哪种控件渲染。"""
    for s in client.get("/admin/api/settings").json()["settings"]:
        assert set(s.keys()) >= {"id", "name", "desc", "value", "type"}
        assert s["name"]
        assert s["type"] in ("number", "radio", "timerange")
        if s["type"] == "radio":
            values = [str(o["value"]) for o in s["options"]]
            assert str(s["value"]) in values, s["id"]
            for o in s["options"]:
                assert set(o.keys()) == {"value", "label", "desc"}


def test_dwell_and_hold_are_number_inputs(client):
    """时长让用户自己填 —— 不给固定选项。"""
    items = {s["id"]: s for s in client.get("/admin/api/settings").json()["settings"]}
    assert items["dwell"]["type"] == "number"
    assert items["hold"]["type"] == "number"
    assert items["dwell"]["min"] == 1
    assert items["hold"]["min"] == 0
    assert items["dwell"]["unit"] == "秒"


def test_sessions_feature_carries_session_choice(client):
    """「优先显示哪个会话」跟着会话能力走，不是独立一项。"""
    caps = {c["name"]: c for c in client.get("/admin/api/settings").json()["features"]}
    opts = caps["sessions"]["options"]
    assert len(opts) == 1
    assert opts[0]["id"] == "session"
    assert opts[0]["type"] == "select"


def test_weather_feature_carries_city(client):
    """天气城市以前没地方填 —— 现在跟着天气能力走。"""
    caps = {c["name"]: c for c in client.get("/admin/api/settings").json()["features"]}
    opts = caps["weather"]["options"]
    assert len(opts) == 1
    assert opts[0]["id"] == "weatherCity"
    assert opts[0]["type"] == "text"


def test_no_skin_option_in_settings(client):
    """换宠物在宠物库里点一下就行 —— 这页不重复一份。"""
    body = client.get("/admin/api/settings").json()
    ids = [s["id"] for s in body["settings"]]
    assert "skin" not in ids


def test_set_features_takes_effect(client):
    r = client.post("/admin/api/settings",
                    json={"id": "features", "value": ["clock", "sessions"]})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.features_enabled == {"clock", "sessions"}


def test_toggle_feature_reflects_in_payload(client):
    """勾掉一个能力 —— 返回的清单里它就不是勾上的了。"""
    client.post("/admin/api/settings",
                json={"id": "features", "value": ["clock", "sessions"]})
    body = client.post("/admin/api/settings",
                       json={"id": "features", "value": ["clock"]}).json()
    caps = {c["name"]: c for c in body["features"]}
    assert caps["clock"]["enabled"] is True
    assert caps["sessions"]["enabled"] is False


def test_set_weather_city_takes_effect(client):
    r = client.post("/admin/api/settings", json={"id": "weatherCity", "value": "杭州"})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.cfg["ui"]["weatherCity"] == "杭州"


def test_set_features_ignores_unknown(client):
    """不存在的 feature 直接丢掉 —— 不能让一个坏名字进配置。"""
    r = client.post("/admin/api/settings",
                    json={"id": "features", "value": ["clock", "nope"]})
    assert r.status_code == 200
    assert client.app.state.pet.features_enabled == {"clock"}


def test_set_dwell_takes_effect(client):
    r = client.post("/admin/api/settings", json={"id": "dwell", "value": 12})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.card_dwell_sec == 12
    assert pet.director.content_dwell_ms == 12000


def test_set_hold_takes_effect(client):
    r = client.post("/admin/api/settings", json={"id": "hold", "value": 5})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.message_hold_sec == 5
    assert pet.director.message_hold_ms == 5000


def test_sleep_is_one_item(client):
    """睡觉时段是**一项** —— 起止在一个卡里选，不拆成两张。"""
    items = {s["id"]: s for s in client.get("/admin/api/settings").json()["settings"]}
    f = items["sleep"]
    assert f["type"] == "timerange"
    assert f["from"] and f["to"]
    assert f["value"] == "%s-%s" % (f["from"], f["to"])


def test_set_sleep_window_takes_effect(client):
    r = client.post("/admin/api/settings",
                    json={"id": "sleep", "value": "23:00-08:00"})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.sleep_start == "23:00"
    assert pet.sleep_end == "08:00"
    assert pet.sleep_enabled is True


def test_set_sleep_window_from_struct(client):
    """前端给结构体也认。"""
    r = client.post("/admin/api/settings",
                    json={"id": "sleep", "value": {"from": "21:00", "to": "06:30"}})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.sleep_start == "21:00"
    assert pet.sleep_end == "06:30"


def test_sleep_can_be_turned_off(client):
    r = client.post("/admin/api/settings",
                    json={"id": "sleep", "value": {"from": "22:00", "to": "07:00",
                                                  "enabled": False}})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.sleep_enabled is False
    assert pet.is_night() is False


def test_sleep_rejects_bad_time(client):
    r = client.post("/admin/api/settings",
                    json={"id": "sleep", "value": "25:00-07:00"})
    assert r.status_code == 400


def test_sleep_accepts_midnight_as_end(client):
    """睡到午夜 —— 终点可以是 24:00。"""
    import time as _t
    r = client.post("/admin/api/settings",
                    json={"id": "sleep", "value": "22:00-24:00"})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.sleep_end == "24:00"
    assert pet.is_night(_t.mktime((2026, 11, 4, 23, 30, 0, 0, 0, -1))) is True
    assert pet.is_night(_t.mktime((2026, 11, 4, 12, 0, 0, 0, 0, -1))) is False


def test_sleep_cross_midnight_is_night(client):
    """跨午夜 —— 两头算夜里，中间不算。"""
    import time as _t
    r = client.post("/admin/api/settings",
                    json={"id": "sleep", "value": "22:00-07:00"})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.is_night(_t.mktime((2026, 11, 4, 23, 30, 0, 0, 0, -1))) is True
    assert pet.is_night(_t.mktime((2026, 11, 4, 2, 0, 0, 0, 0, -1))) is True
    assert pet.is_night(_t.mktime((2026, 11, 4, 12, 0, 0, 0, 0, -1))) is False
    assert pet.is_night(_t.mktime((2026, 11, 4, 7, 0, 0, 0, 0, -1))) is False


def test_sleep_start_equals_end_means_never(client):
    """起止相同 —— 不睡。"""
    import time as _t
    r = client.post("/admin/api/settings",
                    json={"id": "sleep", "value": "22:00-22:00"})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.is_night(_t.mktime((2026, 11, 4, 22, 30, 0, 0, 0, -1))) is False


def test_set_density_takes_effect(client):
    r = client.post("/admin/api/settings", json={"id": "density", "value": 2})
    assert r.status_code == 200
    assert client.app.state.pet.density == 2


def test_set_session_takes_effect(client):
    pet = client.app.state.pet
    pet.engine.update([{"key": "s1", "status": "running", "hasActiveRun": False,
                        "unread": False, "permissionModePending": False,
                        "isBackground": False, "lastActivityAt": 0}])
    r = client.post("/admin/api/settings", json={"id": "session", "value": "s1"})
    assert r.status_code == 200
    assert pet.engine.selected_key == "s1"


def test_unknown_setting_rejected(client):
    r = client.post("/admin/api/settings", json={"id": "nope", "value": "x"})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_dwell_accepts_any_number(client):
    """用户填多少就是多少 —— 不给固定的那几个选项。"""
    r = client.post("/admin/api/settings", json={"id": "dwell", "value": 7})
    assert r.status_code == 200
    assert client.app.state.pet.card_dwell_sec == 7


def test_logout_clears_cookie(monkeypatch):
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", "ceshi-mima-abc123")
    from starlette.testclient import TestClient
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        c.post("/admin/api/login", json={"password": "ceshi-mima-abc123"})
        assert c.get("/admin/api/settings").status_code == 200
        assert c.post("/admin/api/logout").status_code == 200
        # 登出后必须进不去了 —— 不然「退出登录」只是个装饰
        assert c.get("/admin/api/settings").status_code == 401


def test_public_setup_needs_no_auth(monkeypatch):
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", "ceshi-mima-abc123")
    from starlette.testclient import TestClient
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        r = c.get("/admin/api/setup/public")
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"mdns", "provisioning", "servers"}


def test_public_setup_hides_private_data(monkeypatch):
    """公开引导里不能有设备编号、会话数、帧数。"""
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", "ceshi-mima-abc123")
    from starlette.testclient import TestClient
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        body = c.get("/admin/api/setup/public").json()
    flat = repr(body)
    assert "steps" not in body
    assert "deviceId" not in flat
    assert "sessions" not in flat
