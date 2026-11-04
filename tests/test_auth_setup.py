"""首次访问设口令的单测。

口令有三种状态：

  none      还没设 —— 第一次访问时让用户设一个，设之前后台全锁
  set       设过了 —— 要登录
  disabled  显式关掉（PETD_ADMIN_AUTH=off）—— 完全敞开

口令只存哈希（petd/data/admin.json），不存明文。
"""

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config  # noqa: E402
from petd.server import create_app  # noqa: E402

PW = "ceshi-mima-abc123"


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    """口令文件写到临时目录，别污染仓库里的 petd/data/。"""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv("PETD_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("PETD_ADMIN_AUTH", raising=False)
    yield


def _client(monkeypatch, **env):
    from starlette.testclient import TestClient
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        yield c


@pytest.fixture()
def fresh_client():
    from starlette.testclient import TestClient
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        yield c


@pytest.fixture()
def env_client(monkeypatch):
    from starlette.testclient import TestClient
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", PW)
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        yield c


# ---------- 还没设口令 ----------
def test_session_reports_none_mode(fresh_client):
    body = fresh_client.get("/admin/api/session").json()
    assert body["authMode"] == "none"
    assert body["authRequired"] is False


def test_status_is_locked_before_setup(fresh_client):
    """没设口令时后台是锁着的 —— 不能让陌生人先看再设。"""
    assert fresh_client.get("/admin/api/status").status_code == 401
    assert fresh_client.get("/admin/api/config").status_code == 401
    assert fresh_client.get("/admin/api/sessions").status_code == 401


def test_setup_password_works_and_unlocks(fresh_client):
    r = fresh_client.post("/admin/api/setup/password", json={"password": PW})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # 设完直接放行 —— 不用再登一次
    assert fresh_client.get("/admin/api/status").status_code == 200


def test_setup_password_is_one_shot(fresh_client):
    """已经设了 —— 这条路必须锁死，否则谁都能改掉别人的口令。"""
    fresh_client.post("/admin/api/setup/password", json={"password": PW})
    r = fresh_client.post("/admin/api/setup/password", json={"password": "hacked"})
    assert r.status_code == 403
    # 原口令还管用
    fresh_client.post("/admin/api/logout")
    fresh_client.post("/admin/api/login", json={"password": PW})
    assert fresh_client.get("/admin/api/status").status_code == 200


def test_setup_rejects_empty_password(fresh_client):
    r = fresh_client.post("/admin/api/setup/password", json={"password": ""})
    assert r.status_code == 400


def test_login_before_setup_is_refused(fresh_client):
    r = fresh_client.post("/admin/api/login", json={"password": PW})
    assert r.status_code == 409


def test_password_file_has_hash_not_plaintext(fresh_client):
    fresh_client.post("/admin/api/setup/password", json={"password": PW})
    p = config.admin_file_path()
    assert p.exists()
    raw = p.read_text(encoding="utf-8")
    assert PW not in raw, "明文口令不能落盘"
    blob = json.loads(raw)
    assert blob["passwordHash"].startswith("scrypt$")


def test_admin_file_is_not_tracked():
    """口令文件不能进仓库。"""
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "petd/data/admin.json" in ignore


# ---------- 哈希校验 ----------
def test_verify_accepts_right_password(fresh_client):
    fresh_client.post("/admin/api/setup/password", json={"password": PW})
    assert config.verify_admin_password(PW) is True


def test_verify_rejects_wrong_password(fresh_client):
    fresh_client.post("/admin/api/setup/password", json={"password": PW})
    assert config.verify_admin_password("wrong") is False


def test_hash_is_salted():
    """同样的口令两次哈希必须不同 —— 否则可以拿哈希反查。"""
    a = config.hash_admin_password(PW)
    b = config.hash_admin_password(PW)
    assert a != b
    assert a.startswith("scrypt$")


# ---------- 显式关掉 ----------
def test_auth_off_opens_everything(monkeypatch):
    from starlette.testclient import TestClient
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        body = c.get("/admin/api/session").json()
        assert body["authMode"] == "disabled"
        assert c.get("/admin/api/status").status_code == 200


def test_auth_off_blocks_setup_endpoint(monkeypatch):
    """显式关掉的时候不该还能从接口设口令 —— 状态是明确的。"""
    from starlette.testclient import TestClient
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        r = c.post("/admin/api/setup/password", json={"password": PW})
        assert r.status_code == 200
        assert r.json()["authRequired"] is False


# ---------- env 口令（自动部署） ----------
def test_env_password_still_works(env_client):
    body = env_client.get("/admin/api/session").json()
    assert body["authMode"] == "set"
    assert body["authRequired"] is True


def test_env_password_cannot_be_overwritten_by_setup(env_client):
    """自动部署给的口令 —— 不许被网页上的「设口令」覆盖。"""
    r = env_client.post("/admin/api/setup/password", json={"password": "other"})
    assert r.status_code == 403


def test_wrong_password_rejected(env_client):
    assert env_client.post("/admin/api/login",
                            json={"password": "wrong"}).status_code == 401


def test_correct_password_unlocks(env_client):
    r = env_client.post("/admin/api/login", json={"password": PW})
    assert r.status_code == 200
    assert env_client.get("/admin/api/status").status_code == 200


# ---------- 试错限流 ----------
def test_repeated_failures_get_rate_limited(env_client):
    """连错 5 次 —— 先歇 30 秒。"""
    for _ in range(5):
        env_client.post("/admin/api/login", json={"password": "wrong"})
    r = env_client.post("/admin/api/login", json={"password": PW})
    assert r.status_code == 429


def test_correct_password_after_failures_still_works(env_client):
    """错两次就锁 —— 那是在惩罚手滑。"""
    env_client.post("/admin/api/login", json={"password": "wrong"})
    env_client.post("/admin/api/login", json={"password": "wrong"})
    r = env_client.post("/admin/api/login", json={"password": PW})
    assert r.status_code == 200
