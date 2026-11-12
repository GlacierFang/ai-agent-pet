"""游戏包（pack）的校验测试。

pack 是设备端引擎的数据文件 —— 它声明的能力必须都在固件的能力表里，
不然设备会拒绝加载，那个游戏在用户设备上就玩不了。

这套校验跟 tools/lint_packs.py 是同一份逻辑 —— 那边给命令行用，这边给 CI 用。
（CI 的 workflow 文件里加不进去：出口代理禁写 .github/workflows/。
  做成测试就绕开了这个限制，效果一样 —— 跑单测那一步就会检查。）
"""
import importlib.util
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import packs as packs_mod  # noqa: E402


def _load_lint():
    """加载 tools/lint_packs.py —— 它不在包里，按路径加载。"""
    path = ROOT / "tools" / "lint_packs.py"
    spec = importlib.util.spec_from_file_location("lint_packs", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_builtin_packs_pass_lint():
    """仓库自带的 pack 都要过校验。"""
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "lint_packs.py")],
                         capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0, out.stdout + out.stderr


def test_builtin_packs_are_discoverable():
    """内置 pack 都要能被 petd 找到 —— 后台要列得出来才能勾选。"""
    ids = packs_mod.known_ids()
    assert "dice" in ids
    assert "snake" in ids
    assert "whack" in ids


def test_every_pack_declares_supported_capabilities():
    """pack 声明的每个能力都必须在固件的能力表里。

    能力表只有一处真相（firmware/main/game/game_comp.c）。
    加了能力忘了同步，这里就会红。
    """
    lint = _load_lint()
    caps = lint.firmware_caps()
    files = sorted((ROOT / "petd" / "packs").glob("*.json"))
    assert files, "没有 pack 文件"
    for f in files:
        errs = lint.check_pack(f, caps)
        assert not errs, "%s: %s" % (f.name, "; ".join(errs))


def test_pack_glyphs_cover_their_own_text():
    """pack 里的中文得自带字模 —— 否则设备上显示的是空白。"""
    import json

    for f in sorted((ROOT / "petd" / "packs").glob("*.json")):
        blob = json.loads(f.read_text(encoding="utf-8"))
        glyphs = blob.get("glyphs") or {}
        text = str(blob.get("title") or "") + str(blob.get("hint") or "")
        need = {ch for ch in text if ord(ch) >= 128}
        missing = need - set(glyphs)
        assert not missing, "%s 缺字模: %s" % (f.name, "".join(sorted(missing)))


def test_packs_have_titles_and_hints():
    """标题和操作说明 —— 后台菜单和屏上提示都要用。"""
    for d in packs_mod.list_packs():
        assert d["title"], "%s 没标题" % d["id"]
        assert d["hint"], "%s 没操作说明" % d["id"]


def test_user_pack_dir_is_not_tracked():
    """用户自己的游戏包不进仓库。

    文档明确让用户把自创作的 pack 放进 petd/data/packs/。
    这个目录要是没被 git 忽略，用户手一抖 git add . 就把自己的包提交了。

    其他用户资产（皮肤 / 相册 / 背景）都有这层保护，packs 不能漏。
    """
    out = subprocess.run(["git", "check-ignore", "-q",
                          "petd/data/packs/mypack.json"],
                         capture_output=True, cwd=str(ROOT))
    assert out.returncode == 0, "petd/data/packs/ 没被 git 忽略"


def test_all_user_asset_dirs_are_ignored():
    """所有用户资产目录都得在 .gitignore 里 —— 漏一个就是一个泄漏口。"""
    for d in ("skins", "ota", "album", "backgrounds",
              "card_backgrounds", "packs"):
        out = subprocess.run(["git", "check-ignore", "-q",
                              "petd/data/%s/x.json" % d],
                             capture_output=True, cwd=str(ROOT))
        assert out.returncode == 0, "petd/data/%s/ 没被 git 忽略" % d
