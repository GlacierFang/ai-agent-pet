"""后台口令的单测。

口令是**可选**的：没设 PETD_ADMIN_PASSWORD 时行为跟以前一模一样，
这样 clone 下来 `python3 -m petd` 就能直接跑。
设了之后就是一把共享锁 —— 没有注册、没有用户表、没有多账号。
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config  # noqa: E402
from petd.server import create_app  # noqa: E402

PW = "ceshi-mima-abc123"


@pytest.fixture
def no_pw_client(monkeypatch):
    monkeypatch.delenv("PETD_ADMIN_PASSWORD", raising=False)
    from starlette.testclient import TestClient
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        yield c


@pytest.fixture
def pw_client(monkeypatch):
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", PW)
    from starlette.testclient import TestClient
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        yield c


# ---------- 没设口令：行为不变 ----------
def test_no_password_session_says_not_required(no_pw_client):
    r = no_pw_client.get("/admin/api/session")
    assert r.status_code == 200
    assert r.json()["authRequired"] is False


def test_no_password_status_is_open(no_pw_client):
    assert no_pw_client.get("/admin/api/status").status_code == 200


def test_no_password_config_is_open(no_pw_client):
    assert no_pw_client.get("/admin/api/config").status_code == 200


def test_no_password_login_says_not_required(no_pw_client):
    r = no_pw_client.post("/admin/api/login", json={"password": "whatever"})
    assert r.status_code == 200
    assert r.json()["authRequired"] is False


# ---------- 设了口令：必须先登录 ----------
def test_password_session_requires_auth(pw_client):
    r = pw_client.get("/admin/api/session")
    assert r.status_code == 200
    body = r.json()
    assert body["authRequired"] is True
    assert body["authed"] is False


def test_password_blocks_status(pw_client):
    assert pw_client.get("/admin/api/status").status_code == 401


def test_password_blocks_config_read(pw_client):
    assert pw_client.get("/admin/api/config").status_code == 401


def test_password_blocks_config_write(pw_client):
    """改配置是最需要挡住的一步。"""
    r = pw_client.post("/admin/api/config", json={"render": {"quality": 50}})
    assert r.status_code == 401


def test_password_blocks_logs(pw_client):
    assert pw_client.get("/admin/api/logs").status_code == 401


def test_wrong_password_rejected(pw_client):
    r = pw_client.post("/admin/api/login", json={"password": "wrong"})
    assert r.status_code == 401
    assert r.json()["ok"] is False


def test_empty_password_rejected(pw_client):
    r = pw_client.post("/admin/api/login", json={"password": ""})
    assert r.status_code == 401


def test_correct_password_unlocks(pw_client):
    r = pw_client.post("/admin/api/login", json={"password": PW})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "petd_admin" in r.cookies
    assert pw_client.get("/admin/api/status").status_code == 200


def test_logged_in_session_reports_authed(pw_client):
    pw_client.post("/admin/api/login", json={"password": PW})
    body = pw_client.get("/admin/api/session").json()
    assert body["authed"] is True


def test_login_page_is_served_without_auth(pw_client):
    """页面外壳本身不给数据，所以不挡 —— 挡了就没法显示口令框。"""
    r = pw_client.get("/admin/")
    assert r.status_code == 200
    assert "gate-password" in r.text


def test_tampered_cookie_rejected(pw_client):
    pw_client.cookies.set("petd_admin", "9999999999.deadbeef")
    assert pw_client.get("/admin/api/status").status_code == 401


# ---------- 口令从哪来 ----------
def test_password_from_env(monkeypatch):
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", "from-env")
    assert config.admin_password() == "from-env"


def test_password_absent_is_empty(monkeypatch):
    monkeypatch.delenv("PETD_ADMIN_PASSWORD", raising=False)
    assert config.admin_password() == ""


def test_password_not_in_public_config_view():
    """口令不能出现在给后台页看的配置里。"""
    cfg = config.defaults()
    cfg["gateway"]["token"] = "SECRET"
    pub = config.public_view(cfg)
    assert "SECRET" not in str(pub)


def test_dashboard_body_not_hidden_by_default(no_pw_client):
    """没设口令时主体必须可见。

    回归：加口令那次给 <main> 加了 class=hidden，而解锁它的 hideGate()
    只在登录成功后调用 —— 没设口令的路径没人调，页面只剩页头页脚。
    """
    html = no_pw_client.get("/admin/").text
    assert '<main id="app">' in html
    assert '<main id="app" class="hidden">' not in html


def test_dashboard_unlocks_body_in_js(no_pw_client):
    """app.js 必须自己解锁 #app，不能指望 hideGate()。

    没设口令时没人调 hideGate()，解锁只能写在 startDashboard() 里。
    """
    js = no_pw_client.get("/admin/assets/app.js").text
    assert "el('app').classList.remove('hidden')" in js
