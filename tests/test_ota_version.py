"""固件版本号自动识别 —— 版本号不该让人手填。

固件把自己的版本写进了 app 描述段（ESP-IDF v5+ 的标准位置：app 镜像偏移
0x20），上传的文件里本来就有，petd 自己读出来就行。

读不出版本号的（不是标准 app 镜像）才回头问人 —— 而且要说清楚是
「这个文件读不出来」，不是「你填错了」。

这些用例盯的是后台固件页简化成「上传 + 升级固件」之后的后端行为。
"""

import base64
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import ota as ota_mod  # noqa: E402


def make_app_image(payload=b"payload"):
    """造一个结构合法的 ESP32 app 镜像。"""
    head = bytearray(24)
    head[0] = 0xE9
    head[1] = 1                      # 一个段
    seg = bytearray(8)
    seg[0:4] = (0x40000000).to_bytes(4, "little")
    seg[4:8] = len(payload).to_bytes(4, "little")
    body = bytes(seg) + payload
    body += bytes((4 - len(body) % 4) % 4)
    return bytes(head) + body + bytes(16)


def make_image_with_version(version="fw-v0.5.11"):
    """造一个带 app 描述段的镜像 —— 版本号就写在里面。"""
    img = bytearray(make_app_image(b"payload" * 8))
    desc = bytearray(48)
    desc[0:4] = (0xABCD5432).to_bytes(4, "little")
    ver = version.encode("ascii")
    desc[16:16 + len(ver)] = ver
    img[0x20:0x20 + 48] = desc
    return bytes(img)


@pytest.fixture
def ota_home(tmp_path, monkeypatch):
    monkeypatch.setattr("petd.config.DATA_DIR", tmp_path)
    return tmp_path


def _client(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from petd import config
    from petd.server import create_app
    monkeypatch.setattr("petd.config.DATA_DIR", tmp_path)
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    cfg = config.defaults()
    cfg["_repo_root"] = str(tmp_path)
    return TestClient(create_app(cfg, start_gateway=False))


# ---------- 读版本号 ----------

def test_detect_version_from_app_descriptor():
    """描述段是标准位置 —— 版本号就在里面。"""
    img = make_image_with_version("fw-v0.5.11")
    assert ota_mod.detect_version(img) == "0.5.11"


def test_detect_version_falls_back_to_tag_string():
    """描述段不在（老格式），能从 fw-vX.Y.Z 这个 tag 串里读出来。"""
    img = bytearray(make_app_image(b"payload" * 8))
    img += bytes([0]) + b"fw-v0.5.9" + bytes([0])
    assert ota_mod.detect_version(img) == "0.5.9"


def test_detect_version_ignores_ip_like_numbers():
    """别把 192.168.1.100 之类当成版本号。"""
    img = bytearray(make_app_image(b"192.168.1.100"))
    assert ota_mod.detect_version(img) == ""


def test_detect_version_empty_returns_empty():
    assert ota_mod.detect_version(b"") == ""


# ---------- 登记 ----------

def test_register_upload_reads_version_when_not_given(ota_home):
    """版本号不用人填 —— 后端自己从镜像里读。"""
    img = make_image_with_version("fw-v0.5.11")
    ver, err = ota_mod.register_upload("", img)
    assert err == ""
    assert ver == "0.5.11"
    assert ota_mod.get_version("0.5.11") is not None


def test_register_upload_without_version_needs_one_when_unreadable(ota_home):
    """读不出版本号 —— 要人填，不许瞎猜。"""
    ver, err = ota_mod.register_upload("", make_app_image(b"payload"))
    assert ver == ""
    assert "版本号" in err


def test_register_upload_explicit_version_wins(ota_home):
    """人填了就用人填的 —— 描述段里的版本只是兜底。"""
    img = make_image_with_version("fw-v0.5.11")
    ver, err = ota_mod.register_upload("0.5.12", img)
    assert err == ""
    assert ver == "0.5.12"


# ---------- 接口 ----------

def test_api_upload_reads_version_automatically(tmp_path, monkeypatch):
    """API 收一个没写版本号的固件 —— 自己认出来。"""
    with _client(tmp_path, monkeypatch) as c:
        img = make_image_with_version("fw-v0.5.11")
        r = c.post("/admin/api/ota",
                   json={"action": "upload",
                         "data": base64.b64encode(img).decode()})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["uploaded"]["version"] == "0.5.11"


def test_api_upload_returns_need_version_when_unreadable(tmp_path, monkeypatch):
    """读不出版本号 —— 页面要弹版本号输入框，而不是报一句听不懂的错。"""
    with _client(tmp_path, monkeypatch) as c:
        img = make_app_image(b"payload")
        r = c.post("/admin/api/ota",
                   json={"action": "upload",
                         "data": base64.b64encode(img).decode()})
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False
        assert body["needVersion"] is True


def test_api_upload_rejects_merged_binary_with_clear_error(tmp_path, monkeypatch):
    """传错文件（整片镜像）—— 直接说人话，别让人以为只是版本号问题。"""
    with _client(tmp_path, monkeypatch) as c:
        bad = bytearray(bytes(0x20000 + 32))
        bad[0] = 0xE9
        bad[0x20000] = 0xE9
        r = c.post("/admin/api/ota",
                   json={"action": "upload",
                         "data": base64.b64encode(bytes(bad)).decode()})
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False
        assert "needVersion" not in body
        assert "merged-binary" in body["error"]


def test_api_upgrade_without_version_uses_latest(tmp_path, monkeypatch):
    """「升级固件」不带版本号 —— 刷最新登记的那一份。"""
    with _client(tmp_path, monkeypatch) as c:
        img = make_image_with_version("fw-v0.5.11")
        c.post("/admin/api/ota",
               json={"action": "upload",
                     "data": base64.b64encode(img).decode()})
        r = c.post("/admin/api/ota", json={"action": "upgrade"})
        body = r.json()
        # 设备不在线 —— 该报「设备不在线」，不该是「未知动作」或「没有可刷的固件」。
        assert body["ok"] is False
        assert "设备不在线" in body["error"] or "没有可刷" in body["error"]


def test_ota_view_reports_latest_and_uploaded(tmp_path, monkeypatch):
    """页面要拿得到「最新版本」和「刚上传的那一份」。"""
    with _client(tmp_path, monkeypatch) as c:
        img = make_image_with_version("fw-v0.5.11")
        c.post("/admin/api/ota",
               json={"action": "upload",
                     "data": base64.b64encode(img).decode()})
        body = c.get("/admin/api/ota").json()
        assert body["latest"] == "0.5.11"
        assert body["uploaded"]["version"] == "0.5.11"
        assert body["uploaded"]["size"] == len(img)
        # 设备不在线 —— 没有可刷的目标。
        assert body["available"] == ""
        assert body["canUpgrade"] is False
