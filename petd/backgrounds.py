"""背景：仓库自带 + 用户自建。

背景分**两套**，各管各的，互不串：

- **宠物背景** —— 铺在宠物那一屏
  仓库： <repo>/backgrounds/<name>.png
  用户： <repo>/petd/data/backgrounds/<name>.png
- **卡片背景** —— 铺在内容卡和骰子上
  仓库： <repo>/card_backgrounds/<name>.png
  用户： <repo>/petd/data/card_backgrounds/<name>.png

两套各有自己的目录、自己的清单、自己的上传入口 ——
宠物背景那张图不会出现在卡片背景列表里，反之亦然。
想给卡片换个底，就在卡片背景那一栏自己传一张。

一张背景 = 一张 240×320 的图，铺满整屏。

背景和宠物形象是**解耦**的两件事 ——
换宠物不影响背景，换背景不影响宠物。

目录约定见 docs/美术规范.md。
"""
import io
import pathlib

from PIL import Image

# 两套背景的种类。
KIND_PET = "pet"    # 宠物背景 —— 铺在宠物那一屏
KIND_CARD = "card"  # 卡片背景 —— 铺在内容卡和骰子上

# 每套背景落盘的位置：(仓库目录, 用户目录)。
# 仓库那份是随版本走的底线，用户那份同名盖掉它。
# 卡片背景的仓库目录现在没有内置图 —— 卡片默认用自己的深色渐变。
_KIND_DIRS = {
    KIND_PET: ("backgrounds", "backgrounds"),
    KIND_CARD: ("card_backgrounds", "card_backgrounds"),
}

# 名字直接当目录名用（petd/data/backgrounds/<名字>.png）。中文原样存 ——
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


def _dirs(kind):
    """这套背景的 (仓库目录, 用户目录)。"""
    if kind not in _KIND_DIRS:
        raise ValueError("未知的背景种类：%s" % kind)
    return _KIND_DIRS[kind]


def user_root(repo_root, kind=KIND_PET):
    """用户自己上传的那份落在哪儿。"""
    return pathlib.Path(repo_root) / "petd" / "data" / _dirs(kind)[1]


def repo_bg_root(repo_root, kind=KIND_PET):
    """仓库自带的那份落在哪儿。"""
    return pathlib.Path(repo_root) / _dirs(kind)[0]


def _roots(repo_root, name, kind):
    # 用户那份优先 —— 同名时盖掉仓库那份。
    return [user_root(repo_root, kind) / ("%s.png" % name),
            repo_bg_root(repo_root, kind) / ("%s.png" % name)]


def bg_path(repo_root, name, kind=KIND_PET):
    """背景图文件 —— <name>.png。用户那份盖掉仓库那份。"""
    for p in _roots(repo_root, name, kind):
        if p.is_file():
            return p
    return user_root(repo_root, kind) / ("%s.png" % name)


def load_image(repo_root, name, kind=KIND_PET):
    """读背景图。没有就返回 None —— 屏上退回状态色渐变。"""
    p = bg_path(repo_root, name, kind)
    if not p.is_file():
        return None
    try:
        return Image.open(p).convert("RGB")
    except Exception:
        return None


def has_bg(repo_root, name, kind=KIND_PET):
    return bg_path(repo_root, name, kind).is_file()


def list_bgs(repo_root, kind=KIND_PET):
    """这套背景里所有可用的名字（用户 + 仓库），去重。"""
    names = []
    for base in (user_root(repo_root, kind), repo_bg_root(repo_root, kind)):
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*.png")):
            if p.stem not in names:
                names.append(p.stem)
    return names


def bg_source(repo_root, name, kind=KIND_PET):
    if (user_root(repo_root, kind) / ("%s.png" % name)).is_file():
        return "user"
    if (repo_bg_root(repo_root, kind) / ("%s.png" % name)).is_file():
        return "builtin"
    return ""


def bg_info(repo_root, name, kind=KIND_PET):
    """一张背景的详情。"""
    p = bg_path(repo_root, name, kind)
    size = ""
    if p.is_file():
        try:
            with Image.open(p) as im:
                size = "%dx%d" % im.size
        except Exception:
            size = ""
    return {"name": name,
            "title": BUILTIN_TITLES.get(name, name),
            "source": bg_source(repo_root, name, kind),
            "size": size}


def list_bg_info(repo_root, kind=KIND_PET):
    return [bg_info(repo_root, n, kind) for n in list_bgs(repo_root, kind)]


def create_bg(repo_root, name, kind=KIND_PET):
    if not valid_name(name):
        raise ValueError("名字里不能有 / \\ : * ? \" < > | 这些符号")
    if str(name) in RESERVED:
        raise ValueError("%s 是内置背景，不能用这个名字" % name)
    d = user_root(repo_root, kind)
    d.mkdir(parents=True, exist_ok=True)
    return d


def delete_bg(repo_root, name, kind=KIND_PET):
    """只能删用户自己的 —— 仓库自带的别乱动。"""
    if not valid_name(name):
        raise ValueError("名字不合法")
    if str(name) in RESERVED:
        raise ValueError("内置背景不能删")
    p = user_root(repo_root, kind) / ("%s.png" % name)
    if not p.is_file():
        raise ValueError("没有这个背景")
    p.unlink()
    return True


def save_image(repo_root, name, png_bytes, kind=KIND_PET):
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
    d = create_bg(repo_root, name, kind)
    path = d / ("%s.png" % name)
    img.save(path, format="PNG")
    return path


def image_bytes(repo_root, name, kind=KIND_PET):
    """背景图的原始字节 —— 后台预览用。"""
    p = bg_path(repo_root, name, kind)
    if not p.is_file():
        return None
    try:
        return p.read_bytes()
    except OSError:
        return None
