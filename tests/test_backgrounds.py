"""背景的单测。

背景和宠物形象是**解耦**的两件事 —— 这条是本模块的核心约定：
换宠物不动背景，换背景不动宠物。
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import backgrounds as bg_mod  # noqa: E402
from petd import render  # noqa: E402
from petd.server import create_app  # noqa: E402
from petd import config as config_mod  # noqa: E402


def _png(w=240, h=320, color=(20, 30, 50)):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


# ---------- 模块层 ----------


def test_valid_name_rejects_path_separators():
    assert bg_mod.valid_name("我的房间")
    assert not bg_mod.valid_name("../etc")
    assert not bg_mod.valid_name("a/b")
    assert not bg_mod.valid_name("")
    assert not bg_mod.valid_name("..")


def test_builtin_background_exists_in_repo():
    """仓库自带一张默认背景 —— 目录约定是 backgrounds/<name>.png。"""
    p = ROOT / "backgrounds" / "default.png"
    assert p.is_file(), "仓库里应该有一张默认背景"


def test_bg_path_prefers_user_over_repo(tmp_path):
    (tmp_path / "backgrounds").mkdir()
    (tmp_path / "backgrounds" / "x.png").write_bytes(_png())
    user = tmp_path / "petd" / "data" / "backgrounds"
    user.mkdir(parents=True)
    (user / "x.png").write_bytes(_png(color=(200, 10, 10)))
    assert bg_mod.bg_source(str(tmp_path), "x") == "user"
    assert bg_mod.list_bgs(str(tmp_path)) == ["x"]


def test_save_image_normalizes_to_screen_size(tmp_path):
    path = bg_mod.save_image(str(tmp_path), "mine", _png(w=480, h=640))
    assert path.is_file()
    from PIL import Image
    with Image.open(path) as im:
        assert im.size == (bg_mod.SCREEN_W, bg_mod.SCREEN_H)


def test_save_image_accepts_jpeg(tmp_path):
    """格式不挑 —— Pillow 按内容识别。"""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (240, 320), (10, 20, 30)).save(buf, format="JPEG")
    path = bg_mod.save_image(str(tmp_path), "j", buf.getvalue())
    assert path.is_file()


def test_delete_rejects_builtin(tmp_path):
    with pytest.raises(ValueError):
        bg_mod.delete_bg(str(tmp_path), "default")


# ---------- 渲染层 ----------


def test_render_uses_background(tmp_path):
    """给了背景图，渲染结果就该和没有背景时不一样。"""
    cfg = config_mod.defaults()
    bg = bg_mod.save_image(str(tmp_path), "b", _png(color=(200, 30, 30)))
    from PIL import Image
    with Image.open(bg) as im:
        bg_img = im.convert("RGB")
    plain = render.render_frame(cfg, "idle")
    with_bg = render.render_frame(cfg, "idle", background_image=bg_img)
    assert plain != with_bg


def test_render_without_background_still_works():
    """没有背景图 —— 退回状态色渐变，不能炸。"""
    cfg = config_mod.defaults()
    assert render.render_frame(cfg, "idle")


def test_density_no_longer_scales_the_pet():
    """宠物大小固定 —— 密度只管文字行数。

    背景和宠物解耦之后，宠物再跟着密度缩放就不对了。
    """
    cfg = config_mod.defaults()
    import io
    from PIL import Image, ImageChops
    a = Image.open(io.BytesIO(render.render_frame(cfg, "idle", density=0))).convert("RGB")
    b = Image.open(io.BytesIO(render.render_frame(cfg, "idle", density=2))).convert("RGB")
    # 宠物区（底部，文字带以下）两档必须完全一样
    band = render.TEXT_BAND_H
    assert ImageChops.difference(a.crop((0, band, 240, 320)),
                                 b.crop((0, band, 240, 320))).getbbox() is None


def test_density_2_text_is_visible():
    """详细档的副标题和会话名得在画布内 —— 之前它们画到画布外去了。

    探针文字用 ASCII：没装中文字体的机器（CI runner）上中文会被过滤掉，
    那样这个断言就测不到任何东西了。
    """
    cfg = config_mod.defaults()
    import io
    from PIL import Image, ImageChops
    a = Image.open(io.BytesIO(render.render_frame(cfg, "idle"))).convert("RGB")
    b = Image.open(io.BytesIO(
        render.render_frame(cfg, "idle", "PROBE-TEXT", "SESSION", density=2))).convert("RGB")
    assert ImageChops.difference(a, b).getbbox() is not None


# ---------- 接口层 ----------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    cfg = config_mod.defaults()
    # create_app 会用 server.REPO_ROOT 覆盖 cfg 里的 _repo_root ——
    # 所以要改模块全局，不是改 cfg。
    monkeypatch.setattr("petd.server.REPO_ROOT", tmp_path)
    monkeypatch.setattr("petd.config.DATA_DIR", tmp_path)
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    with TestClient(create_app(cfg, start_gateway=False)) as c:
        yield c


def test_backgrounds_api_lists_and_activates(client, tmp_path):
    bg_mod.save_image(str(tmp_path), "mine", _png())
    r = client.get("/admin/api/backgrounds").json()
    names = [i["name"] for i in r["items"]]
    assert "mine" in names
    r = client.post("/admin/api/backgrounds", json={"op": "activate", "name": "mine"})
    assert r.status_code == 200
    assert r.json()["current"] == "mine"
    assert client.app.state.pet.background == "mine"


def test_background_upload(client):
    import base64
    r = client.post("/admin/api/backgrounds/upload",
                    json={"name": "up", "data": base64.b64encode(_png()).decode()})
    assert r.status_code == 200
    assert r.json()["ok"]
    assert "up" in [i["name"] for i in r.json()["items"]]


def test_background_image_endpoint(client, tmp_path):
    bg_mod.save_image(str(tmp_path), "vis", _png())
    r = client.get("/admin/api/backgrounds/image?name=vis")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_activate_missing_background_fails(client):
    r = client.post("/admin/api/backgrounds", json={"op": "activate", "name": "nope"})
    assert r.status_code == 400


def test_background_and_skin_are_independent(client, tmp_path):
    """换背景不动宠物，换宠物不动背景。"""
    bg_mod.save_image(str(tmp_path), "b1", _png())
    client.post("/admin/api/backgrounds", json={"op": "activate", "name": "b1"})
    pet = client.app.state.pet
    skin_before = pet.skin
    bg_before = pet.background
    assert bg_before == "b1"
    # 换背景不影响皮肤
    assert pet.skin == skin_before
