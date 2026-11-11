"""后台口令的单测。

口令的状态有三种（"none" 还没设 / "set" 设过了 / "disabled" 显式关掉）——
"none" 和 "disabled" 那两条路径在 tests/test_auth_setup.py 里。

这里测的是「设过了」这条路径上的鉴权行为：一把共享锁，
没有注册、没有用户表、没有多账号。
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


@pytest.fixture()
def pw_client(monkeypatch):
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", PW)
    from starlette.testclient import TestClient
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        yield c


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
# ---------- 后台填网关令牌：得真存下来 ----------
def test_admin_token_lands_in_secrets_not_config(pw_client):
    """后台输入框填的令牌 —— 落凭据文件，不落 config.json。

    回归：config.save() 只允许文件里原本就有的 token，
    后台新填的会被抹掉 —— 填完重启 petd，令牌就没了。
    """
    pw_client.post("/admin/api/login", json={"password": PW})
    r = pw_client.post("/admin/api/config",
                       json={"gateway": {"token": "tok-from-admin"}})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["tokenSaved"] is True

    secrets = config.DATA_DIR / "secrets.json"
    blob = json.loads(secrets.read_text(encoding="utf-8"))
    assert blob["gatewayToken"] == "tok-from-admin"

    # config.json 是用户会随手复制走的文件 —— 里面不能有令牌
    cfg_file = config.DATA_DIR / "config.json"
    assert cfg_file.exists()
    assert "tok-from-admin" not in cfg_file.read_text(encoding="utf-8")


def test_admin_token_lands_in_running_config(pw_client):
    """填完得立刻能用 —— 内存里的配置要拿到新令牌。

    回归：pet.cfg = cur 换掉了整个 dict，
    GatewayClient 握的旧引用永远看不到新配置。
    """
    pet = pw_client.app.state.pet
    before = pet.cfg
    pw_client.post("/admin/api/login", json={"password": PW})
    pw_client.post("/admin/api/config",
                   json={"gateway": {"token": "tok-live"}})
    assert pet.cfg["gateway"]["token"] == "tok-live"
    # 必须是原地更新 —— 换成新 dict 的话握旧引用的代码就看不见了
    assert pet.cfg is before


def test_admin_empty_token_keeps_existing(pw_client):
    """令牌留空 = 不改动，别把已设的清掉。"""
    pw_client.post("/admin/api/login", json={"password": PW})
    pw_client.post("/admin/api/config",
                   json={"gateway": {"token": "tok-keep"}})
    pw_client.post("/admin/api/config",
                   json={"gateway": {"url": "ws://127.0.0.1:19999"}})
    pet = pw_client.app.state.pet
    assert pet.cfg["gateway"]["token"] == "tok-keep"


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


def test_dashboard_body_not_hidden_by_default(pw_client):
    """页面外壳里主体不能预先藏起来。

    回归：加口令那次给 <main> 加了 class=hidden，而解锁它的 hideGate()
    只在登录成功后调用 —— 别的路径没人调，页面只剩页头页脚。
    """
    html = pw_client.get("/admin/").text
    assert '<main id="app">' in html
    assert '<main id="app" class="hidden">' not in html


def test_preview_img_has_no_static_src(pw_client):
    """预览图不能用静态 src。

    回归：<img src="api/preview.jpg"> 是静态引用，浏览器一解析 HTML 就发请求，
    那时还没登录、没有 cookie -> 401。真实 URL 由 app.js 在登录后设置。
    """
    html = pw_client.get("/admin/").text
    assert 'src="api/preview.jpg"' not in html
    assert "data:image/gif;base64" in html


def test_dashboard_unlocks_body_in_js(pw_client):
    """app.js 必须自己解锁 #app，不能指望 hideGate()。

    没设口令时没人调 hideGate()，解锁只能写在 startDashboard() 里。
    """
    js = pw_client.get("/admin/assets/app.js").text
    assert "el('app').classList.remove('hidden')" in js


def test_setup_form_exists_in_page(pw_client):
    """页面里得有「设口令」那个表单 —— 第一次访问要用。"""
    html = pw_client.get("/admin/").text
    assert "form-gate-setup" in html
    assert "gate-setup-password" in html
