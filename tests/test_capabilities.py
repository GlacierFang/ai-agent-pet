"""能力清单 + 形象素材的测试。

这两块是「用户自己的资产」：仓库自带一份，用户可以在自己的 petd/data/ 里改。
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import capabilities, skins  # noqa: E402


@pytest.fixture()
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


# ---------- 能力清单 ----------

def test_builtin_capabilities_load(data_dir):
    (data_dir / "capabilities.json").write_text(json.dumps({
        "version": 1,
        "capabilities": [
            {"id": "a.one", "name": "甲", "action": "state.refresh"},
            {"id": "a.two", "name": "乙", "action": "bogus.action"},
        ],
    }), encoding="utf-8")
    out = capabilities.load(data_dir)
    assert [c["id"] for c in out["items"]] == ["a.one", "a.two"]
    # 不认识的动作被丢掉，不静默接受
    assert out["items"][1]["action"] == ""


def test_user_overrides_builtin(data_dir):
    (data_dir / "capabilities.json").write_text(json.dumps({
        "version": 1,
        "capabilities": [{"id": "a.one", "name": "仓库版"}],
    }), encoding="utf-8")
    (data_dir / "capabilities.local.json").write_text(json.dumps({
        "version": 1,
        "capabilities": [{"id": "a.one", "name": "我的版"}],
    }), encoding="utf-8")
    out = capabilities.load(data_dir)
    assert len(out["items"]) == 1
    assert out["items"][0]["name"] == "我的版"
    assert out["items"][0]["source"] == "user"


def test_user_can_add_capability(data_dir):
    (data_dir / "capabilities.json").write_text(json.dumps({
        "version": 1, "capabilities": [],
    }), encoding="utf-8")
    capabilities.save_user([{"id": "my.thing", "name": "我的能力",
                             "action": "session.next"}], data_dir)
    out = capabilities.load(data_dir)
    assert [c["id"] for c in out["items"]] == ["my.thing"]
    assert out["userItems"][0]["name"] == "我的能力"


def test_entry_without_id_is_dropped(data_dir):
    capabilities.save_user([{"name": "没 id"}, {"id": "ok", "name": "有 id"}], data_dir)
    out = capabilities.load(data_dir)
    assert [c["id"] for c in out["items"]] == ["ok"]


def test_disabled_capability_kept_but_marked(data_dir):
    capabilities.save_user([{"id": "x", "name": "关掉的", "enabled": False}],
                            data_dir)
    out = capabilities.load(data_dir)
    assert out["items"][0]["enabled"] is False


def test_only_declared_actions_allowed(data_dir):
    """清单只能声明白名单里的动作 —— 不开放任意命令执行。"""
    capabilities.save_user([{"id": "x", "action": "os.system"}], data_dir)
    out = capabilities.load(data_dir)
    assert out["items"][0]["action"] == ""


# ---------- 形象 ----------

def test_user_skin_shadows_repo_skin(tmp_path):
    repo = tmp_path / "repo"
    (repo / "skins" / "cat" / "frames" / "idle").mkdir(parents=True)
    (repo / "petd" / "data" / "skins" / "cat" / "frames" / "idle").mkdir(parents=True)
    names = skins.list_skins(repo)
    assert names == ["cat"]
    assert skins.skin_source(repo, "cat") == "user"


def test_skin_info_counts_states(tmp_path):
    repo = tmp_path / "repo"
    d = repo / "skins" / "cat" / "frames" / "idle"
    d.mkdir(parents=True)
    (d / "idle_00.png").write_bytes(b"x")
    info = skins.skin_info(repo, "cat")
    assert info["states"] == {"idle": 1}
    assert info["frames"] == 1
    assert info["source"] == "builtin"


def test_invalid_skin_name_rejected(tmp_path):
    repo = tmp_path / "repo"
    with pytest.raises(ValueError):
        skins.create_skin(repo, "../etc")
    with pytest.raises(ValueError):
        skins.create_skin(repo, "a/b")


def test_delete_only_user_skins(tmp_path):
    repo = tmp_path / "repo"
    (repo / "skins" / "cat").mkdir(parents=True)
    with pytest.raises(ValueError):
        skins.delete_skin(repo, "cat")
    skins.create_skin(repo, "mine")
    assert skins.delete_skin(repo, "mine") is True
    assert "mine" not in skins.list_skins(repo)


def test_save_frame_rejects_non_png(tmp_path):
    repo = tmp_path / "repo"
    with pytest.raises(ValueError):
        skins.save_frame(repo, "cat", "idle", 0, b"not an image")


def test_save_frame_writes_png(tmp_path):
    from PIL import Image
    import io
    repo = tmp_path / "repo"
    buf = io.BytesIO()
    Image.new("RGBA", (240, 320), (255, 0, 0, 255)).save(buf, format="PNG")
    path = skins.save_frame(repo, "cat", "idle", 2, buf.getvalue())
    assert path.name == "idle_02.png"
    assert path.exists()
    assert skins.has_skin(repo, "cat", "idle")
