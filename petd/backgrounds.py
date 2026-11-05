"""背景：仓库自带 + 用户自建。

仓库： <repo>/backgrounds/<name>.png
用户： <repo>/petd/data/backgrounds/<name>.png

一张背景 = 一张 240×320 的图，铺满整屏。

背景和宠物形象是**解耦**的两件事 ——
换宠物不影响背景，换背景不影响宠物。
用户自己维护背景，跟维护宠物形象一样。

目录约定见 docs/美术规范.md。
"""
import io
import pathlib

from PIL import Image

# 名字直接当目录名用（petd/data/backgrounds/<名字>/）。中文原样存 ——
# 用户起名不该被文件系统逼着只能用字母。只挡真会拼坏路径的字符。
_BAD_CHARS = set('/\\:*?"<>|')
NAME_MAX = 40

# 屏幕尺寸 —— 背景按这个铺。
SCREEN_W = 240
SCREEN_H = 320

# 内置背景的名字。用户不能占 —— 否则用户那份会盖掉内置的 default。
RESERVED = ("default",)

# 内置背景在界面上叫什么。目录名还是 default，只是显示得好看点。
BUILTIN_TITLES = {"default": "默认背景"}


def valid_name(name):
    """名字要能安全地当目录名用 —— 中文照原样保留。"""
    name = str(name or "").strip()
    if not name or len(name) > NAME_MAX:
        return False
    if name in (".", ".."):
        return False
    for ch in name:
        if ch in _BAD_CHARS or ord(ch) < 32:
            return False
    return True


def user_root(repo_root):
    return pathlib.Path(repo_root) / "petd" / "data" / "backgrounds"


def repo_bg_root(repo_root):
    return pathlib.Path(repo_root) / "backgrounds"


def _roots(repo_root, name):
    # 用户那份优先 —— 同名时盖掉仓库那份。
    return [user_root(repo_root) / ("%s.png" % name),
            repo_bg_root(repo_root) / ("%s.png" % name)]


def bg_path(repo_root, name):
    """背景图文件 —— <name>.png。用户那份盖掉仓库那份。"""
    for p in _roots(repo_root, name):
        if p.is_file():
            return p
    return user_root(repo_root) / ("%s.png" % name)


def load_image(repo_root, name):
    """读背景图。没有就返回 None —— 屏上退回状态色渐变。"""
    p = bg_path(repo_root, name)
    if not p.is_file():
        return None
    try:
        return Image.open(p).convert("RGB")
    except Exception:
        return None


def has_bg(repo_root, name):
    return bg_path(repo_root, name).is_file()


def list_bgs(repo_root):
    """所有可用背景的名字（用户 + 仓库），去重。"""
    names = []
    for base in (user_root(repo_root), repo_bg_root(repo_root)):
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*.png")):
            if p.stem not in names:
                names.append(p.stem)
    return names


def bg_source(repo_root, name):
    if (user_root(repo_root) / ("%s.png" % name)).is_file():
        return "user"
    if (repo_bg_root(repo_root) / ("%s.png" % name)).is_file():
        return "builtin"
    return ""


def bg_info(repo_root, name):
    """一张背景的详情。"""
    p = bg_path(repo_root, name)
    size = ""
    if p.is_file():
        try:
            with Image.open(p) as im:
                size = "%dx%d" % im.size
        except Exception:
            size = ""
    return {"name": name,
            "title": BUILTIN_TITLES.get(name, name),
            "source": bg_source(repo_root, name),
            "size": size}


def list_bg_info(repo_root):
    return [bg_info(repo_root, n) for n in list_bgs(repo_root)]


def create_bg(repo_root, name):
    if not valid_name(name):
        raise ValueError("名字里不能有 / \\ : * ? \" < > | 这些符号")
    if str(name) in RESERVED:
        raise ValueError("%s 是内置背景，不能用这个名字" % name)
    d = user_root(repo_root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def delete_bg(repo_root, name):
    """只能删用户自己的 —— 仓库自带的别乱动。"""
    if not valid_name(name):
        raise ValueError("名字不合法")
    if str(name) in RESERVED:
        raise ValueError("内置背景不能删")
    p = user_root(repo_root) / ("%s.png" % name)
    if not p.is_file():
        raise ValueError("没有这个背景")
    p.unlink()
    return True


def save_image(repo_root, name, png_bytes):
    """存一张背景图。

    格式不挑 —— Pillow 按内容识别，PNG / JPEG / WebP 都收。
    但存的时候统一转成 PNG：渐变背景用 JPEG 会有块状伪影。
    """
    if not valid_name(name):
        raise ValueError("名字不合法")
    try:
        img = Image.open(io.BytesIO(png_bytes))
        img.load()
    except Exception as exc:
        raise ValueError("不是有效的图片: %s" % exc)
    img = img.convert("RGB").resize((SCREEN_W, SCREEN_H), Image.LANCZOS)
    d = create_bg(repo_root, name)
    path = d / ("%s.png" % name)
    img.save(path, format="PNG")
    return path


def image_bytes(repo_root, name):
    """背景图的原始字节 —— 后台预览用。"""
    p = bg_path(repo_root, name)
    if not p.is_file():
        return None
    try:
        return p.read_bytes()
    except OSError:
        return None
