"""游戏包（pack）—— 设备端小游戏的定义文件。

一个 pack = 一个 JSON 文件 = 一个游戏。固件内置引擎，pack 只是数据 ——
加游戏不用刷固件，petd 把 pack 推给设备，设备写进 SPIFFS。

两套目录（跟 skins 一样的模式）：
  内置：petd/packs/          —— 仓库自带
  用户：petd/data/packs/     —— 用户自己放的，同名盖掉内置的

**不做上传界面** —— 用户把 JSON 放进目录就行。我们不做平台。
"""
import json
import pathlib


def builtin_root():
    return pathlib.Path(__file__).resolve().parent / "packs"


def user_root():
    return pathlib.Path(__file__).resolve().parent / "data" / "packs"


def _roots():
    """用户目录优先，内置目录兜底。跟 petd/skins.py 的 _roots 一个套路。"""
    return [user_root(), builtin_root()]


def pack_path(pack_id):
    """按 id 找 pack 文件路径。找不到返回 None。"""
    for root in _roots():
        p = root / ("%s.json" % pack_id)
        if p.is_file():
            return p
    return None


def list_packs():
    """所有可用 pack。返回 [{id, title, hint, order, path}]，按 order 排。"""
    seen = {}
    for root in _roots():
        if not root.is_dir():
            continue
        for f in sorted(root.glob("*.json")):
            try:
                blob = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(blob, dict):
                continue
            pid = str(blob.get("id") or f.stem)
            if pid in seen:
                continue        # 用户目录先扫到的已经在了
            seen[pid] = {
                "id": pid,
                "title": str(blob.get("title") or pid),
                "hint": str(blob.get("hint") or ""),
                "order": int(blob.get("order") or 100),
                "path": str(f),
            }
    return sorted(seen.values(), key=lambda d: (d["order"], d["id"]))


def read_pack(pack_id):
    """读一个 pack 的原始 JSON 文本。给设备下发的就是这份原文。"""
    p = pack_path(pack_id)
    if p is None:
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def pack_data(pack_id):
    """读一个 pack 解析成 dict。"""
    p = pack_path(pack_id)
    if p is None:
        return None
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return blob if isinstance(blob, dict) else None


def known_ids():
    """所有可用 pack 的 id。"""
    return [d["id"] for d in list_packs()]


def normalize(ids):
    """把启用的 id 列表收拾干净：去重、只留真有的。"""
    known = set(known_ids())
    out = []
    for i in ids or []:
        i = str(i).strip()
        if i and i in known and i not in out:
            out.append(i)
    return out
