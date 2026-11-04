"""服务端整帧渲染：Pillow → JPEG。

设备端零字体、零业务语义 —— 所有文字在这里烧进 JPEG。
v1 只有三种信息密度，差别是表情区高度，文字区跟着变。
"""
import io
import math
import pathlib

from PIL import Image, ImageDraw, ImageFont

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

DENSITY_FACE_H = [140, 200, 280]

STATE_CN = {
    "idle": "空闲",
    "working": "忙",
    "waiting": "等你确认",
    "done": "完成",
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


def _draw_pet(base, cx, cy, r, state, phase):
    """程序化默认角色 —— 几何形状 + 状态参数，不依赖任何美术素材。"""
    d = ImageDraw.Draw(base, "RGBA")
    pal = PALETTE.get(state, PALETTE["idle"])
    body = pal["body"]
    glow = pal["glow"]

    breathe = 1.0 + 0.04 * math.sin(phase * 2 * math.pi)
    rr = r * breathe

    # 光晕
    for i in range(6, 0, -1):
        alpha = int(10 + i * 3)
        d.ellipse([cx - rr * (1 + i * 0.06), cy - rr * (1 + i * 0.06),
                   cx + rr * (1 + i * 0.06), cy + rr * (1 + i * 0.06)],
                  fill=glow + (alpha,))

    # 耳朵
    ear = rr * 0.34
    d.polygon([(cx - rr * 0.72, cy - rr * 0.55), (cx - rr * 0.30, cy - rr * 1.18),
               (cx - rr * 0.10, cy - rr * 0.62)], fill=body)
    d.polygon([(cx + rr * 0.72, cy - rr * 0.55), (cx + rr * 0.30, cy - rr * 1.18),
               (cx + rr * 0.10, cy - rr * 0.62)], fill=body)

    # 身体
    d.ellipse([cx - rr, cy - rr * 0.95, cx + rr, cy + rr * 1.05], fill=body)

    # 脸
    ex = rr * 0.38
    ey = cy - rr * 0.12
    er = rr * 0.17
    ink = (26, 28, 38)
    blink = state in ("idle", "sleeping") and (phase % 1.0) > 0.92
    if state == "error":
        for sx in (cx - ex, cx + ex):
            d.line([(sx - er, ey - er), (sx + er, ey + er)], fill=ink, width=max(3, int(rr * 0.08)))
            d.line([(sx - er, ey + er), (sx + er, ey - er)], fill=ink, width=max(3, int(rr * 0.08)))
    elif blink:
        for sx in (cx - ex, cx + ex):
            d.line([(sx - er, ey), (sx + er, ey)], fill=ink, width=max(3, int(rr * 0.07)))
    elif state == "working":
        for sx in (cx - ex, cx + ex):
            d.line([(sx - er, ey - er * 0.2), (sx + er, ey - er * 0.2)], fill=ink, width=max(3, int(rr * 0.07)))
    else:
        for sx in (cx - ex, cx + ex):
            d.ellipse([sx - er, ey - er * 1.15, sx + er, ey + er * 1.15], fill=ink)
            if state == "waiting":
                d.ellipse([sx - er * 0.45, ey - er * 0.5, sx + er * 0.45, ey + er * 0.35],
                          fill=(255, 255, 255))

    # 嘴
    my = cy + rr * 0.42
    if state in ("idle", "done", "sleeping"):
        d.arc([cx - rr * 0.28, my - rr * 0.20, cx + rr * 0.28, my + rr * 0.24],
              start=10, end=170, fill=ink, width=max(3, int(rr * 0.07)))
    elif state == "waiting":
        d.ellipse([cx - rr * 0.12, my - rr * 0.12, cx + rr * 0.12, my + rr * 0.16], fill=ink)
    elif state == "working":
        d.line([(cx - rr * 0.22, my + rr * 0.06), (cx + rr * 0.22, my + rr * 0.06)],
               fill=ink, width=max(3, int(rr * 0.07)))
    elif state == "error":
        d.arc([cx - rr * 0.26, my - rr * 0.10, cx + rr * 0.26, my + rr * 0.36],
              start=190, end=350, fill=ink, width=max(3, int(rr * 0.07)))

    # waiting 举牌子
    if state == "waiting":
        bx = cx + rr * 1.05
        by = cy - rr * 1.05
        d.rounded_rectangle([bx - rr * 0.28, by - rr * 0.34, bx + rr * 0.28, by + rr * 0.34],
                            radius=int(rr * 0.08), fill=(255, 226, 120))
        _center(d, bx, by - rr * 0.30, "!", int(rr * 0.42), (40, 34, 20))
    return base


CARD_BG_TOP = (24, 28, 44)
CARD_BG_BOTTOM = (13, 15, 24)


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


def render_card(cfg, card, phase=0.0, skin_frames=None):
    """内容层：一张 feature 整屏卡片。

    内容层和消息层互斥 —— 屏上永远只有一样东西。
    卡里那只宠物就是用户选的那只（宠物本体复用，feature 不带自己的美术）。
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
    body = [str(b) for b in (card.get("body") or [])][:3]
    source = str(card.get("source") or "")
    pet_state = str(card.get("state") or "idle")

    ty = int(16 * scale)
    if title:
        _center(d, width * scale // 2, ty, title, int(19 * scale), (238, 242, 250))
        ty += int(34 * scale)
    for line in body:
        _center(d, width * scale // 2, ty, line, int(13 * scale), (186, 196, 216))
        ty += int(22 * scale)
    if source:
        _center(d, width * scale // 2, ty + int(2 * scale), source,
                int(9 * scale), (118, 126, 146))
        ty += int(20 * scale)

    # 宠物本体 —— 屏上那只就是用户选的那只
    area_top = ty + int(6 * scale)
    area_bottom = height * scale - int(6 * scale)
    area_h = max(int(40 * scale), area_bottom - area_top)
    pet = Image.new("RGBA", (width * scale, area_h), (0, 0, 0, 0))
    if skin_frames:
        frame = skin_frames[int(phase * len(skin_frames)) % len(skin_frames)]
        fw, fh = frame.size
        factor = min((width * scale) / fw, area_h / fh)
        nw, nh = max(1, int(fw * factor)), max(1, int(fh * factor))
        frame = frame.resize((nw, nh), Image.LANCZOS)
        pet.paste(frame, ((width * scale - nw) // 2, (area_h - nh) // 2), frame)
    else:
        radius = int(min(width * scale * 0.30, area_h * 0.34))
        _draw_pet(pet, width * scale // 2, int(area_h * 0.52), radius, pet_state, phase)
    big.paste(pet, (0, area_top), pet)

    img = big.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, subsampling=subsampling)
    return buf.getvalue()


def render_frame(cfg, state, subtitle="", session_name="", density=1, phase=0.0,
                 skin_frames=None):
    width = int(cfg.get("render", {}).get("width", 240))
    height = int(cfg.get("render", {}).get("height", 320))
    quality = int(cfg.get("render", {}).get("quality", 85))
    subsampling = int(cfg.get("render", {}).get("subsampling", 2))

    scale = 2
    big = Image.new("RGB", (width * scale, height * scale), (20, 22, 32))
    pal = PALETTE.get(state, PALETTE["idle"])
    _gradient(big, tuple(min(255, c + 14) for c in pal["bg"]), pal["bg"])

    density = max(0, min(2, int(density)))
    face_h = DENSITY_FACE_H[density]
    face_px = face_h * scale

    # 表情区
    pet = Image.new("RGBA", (width * scale, face_px), (0, 0, 0, 0))
    if skin_frames:
        # 有皮肤素材就贴第一帧，缩放裁切不拉伸
        frame = skin_frames[int(phase * len(skin_frames)) % len(skin_frames)]
        sw, sh = frame.size
        box_h = face_px
        box_w = width * scale
        scale_factor = min(box_w / sw, box_h / sh)
        nw, nh = int(sw * scale_factor), int(sh * scale_factor)
        frame = frame.resize((nw, nh), Image.LANCZOS)
        ox = (box_w - nw) // 2
        oy = (box_h - nh) // 2
        pet.paste(frame, (ox, oy), frame)
    else:
        _draw_pet(pet, width * scale // 2, int(face_px * 0.52),
                  int(min(width * scale * 0.34, face_px * 0.36)), state, phase)
    big.paste(pet, (0, 0), pet)

    d = ImageDraw.Draw(big)
    d.line([(0, face_px), (width * scale, face_px)], fill=pal["glow"] + (70,), width=2)

    # 文字区
    ty = face_px + int(10 * scale)
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

    # 页脚提示
    _center(d, width * scale // 2, height * scale - int(16 * scale),
            "petd", int(9 * scale), (110, 118, 140))

    img = big.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, subsampling=subsampling)
    return buf.getvalue()
