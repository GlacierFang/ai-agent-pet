"""相册的测试：存、取、删，还有屏上换照片。

相册是后台「宠物设定」里的一个功能 —— 勾上它，轮播到就换一张照片。
这些测试钉住：上限 10 张、存的统一是 JPEG、换照片靠 on_show 钩子。
"""

import io
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import album as album_mod  # noqa: E402
from petd import features as feature_mod  # noqa: E402
from petd import render as render_mod  # noqa: E402
from petd import screen as screen_mod  # noqa: E402


@pytest.fixture()
def album_dir(tmp_path, monkeypatch):
    """相册目录换个地方 —— 别把测试文件写进仓库。"""
    monkeypatch.setattr("petd.config.DATA_DIR", tmp_path)
    return tmp_path / "album"


def make_png(w=40, h=30):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 40, 30)).save(buf, format="PNG")
    return buf.getvalue()


def make_jpeg(w=40, h=30):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 90, 200)).save(buf, format="JPEG")
    return buf.getvalue()


# ---------- 存 ----------
def test_add_then_list_keeps_order(album_dir):
    album_mod.add(make_png(), "a.png")
    album_mod.add(make_jpeg(), "b.jpg")
    items = album_mod.list_items()
    assert [it["name"] for it in items] == ["a.png", "b.jpg"]


def test_stored_file_is_jpeg(album_dir):
    """存的统一是 JPEG —— 设备那边收的就是 JPEG 帧。"""
    album_mod.add(make_png(), "a.png")
    path = pathlib.Path(album_mod.list_photos()[0])
    assert path.suffix == ".jpg"
    from PIL import Image
    assert Image.open(path).format == "JPEG"


def test_rejects_more_than_ten(album_dir):
    for i in range(album_mod.MAX_PHOTOS):
        album_mod.add(make_png(), "%d.png" % i)
    with pytest.raises(ValueError):
        album_mod.add(make_png(), "overflow.png")
    assert album_mod.count() == album_mod.MAX_PHOTOS


def test_rejects_garbage(album_dir):
    with pytest.raises(ValueError):
        album_mod.add(b"not an image", "x.png")


def test_big_image_is_shrunk(album_dir):
    """长边超过 1280 的缩到 1280 —— 屏只有 240x320。"""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), (10, 10, 10)).save(buf, format="PNG")
    album_mod.add(buf.getvalue(), "big.png")
    path = album_mod.list_photos()[0]
    assert max(Image.open(path).size) <= album_mod.MAX_EDGE


# ---------- 删 ----------
def test_delete_removes_file(album_dir):
    rec = album_mod.add(make_png(), "a.png")
    assert album_mod.delete(rec["file"]) is True
    assert album_mod.count() == 0
    assert not (album_dir / rec["file"]).exists()


def test_delete_unknown_is_false(album_dir):
    assert album_mod.delete("deadbeefdeadbeef.jpg") is False


def test_delete_rejects_path_traversal(album_dir):
    assert album_mod.delete("../../etc/passwd") is False


# ---------- 屏上 ----------
def test_album_feature_is_registered():
    assert feature_mod.get("album") is not None
    assert "album" in [f.name for f in feature_mod.all_features()]


def test_album_quiet_without_photos(album_dir):
    """没有照片 —— 没话说，不上屏。"""
    f = feature_mod.get("album")
    f.reload()
    assert f.context({"now": 1000.0}) is None


def test_album_advances_on_show(album_dir):
    """轮播切到相册 —— 换下一张。"""
    f = feature_mod.get("album")
    album_mod.add(make_png(), "a.png")
    album_mod.add(make_png(), "b.png")
    f.reload()
    seen = []
    for _ in range(3):
        f.on_show({})
        card = f.context({"now": 1000.0})
        seen.append(card["counter"])
    assert seen == ["1 / 2", "2 / 2", "1 / 2"]


def test_screen_calls_on_show(album_dir):
    """屏上仲裁切到相册 —— 得叫它一声。"""
    f = feature_mod.get("album")
    album_mod.add(make_png(), "a.png")
    album_mod.add(make_png(), "b.png")
    f.reload()
    d = screen_mod.ScreenDirector(dwell_ms=0)
    d.update(1000.0, "idle", {}, [f])
    first = f.context({"now": 1000.0})["counter"]
    d.update(1001.0, "idle", {}, [f])
    second = f.context({"now": 1001.0})["counter"]
    assert first != second


def test_render_photo_card_is_jpeg(album_dir):
    """照片卡 —— JPEG，尺寸跟屏一致。"""
    album_mod.add(make_jpeg(400, 300), "a.jpg")
    path = album_mod.list_photos()[0]
    jpeg = render_mod.render_photo_card(
        {"render": {"width": 240, "height": 320}}, path, "1 / 1")
    assert jpeg[:2] == b"\xff\xd8"
    from PIL import Image
    assert Image.open(io.BytesIO(jpeg)).size == (240, 320)


# ---------- 后台接口 ----------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """后台接口 —— 显式关掉鉴权，省得每个用例都先登录。"""
    from starlette.testclient import TestClient
    from petd import config
    from petd.server import create_app
    cfg = config.defaults()
    cfg["_repo_root"] = str(tmp_path)
    monkeypatch.setattr("petd.config.DATA_DIR", tmp_path)
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    with TestClient(create_app(cfg, start_gateway=False)) as c:
        yield c


def test_album_api_upload_and_list(client):
    import base64
    payload = base64.b64encode(make_png(60, 40)).decode()
    r = client.post("/admin/api/album/upload",
                    json={"data": payload, "name": "a.png"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["album"]["count"] == 1
    assert body["album"]["max"] == 10


def test_album_api_rejects_eleventh(client):
    import base64
    payload = base64.b64encode(make_png()).decode()
    for _ in range(10):
        r = client.post("/admin/api/album/upload",
                        json={"data": payload, "name": "x.png"})
        assert r.status_code == 200
    r = client.post("/admin/api/album/upload",
                    json={"data": payload, "name": "y.png"})
    assert r.status_code == 400
    assert "10" in r.json()["error"]


def test_album_api_rejects_garbage(client):
    import base64
    payload = base64.b64encode(b"not an image").decode()
    r = client.post("/admin/api/album/upload",
                    json={"data": payload, "name": "x.png"})
    assert r.status_code == 400


def test_album_api_delete(client):
    import base64
    payload = base64.b64encode(make_png()).decode()
    r = client.post("/admin/api/album/upload",
                    json={"data": payload, "name": "a.png"})
    fname = r.json()["album"]["items"][0]["file"]
    r = client.post("/admin/api/album/delete", json={"file": fname})
    assert r.status_code == 200
    assert r.json()["album"]["count"] == 0


def test_album_thumb_returns_jpeg(client):
    import base64
    payload = base64.b64encode(make_png()).decode()
    r = client.post("/admin/api/album/upload",
                    json={"data": payload, "name": "a.png"})
    fname = r.json()["album"]["items"][0]["file"]
    r = client.get("/admin/api/album/thumb", params={"file": fname})
    assert r.status_code == 200
    assert r.content[:2] == b"\xff\xd8"


def test_album_feature_is_in_settings(client):
    """相册是后台「宠物设定」里的一个功能 —— 跟时钟、天气排在一起。"""
    caps = {c["name"]: c for c in client.get("/admin/api/settings").json()["features"]}
    assert "album" in caps
    item = caps["album"]
    assert item["title"] == "相册"
    opts = item["options"]
    assert len(opts) == 1
    assert opts[0]["type"] == "album"
    assert opts[0]["max"] == 10


def test_album_api_requires_auth(monkeypatch):
    """相册接口跟别的后台接口一样要过鉴权。"""
    from starlette.testclient import TestClient
    from petd import config
    from petd.server import create_app
    monkeypatch.setenv("PETD_ADMIN_PASSWORD", "ceshi-mima-abc123")
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        assert c.get("/admin/api/album").status_code == 401
        assert c.post("/admin/api/album/upload", json={}).status_code == 401
        assert c.post("/admin/api/album/delete", json={}).status_code == 401
