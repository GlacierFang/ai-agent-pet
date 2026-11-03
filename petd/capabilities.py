"""能力清单。

清单是数据，不是代码 —— 随仓库发布，用户可以在自己的 petd/data/ 里加条目。
固件不感知具体能力：服务端把能力渲染成画面，设备只负责显示 + 上报旋钮。

两个来源：
  仓库自带  petd/data/capabilities.json       跟着版本走
  用户自建  petd/data/capabilities.local.json  gitignore，不进仓库

合并规则：同 id 用户覆盖仓库；enabled=false 表示停用。
"""

import json
import pathlib

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"

BUILTIN_FILE = "capabilities.json"
USER_FILE = "capabilities.local.json"

# 只允许声明式能力：触发后调用服务端已有的操作。
# 不开放任意命令执行 —— 开源项目让用户填任意 shell 到自己设备上是安全雷区。
ALLOWED_ACTIONS = (
    "state.refresh",
    "page.next",
    "page.prev",
    "density.cycle",
    "session.next",
    "skin.next",
)


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _norm(item, source):
    """把一条能力补齐成完整结构。非法条目返回 None。"""
    if not isinstance(item, dict):
        return None
    cid = str(item.get("id") or "").strip()
    if not cid:
        return None
    action = str(item.get("action") or "").strip()
    if action and action not in ALLOWED_ACTIONS:
        # 不认识的动作直接丢掉 —— 不静默接受，等着炸
        action = ""
    return {
        "id": cid,
        "name": str(item.get("name") or cid),
        "desc": str(item.get("desc") or ""),
        "action": action,
        "scope": "device" if item.get("scope") == "device" else "server",
        "screen": bool(item.get("screen", True)),
        "enabled": item.get("enabled", True) is not False,
        "source": source,
    }


def _builtin(data_dir):
    blob = _read(data_dir / BUILTIN_FILE) or {}
    out = []
    for item in blob.get("capabilities") or []:
        norm = _norm(item, "builtin")
        if norm:
            out.append(norm)
    return out, blob.get("version", 1)


def _user(data_dir):
    blob = _read(data_dir / USER_FILE) or {}
    out = []
    for item in blob.get("capabilities") or []:
        norm = _norm(item, "user")
        if norm:
            out.append(norm)
    return out


def load(data_dir=None):
    """返回 {"version", "items", "userItems"}。

    items 是合并后的完整清单；userItems 是用户自己那部分（后台编辑的就是它）。
    """
    data_dir = pathlib.Path(data_dir) if data_dir else DATA_DIR
    builtin, version = _builtin(data_dir)
    user = _user(data_dir)

    merged = {c["id"]: c for c in builtin}
    for c in user:
        merged[c["id"]] = c

    # 保持仓库顺序，用户新增的排在后面
    ordered = []
    seen = set()
    for c in builtin:
        if c["id"] in merged and c["id"] not in seen:
            ordered.append(merged[c["id"]])
            seen.add(c["id"])
    for c in user:
        if c["id"] not in seen:
            ordered.append(c)
            seen.add(c["id"])

    return {"version": version, "items": ordered, "userItems": user}


def save_user(items, data_dir=None):
    """写用户条目。只保存用户那份，不动仓库自带的。"""
    data_dir = pathlib.Path(data_dir) if data_dir else DATA_DIR
    clean = []
    for item in items or []:
        norm = _norm(item, "user")
        if norm:
            clean.append(norm)
    payload = {"version": 1, "capabilities": clean}
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / USER_FILE).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return clean
