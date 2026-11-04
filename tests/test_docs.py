"""文档阅读器的测试。

后台「文档」页把仓库里的 docs/*.md 渲染出来。这些测试钉住：
  · 分组：登记过的进对应组，没登记的落进「其它」，不能消失
  · 路径：只认 docs 目录里的文件，挡掉路径穿越
  · 链接：指向另一篇的改成 doc:，指到仓库根的落到 GitHub
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import docs as docs_mod  # noqa: E402


@pytest.fixture()
def repo(tmp_path):
    """造一个假的仓库目录。

    名字用登记过的真名（部署手册.md）—— 分组是按文件名登记的，
    用假名会全落进「其它」组，测不到分组。
    """
    d = tmp_path / "docs"
    d.mkdir(parents=True)
    (d / "部署手册.md").write_text("# 部署手册\n\n正文。\n", encoding="utf-8")
    (d / "协议.md").write_text("# 协议\n\n看 [部署手册](部署手册.md)。\n", encoding="utf-8")
    (d / "新文档.md").write_text("# 新文档\n\n看 [安全](../SECURITY.md)。\n", encoding="utf-8")
    return tmp_path


# ---------- 清单 ----------
def test_lists_every_file(repo):
    blob = docs_mod.list_docs(str(repo))
    names = [d["name"] for g in blob["groups"] for d in g["docs"]]
    assert set(names) == {"部署手册.md", "协议.md", "新文档.md"}


def test_registered_docs_get_their_group(repo):
    """登记过的进对应组。"""
    blob = docs_mod.list_docs(str(repo))
    by_id = {g["id"]: g for g in blob["groups"]}
    assert "user" in by_id
    names = [d["name"] for d in by_id["user"]["docs"]]
    assert "部署手册.md" in names


def test_unregistered_doc_lands_in_other(repo):
    """没登记的新文档不能消失 —— 落进「其它」组。"""
    blob = docs_mod.list_docs(str(repo))
    other = [g for g in blob["groups"] if g["id"] == "other"]
    assert other, "没登记的文档应该有地方放"
    names = [d["name"] for d in other[0]["docs"]]
    assert "新文档.md" in names


def test_doc_title_from_heading(repo):
    blob = docs_mod.list_docs(str(repo))
    titles = {d["name"]: d["title"] for g in blob["groups"] for d in g["docs"]}
    assert titles["部署手册.md"] == "部署手册"


def test_missing_docs_dir_is_reported(repo):
    blob = docs_mod.list_docs(str(repo / "没有"))
    assert blob["available"] is False
    assert blob["groups"] == []
    assert blob["repoUrl"]


# ---------- 渲染 ----------
def test_render_returns_html(repo):
    doc = docs_mod.render_doc(str(repo), "部署手册.md")
    assert doc is not None
    assert doc["ok"] is True
    assert "<h1>部署手册</h1>" in doc["html"]
    assert doc["title"] == "部署手册"


def test_render_turns_relative_link_into_doc_scheme(repo):
    """中文文件名的链接也得认 —— markdown-it 会 percent-encoding。"""
    doc = docs_mod.render_doc(str(repo), "协议.md")
    assert "doc:部署手册.md" in doc["html"]


def test_render_turns_repo_link_into_github(repo):
    doc = docs_mod.render_doc(str(repo), "新文档.md")
    assert "doc:" not in doc["html"]
    assert "github.com" in doc["html"]


def test_render_disables_raw_html(repo):
    """原始 HTML 标签关掉 —— 渲染器不冒注入的风险。"""
    (repo / "docs" / "注入.md").write_text(
        "# 注入\n\n<script>alert(1)</script>\n", encoding="utf-8")
    doc = docs_mod.render_doc(str(repo), "注入.md")
    assert "<script>" not in doc["html"]


# ---------- 路径 ----------
def test_rejects_path_traversal(repo):
    assert docs_mod.render_doc(str(repo), "../SECURITY.md") is None
    assert docs_mod.render_doc(str(repo), "../../etc/passwd") is None


def test_rejects_unknown_file(repo):
    assert docs_mod.render_doc(str(repo), "没有这个.md") is None


def test_rejects_empty_name(repo):
    assert docs_mod.render_doc(str(repo), "") is None


# ---------- 后台接口 ----------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from petd import config
    from petd.server import create_app
    d = tmp_path / "docs"
    d.mkdir(parents=True)
    (d / "测试.md").write_text("# 测试\n\n正文。\n", encoding="utf-8")
    cfg = config.defaults()
    # create_app 会把 cfg["_repo_root"] 覆盖成模块里的 REPO_ROOT ——
    # 光设 cfg 不管用，得改 REPO_ROOT 本身。
    monkeypatch.setattr("petd.server.REPO_ROOT", tmp_path)
    monkeypatch.setattr("petd.config.DATA_DIR", tmp_path)
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    with TestClient(create_app(cfg, start_gateway=False)) as c:
        yield c


def test_docs_api_lists(client):
    r = client.get("/admin/api/docs")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["available"] is True


def test_docs_api_reads(client):
    r = client.get("/admin/api/docs/read", params={"file": "测试.md"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "测试" in body["html"]


def test_docs_api_unknown_is_404(client):
    r = client.get("/admin/api/docs/read", params={"file": "没有.md"})
    assert r.status_code == 404


def test_docs_api_requires_auth(monkeypatch):
    from starlette.testclient import TestClient
    from petd import config
    from petd.server import create_app
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", "ceshi-mima-abc123")
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        assert c.get("/admin/api/docs").status_code == 401
        assert c.get("/admin/api/docs/read?file=x.md").status_code == 401


# ---------- 缓存头 ----------
def test_admin_assets_are_no_cache(client):
    """改了前端刷新一次就最新 —— 少了这条，用户看到的和代码对不上。"""
    r = client.get("/admin/assets/app.js")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache"
