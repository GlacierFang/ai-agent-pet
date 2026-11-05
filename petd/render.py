"""服务端整帧渲染：Pillow → JPEG。

设备端零字体、零业务语义 —— 所有文字在这里烧进 JPEG。
版式：文字带在上，宠物在下 —— 跟功能卡一个顺序。
密度只管文字带显示几行字，宠物大小不变。
"""
import io
import os
import pathlib

from PIL import Image, ImageChops, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

PALETTE = {
    "idle": {"bg": (26, 32, 46), "body": (118, 190, 232), "glow": (150, 210, 245)},
    "working": {"bg": (32, 29, 48), "body": (150, 152, 235), "glow": (190, 190, 255)},
    "waiting": {"bg": (50, 38, 22), "body": (242, 172, 78), "glow": (255, 214, 140)},
    "done": {"bg": (24, 44, 34), "body": (118, 222, 152), "glow": (170, 250, 200)},
    "error": {"bg": (50, 26, 30), "body": (238, 120, 122), "glow": (255, 180, 180)},
    "sleeping": {"bg": (18, 20, 32), "body": (108, 118, 172), "glow": (150, 160, 210)},
}

# 文字带高度（逻辑 px）—— 顶部那条，放状态词、副标题、会话名。
#
# 文字在上、宠物在下：跟功能卡一个顺序。屏上不会一会儿头重脚轻，
# 一会儿脚重头轻。宠物区因此固定，密度只管显示几行字。
TEXT_BAND_H = 100

STATE_CN = {
    "idle": "闲置",
    "working": "干活",
    "waiting": "等你确认",
    "done": "刚完成",
    "error": "出错",
    "sleeping": "睡着了",
}

STATE_EN = {
    "idle": "idle",
    "working": "busy",
    "waiting": "waiting",
    "done": "done",
    "error": "error",
    "sleeping": "zzz",
}

_FONT_CACHE = {}


def _pick_font_path():
    for p in FONT_CANDIDATES:
        if pathlib.Path(p).exists():
            return p
    return None


def _font(size):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    path = _pick_font_path()
    f = None
    if path:
        try:
            f = ImageFont.truetype(path, size)
        except Exception:
            f = None
    if f is None:
        f = ImageFont.load_default()
    _FONT_CACHE[size] = (f, bool(path and ("CJK" in path or "wqy" in path or "PingFang" in path)))
    return _FONT_CACHE[size]


def _text(draw, xy, s, size, fill):
    f, cjk = _font(size)
    if not cjk:
        s = s.encode("ascii", "ignore").decode("ascii")
        if not s:
            return
    draw.text(xy, s, font=f, fill=fill)


def _center(draw, cx, y, s, size, fill):
    f, cjk = _font(size)
    if not cjk:
        s = s.encode("ascii", "ignore").decode("ascii")
        if not s:
            return
    box = draw.textbbox((0, 0), s, font=f)
    draw.text((cx - (box[2] - box[0]) / 2, y), s, font=f, fill=fill)


def _gradient(img, top, bottom):
    w, h = img.size
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        col = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=col)


def _scrim(img, top_y, bottom_y, max_alpha=215, dense_top=True):
    # 文字区铺一条暗带。
    # 文字压在背景图上得看得清 —— 用户自己画的背景可能是亮色。
    # dense_top=True  上浓下淡（文字带在顶部）
    # dense_top=False 上淡下浓（文字区在底部）
    w, h = img.size
    top_y = max(0, min(h, int(top_y)))
    bottom_y = max(top_y, min(h, int(bottom_y)))
    band_h = bottom_y - top_y
    if band_h <= 0:
        return img
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for y in range(top_y, bottom_y):
        t = (y - top_y) / max(1, band_h - 1)
        if dense_top:
            a = int(max_alpha * (1.0 - 0.55 * t))
        else:
            a = int(max_alpha * (0.5 + 0.5 * t))
        od.line([(0, y), (w, y)], fill=(8, 10, 16, a))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


CARD_BG_TOP = (24, 28, 44)
CARD_BG_BOTTOM = (13, 15, 24)

# 列表行右侧文字的颜色，按语义分
ACCENT_COLORS = {
    "waiting": (242, 172, 78),
    "error": (238, 120, 122),
    "working": (150, 152, 235),
    "done": (118, 222, 152),
    "idle": (150, 160, 185),
    "sleeping": (130, 138, 175),
}


def draw_standard_card(img, draw, box, card, pet=None):
    """自定义 feature 的默认版式：标题 + 正文 + 来源。

    box 是 (x, y, w, h)，坐标是超采样后的（屏幕尺寸的两倍）。
    pet 是那只宠物（RGBA 图），给了就画在下方。
    """
    x, y, w, h = box
    ty = y
    title = str(card.get("title") or "")
    if title:
        _center(draw, x + w // 2, ty, title, int(19 * 2), (238, 242, 250))
        ty += int(34 * 2)
    for line in [str(b) for b in (card.get("body") or [])][:3]:
        _center(draw, x + w // 2, ty, line, int(13 * 2), (186, 196, 216))
        ty += int(22 * 2)
    source = str(card.get("source") or "")
    if source:
        _center(draw, x + w // 2, ty + 4, source, int(9 * 2), (118, 126, 146))
    if pet is not None:
        img.paste(pet, (x, y + h - pet.size[1]), pet)


def render_card(cfg, card, skin_image=None, overlay=None):
    """内容层：一张 feature 整屏卡片。

    内容层和消息层互斥 —— 屏上永远只有一样东西。
    卡里那只宠物就是用户选的那只（宠物本体复用，feature 不带自己的美术）。

    卡片能带的字段：
        title  一行标题
        big    超大字（时间、温度）
        body   短句，最多三行
        rows   列表行 [{"left", "right", "accent"}]
        state  宠物表情
        source 底部小字
    """
    width = int(cfg.get("render", {}).get("width", 240))
    height = int(cfg.get("render", {}).get("height", 320))
    quality = int(cfg.get("render", {}).get("quality", 85))
    subsampling = int(cfg.get("render", {}).get("subsampling", 2))

    scale = 2
    big = Image.new("RGB", (width * scale, height * scale), CARD_BG_BOTTOM)
    _gradient(big, CARD_BG_TOP, CARD_BG_BOTTOM)
    d = ImageDraw.Draw(big)

    title = str(card.get("title") or "")
    big_text = str(card.get("big") or "")
    body = [str(b) for b in (card.get("body") or [])][:3]
    rows = [r for r in (card.get("rows") or []) if isinstance(r, dict)][:5]
    source = str(card.get("source") or "")

    ty = int(14 * scale)
    if title:
        _center(d, width * scale // 2, ty, title, int(19 * scale), (238, 242, 250))
        ty += int(32 * scale)
    if big_text:
        # 超大字 —— 时间、温度这类。它占地方，宠物就缩小。
        _center(d, width * scale // 2, ty, big_text, int(46 * scale), (246, 248, 255))
        ty += int(56 * scale)
    for line in body:
        _center(d, width * scale // 2, ty, line, int(13 * scale), (186, 196, 216))
        ty += int(20 * scale)

    # 列表行
    if rows:
        ty += int(6 * scale)
        for r in rows:
            left = str(r.get("left") or "")
            right = str(r.get("right") or "")
            accent = str(r.get("accent") or "idle")
            color = ACCENT_COLORS.get(accent, ACCENT_COLORS["idle"])
            if left:
                _text(d, (int(18 * scale), ty), left, int(12 * scale), (196, 204, 222))
            if right:
                f, cjk = _font(int(12 * scale))
                if cjk:
                    box = d.textbbox((0, 0), right, font=f)
                    rx = width * scale - int(18 * scale) - (box[2] - box[0])
                else:
                    rx = width * scale - int(18 * scale) - 7 * len(right)
                _text(d, (rx, ty), right, int(12 * scale), color)
            ty += int(20 * scale)

    if source:
        _center(d, width * scale // 2, ty + int(4 * scale), source,
                int(9 * scale), (118, 126, 146))

    # 宠物本体 —— 屏上那只就是用户选的那只
    area_top = ty + int(8 * scale)
    area_bottom = height * scale - int(6 * scale)
    area_h = max(int(40 * scale), area_bottom - area_top)
    pet = Image.new("RGBA", (width * scale, area_h), (0, 0, 0, 0))
    if skin_image is not None:
        # 皮肤图 —— 一态一张，等比缩放，不拉伸
        fw, fh = skin_image.size
        factor = min((width * scale) / fw, area_h / fh)
        nw, nh = max(1, int(fw * factor)), max(1, int(fh * factor))
        frame = skin_image.resize((nw, nh), Image.LANCZOS)
        pet.paste(frame, ((width * scale - nw) // 2, (area_h - nh) // 2), frame)
    big.paste(pet, (0, area_top), pet)

    img = big.resize((width, height), Image.LANCZOS)
    if overlay is not None:
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, subsampling=subsampling)
    return buf.getvalue()


# ---------- 防烧屏 ----------

# 长时间显示同一张图，IPS 屏的液晶会慢慢烙出残影。
# 这块屏的背光直接接 3.3V（硬件上没有开关），所以只能靠软件：
# 把画面挪一挪，让每个物理像素看到的内容持续变化。
#
# 位移是主力 —— 它直接改变像素显示的内容。
# 亮度微调是补刀 —— 纯色背景位移也看不出变化（所有像素电平相同，
# 移了还是同一个值），画面整体亮一点再暗回来，电平就在两个值之间来回。

# 每步 30 秒。四个位置循环 —— 每两分钟过一遍四种内容。
ANTI_BURN_STEP_SEC = 30
ANTI_BURN_POSITIONS = ((0, 0), (1, 0), (0, 1), (1, 1))
# 亮度偏移（色阶）。每走完一轮位置换一次档 —— 两档之间来回。
# ±4 约合 1.6% —— 肉眼基本看不出，但足以让像素的电平在两个值之间来回。
# 实测 ±2 也能活过 JPEG，但余量太小，这里留一倍。
ANTI_BURN_LEVELS = (4, -4)

# 亮度偏移的查找表。缓存起来 —— 每帧重算 768 个数没必要。
_LEVEL_LUTS = {}


def _level_lut(level):
    """亮度偏移的查找表。

    多通道图要 3*256 项 —— Pillow 自己处理 callable 时也是这么拼的。
    """
    lut = _LEVEL_LUTS.get(level)
    if lut is None:
        one = [max(0, min(255, v + level)) for v in range(256)]
        lut = one * 3
        _LEVEL_LUTS[level] = lut
    return lut


def anti_burn_state(now):
    """算出这一帧的防烧屏参数。

    返回 (dx, dy, level) —— dx/dy 是**逻辑像素**的位移，level 是亮度偏移色阶。
    """
    step = int(now // ANTI_BURN_STEP_SEC)
    dx, dy = ANTI_BURN_POSITIONS[step % len(ANTI_BURN_POSITIONS)]
    level = ANTI_BURN_LEVELS[(step // len(ANTI_BURN_POSITIONS)) % len(ANTI_BURN_LEVELS)]
    return dx, dy, level


def render_frame(cfg, state, subtitle="", session_name="", density=1,
                 skin_image=None, overlay=None, merit=0, background_image=None,
                 anti_burn=None):
    width = int(cfg.get("render", {}).get("width", 240))
    height = int(cfg.get("render", {}).get("height", 320))
    quality = int(cfg.get("render", {}).get("quality", 85))
    subsampling = int(cfg.get("render", {}).get("subsampling", 2))

    scale = 2
    big = Image.new("RGB", (width * scale, height * scale), (20, 22, 32))
    pal = PALETTE.get(state, PALETTE["idle"])

    # 背景 —— 铺满整屏。有背景图就用它，没有就退回状态色渐变。
    has_bg = background_image is not None
    if has_bg:
        bg = background_image.convert("RGB").resize((width * scale, height * scale),
                                                    Image.LANCZOS)
        big.paste(bg, (0, 0))
        # 状态色只留一层淡罩 —— 别把背景盖光
        tint = Image.new("RGBA", big.size, pal["bg"] + (46,))
        big = Image.alpha_composite(big.convert("RGBA"), tint).convert("RGB")
    else:
        _gradient(big, tuple(min(255, c + 14) for c in pal["bg"]), pal["bg"])

    density = max(0, min(2, int(density)))
    band_px = TEXT_BAND_H * scale

    # 文字带在顶部 —— 铺一条上浓下淡的暗带，字压在亮背景上也读得清
    if has_bg:
        big = _scrim(big, 0, band_px, dense_top=True)
    d = ImageDraw.Draw(big)
    if not has_bg:
        d.line([(0, band_px - int(1 * scale)), (width * scale, band_px - int(1 * scale))],
               fill=pal["glow"] + (70,), width=2)

    # 文字区 —— 从文字带顶部往下排
    ty = int(12 * scale)
    cjk = _font(18)[1]
    label = STATE_CN.get(state, state) if cjk else STATE_EN.get(state, state)
    _center(d, width * scale // 2, ty, label, int(18 * scale), pal["glow"])
    ty += int(30 * scale)

    if density >= 1 and subtitle:
        if cjk:
            _center(d, width * scale // 2, ty, subtitle[:22], int(12 * scale), (205, 212, 228))
        else:
            _center(d, width * scale // 2, ty, subtitle[:30], int(12 * scale), (205, 212, 228))
        ty += int(20 * scale)

    if density >= 2 and session_name:
        if cjk:
            _center(d, width * scale // 2, ty, session_name[:16], int(11 * scale), (150, 160, 185))
        else:
            _center(d, width * scale // 2, ty, session_name[:26], int(11 * scale), (150, 160, 185))
        ty += int(18 * scale)

    # 功德计数 —— 常驻左上角。宠物挪到底下，这里才不会被压到。
    # 飘字只是一瞬间，想看累计值的时候得有个地方能看。
    if merit:
        _text(d, (int(6 * scale), int(10 * scale)),
              "功德 %d" % int(merit), int(9 * scale), (150, 158, 180))

    # 宠物区 —— 底部，高度固定，密度不影响它
    pet_h = height * scale - band_px
    pet = Image.new("RGBA", (width * scale, pet_h), (0, 0, 0, 0))
    if skin_image is not None:
        # 皮肤图 —— 一态一张，等比缩放，不拉伸。
        # 整幅缩放，不裁到墨迹：六态墨迹范围不一样，
        # 一裁，宠物切状态时就会上下跳。
        sw, sh = skin_image.size
        box_w = width * scale
        factor = min(box_w / sw, pet_h / sh)
        nw, nh = max(1, int(sw * factor)), max(1, int(sh * factor))
        frame = skin_image.resize((nw, nh), Image.LANCZOS)
        pet.paste(frame, ((box_w - nw) // 2, (pet_h - nh) // 2), frame)
    big.paste(pet, (0, band_px), pet)

    img = big.resize((width, height), Image.LANCZOS)

    # 防烧屏 —— 放在缩到屏尺寸之后，位移量就是屏幕上的实际像素。
    # 整幅一起移：文字带、宠物、背景都在里面，每一个像素都被轮到。
    # 文字也移 —— 文字带占 31% 屏面、还带最亮的像素，静止一整夜
    # 正是最该打散的地方。1 像素 / 30 秒看不出来。
    if anti_burn:
        dx, dy, level = anti_burn
        if dx or dy:
            # 环绕位移 —— 边缘卷回来的那一两像素来自另一侧，看不出来。
            img = ImageChops.offset(img, int(dx), int(dy))
        if level:
            img = img.point(_level_lut(int(level)))

    if overlay is not None:
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, subsampling=subsampling)
    return buf.getvalue()

# ---------- 骰子与飘字（一次性覆盖层） ----------

# 配色沿用宠物皮肤那三色：主橙 / 浅肤 / 灰。
# 不新增色 —— 屏上所有颜色应该看起来像同一个世界。
DICE_FILL = (245, 86, 47)
DICE_FACE = (251, 156, 108)
DICE_EDGE = (172, 172, 174)
DICE_DOT = (26, 20, 26)

# 每个点数对应圆点在骰子面上的相对位置（0..1）
DICE_DOTS = {
    1: ((0.5, 0.5),),
    2: ((0.26, 0.26), (0.74, 0.74)),
    3: ((0.24, 0.24), (0.5, 0.5), (0.76, 0.76)),
    4: ((0.27, 0.27), (0.73, 0.27), (0.27, 0.73), (0.73, 0.73)),
    5: ((0.26, 0.26), (0.74, 0.26), (0.5, 0.5), (0.26, 0.74), (0.74, 0.74)),
    6: ((0.26, 0.22), (0.74, 0.22), (0.26, 0.5),
        (0.74, 0.5), (0.26, 0.78), (0.74, 0.78)),
}


def render_dice(cfg, value=1, rolling=False, title="赛博骰子", anti_burn=None):
    """整屏骰子。宠物脸不画 —— 骰子占屏时没有脸。

    value 在 1..6；rolling 时画面上的点数每帧都在换，出结果后定住。
    """
    width = int(cfg.get("render", {}).get("width", 240))
    height = int(cfg.get("render", {}).get("height", 320))
    quality = int(cfg.get("render", {}).get("quality", 85))
    subsampling = int(cfg.get("render", {}).get("subsampling", 2))

    scale = 2
    big = Image.new("RGB", (width * scale, height * scale), (20, 22, 32))
    _gradient(big, (30, 24, 34), (14, 14, 22))
    d = ImageDraw.Draw(big)

    _center(d, width * scale // 2, int(16 * scale), title,
            int(15 * scale), (196, 200, 214))

    # 骰子本体 —— 正方形，居中
    side = int(min(width, height) * 0.52) * scale
    x0 = (width * scale - side) // 2
    y0 = (height * scale - side) // 2 + int(8 * scale)
    x1, y1 = x0 + side, y0 + side
    radius = int(side * 0.18)
    d.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=DICE_FILL,
                        outline=DICE_EDGE, width=max(2, int(2 * scale)))

    # 圆点 —— 像素风：画成方块，不画成圆
    dot = max(3, int(side * 0.075))
    for fx, fy in DICE_DOTS.get(int(value), DICE_DOTS[1]):
        cx = x0 + int(fx * side)
        cy = y0 + int(fy * side)
        d.rectangle([cx - dot // 2, cy - dot // 2, cx + dot // 2, cy + dot // 2],
                    fill=DICE_DOT)

    # 状态字 —— 滚的时候说在滚，停了就报点数
    label = "..." if rolling else str(int(value))
    _center(d, width * scale // 2, y1 + int(14 * scale), label,
            int(16 * scale), DICE_FACE)

    img = big.resize((width, height), Image.LANCZOS)
    if anti_burn:
        dx, dy, level = anti_burn
        if dx or dy:
            img = ImageChops.offset(img, int(dx), int(dy))
        if level:
            img = img.point(_level_lut(int(level)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, subsampling=subsampling)
    return buf.getvalue()


def bubble_overlay(cfg, text, phrase="", alpha=1.0):
    """飘字层 —— 功德 +1 之类，盖在宠物脸上飘过去。

    这层不改变宠物在干什么 —— 它只是飘过去一行字。
    返回 RGBA 图，由调用方贴到整帧上（自己编码 JPEG 会掉一次画质）。
    """
    width = int(cfg.get("render", {}).get("width", 240))
    height = int(cfg.get("render", {}).get("height", 320))

    scale = 2
    big = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)

    a = max(0.0, min(1.0, float(alpha)))
    main = tuple(int(c * a + 255 * (1 - a)) for c in (245, 86, 47))
    sub = tuple(int(c * a + 255 * (1 - a)) for c in (220, 226, 240))

    # 飘字压在宠物脸上 —— 不垫底色的话，橙色字叠在橙色宠物身上看不清。
    # 垫一条半透明深色带，字才读得出来。
    y = int(height * scale * 0.07)
    band_h = int(46 * scale) if phrase else int(34 * scale)
    band = Image.new("RGBA", (width * scale, band_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    bd.rectangle([0, 0, width * scale, band_h],
                 fill=(12, 12, 20, int(185 * max(a, 0.25))))
    big.paste(band, (0, y - int(4 * scale)), band)

    _center(d, width * scale // 2, y, text, int(22 * scale), main)
    if phrase:
        _center(d, width * scale // 2, y + int(28 * scale), phrase,
                int(13 * scale), sub)
    return big.resize((width, height), Image.LANCZOS)


# ---------- 照片（整屏一张图） ----------

# 照片缓存 —— 同一张照片在屏上待 8 秒，按 1fps 算就是解码 8 次。
# 存的是缩好的图，key 是 (路径, 修改时间) —— 改了文件自动失效。
_PHOTO_CACHE = {}
_PHOTO_CACHE_MAX = 4


def _photo_scaled(path, tw, th):
    """读照片、缩到屏尺寸。命中缓存就直接给。"""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = (str(path), mtime, tw, th)
    hit = _PHOTO_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        src = Image.open(path)
        src.load()
    except Exception:
        return None
    if src.mode != "RGB":
        src = src.convert("RGB")
    fw, fh = src.size
    if fw < 1 or fh < 1:
        return None
    # cover —— 铺满，宁可裁边
    factor = max(tw / float(fw), th / float(fh))
    nw, nh = max(1, int(fw * factor)), max(1, int(fh * factor))
    big = src.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    big = big.crop((left, top, left + tw, top + th))
    if len(_PHOTO_CACHE) >= _PHOTO_CACHE_MAX:
        _PHOTO_CACHE.clear()
    _PHOTO_CACHE[key] = big
    return big


def render_photo_card(cfg, path, counter=""):

    """整屏照片。没有宠物脸 —— 照片就是屏上全部的东西。

    等比裁切铺满（cover）：宁可裁掉边，也不留黑边、也不压扁。
    照片读不出来就返回 None —— 让调用方退回普通卡片，别让屏上开天窗。
    """
    width = int(cfg.get("render", {}).get("width", 240))
    height = int(cfg.get("render", {}).get("height", 320))
    quality = int(cfg.get("render", {}).get("quality", 85))
    subsampling = int(cfg.get("render", {}).get("subsampling", 2))

    scale = 2
    tw, th = width * scale, height * scale
    big = _photo_scaled(path, tw, th)
    if big is None:
        return None
    # 缓存里那张不能改 —— 角标是叠上去的
    big = big.copy()

    # 角标 —— 右下角「第几张 / 共几张」
    if counter:
        ov = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        f, _ = _font(int(11 * scale))
        box = od.textbbox((0, 0), counter, font=f)
        pad = int(6 * scale)
        x1 = tw - int(8 * scale)
        y1 = th - int(8 * scale)
        x0 = x1 - (box[2] - box[0]) - pad * 2
        y0 = y1 - (box[3] - box[1]) - pad * 2
        od.rounded_rectangle([x0, y0, x1, y1], radius=int(4 * scale),
                             fill=(12, 12, 20, 160))
        od.text((x0 + pad - box[0], y0 + pad - box[1]), counter, font=f,
                fill=(214, 220, 234, 255))
        big = Image.alpha_composite(big.convert("RGBA"), ov).convert("RGB")

    img = big.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, subsampling=subsampling)
    return buf.getvalue()
