"""形象素材的测试。

素材是「用户自己的资产」：仓库自带一份，用户可以在自己的 petd/data/ 里改。
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


def test_user_skin_shadows_repo_skin(repo):
    (repo / "skins" / "cat" / "frames" / "idle").mkdir(parents=True)
    (repo / "petd" / "data" / "skins" / "cat" / "frames" / "idle").mkdir(parents=True)
    names = skins.list_skins(repo)
    assert names == ["cat"]
    assert skins.skin_source(repo, "cat") == "user"


def test_skin_info_counts_states(repo):
    d = repo / "skins" / "cat" / "frames" / "idle"
    d.mkdir(parents=True)
    (d / "idle_00.png").write_bytes(b"x")
    info = skins.skin_info(repo, "cat")
    assert info["states"] == {"idle": 1}
    assert info["frames"] == 1
    assert info["source"] == "builtin"


def test_invalid_skin_name_rejected(repo):
    with pytest.raises(ValueError):
        skins.create_skin(repo, "../etc")
    with pytest.raises(ValueError):
        skins.create_skin(repo, "a/b")


def test_delete_only_user_skins(repo):
    (repo / "skins" / "cat").mkdir(parents=True)
    with pytest.raises(ValueError):
        skins.delete_skin(repo, "cat")
    skins.create_skin(repo, "mine")
    assert skins.delete_skin(repo, "mine") is True
    assert "mine" not in skins.list_skins(repo)


def test_save_frame_rejects_non_png(repo):
    with pytest.raises(ValueError):
        skins.save_frame(repo, "cat", "idle", 0, b"not an image")


def test_save_frame_writes_png(repo):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGBA", (240, 320), (255, 0, 0, 255)).save(buf, format="PNG")
    path = skins.save_frame(repo, "cat", "idle", 2, buf.getvalue())
    assert path.name == "idle_02.png"
    assert path.exists()
    assert skins.has_skin(repo, "cat", "idle")
