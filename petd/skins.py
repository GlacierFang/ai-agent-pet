"""皮肤：优先读 PNG 帧，没有就用程序化默认角色。

目录约定见 docs/美术规范.md：
    <repo>/skins/<name>/frames/<state>/<state>_00.png
"""
import pathlib

from PIL import Image


def frames_dir(repo_root, skin, state):
    return pathlib.Path(repo_root) / "skins" / str(skin) / "frames" / str(state)


def load_frames(repo_root, skin, state):
    d = frames_dir(repo_root, skin, state)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.png")):
        try:
            out.append(Image.open(f).convert("RGBA"))
        except Exception:
            continue
    return out


def has_skin(repo_root, skin, state):
    return frames_dir(repo_root, skin, state).is_dir()


def list_skins(repo_root):
    root = pathlib.Path(repo_root) / "skins"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())
