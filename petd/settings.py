"""宠物设定 —— 用户能挑的东西。

这页分两段：
  功能  屏上会显示哪些内容（会话、通知、最近完成、时间、设备、天气）
  设置  做事的节奏（每张卡停多久、干完留多久、信息密度、睡觉时段）

每一项都对应 petd 里一个**真的能改**的运行时状态 —— 改完立刻生效，
也写进配置（重启还在）。

以前这里放过一份 capabilities.json —— 列的是旋钮动作 id，而那个 enabled
字段全仓没有任何地方读它，勾掉了什么也不会发生。那种清单是骗人的，不如没有。
"""

from . import album as album_mod
from . import config as config_mod
from . import features as feature_mod

DENSITY_LABELS = {0: "简洁", 1: "标准", 2: "详细"}

DENSITY_DESCS = {
    0: "只有宠物形象",
    1: "加一行状态说明",
    2: "再加会话名",
}

# 睡觉时段是**一项**，不是一个值 —— 起止两个钟点在一张卡里选。
# value 是一个组合串："22:00-07:00"，或 "off"（不睡）。
SLEEP_OFF = "off"

# 哪些功能自带一个设定项。功能勾上了才上屏，它的设定也跟着生效。
FEATURE_OPTIONS = {
    "sessions": "session",
    "weather": "weatherCity",
    "dice": "diceButton",
    "album": "albumPanel",
}


def _session_option(pet):
    """优先显示哪个会话 —— 它跟着会话功能走，不是独立一项。"""
    opts = [{"value": "", "label": "自动（跟着最活跃的会话）", "desc": ""}]
    for s in pet.public_sessions():
        opts.append({"value": s.get("key") or "",
                     "label": s.get("name") or s.get("key") or "",
                     "desc": s.get("state") or ""})
    return {"id": "session", "name": "优先显示",
            "desc": "宠物优先显示哪个会话（不影响状态判断）",
            "value": pet.engine.selected_key or "",
            "type": "select", "options": opts}


def _city_option(pet):
    return {"id": "weatherCity", "name": "城市",
            "desc": "填城市名，比如「杭州」。留空就用默认城市",
            "value": str(pet.cfg.get("ui", {}).get("weatherCity") or ""),
            "type": "text"}


def _dice_button_option():
    """「模拟短按旋钮」按钮 —— 不改任何配置，只是按一下。

    它走的是真手势表：改了 petd/data/gestures.json，这个按钮跟着变。
    """
    return {"id": "diceButton", "name": "模拟短按旋钮",
            "label": "模拟短按旋钮",
            "desc": "在浏览器里模拟一次短按旋钮 —— 没有板子也能看效果",
            "type": "button", "gesture": "press_short"}


def _album_option(pet):
    """相册面板 —— 缩略图网格 + 上传按钮。

    照片在服务端存，这里只给清单和元数据。
    """
    items = album_mod.list_items()
    return {
        "id": "albumPanel",
        "name": "照片",
        "desc": "最多 %d 张，轮播到就换一张" % album_mod.MAX_PHOTOS,
        "type": "album",
        "max": album_mod.MAX_PHOTOS,
        "count": len(items),
        "photos": [{"file": it["file"], "name": it["name"]} for it in items],
    }


def _feature(pet, entry, selected):
    """一个功能 = 勾选框 + 说明 + 它自己的设定项。"""
    name = entry["name"]
    item = {"name": name, "title": entry["title"], "tip": entry["tip"],
            "enabled": name in selected, "options": []}
    extra = FEATURE_OPTIONS.get(name)
    if extra == "session":
        item["options"].append(_session_option(pet))
    elif extra == "weatherCity":
        item["options"].append(_city_option(pet))
    elif extra == "diceButton":
        item["options"].append(_dice_button_option())
    elif extra == "albumPanel":
        item["options"].append(_album_option(pet))
    # live —— 这张卡上会显示的实时数字。前端按 id 填，不猜。
    if name == "merit":
        item["live"] = [{"id": "feat-live-merit", "kind": "merit",
                         "text": "功德 %d" % int(pet.merit.value)}]
    elif name == "album":
        n = album_mod.count()
        item["live"] = [{"id": "feat-live-album", "kind": "album",
                         "text": ("%d / %d 张照片" % (n, album_mod.MAX_PHOTOS))
                                 if n else "还没有照片"}]
    elif name == "dice":
        item["live"] = [
            {"id": "feat-live-dice", "kind": "dice",
             "text": ("上次摇出 %d" % int(pet.dice.value)) if pet.dice.rolled
                     else "还没摇过"},
            {"id": "feat-live-press", "kind": "press", "text": ""},
            {"id": "feat-live-roll", "kind": "roll", "text": ""},
        ]
    return item


def _dwell_item(pet):
    return {"id": "dwell", "name": "每张卡停留",
            "desc": "一张内容卡在屏上待多久",
            "value": int(pet.card_dwell_sec),
            "type": "number", "unit": "秒", "min": 1}


def _hold_item(pet):
    return {"id": "hold", "name": "干完留多久",
            "desc": "活干完，宠物形象在屏上多留多久",
            "value": int(pet.message_hold_sec),
            "type": "number", "unit": "秒", "min": 0}


def _density_item(pet):
    return {"id": "density", "name": "信息密度",
            "desc": "屏幕上放多少东西",
            "value": pet.density, "type": "radio",
            "options": [{"value": d, "label": DENSITY_LABELS.get(d, str(d)),
                         "desc": DENSITY_DESCS.get(d, "")} for d in (0, 1, 2)]}


def _sleep_item(pet):
    """睡觉时段 —— 起止两个钟点在一张卡里选。

    这一项的值是组合串（"22:00-07:00"），不是单值 —— 页面上给一条
    24 小时轴，在轴上划一段，别拆成两张卡。
    """
    start = pet.sleep_start
    end = pet.sleep_end
    enabled = bool(pet.sleep_enabled)
    combined = ("%s-%s" % (start, end)) if enabled else SLEEP_OFF
    return {
        "id": "sleep",
        "name": "睡觉时段",
        "desc": "这段时间宠物睡觉，不显示内容。但 OpenClaw 接到活，它会立刻醒来。",
        "value": combined,
        # 通用契约要求「当前值在可选项里」—— 放当前值进去。
        # 这一项真正的界面是 type=timerange，options 不参与渲染。
        "options": [{"value": combined, "label": combined, "desc": ""}],
        "type": "timerange",
        "from": start,
        "to": end,
        "enabled": enabled,
    }


def build(pet):
    """给后台页的宠物设定。

    返回两个部分：
      features  屏上会显示哪些内容（每项一个勾选框，可能再带自己的设定）
      settings  做事的节奏（时长、密度、睡觉时段）
    """
    selected = set(pet.features_enabled)
    features = [_feature(pet, c, selected) for c in feature_mod.catalog()]
    settings = [_dwell_item(pet), _hold_item(pet),
                _density_item(pet), _sleep_item(pet)]
    return {"features": features, "settings": settings}
