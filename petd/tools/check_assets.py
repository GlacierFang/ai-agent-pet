#!/usr/bin/env python3
"""check_assets.py —— 校验皮肤素材是否符合 docs/美术规范.md。

目录约定：
    skins/<skin>/<state>.png

检查项：
    - 六个状态各一张 PNG（idle/working/waiting/done/error/sleeping）
    - 文件名就是状态名 + .png
    - 图片能打开，有 alpha 通道
    - 没有多出来的文件（旧的 frames/ 结构会被点名）

退出码 0 = 通过；非 0 = 有错。
"""
import argparse
import os
import sys

try:
    from PIL import Image
except Exception:
    Image = None

STATES = ("idle", "working", "waiting", "done", "error", "sleeping")

# 允许存在的附属文件 —— 只有出处信息，不参与渲染
ALLOWED_EXTRA = ("meta.json",)

NAME_RE = __import__("re").compile(r"^([a-z]+)\.png$")


def repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


def find_skins(root):
    base = os.path.join(root, "skins")
    if not os.path.isdir(base):
        return []
    return sorted(
        os.path.join(base, name)
        for name in os.listdir(base)
        if os.path.isdir(os.path.join(base, name))
    )


def check_image(path):
    """返回 (ok, 说明)。"""
    if Image is None:
        return True, "跳过（未安装 Pillow）"
    try:
        with Image.open(path) as im:
            im.load()
            w, h = im.size
            if w <= 0 or h <= 0:
                return False, "尺寸非法 %dx%d" % (w, h)
            mode = im.mode
            has_alpha = mode in ("RGBA", "LA", "PA") or "transparency" in im.info
            if not has_alpha:
                return False, "没有 alpha 通道（mode=%s）—— 宠物要叠在背景上" % mode
            return True, "%dx%d mode=%s ✓" % (w, h, mode)
    except Exception as exc:
        return False, "打不开: %s" % exc


def check_skin(skin_dir):
    """检查一个皮肤目录，返回 (errors, notes)。"""
    errors = []
    notes = []
    name = os.path.basename(skin_dir)

    old = os.path.join(skin_dir, "frames")
    if os.path.isdir(old):
        errors.append("%s: 还有旧的 frames/ 目录 —— 新结构是直接放六张 <状态>.png" % name)

    present = []
    for state in STATES:
        fname = "%s.png" % state
        path = os.path.join(skin_dir, fname)
        if not os.path.isfile(path):
            errors.append("%s: 缺 %s" % (name, fname))
            continue
        ok, why = check_image(path)
        if not ok:
            errors.append("%s/%s: %s" % (name, fname, why))
            continue
        present.append(state)

    # 不该有的文件 —— 一态只有一张，多出来说明还留着旧的多帧素材
    for f in sorted(os.listdir(skin_dir)):
        p = os.path.join(skin_dir, f)
        if os.path.isdir(p):
            continue
        if f in ALLOWED_EXTRA:
            continue
        if not NAME_RE.match(f):
            errors.append("%s: 多出来的文件 %s（只允许六张 <状态>.png）" % (name, f))

    if len(present) == len(STATES):
        notes.append("%s: 六态齐 ✓" % name)
    else:
        notes.append("%s: 有 %d/6 态" % (name, len(present)))
    return errors, notes


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check_assets", description="校验皮肤素材")
    ap.add_argument("--root", default=None, help="仓库根目录（默认自动推断）")
    ap.add_argument("--skin", default=None, help="只检查指定皮肤目录名")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root) if args.root else repo_root()
    skins = find_skins(root)
    if args.skin:
        skins = [s for s in skins if os.path.basename(s) == args.skin]

    if not skins:
        print("没有找到皮肤：%s/skins 下没有任何皮肤目录" % root)
        return 2

    all_errors = []
    all_notes = []
    for skin_dir in skins:
        errors, notes = check_skin(skin_dir)
        all_errors.extend(errors)
        all_notes.extend(notes)

    for n in all_notes:
        print("  " + n)
    if all_errors:
        print("")
        print("发现 %d 个问题：" % len(all_errors))
        for e in all_errors:
            print("  [错误] " + e)
        return 1
    print("")
    print("皮肤素材校验通过（%d 个皮肤）" % len(skins))
    return 0


if __name__ == "__main__":
    sys.exit(main())
