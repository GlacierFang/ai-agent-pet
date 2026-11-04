"""相册：用户上传的照片，轮播时一张一张显示。

照片存在 petd/data/album/，index.json 记顺序和原名。
index.json 是唯一的元数据 —— 不再给每张照片建一堆字段。

上限 10 张：屏只有 240x320，塞不下更多，轮一圈也没必要那么久。

存的统一是 JPEG —— 设备那边收的就是 JPEG 帧，存别的格式等于渲染时多转一次。
"""

import io
import json
import pathlib
import re
import uuid

from PIL import Image, ImageOps

from . import config as config_mod

MAX_PHOTOS = 10
MAX_EDGE = 1280          # 存盘长边上限 —— 屏只有 240x320，存原始大图白占磁盘
QUALITY = 82
THUMB_EDGE = 480         # 后台缩略图
DIR_NAME = "album"
INDEX_NAME = "index.json"

# 存盘的文件名长这样 —— 顺序靠 index.json，不靠文件名。
_NAME_RE = re.compile(r"^[0-9a-f]{16}\.jpg$")

# 上传的原始数据上限（base64 字符串长度）—— 挡住一把塞几百兆的请求
MAX_UPLOAD_B64 = 12 * 1024 * 1024


def album_dir():
    """相册目录。调用时取 DATA_DIR —— 测试会把它换掉。"""
    return pathlib.Path(config_mod.DATA_DIR) / DIR_NAME


def index_path():
    return album_dir() / INDEX_NAME


def _safe_name(name):
    """只认自己生成的文件名 —— 别让路径拼到目录外面去。"""
    name = str(name or "")
    if not _NAME_RE.match(name):
        return None
    p = (album_dir() / name).resolve()
    try:
        p.relative_to(album_dir().resolve())
    except ValueError:
        return None
    return name


def _read_index():
    """读顺序表。读坏了就当空的 —— 索引坏了不该让相册整个打不开。"""
    try:
        blob = json.loads(index_path().read_text(encoding="utf-8"))
    except Exception:
        return []
    items = blob.get("photos") if isinstance(blob, dict) else blob
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        f = _safe_name(it.get("file"))
        if f and (album_dir() / f).is_file():
            out.append({"file": f, "name": str(it.get("name") or "")[:80]})
    return out


def _write_index(items):
    d = album_dir()
    d.mkdir(parents=True, exist_ok=True)
    index_path().write_text(
        json.dumps({"photos": items}, ensure_ascii=False, indent=2),
        encoding="utf-8")


def list_items():
    """按顺序返回照片记录 —— 文件名和原名。"""
    return _read_index()


def list_photos():
    """按顺序返回照片的绝对路径。"""
    d = album_dir()
    return [str(d / it["file"]) for it in _read_index()]


def count():
    return len(_read_index())


def _flatten(img):
    """各种模式转成 RGB —— JPEG 存不了带透明的。"""
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def add(data, name=""):
    """加一张照片。返回这条记录。

    data 是原始图片字节（JPEG / PNG / WebP 都行），存的时候统一转 JPEG。
    """
    n = count()
    if n >= MAX_PHOTOS:
        raise ValueError("最多 %d 张，已经 %d 张了" % (MAX_PHOTOS, n))
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise ValueError("不是有效的图片：%s" % exc)
    # 手机照片的方向信息在 EXIF 里 —— 不转过来，照片会躺着显示
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    img = _flatten(img)
    w, h = img.size
    if max(w, h) > MAX_EDGE:
        factor = MAX_EDGE / float(max(w, h))
        img = img.resize((max(1, int(w * factor)), max(1, int(h * factor))),
                         Image.LANCZOS)
    d = album_dir()
    d.mkdir(parents=True, exist_ok=True)
    fname = _new_name()
    img.save(d / fname, format="JPEG", quality=QUALITY)
    rec = {"file": fname, "name": str(name or "")[:80]}
    items = _read_index()
    items.append(rec)
    _write_index(items)
    return rec


def _new_name():
    """生成一个不撞名的文件名。"""
    while True:
        fname = uuid.uuid4().hex[:16] + ".jpg"
        if not (album_dir() / fname).exists():
            return fname


def delete(file):
    """删一张。返回 True = 确实删掉了。"""
    fname = _safe_name(file)
    if not fname:
        return False
    items = _read_index()
    keep = [it for it in items if it["file"] != fname]
    if len(keep) == len(items):
        return False
    _write_index(keep)
    try:
        (album_dir() / fname).unlink()
    except OSError:
        pass
    return True


def thumb_bytes(file, max_edge=THUMB_EDGE):
    """后台缩略图的字节。没有就 None。"""
    fname = _safe_name(file)
    if not fname:
        return None
    p = album_dir() / fname
    if not p.is_file():
        return None
    try:
        img = Image.open(p)
        img.load()
    except Exception:
        return None
    w, h = img.size
    factor = min(1.0, float(max_edge) / float(max(w, h)))
    if factor < 1.0:
        img = img.resize((max(1, int(w * factor)), max(1, int(h * factor))),
                         Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()
