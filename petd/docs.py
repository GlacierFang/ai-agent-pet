"""文档阅读器 —— 后台把仓库里的 docs/*.md 渲染出来。

为什么服务端渲染：
  前端渲染要么引 CDN（破坏「断网内网也能用」这条），要么自己写 markdown
  解析器（文档里有 400 多行表格、50 多个引用块，手写必翻车）。
  markdown-it-py 纯 Python、没有外部资源，装进 requirements 就完事。

分组写死在这里，但**没登记的新文档不会消失** —— 它们落进「其它」组。
省得以后加文档忘了登记，文档就没人看得见了。
"""

import os
import pathlib
import urllib.parse

from markdown_it import MarkdownIt

DOCS_DIRNAME = "docs"

# 仓库地址 —— 文档里指到仓库根的链接（比如 ../SECURITY.md）落到这儿。
REPO_URL = os.environ.get(
    "PETD_REPO_URL", "https://github.com/GlacierFang/ai-agent-pet").rstrip("/")

# 分组 —— 顺序就是显示顺序。
# key 是文件名，value 是给用户看的一句话说明。
GROUPS = (
    ("user", "给你用的", (
        ("部署手册.md", "从零装起来"),
        ("硬件指南.md", "接线与 BOM"),
        ("故障排查.md", "出问题了查这儿"),
    )),
    ("dev", "给开发者看的", (
        ("后台控制台.md", "控制台的接口与页面"),
        ("协议.md", "设备与服务端怎么说话"),
        ("状态语义.md", "六态怎么判"),
        ("旋钮.md", "手势语义表"),
        ("固件构建.md", "固件怎么编"),
        ("美术规范.md", "宠物图怎么画"),
        ("feature开发.md", "加一个新功能"),
        ("项目定位.md", "私有化定位与仓库结构"),
    )),
)


def docs_dir(repo_root):
    return pathlib.Path(repo_root) / DOCS_DIRNAME


def _safe_name(repo_root, name):
    """只认 docs 目录里真实存在的文件。

    名字可能带中文（协议.md），照原样用；挡掉一切路径拼接。
    """
    name = str(name or "").strip()
    if not name or name.startswith("."):
        return None
    if "/" in name or chr(92) in name:
        return None
    d = docs_dir(repo_root)
    p = d / name
    try:
        p.resolve().relative_to(d.resolve())
    except (ValueError, OSError):
        return None
    if not p.is_file():
        return None
    return name


def _title(text, fallback):
    """第一行 # 标题就是显示名。取不到就用文件名。"""
    for line in text.splitlines()[:40]:
        if line.startswith("# "):
            t = line[2:].strip()
            if t:
                return t
    return fallback


def _item(path, desc=""):
    try:
        with path.open("r", encoding="utf-8") as fh:
            head = "".join([next(fh, "") for _ in range(40)])
    except Exception:
        head = ""
    return {
        "name": path.name,
        "title": _title(head, path.stem),
        "desc": desc,
    }


def list_docs(repo_root):
    """列出所有文档，分好组。没登记的落进「其它」。"""
    d = docs_dir(repo_root)
    if not d.is_dir():
        return {
            "ok": True,
            "available": False,
            "groups": [],
            "reason": "这份安装里没有 docs 目录",
            "repoUrl": REPO_URL,
        }
    files = {}
    for p in sorted(d.glob("*.md")):
        files[p.name] = p
    groups = []
    used = set()
    for gid, gtitle, entries in GROUPS:
        items = []
        for fname, desc in entries:
            if fname in files and fname not in used:
                items.append(_item(files[fname], desc))
                used.add(fname)
        if items:
            groups.append({"id": gid, "title": gtitle, "docs": items})
    others = []
    for name, p in files.items():
        if name in used:
            continue
        others.append(_item(p, ""))
    if others:
        groups.append({"id": "other", "title": "其它", "docs": others})
    return {
        "ok": True,
        "available": True,
        "groups": groups,
        "repoUrl": REPO_URL,
    }


def _rewrite_link(href, repo_root):
    """文档里的链接改成阅读器能用的形式。

    指向 docs 里另一篇的 -> doc:文件名（页内跳）
    指向仓库根的（比如 ../SECURITY.md）-> 仓库网页地址
    """
    if not href or href.startswith("#"):
        return href
    if href.startswith(("http://", "https://", "mailto:", "tel:")):
        return href
    if not href.endswith(".md"):
        return href
    # markdown-it 把中文文件名 percent-encoding 了（协议.md -> %E5%8D%8F%E8%AE%AE.md）。
    # 不先解码就找不到文件 —— 中文文档全部变成死链。
    try:
        plain = urllib.parse.unquote(href)
    except Exception:
        plain = href
    base = os.path.basename(plain)
    if _safe_name(repo_root, base):
        return "doc:" + base
    return REPO_URL + "/blob/main/" + plain.lstrip("./")


def _make_md(repo_root):
    """造一个渲染器。原始 HTML 标签是关掉的 —— 文档是仓库内容，
    但渲染器不冒 HTML 注入的风险。
    """
    md = MarkdownIt("default", {"html": False, "typographer": False})
    default_link_open = md.renderer.rules.get("link_open")

    def link_open(tokens, idx, options, env):
        href = tokens[idx].attrGet("href") or ""
        tokens[idx].attrSet("href", _rewrite_link(href, repo_root))
        if default_link_open is not None:
            return default_link_open(tokens, idx, options, env)
        return md.renderer.renderToken(tokens, idx, options, env)

    md.renderer.rules["link_open"] = link_open
    return md


def render_doc(repo_root, name):
    """渲染一篇。返回 None = 没这篇文档。"""
    fname = _safe_name(repo_root, name)
    if not fname:
        return None
    p = docs_dir(repo_root) / fname
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": "读不了：%s" % exc}
    md = _make_md(repo_root)
    try:
        body = md.render(text)
    except Exception as exc:
        return {"ok": False, "error": "渲染失败：%s" % exc}
    return {
        "ok": True,
        "name": fname,
        "title": _title(text, fname),
        "html": body,
    }
