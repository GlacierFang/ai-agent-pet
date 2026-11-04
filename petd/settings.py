"""功能清单 —— 用户能挑的东西。

这一份列的每一项都对应 petd 里一个**真的能改**的运行时状态：屏幕页面、
信息密度、宠物形象、关注的会话、睡眠阈值。改完立刻生效，也写进配置
（重启还在）。

和 docs/feature开发.md 里那套 feature 插件不是一回事：那一套是屏上
「内容层」的来源（petd/features/），这一份是列出 petd 现有的、能改的设置。

以前这里放过一份 capabilities.json —— 列的是旋钮动作 id，而那个 enabled
字段全仓没有任何地方读它，勾掉了什么也不会发生。那种清单是骗人的，不如没有。
"""

from . import skins as skins_mod

# 屏幕上的三块页面。app.py 也用这份列表 —— 单一来源，别各写一份。
PAGES = ("face", "session", "notify")

PAGE_LABELS = {
    "face": "表情页",
    "session": "会话页",
    "notify": "通知页",
}

PAGE_DESCS = {
    "face": "宠物脸 + 状态 + 一句话",
    "session": "正在跑的会话",
    "notify": "等你处理的提醒",
}

DENSITY_LABELS = {0: "简洁", 1: "标准", 2: "详细"}

DENSITY_DESCS = {
    0: "只有宠物脸",
    1: "加一行状态说明",
    2: "再加会话名",
}

# 睡眠阈值给几个常用的 —— 让用户选秒数没意义。
SLEEP_CHOICES = (0, 5, 10, 30, 60)


def _item(fid, name, desc, value, options):
    return {"id": fid, "name": name, "desc": desc,
            "value": value, "options": options}


def build(pet):
    """给后台页的功能清单。

    每项长这样：
      id       标识（提交时用）
      name     中文名
      desc     一句话说明
      value    当前值
      options  可选值 [{value, label, desc}]
    """
    root = pet.cfg.get("_repo_root", ".")
    items = []

    items.append(_item(
        "page", "屏幕页面", "设备屏幕现在显示哪一块", pet.page,
        [{"value": p, "label": PAGE_LABELS.get(p, p),
          "desc": PAGE_DESCS.get(p, "")} for p in PAGES]))

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

    mins = int(pet.engine.sleep_after_min)
    sleep_opts = [{"value": m, "label": ("不睡" if m == 0 else "%d 分钟" % m), "desc": ""}
                  for m in SLEEP_CHOICES]
    # 用户在配置文件里写了个不在常用值里的数 —— 也得能选回去
    if mins not in SLEEP_CHOICES:
        sleep_opts.append({"value": mins, "label": "%d 分钟" % mins, "desc": ""})
    items.append(_item(
        "sleep", "多久算睡着", "长时间没动静就睡觉（0 = 不睡）", mins, sleep_opts))

    return items
