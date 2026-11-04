"""「主机」—— 运行 petd 的这台机器的状态。

屏摆在客厅，主机塞在机箱里或者另一个房间 —— 用户想知道它还活着吗、
磁盘满了没、CPU 烫不烫。这张卡就是干这个的。

以前这里有个「设备」功能，显示的是那块 ESP32 屏的状态（信号、固件版本、
在线时长）。但屏就在用户面前 —— 它工作不工作抬眼就看见了，做成轮播卡
占的是屏上一格宝贵的位置。那份数据也还在「连接与诊断」页的原始遥测里，
排障的人去那儿看正好。

数据全部从 /proc 读 —— 不引新依赖。
"""
import glob
import logging
import os
import shutil
import socket
import threading
import time

from .base import Feature

log = logging.getLogger("petd.features.host")

# 采样间隔。CPU 占用率要靠两次 /proc/stat 的差值算，间隔太短噪声大。
SAMPLE_INTERVAL_SEC = 5.0

_lock = threading.Lock()
_state = {"data": None, "prev_cpu": None, "prev_at": 0.0}
_thread = None


def _read_cpu_times():
    """CPU 时间片 -> (总时间, 空闲时间)。取不到返回 None。"""
    try:
        with open("/proc/stat", "r") as f:
            for line in f:
                if line.startswith("cpu "):
                    parts = [int(x) for x in line.split()[1:]]
                    if not parts:
                        return None
                    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
                    return sum(parts), idle
    except Exception:
        return None
    return None


def _read_mem():
    """内存 -> {total, used, pct}，单位 kB。"""
    info = {}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0])
    except Exception:
        return None
    total = info.get("MemTotal")
    if not total:
        return None
    avail = info.get("MemAvailable")
    if avail is None:
        avail = info.get("MemFree", 0) + info.get("Cached", 0) + info.get("Buffers", 0)
    used = max(0, total - avail)
    return {"total": total, "used": used, "pct": int(round(100.0 * used / total))}


def _read_disk():
    """根分区 -> {total, free, pct}，单位字节。"""
    try:
        st = shutil.disk_usage("/")
    except Exception:
        return None
    return {"total": st.total, "free": st.free,
            "pct": int(round(100.0 * st.used / st.total)) if st.total else 0}


def _read_uptime():
    """开机时长（秒）。"""
    try:
        with open("/proc/uptime", "r") as f:
            return float(f.read().split()[0])
    except Exception:
        return None


def _zone_temp(path):
    try:
        with open(path, "r") as f:
            val = float(f.read().strip())
    except Exception:
        return None
    # 有些机器报毫度（50000），有些报度（50）
    if val > 1000:
        val = val / 1000.0
    return val


def _read_temp():
    """CPU 温度。树莓派有，别的机器没有 —— 没有就返回 None，整行不显示。"""
    for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        typ = ""
        try:
            with open(os.path.join(zone, "type"), "r") as f:
                typ = f.read().strip().lower()
        except Exception:
            continue
        if "cpu" not in typ and "soc" not in typ:
            continue
        val = _zone_temp(os.path.join(zone, "temp"))
        if val is not None:
            return val
    return None


def _hostname():
    try:
        name = socket.gethostname().strip()
    except Exception:
        name = ""
    return name[:16]


def _fmt_dur(seconds):
    """开机时长 —— 短一点，卡上放得下。"""
    s = int(max(0, seconds))
    if s >= 86400:
        d, h = s // 86400, (s % 86400) // 3600
        return ("%d 天 %d 小时" % (d, h)) if h else ("%d 天" % d)
    if s >= 3600:
        h, m = s // 3600, (s % 3600) // 60
        return ("%d 小时 %d 分" % (h, m)) if m else ("%d 小时" % h)
    return "%d 分钟" % max(1, s // 60)


def _fmt_size(n):
    """可用空间 —— 整数 GiB / MiB。"""
    gib = n / (1024.0 ** 3)
    if gib >= 1:
        return "%dG" % int(round(gib))
    return "%dM" % int(round(n / (1024.0 ** 2)))


def _sample():
    """采一次。CPU 占用率靠跟上次采样比。"""
    cpu_now = _read_cpu_times()
    now = time.time()
    with _lock:
        prev = _state["prev_cpu"]
        prev_at = _state["prev_at"]
        _state["prev_cpu"] = cpu_now
        _state["prev_at"] = now
    pct = None
    if cpu_now and prev:
        d_total = cpu_now[0] - prev[0]
        d_idle = cpu_now[1] - prev[1]
        if d_total > 0 and now > prev_at:
            pct = int(round(100.0 * (d_total - d_idle) / d_total))
    data = {
        "cpu": pct,
        "mem": _read_mem(),
        "disk": _read_disk(),
        "uptime": _read_uptime(),
        "temp": _read_temp(),
    }
    with _lock:
        _state["data"] = data
    return data


def _loop():
    while True:
        try:
            _sample()
        except Exception as exc:
            log.warning("主机状态采样失败: %s", exc)
        time.sleep(SAMPLE_INTERVAL_SEC)


def _ensure_sampler():
    """采样线程起一次就够了。"""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        t = threading.Thread(target=_loop, name="petd-host-sampler", daemon=True)
        _thread = t
    t.start()


class HostStatus(Feature):
    name = "host"
    title = "主机"
    tip = "CPU、内存和磁盘"
    priority = 5

    def wants(self, state):
        return True

    def poll(self, ctx=None):
        """后台线程里调 —— 采样线程起来后，这里只是看一眼缓存。"""
        _ensure_sampler()
        with _lock:
            return _state["data"]

    def context(self, ctx):
        with _lock:
            data = _state["data"]
        if not data:
            return None
        rows = []
        mem = data.get("mem")
        if mem:
            rows.append({"left": "内存",
                         "right": "%d%%" % mem["pct"],
                         "accent": "waiting" if mem["pct"] >= 85 else "idle"})
        disk = data.get("disk")
        if disk:
            rows.append({"left": "磁盘",
                         "right": "%s 可用" % _fmt_size(disk["free"]),
                         "accent": "waiting" if disk["pct"] >= 85 else "idle"})
        temp = data.get("temp")
        if temp is not None:
            rows.append({"left": "温度",
                         "right": "%d°C" % int(round(temp)),
                         "accent": "waiting" if temp >= 75 else "idle"})
        up = data.get("uptime")
        if up:
            rows.append({"left": "已运行", "right": _fmt_dur(up), "accent": "idle"})
        if not rows:
            return None
        cpu = data.get("cpu")
        name = _hostname()
        return {
            "title": ("主机 · " + name) if name else "主机",
            "big": ("%d%%" % cpu) if cpu is not None else "",
            "body": ["CPU 使用率"] if cpu is not None else [],
            "rows": rows,
            "state": "idle",
            "source": "主机状态",
        }
