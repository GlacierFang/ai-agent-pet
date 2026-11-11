#!/usr/bin/env python3
"""check_docs.py —— 查文档里那些会骗到人的过期说法。

仓库里最坑的一类 bug 不是代码写错，是文档写着「不做 OTA」而代码早就支持 OTA ——
读文档的人按旧事实做决定，比没有文档更糟。

所以这里钉住几条**已经确认过期**的说法。宁可少查，不可误报：
只查写死的句子，不查关键词（文档里提到这些词讨论历史是合理的）。

用法：
    python tools/check_docs.py        # 有过期说法就返回 1
    python tools/check_docs.py --quiet # 只在出错时说话
"""
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 已经确认过期的说法 —— 代码早改了，文档没跟上。
# 每条给出正确说法，方便直接改。
STALE = [
    ("不做 OTA",
     "OTA 已经支持（0.5.4 起）：升级只由人点，ota_0 / ota_1 分区，写坏不覆盖当前固件，bootloader 自动回滚"),
    ("不支持 OTA",
     "OTA 已经支持（0.5.4 起）：升级只由人点，ota_0 / ota_1 分区，写坏不覆盖当前固件，bootloader 自动回滚"),
    ("不能 OTA",
     "OTA 已经支持（0.5.4 起）：升级只由人点，ota_0 / ota_1 分区，写坏不覆盖当前固件，bootloader 自动回滚"),
    ("只能 USB 烧录",
     "首次要 USB 整片刷，之后可以纯 OTA"),
    # 0.5.4 到 0.5.6 的 hello 握手有缺陷，连不上就收不到 OTA 推送。
    # 文档说「≥ 0.5.4 就能 OTA」会把人引到那三版上。
    ("≥ 0.5.4",
     "能走 OTA 的固件是 ≥ 0.5.7 —— 0.5.4 到 0.5.6 握手有缺陷，连不上就收不到推送"),
]

# 这一行确实要提这句（讲历史、列对比）时，写上这个标记就跳过。
ALLOW = "check-docs: allow"


def scan(path):
    """返回这个文件里的过期说法：[(行号, 命中短语, 正确说法, 原句)]。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    problems = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if ALLOW in line:
            continue
        for phrase, right in STALE:
            if phrase in line:
                problems.append((lineno, phrase, right, line.strip()))
    return problems


def targets(root=None):
    """要扫的文件：docs/ 下所有 md + README.md。"""
    root = root or ROOT
    out = []
    docs = root / "docs"
    if docs.is_dir():
        out += sorted(docs.rglob("*.md"))
    readme = root / "README.md"
    if readme.exists():
        out.append(readme)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check_docs")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    files = targets()
    problems = []
    for path in files:
        for lineno, phrase, right, line in scan(path):
            try:
                rel = path.relative_to(ROOT)
            except ValueError:
                rel = path
            problems.append((rel, lineno, phrase, right, line))

    if problems:
        print("文档里有已经过期的说法：")
        for rel, lineno, phrase, right, line in problems:
            print("  %s:%d  命中「%s」" % (rel, lineno, phrase))
            print("      现在是：%s" % right)
            print("      原句：%s" % line[:100])
            print("")
        print("改完再跑。确实要提原文的那行，加个 %s 标记就跳过。" % ALLOW)
        return 1

    if not args.quiet:
        print("文档一致性检查通过（扫了 %d 个文件）。" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
