"""首次使用指引接口（/admin/api/setup）的单测。

字段名是前后端契约 —— 改了就白屏，这里钉住。
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config  # noqa: E402
from petd import app as app_mod  # noqa: E402
from petd.server import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_setup_state(tmp_path, monkeypatch):
    """引导状态写到临时目录，别污染仓库里的 petd/data/。"""
    monkeypatch.setattr(app_mod, "SETUP_STATE_PATH", tmp_path / "setup_state.json")
    yield


@pytest.fixture
def client():
    from starlette.testclient import TestClient
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        yield c


def test_setup_requires_auth_when_password_set(monkeypatch):
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", "ceshi-mima-abc123")
    from starlette.testclient import TestClient
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        assert c.get("/admin/api/setup").status_code == 401
        c.post("/admin/api/login", json={"password": "ceshi-mima-abc123"})
        assert c.get("/admin/api/setup").status_code == 200


def test_setup_shape(client):
    body = client.get("/admin/api/setup").json()
    assert set(body.keys()) == {"steps", "mdns", "provisioning"}


def test_steps_have_fixed_ids_and_labels(client):
    body = client.get("/admin/api/setup").json()
    steps = body["steps"]
    assert [s["id"] for s in steps] == ["admin", "device", "frames", "pet"]
    for step in steps:
        assert set(step.keys()) == {"id", "label", "done", "detail", "hint"}
        assert isinstance(step["done"], bool)
        assert isinstance(step["detail"], str)
        assert isinstance(step["hint"], str)


def test_admin_step_always_done(client):
    body = client.get("/admin/api/setup").json()
    admin = body["steps"][0]
    assert admin["done"] is True
    assert admin["detail"] == "petd 正在运行"


def test_device_step_pending_without_device(client):
    body = client.get("/admin/api/setup").json()
    device = body["steps"][1]
    assert device["done"] is False
    assert device["hint"] == "设备刷好固件后会自己连上来"


def test_frames_step_pending_without_frames(client):
    body = client.get("/admin/api/setup").json()
    assert body["steps"][2]["done"] is False


def test_pet_step_pending_without_sessions(client):
    body = client.get("/admin/api/setup").json()
    pet = body["steps"][3]
    assert pet["done"] is False
    assert pet["hint"] == "宠物需要至少一个会话才能醒"


def test_mdns_block_shape(client):
    mdns = client.get("/admin/api/setup").json()["mdns"]
    assert set(mdns.keys()) == {"enabled", "hostname", "addresses", "port"}
    assert isinstance(mdns["enabled"], bool)
    assert isinstance(mdns["addresses"], list)
    assert mdns["port"] == 18860
    assert mdns["hostname"] == "petd.local"


def test_provisioning_block_shape(client):
    prov = client.get("/admin/api/setup").json()["provisioning"]
    assert set(prov.keys()) == {"supported", "apSsidPattern", "apUrl", "note"}
    assert prov["supported"] is True
    assert prov["apSsidPattern"] == "petd-setup-XXXX"
    assert prov["apUrl"] == "http://192.168.4.1"
    assert prov["note"] == "密码显示在设备屏幕上"


def test_mdns_can_be_disabled_by_config():
    cfg = config.defaults()
    cfg["mdns"] = {"enabled": False}
    from starlette.testclient import TestClient
    with TestClient(create_app(cfg, start_gateway=False)) as c:
        mdns = c.get("/admin/api/setup").json()["mdns"]
    assert mdns["enabled"] is False


def test_device_seen_is_persisted(client):
    """设备连过一次，这一项就该记着 —— 重启后也不能退回未开始。"""
    pet = client.app.state.pet
    pet._mark_device_seen(type("S", (), {"device_id": "esp32-001", "frame_count": 7})())
    body = client.get("/admin/api/setup").json()
    device = body["steps"][1]
    assert device["done"] is True
    assert device["detail"] == "esp32-001"
    frames = body["steps"][2]
    assert frames["done"] is True
    assert "7" in frames["detail"]


def test_pet_step_done_with_sessions(client):
    pet = client.app.state.pet
    pet.engine.update([{"key": "a", "status": "running", "hasActiveRun": False,
                         "unread": False, "permissionModePending": False,
                         "isBackground": False, "lastActivityAt": 0}])
    body = client.get("/admin/api/setup").json()
    assert body["steps"][3]["done"] is True


def test_status_api_shape_unchanged(client):
    """不能动现有接口的结构。"""
    body = client.get("/admin/api/status").json()
    assert set(body.keys()) == {"gateway", "device", "pet", "frames"}
