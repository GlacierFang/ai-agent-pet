"""OTA 的测试。

三条底线要钉住：
- 设备自己不会升级 —— 只有后台点一下才下发
- 不支持 OTA 的固件不接（0.5.3 认都不认识 otaStart）
- 版本登记表要能上传、登记、删掉
"""

import base64
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import ota as ota_mod  # noqa: E402


# ---------- 版本闸门 ----------
def test_ota_needs_fw_054():
    """0.5.3 没有 OTA 模块 —— 下去也是白下。"""
    assert ota_mod.fw_supports_ota("0.5.3") is False
    assert ota_mod.fw_supports_ota("0.5.4") is True
    assert ota_mod.fw_supports_ota("0.6.0") is True
    assert ota_mod.fw_supports_ota("") is False


def test_ver_key_orders_versions():
    assert ota_mod._ver_key("0.5.10") > ota_mod._ver_key("0.5.9")
    assert ota_mod._ver_key("0.10.0") > ota_mod._ver_key("0.9.9")
    assert ota_mod._ver_key("0.5.4") == (0, 5, 4)


# ---------- 版本登记表 ----------
@pytest.fixture()
def ota_home(tmp_path, monkeypatch):
    monkeypatch.setattr(ota_mod, "ota_dir", lambda: tmp_path / "ota")
    return tmp_path


def test_register_upload_computes_sha256(ota_home):
    data = b"fake firmware bytes"
    ver, err = ota_mod.register_upload("0.5.5", data)
    assert err == ""
    assert ver == "0.5.5"
    rec = ota_mod.get_version("0.5.5")
    assert rec is not None
    assert rec["size"] == len(data)
    import hashlib
    assert rec["sha256"] == hashlib.sha256(data).hexdigest()
    assert rec["source"] == "upload"


def test_register_upload_rejects_empty_version(ota_home):
    ver, err = ota_mod.register_upload("", b"x")
    assert ver == ""
    assert err


def test_register_upload_rejects_empty_file(ota_home):
    ver, err = ota_mod.register_upload("0.5.5", b"")
    assert err


def test_register_upload_rejects_oversized(ota_home):
    ver, err = ota_mod.register_upload("0.5.5", b"x" * (5 * 1024 * 1024))
    assert err


def test_versions_sorted_newest_first(ota_home):
    ota_mod.register_upload("0.5.4", b"a")
    ota_mod.register_upload("0.5.10", b"b")
    ota_mod.register_upload("0.5.9", b"c")
    vs = [v["version"] for v in ota_mod.list_versions()]
    assert vs == ["0.5.10", "0.5.9", "0.5.4"]
    assert ota_mod.latest_version() == "0.5.10"


def test_delete_version_removes_file(ota_home):
    ota_mod.register_upload("0.5.5", b"payload")
    rec = ota_mod.get_version("0.5.5")
    path = pathlib.Path(rec["file"])
    assert path.exists()
    assert ota_mod.delete_version("0.5.5") is True
    assert not path.exists()
    assert ota_mod.get_version("0.5.5") is None
    assert ota_mod.delete_version("0.5.5") is False


def test_read_firmware_returns_bytes(ota_home):
    data = b"\x00\x01\x02payload"
    ota_mod.register_upload("0.5.5", data)
    assert ota_mod.read_firmware("0.5.5") == data
    assert ota_mod.read_firmware("0.9.9") is None


def test_register_url_rejects_bad_scheme(ota_home):
    ver, err = ota_mod.register_url("0.5.5", "ftp://x/y.bin")
    assert ver == ""
    assert err


def test_register_url_rejects_empty_url(ota_home):
    ver, err = ota_mod.register_url("0.5.5", "")
    assert err


# ---------- 后台接口 ----------
def test_ota_api_requires_auth(monkeypatch):
    """OTA 是能刷固件的接口 —— 必须跟别的后台接口一样鉴权。"""
    from starlette.testclient import TestClient
    from petd import config
    from petd.server import create_app
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", "ceshi-mima-abc123")
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        assert c.get("/admin/api/ota").status_code == 401
        assert c.post("/admin/api/ota", json={"action": "upgrade",
                                              "version": "0.5.5"}).status_code == 401


def test_ota_api_get_returns_device_and_versions(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from petd import config
    from petd.server import create_app
    monkeypatch.setattr("petd.config.DATA_DIR", tmp_path)
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    cfg = config.defaults()
    cfg["_repo_root"] = str(tmp_path)
    with TestClient(create_app(cfg, start_gateway=False)) as c:
        body = c.get("/admin/api/ota").json()
        assert body["ok"] is True
        assert "device" in body
        assert "versions" in body
        assert body["device"]["online"] is False


def test_ota_api_upload_registers_version(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from petd import config
    from petd.server import create_app
    monkeypatch.setattr("petd.config.DATA_DIR", tmp_path)
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    cfg = config.defaults()
    cfg["_repo_root"] = str(tmp_path)
    with TestClient(create_app(cfg, start_gateway=False)) as c:
        raw = base64.b64encode(b"fake firmware").decode()
        r = c.post("/admin/api/ota", json={"action": "upload",
                                           "version": "0.5.5",
                                           "data": raw})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert any(v["version"] == "0.5.5" for v in body["versions"])


def test_ota_api_rejects_unknown_action(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from petd import config
    from petd.server import create_app
    monkeypatch.setattr("petd.config.DATA_DIR", tmp_path)
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    cfg = config.defaults()
    cfg["_repo_root"] = str(tmp_path)
    with TestClient(create_app(cfg, start_gateway=False)) as c:
        r = c.post("/admin/api/ota", json={"action": "explode"})
        assert r.status_code == 400


def test_upgrade_without_device_fails(tmp_path, monkeypatch):
    """设备不在线 —— 不能升级。"""
    from starlette.testclient import TestClient
    from petd import config
    from petd.server import create_app
    monkeypatch.setattr("petd.config.DATA_DIR", tmp_path)
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    cfg = config.defaults()
    cfg["_repo_root"] = str(tmp_path)
    with TestClient(create_app(cfg, start_gateway=False)) as c:
        r = c.post("/admin/api/ota", json={"action": "upgrade",
                                           "version": "0.5.5"})
        assert r.status_code == 400
        assert r.json()["ok"] is False
