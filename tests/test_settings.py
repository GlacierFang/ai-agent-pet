"""功能清单接口（/admin/api/features）的单测。

功能清单列的每一项都必须**真的能改** —— 这是它和以前那份
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
        assert c.get("/admin/api/features").status_code == 401
        c.post("/admin/api/login", json={"password": "ceshi-mima-abc123"})
        assert c.get("/admin/api/features").status_code == 200


def test_features_shape(client):
    body = client.get("/admin/api/features").json()
    assert set(body.keys()) == {"items"}
    ids = [f["id"] for f in body["items"]]
    assert ids == ["features", "dwell", "hold", "sleep",
                   "density", "skin", "session"]


def test_each_feature_has_options(client):
    for f in client.get("/admin/api/features").json()["items"]:
        assert set(f.keys()) >= {"id", "name", "desc", "value", "options"}
        assert f["name"]
        assert f["options"], "每一项都得有可选项 —— 没得选就不叫清单"
        for o in f["options"]:
            assert set(o.keys()) == {"value", "label", "desc"}


def test_current_value_is_among_options(client):
    """当前值必须在可选项里 —— 否则页面显示不出「现在是哪个」。"""
    for f in client.get("/admin/api/features").json()["items"]:
        if f.get("multi"):
            # 多选项的 value 是数组 —— 每一项都得在可选项里
            for v in f["value"]:
                values = [str(o["value"]) for o in f["options"]]
                assert str(v) in values, f["id"]
            continue
        values = [str(o["value"]) for o in f["options"]]
        assert str(f["value"]) in values, f["id"]


def test_features_item_is_multi_select(client):
    """「空闲时显示什么」是多选 —— 选项就是全部 feature。"""
    items = {f["id"]: f for f in client.get("/admin/api/features").json()["items"]}
    f = items["features"]
    assert f["multi"] is True
    names = [o["value"] for o in f["options"]]
    assert "sessions" in names
    assert "clock" in names
    assert "weather" in names


def test_set_features_takes_effect(client):
    r = client.post("/admin/api/features",
                    json={"id": "features", "value": ["clock", "sessions"]})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.features_enabled == {"clock", "sessions"}


def test_set_features_ignores_unknown(client):
    """不存在的 feature 直接丢掉 —— 不能让一个坏名字进配置。"""
    r = client.post("/admin/api/features",
                    json={"id": "features", "value": ["clock", "nope"]})
    assert r.status_code == 200
    assert client.app.state.pet.features_enabled == {"clock"}


def test_set_dwell_takes_effect(client):
    r = client.post("/admin/api/features", json={"id": "dwell", "value": 12})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.card_dwell_sec == 12
    assert pet.director.content_dwell_ms == 12000


def test_set_hold_takes_effect(client):
    r = client.post("/admin/api/features", json={"id": "hold", "value": 5})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.message_hold_sec == 5
    assert pet.director.message_hold_ms == 5000


def test_sleep_is_one_item(client):
    """睡觉时段是**一项** —— 起止在一个卡里选，不拆成两张。"""
    items = {f["id"]: f for f in client.get("/admin/api/features").json()["items"]}
    f = items["sleep"]
    assert f["type"] == "timerange"
    assert f["from"] and f["to"]
    assert f["value"] == "%s-%s" % (f["from"], f["to"])


def test_set_sleep_window_takes_effect(client):
    r = client.post("/admin/api/features",
                    json={"id": "sleep", "value": "23:00-08:00"})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.sleep_start == "23:00"
    assert pet.sleep_end == "08:00"
    assert pet.sleep_enabled is True


def test_set_sleep_window_from_struct(client):
    """前端给结构体也认。"""
    r = client.post("/admin/api/features",
                    json={"id": "sleep", "value": {"from": "21:00", "to": "06:30"}})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.sleep_start == "21:00"
    assert pet.sleep_end == "06:30"


def test_sleep_can_be_turned_off(client):
    r = client.post("/admin/api/features",
                    json={"id": "sleep", "value": {"from": "22:00", "to": "07:00",
                                                  "enabled": False}})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.sleep_enabled is False
    assert pet.is_night() is False


def test_sleep_rejects_bad_time(client):
    r = client.post("/admin/api/features",
                    json={"id": "sleep", "value": "25:00-07:00"})
    assert r.status_code == 400


def test_sleep_accepts_midnight_as_end(client):
    """睡到午夜 —— 终点可以是 24:00。"""
    import time as _t
    r = client.post("/admin/api/features",
                    json={"id": "sleep", "value": "22:00-24:00"})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.sleep_end == "24:00"
    assert pet.is_night(_t.mktime((2026, 11, 4, 23, 30, 0, 0, 0, -1))) is True
    assert pet.is_night(_t.mktime((2026, 11, 4, 12, 0, 0, 0, 0, -1))) is False


def test_sleep_cross_midnight_is_night(client):
    """跨午夜 —— 两头算夜里，中间不算。"""
    import time as _t
    r = client.post("/admin/api/features",
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
    r = client.post("/admin/api/features",
                    json={"id": "sleep", "value": "22:00-22:00"})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.is_night(_t.mktime((2026, 11, 4, 22, 30, 0, 0, 0, -1))) is False


def test_set_density_takes_effect(client):
    r = client.post("/admin/api/features", json={"id": "density", "value": 2})
    assert r.status_code == 200
    assert client.app.state.pet.density == 2


def test_set_session_takes_effect(client):
    pet = client.app.state.pet
    pet.engine.update([{"key": "s1", "status": "running", "hasActiveRun": False,
                        "unread": False, "permissionModePending": False,
                        "isBackground": False, "lastActivityAt": 0}])
    r = client.post("/admin/api/features", json={"id": "session", "value": "s1"})
    assert r.status_code == 200
    assert pet.engine.selected_key == "s1"


def test_unknown_feature_rejected(client):
    r = client.post("/admin/api/features", json={"id": "nope", "value": "x"})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_unknown_skin_rejected(client):
    r = client.post("/admin/api/features", json={"id": "skin", "value": "nope"})
    assert r.status_code == 400


def test_logout_clears_cookie(monkeypatch):
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", "ceshi-mima-abc123")
    from starlette.testclient import TestClient
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        c.post("/admin/api/login", json={"password": "ceshi-mima-abc123"})
        assert c.get("/admin/api/features").status_code == 200
        assert c.post("/admin/api/logout").status_code == 200
        # 登出后必须进不去了 —— 不然「退出登录」只是个装饰
        assert c.get("/admin/api/features").status_code == 401


def test_public_setup_needs_no_auth(monkeypatch):
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", "ceshi-mima-abc123")
    from starlette.testclient import TestClient
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        r = c.get("/admin/api/setup/public")
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"mdns", "provisioning"}


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
