#!/usr/bin/env python3
"""check_assets.py —— 校验皮肤素材是否符合 docs/美术规范.md。

目录约定：
    skins/<skin>/frames/<state>/<state>_NN.png

检查项：
    - 状态目录名合法（idle/working/waiting/done/error/sleeping）
    - 文件名是 <state>_两位序号.png
    - 图片能打开，尺寸大于 0，有 alpha 或 RGB 通道
    - 帧数达到下限（idle 6 / working 4 / waiting 3 / done 4 / error 3 / sleeping 4）

退出码 0 = 通过；非 0 = 有错。仓库里还没有素材时，报「没有找到皮肤」并以非 0 退出。
"""
import argparse
import os
import re
import sys

try:
    from PIL import Image
except Exception:
    Image = None

STATES = ("idle", "working", "waiting", "done", "error", "sleeping")

MIN_FRAMES = {
    "idle": 6,
    "working": 4,
    "waiting": 3,
    "done": 4,
    "error": 3,
    "sleeping": 4,
}

NAME_RE = re.compile(r"^([a-z]+)_(\d{2})\.png$")


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
            has_rgb = mode.startswith("RGB")
            if not (has_alpha or has_rgb):
                return False, "既没有 alpha 也没有 RGB 通道（mode=%s）" % mode
            return True, "%dx%d mode=%s" % (w, h, mode)
    except Exception as exc:
        return False, "打不开: %s" % exc


def check_skin(skin_dir):
    """检查一个皮肤目录，返回 (errors, notes)。"""
    errors = []
    notes = []
    name = os.path.basename(skin_dir)
    frames_root = os.path.join(skin_dir, "frames")
    if not os.path.isdir(frames_root):
        errors.append("%s: 缺少 frames/ 目录" % name)
        return errors, notes

    state_dirs = sorted(
        d for d in os.listdir(frames_root)
        if os.path.isdir(os.path.join(frames_root, d))
    )
    if not state_dirs:
        errors.append("%s: frames/ 下没有任何状态目录" % name)
        return errors, notes

    for state in state_dirs:
        if state not in STATES:
            errors.append("%s: 非法状态目录 %s（只允许 %s）"
                          % (name, state, "/".join(STATES)))
            continue
        sdir = os.path.join(frames_root, state)
        pngs = sorted(f for f in os.listdir(sdir) if f.lower().endswith(".png"))
        if not pngs:
            errors.append("%s/%s: 没有 PNG 帧" % (name, state))
            continue
        for f in pngs:
            m = NAME_RE.match(f)
            if not m or m.group(1) != state:
                errors.append("%s/%s: 文件名不合规 %s（应为 %s_NN.png）"
                              % (name, state, f, state))
                continue
            ok, why = check_image(os.path.join(sdir, f))
            if not ok:
                errors.append("%s/%s/%s: %s" % (name, state, f, why))
        need = MIN_FRAMES[state]
        if len(pngs) < need:
            errors.append("%s/%s: 帧数不足 %d/%d（至少 %d 张）"
                          % (name, state, len(pngs), need, need))
        else:
            notes.append("%s/%s: %d 帧（≥%d）✓" % (name, state, len(pngs), need))

    missing = [s for s in STATES if s not in state_dirs]
    if missing:
        notes.append("%s: 缺状态目录 %s" % (name, ", ".join(missing)))
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
        print("提示：素材尚未产出时这是正常的 —— 提交素材前再跑一次本脚本。")
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
