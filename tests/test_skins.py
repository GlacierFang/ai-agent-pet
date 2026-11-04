"""宠物的测试。

宠物是「用户自己的资产」：仓库自带一份，用户可以在自己的 petd/data/ 里改。

一套宠物 = 六态各一张图。不分帧。
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import skins  # noqa: E402


@pytest.fixture()
def repo(tmp_path):
    return tmp_path / "repo"


def _png_bytes(color=(255, 0, 0, 255)):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGBA", (240, 320), color).save(buf, format="PNG")
    return buf.getvalue()


def test_user_skin_shadows_repo_skin(repo):
    (repo / "skins" / "cat").mkdir(parents=True)
    (repo / "petd" / "data" / "skins" / "cat").mkdir(parents=True)
    names = skins.list_skins(repo)
    assert names == ["cat"]
    assert skins.skin_source(repo, "cat") == "user"


def test_skin_info_counts_states(repo):
    d = repo / "skins" / "cat"
    d.mkdir(parents=True)
    (d / "idle.png").write_bytes(_png_bytes())
    (d / "working.png").write_bytes(_png_bytes())
    info = skins.skin_info(repo, "cat")
    assert info["states"] == {"idle": 1, "working": 1}
    assert info["missing"] == ["waiting", "done", "error", "sleeping"]
    assert info["source"] == "builtin"


def test_skin_info_has_no_frames_field(repo):
    """不再有「帧数」这个概念 —— 一态就是一张。"""
    d = repo / "skins" / "cat"
    d.mkdir(parents=True)
    (d / "idle.png").write_bytes(_png_bytes())
    assert "frames" not in skins.skin_info(repo, "cat")


def test_invalid_skin_name_rejected(repo):
    with pytest.raises(ValueError):
        skins.create_skin(repo, "../etc")
    with pytest.raises(ValueError):
        skins.create_skin(repo, "a/b")
    with pytest.raises(ValueError):
        skins.create_skin(repo, "a:b")
    with pytest.raises(ValueError):
        skins.create_skin(repo, "")


def test_chinese_skin_name_allowed(repo):
    """用户起中文名 —— 不该被文件系统逼着只能用字母。"""
    d = skins.create_skin(repo, "咖啡猫")
    assert d.is_dir()
    assert "咖啡猫" in skins.list_skins(repo)


def test_builtin_pet_has_display_title(repo):
    """内置那只在界面上叫「默认宠物」，目录名还是 default。"""
    (repo / "skins" / "default").mkdir(parents=True)
    info = skins.skin_info(repo, "default")
    assert info["title"] == "默认宠物"
    assert info["name"] == "default"


def test_user_pet_title_is_its_own_name(repo):
    skins.create_skin(repo, "咖啡猫")
    info = skins.skin_info(repo, "咖啡猫")
    assert info["title"] == "咖啡猫"


def test_reserved_name_rejected(repo):
    """default 是内置形象 —— 用户不能占这个名字。"""
    with pytest.raises(ValueError):
        skins.create_skin(repo, "default")


def test_delete_only_user_skins(repo):
    (repo / "skins" / "cat").mkdir(parents=True)
    with pytest.raises(ValueError):
        skins.delete_skin(repo, "cat")
    skins.create_skin(repo, "mine")
    assert skins.delete_skin(repo, "mine") is True
    assert "mine" not in skins.list_skins(repo)


def test_save_image_rejects_non_png(repo):
    with pytest.raises(ValueError):
        skins.save_image(repo, "cat", "idle", b"not an image")


def test_save_image_rejects_bad_state(repo):
    with pytest.raises(ValueError):
        skins.save_image(repo, "cat", "nope", _png_bytes())


def test_save_image_writes_state_png(repo):
    path = skins.save_image(repo, "cat", "idle", _png_bytes())
    assert path.name == "idle.png"
    assert path.exists()
    assert skins.has_skin(repo, "cat", "idle")


def test_save_image_replaces_same_state(repo):
    """同一态只有一张 —— 重传即替换，不留旧的多帧残留。"""
    red = _png_bytes((255, 0, 0, 255))
    skins.save_image(repo, "cat", "idle", red)
    skins.save_image(repo, "cat", "idle", _png_bytes((0, 255, 0, 255)))
    d = repo / "petd" / "data" / "skins" / "cat"
    files = sorted(p.name for p in d.iterdir())
    assert files == ["idle.png"]
    # 换成了新的那张，不是旧的还在
    assert (d / "idle.png").read_bytes() != red


def test_six_states_make_a_complete_skin(repo):
    for st in skins.STATES:
        skins.save_image(repo, "cat", st, _png_bytes())
    assert skins.missing_states(repo, "cat") == []
    info = skins.skin_info(repo, "cat")
    assert len(info["states"]) == 6
