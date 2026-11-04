"""皮肤：仓库自带 + 用户自建。

仓库： <repo>/skins/<name>/frames/<state>/<state>_00.png
用户： <repo>/petd/data/skins/<name>/frames/<state>/<state>_00.png

用户皮肤不进仓库（gitignore），后台可以上传维护。
目录约定见 docs/美术规范.md。
"""
import pathlib
import re

from PIL import Image

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

STATES = ("idle", "working", "waiting", "done", "error", "sleeping")


def valid_name(name):
    """形象名必须是安全的短标识 —— 它会拼进文件路径。"""
    return bool(NAME_RE.match(str(name or "")))


def user_root(repo_root):
    return pathlib.Path(repo_root) / "petd" / "data" / "skins"


def repo_skin_root(repo_root):
    return pathlib.Path(repo_root) / "skins"


def _roots(repo_root, skin):
    """用户皮肤优先 —— 同名时用户的那套盖掉仓库的。"""
    return [user_root(repo_root) / str(skin), repo_skin_root(repo_root) / str(skin)]


def frames_dir(repo_root, skin, state):
    for root in _roots(repo_root, skin):
        d = root / "frames" / str(state)
        if d.is_dir():
            return d
    return user_root(repo_root) / str(skin) / "frames" / str(state)


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
    """所有可用形象的名字（用户 + 仓库），去重。"""
    names = []
    for base in (user_root(repo_root), repo_skin_root(repo_root)):
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            if p.is_dir() and p.name not in names:
                names.append(p.name)
    return names


def skin_source(repo_root, skin):
    if (user_root(repo_root) / str(skin)).is_dir():
        return "user"
    if (repo_skin_root(repo_root) / str(skin)).is_dir():
        return "builtin"
    return ""


def missing_states(repo_root, skin):
    """还缺哪些状态。空列表 = 六态齐了。

    default 是程序画的那张脸 —— 六态都有，不在磁盘上但照样能显示。
    """
    if str(skin) == "default":
        return []
    out = []
    for st in STATES:
        d = frames_dir(repo_root, skin, st)
        if not d.is_dir() or not any(d.glob("*.png")):
            out.append(st)
    return out


def skin_info(repo_root, skin):
    """一个形象的详情：有哪些状态、各几帧、还缺哪些。"""
    info = {"name": skin, "source": skin_source(repo_root, skin),
            "states": {}, "frames": 0}
    for st in STATES:
        d = frames_dir(repo_root, skin, st)
        n = len(list(d.glob("*.png"))) if d.is_dir() else 0
        if n:
            info["states"][st] = n
            info["frames"] += n
    info["missing"] = missing_states(repo_root, skin)
    return info


def list_skin_info(repo_root):
    return [skin_info(repo_root, n) for n in list_skins(repo_root)]


def create_skin(repo_root, skin):
    if not valid_name(skin):
        raise ValueError("形象名只能是字母、数字、下划线、连字符")
    d = user_root(repo_root) / str(skin) / "frames"
    d.mkdir(parents=True, exist_ok=True)
    return d


def delete_skin(repo_root, skin):
    """只能删用户自己的 —— 仓库自带的别乱动。"""
    if not valid_name(skin):
        raise ValueError("形象名不合法")
    d = user_root(repo_root) / str(skin)
    if not d.is_dir():
        raise ValueError("没有这个用户形象")
    import shutil
    shutil.rmtree(d)
    return True


def save_frame(repo_root, skin, state, index, png_bytes):
    """存一帧 PNG。index 决定它在动画里的位置。"""
    if not valid_name(skin):
        raise ValueError("形象名不合法")
    if state not in STATES:
        raise ValueError("状态名不合法")
    if index < 0 or index > 99:
        raise ValueError("序号超出范围")
    # 先验一遍是不是真 PNG —— 别把乱七八糟的东西写进素材目录
    import io
    try:
        img = Image.open(io.BytesIO(png_bytes))
        img.load()
    except Exception as exc:
        raise ValueError("不是有效的图片: %s" % exc)
    d = create_skin(repo_root, skin) / str(state)
    d.mkdir(parents=True, exist_ok=True)
    path = d / ("%s_%02d.png" % (state, int(index)))
    path.write_bytes(png_bytes)
    return path
