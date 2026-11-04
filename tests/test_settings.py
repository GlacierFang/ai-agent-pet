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
    assert ids == ["page", "density", "skin", "session", "sleep"]


def test_each_feature_has_options(client):
    for f in client.get("/admin/api/features").json()["items"]:
        assert set(f.keys()) == {"id", "name", "desc", "value", "options"}
        assert f["name"]
        assert f["options"], "每一项都得有可选项 —— 没得选就不叫清单"
        for o in f["options"]:
            assert set(o.keys()) == {"value", "label", "desc"}


def test_current_value_is_among_options(client):
    """当前值必须在可选项里 —— 否则页面显示不出「现在是哪个」。"""
    for f in client.get("/admin/api/features").json()["items"]:
        values = [str(o["value"]) for o in f["options"]]
        assert str(f["value"]) in values, f["id"]


def test_set_page_takes_effect(client):
    r = client.post("/admin/api/features", json={"id": "page", "value": "session"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    pet = client.app.state.pet
    assert pet.page == "session"


def test_set_density_takes_effect(client):
    r = client.post("/admin/api/features", json={"id": "density", "value": 2})
    assert r.status_code == 200
    assert client.app.state.pet.density == 2


def test_set_sleep_minutes_takes_effect(client):
    r = client.post("/admin/api/features", json={"id": "sleep", "value": 30})
    assert r.status_code == 200
    pet = client.app.state.pet
    assert pet.engine.sleep_after_min == 30
    assert pet.cfg["state"]["sleepAfterMin"] == 30


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


def test_unknown_page_rejected(client):
    r = client.post("/admin/api/features", json={"id": "page", "value": "nope"})
    assert r.status_code == 400


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
