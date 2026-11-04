"""功能清单 —— 用户能挑的东西。

这一份列的每一项都对应 petd 里一个**真的能改**的运行时状态：空闲时屏上
放什么、每张卡住多久、工作结束后留多久、睡觉时段、信息密度、宠物形象、
关注的会话。改完立刻生效，也写进配置（重启还在）。

以前这里放过一份 capabilities.json —— 列的是旋钮动作 id，而那个 enabled
字段全仓没有任何地方读它，勾掉了什么也不会发生。那种清单是骗人的，不如没有。
"""

from . import features as feature_mod
from . import skins as skins_mod

DENSITY_LABELS = {0: "简洁", 1: "标准", 2: "详细"}

DENSITY_DESCS = {
    0: "只有宠物脸",
    1: "加一行状态说明",
    2: "再加会话名",
}

# 每张卡住多久（秒）
DWELL_CHOICES = (5, 8, 12, 20, 30)

# 工作结束后宠物脸留多久（秒）
HOLD_CHOICES = (0, 3, 5, 10)

# 睡觉时段 —— 整点就够，分钟级精度没有意义
HOUR_CHOICES = tuple(range(24))

# 睡觉时段是**一项**，不是一个值 —— 起止两个钟点在一张卡里选。
# value 是一个组合串："22:00-07:00"，或 "off"（不睡）。
SLEEP_OFF = "off"


def _item(fid, name, desc, value, options, multi=False):
    out = {"id": fid, "name": name, "desc": desc,
           "value": value, "options": options}
    if multi:
        out["multi"] = True
    return out


def _hour_options(current):
    opts = []
    for h in HOUR_CHOICES:
        label = "%02d:00" % h
        opts.append({"value": label, "label": label, "desc": ""})
    if current and current not in [o["value"] for o in opts]:
        opts.append({"value": current, "label": current, "desc": ""})
    return opts


def _sleep_item(pet):
    """睡觉时段 —— 起止两个钟点在一张卡里选。

    这一项的值是组合串（"22:00-07:00"），不是单值 —— 页面上给两个
    时间选择器，别拆成两张卡。
    """
    start = pet.sleep_start
    end = pet.sleep_end
    enabled = bool(pet.sleep_enabled)
    combined = ("%s-%s" % (start, end)) if enabled else SLEEP_OFF
    return {
        "id": "sleep",
        "name": "睡觉时段",
        "desc": "这个时段显示睡脸（可跨午夜）。夜里 OpenClaw 干活，宠物会醒着干",
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
    """给后台页的功能清单。

    每项长这样：
      id       标识（提交时用）
      name     中文名
      desc     一句话说明
      value    当前值
      options  可选值 [{value, label, desc}]
      multi    可选 —— True 表示这一项可以多选（value 是数组）
    """
    root = pet.cfg.get("_repo_root", ".")
    items = []

    # 空闲时屏上放什么 —— 选项就是全部 feature，加一个自动多一项
    cat = feature_mod.catalog()
    items.append(_item(
        "features", "空闲时显示什么",
        "宠物没事干的时候，屏上轮播这些内容",
        sorted(pet.features_enabled),
        [{"value": c["name"], "label": c["title"], "desc": c["tip"]}
         for c in cat],
        multi=True))

    dwell = int(pet.card_dwell_sec)
    dwell_opts = [{"value": s, "label": "%d 秒" % s, "desc": ""}
                  for s in DWELL_CHOICES]
    if dwell not in DWELL_CHOICES:
        dwell_opts.append({"value": dwell, "label": "%d 秒" % dwell, "desc": ""})
    items.append(_item(
        "dwell", "每张卡停留", "一张内容卡在屏上待多久", dwell, dwell_opts))

    hold = int(pet.message_hold_sec)
    hold_opts = [{"value": s, "label": "%d 秒" % s, "desc": ""}
                 for s in HOLD_CHOICES]
    if hold not in HOLD_CHOICES:
        hold_opts.append({"value": hold, "label": "%d 秒" % hold, "desc": ""})
    items.append(_item(
        "hold", "工作结束后保留", "活干完，宠物脸在屏上多留多久", hold, hold_opts))

    items.append(_sleep_item(pet))

    items.append(_item(
        "density", "信息密度", "屏幕上放多少东西", pet.density,
        [{"value": d, "label": DENSITY_LABELS.get(d, str(d)),
          "desc": DENSITY_DESCS.get(d, "")} for d in (0, 1, 2)]))

    # default 永远在列表里 —— 它是程序画的那张脸（skins/ 是空的时候就是它），
    # 不在磁盘上，但确实是个能选的值。
    skins = skins_mod.list_skins(root)
    skin_opts = [{"value": "default", "label": "默认", "desc": "程序画的那张脸"}]
    for s in skins:
        skin_opts.append({
            "value": s, "label": s,
            "desc": "你自己建的" if skins_mod.skin_source(root, s) == "user"
                    else "仓库自带",
        })
    items.append(_item(
        "skin", "宠物形象", "屏上那只长什么样", pet.skin, skin_opts))

    opts = [{"value": "", "label": "自动（跟着最活跃的会话）", "desc": ""}]
    for s in pet.public_sessions():
        opts.append({"value": s.get("key") or "",
                     "label": s.get("name") or s.get("key") or "",
                     "desc": s.get("state") or ""})
    items.append(_item(
        "session", "关注的会话", "宠物优先显示哪个会话（不影响状态判断）",
        pet.engine.selected_key or "", opts))

    return items
