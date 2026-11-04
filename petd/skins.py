"""皮肤：仓库自带 + 用户自建。

仓库： <repo>/skins/<name>/<state>.png
用户： <repo>/petd/data/skins/<name>/<state>.png

一套皮肤 = 六个状态各**一张**静态图。不分帧、不做动画 —— 屏上任何一刻
都是六态中的某一态，一态一张就够。

用户皮肤不进仓库（gitignore），后台可以上传维护。
目录约定见 docs/美术规范.md。
"""
import io
import pathlib
import re

from PIL import Image

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

STATES = ("idle", "working", "waiting", "done", "error", "sleeping")

# 内置形象的名字。用户不能占 —— 否则用户那份会盖掉内置的 default。
RESERVED = ("default",)


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


def skin_dir(repo_root, skin):
    """形象目录。用户那份盖掉仓库那份 —— 整套盖，不是一态一态混着来。"""
    for root in _roots(repo_root, skin):
        if root.is_dir():
            return root
    return user_root(repo_root) / str(skin)


def state_path(repo_root, skin, state):
    """某一态的图 —— <skin>/<state>.png。"""
    return skin_dir(repo_root, skin) / ("%s.png" % state)


def load_image(repo_root, skin, state):
    """读某一态的图。没有就返回 None —— 屏上那一格空着，不补画。"""
    p = state_path(repo_root, skin, state)
    if not p.is_file():
        return None
    try:
        return Image.open(p).convert("RGBA")
    except Exception:
        return None


def has_skin(repo_root, skin, state):
    return state_path(repo_root, skin, state).is_file()


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
    """还缺哪些状态。空列表 = 六态齐了。"""
    return [st for st in STATES if not has_skin(repo_root, skin, st)]


def skin_info(repo_root, skin):
    """一个形象的详情：有哪些状态、还缺哪些。"""
    info = {"name": skin, "source": skin_source(repo_root, skin), "states": {}}
    for st in STATES:
        if has_skin(repo_root, skin, st):
            info["states"][st] = 1
    info["missing"] = missing_states(repo_root, skin)
    return info


def list_skin_info(repo_root):
    return [skin_info(repo_root, n) for n in list_skins(repo_root)]


def create_skin(repo_root, skin):
    if not valid_name(skin):
        raise ValueError("形象名只能是字母、数字、下划线、连字符")
    if str(skin) in RESERVED:
        raise ValueError("%s 是内置形象，不能用这个名字" % skin)
    d = user_root(repo_root) / str(skin)
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


def save_image(repo_root, skin, state, png_bytes):
    """存某一态的图。同一态只有一张 —— 重传即替换。"""
    if not valid_name(skin):
        raise ValueError("形象名不合法")
    if state not in STATES:
        raise ValueError("状态名不合法")
    # 先验一遍是不是真 PNG —— 别把乱七八糟的东西写进素材目录
    try:
        img = Image.open(io.BytesIO(png_bytes))
        img.load()
    except Exception as exc:
        raise ValueError("不是有效的图片: %s" % exc)
    d = create_skin(repo_root, skin)
    path = d / ("%s.png" % state)
    path.write_bytes(png_bytes)
    return path
