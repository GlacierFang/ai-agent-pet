#!/usr/bin/env python3
"""mock_device.py —— 没有真硬件时模拟一台 ESP32-S3 设备。

用途：验证 petd 全链路（握手 → 推帧 → ack → 旋钮事件 → 状态上报）。

    python3 petd/tools/mock_device.py --host 127.0.0.1 --port 18860

交互式命令台（读 stdin）：
    r = 旋转      {"type":"input","ev":"rot","dir":1,"steps":3}
    p = 短按      {"type":"input","ev":"press","btn":"sw","ms":120}
    l = 长按      {"type":"input","ev":"press","btn":"sw","ms":900}
    h = 按住旋转  {"type":"input","ev":"rot_press","dir":-1,"steps":2}
    q = 退出

设备只报原始值，短按/长按由 petd 侧按 longPressMs(600) 阈值分派。
"""
import argparse
import asyncio
import json
import sys
import threading
import time

import websockets

DEVICE_ID = "esp32s3-mock01"
FW = "0.1.0"

HELLO = {
    "type": "hello",
    "protocol": 1,
    "deviceId": DEVICE_ID,
    "fw": FW,
    "hostname": "mock",
    "capabilities": {
        "display": {"w": 240, "h": 320},
        "decoder": "tjpgdec",
        "colorFormat": "rgb565",
        "rotary": True,
    },
}

COMMANDS = {
    "r": {"type": "input", "ev": "rot", "dir": 1, "steps": 3},
    "p": {"type": "input", "ev": "press", "btn": "sw", "ms": 120},
    "l": {"type": "input", "ev": "press", "btn": "sw", "ms": 900},
    "h": {"type": "input", "ev": "rot_press", "dir": -1, "steps": 2},
}

HELP = "r=旋转 p=短按 l=长按 h=按住旋转 q=退出"


def check_jpeg(blob):
    """校验 JPEG 头 FFD8 与尾 FFD9。返回 (ok, 说明)。"""
    if not blob or len(blob) < 4:
        return False, "空帧"
    if blob[0:2] != b"\xff\xd8":
        return False, "头部不是 FFD8: %s" % blob[0:2].hex()
    if blob[-2:] != b"\xff\xd9":
        return False, "尾部不是 FFD9: %s" % blob[-2:].hex()
    return True, "ok"


class Stats:
    """帧统计：帧数 / 字节数 / 到达间隔 / 解码耗时。"""

    def __init__(self):
        self.frames = 0
        self.bytes_total = 0
        self.intervals = []
        self.errors = 0
        self.last_ts = None
        self.decode_ms_sum = 0.0
        self.last_latency_ms = 0.0
        self.started = time.time()

    def on_frame(self, size, ts):
        self.frames += 1
        self.bytes_total += size
        if self.last_ts is not None:
            self.intervals.append(ts - self.last_ts)
        self.last_ts = ts

    def report(self):
        avg_bytes = self.bytes_total / self.frames if self.frames else 0
        avg_gap = (sum(self.intervals) / len(self.intervals)) if self.intervals else 0
        avg_decode = self.decode_ms_sum / self.frames if self.frames else 0
        elapsed = max(1e-6, time.time() - self.started)
        lines = [
            "---- 统计 ----",
            "收到帧数: %d" % self.frames,
            "平均字节: %.0f B (总 %d B)" % (avg_bytes, self.bytes_total),
            "平均间隔: %.3f s" % avg_gap,
            "平均解码耗时: %.1f ms" % avg_decode,
            "校验失败: %d" % self.errors,
            "平均帧率: %.2f fps" % (self.frames / elapsed),
        ]
        if self.intervals:
            lines.append("最小/最大间隔: %.3f / %.3f s"
                         % (min(self.intervals), max(self.intervals)))
        return "\n".join(lines)


async def send_input(ws, ev):
    """发一条旋钮原始事件。"""
    payload = dict(ev)
    try:
        await ws.send(json.dumps(payload, ensure_ascii=False))
        print("[mock] -> %s" % json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        print("[mock] 发送失败: %s" % exc)
        return False
    return True


async def command_console(ws, stop):
    """交互式命令台：r / p / l / h / q。读 stdin 的线程是 daemon，退出不阻塞。"""
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    def reader():
        try:
            for line in sys.stdin:
                loop.call_soon_threadsafe(queue.put_nowait, line.strip())
        except Exception:
            pass
        loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=reader, daemon=True).start()
    print("[mock] 命令台就绪：%s" % HELP)
    while not stop["stop"]:
        try:
            line = await queue.get()
        except asyncio.CancelledError:
            break
        if line is None:
            break
        key = line.strip().lower()
        if key == "q":
            print("[mock] 收到退出指令")
            stop["stop"] = True
            break
        if key in COMMANDS:
            await send_input(ws, COMMANDS[key])
        elif key == "?":
            print("[mock] %s" % HELP)
        elif key:
            print("[mock] 未知指令: %s（? 看帮助）" % key)


async def status_loop(ws, stats, interval, stop):
    """每 interval 秒发一次 status。"""
    while not stop["stop"]:
        await asyncio.sleep(interval)
        if stop["stop"]:
            break
        msg = {
            "type": "status",
            "ts": int(time.time()),
            "fw": FW,
            "uptime": int(time.time() - stats.started),
            "heapFree": 184320,
            "rssi": -52,
            "fps": round(stats.frames / max(1e-6, time.time() - stats.started), 2),
            "decodeMs": int(stats.decode_ms_sum / stats.frames) if stats.frames else 0,
            "lastFrameMs": int(stats.last_latency_ms),
            "frameErrors": stats.errors,
        }
        try:
            await ws.send(json.dumps(msg, ensure_ascii=False))
        except Exception as exc:
            print("[mock] status 发送失败: %s" % exc)
            break


async def run(args):
    uri = "ws://%s:%d/device" % (args.host, args.port)
    stats = Stats()
    stop = {"stop": False}
    rc = 0

    print("[mock] 连接 %s (subprotocol petd.v1)" % uri)
    try:
        async with websockets.connect(uri, subprotocols=["petd.v1"]) as ws:
            await ws.send(json.dumps(HELLO, ensure_ascii=False))
            print("[mock] -> hello %s" % json.dumps(HELLO, ensure_ascii=False))

            first = await ws.recv()
            if isinstance(first, bytes):
                first = first.decode("utf-8", "replace")
            print("[mock] <- %s" % first)
            try:
                welcome = json.loads(first)
            except Exception:
                welcome = {}
            if welcome.get("type") != "welcome":
                print("[mock] 不是 welcome，退出")
                return 2

            tasks = [asyncio.create_task(status_loop(ws, stats, args.status_interval, stop))]
            if args.stdin:
                tasks.append(asyncio.create_task(command_console(ws, stop)))

            pending_id = None
            pending_at = 0.0

            # --press / --rotate：连上后触发一次交互（--once 时触发完就退）
            if args.press or args.rotate:
                await asyncio.sleep(0.2)
                ev = COMMANDS["p"] if args.press else COMMANDS["r"]
                await send_input(ws, ev)
                if args.once:
                    # 再等一会儿收帧，确认链路真的通了
                    await asyncio.sleep(args.once_wait)
                    stop["stop"] = True

            try:
                while not stop["stop"]:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        break

                    if isinstance(msg, bytes):
                        size = len(msg)
                        ok, why = check_jpeg(msg)
                        ts = time.time()
                        if not ok:
                            stats.errors += 1
                            print("[mock] 帧校验失败: %s" % why)
                            continue
                        stats.on_frame(size, ts)
                        stats.decode_ms_sum += 10 + (size % 16)
                        if pending_id is not None:
                            stats.last_latency_ms = (ts - pending_at) * 1000
                            await ws.send(json.dumps({"type": "frameAck", "id": pending_id}))
                            print("[mock] 帧 id=%s 大小=%dB 延迟=%.0fms"
                                  % (pending_id, size, stats.last_latency_ms))
                            pending_id = None
                    else:
                        try:
                            obj = json.loads(msg)
                        except Exception:
                            print("[mock] <- 非 JSON: %s" % msg[:120])
                            continue
                        t = obj.get("type")
                        if t == "frame":
                            pending_id = obj.get("id")
                            pending_at = time.time()
                        elif t == "state":
                            print("[mock] <- state %s (%s)"
                                  % (obj.get("state"), obj.get("text")))
                        elif t in ("setPage", "setDensity", "refresh"):
                            print("[mock] <- %s %s" % (t, json.dumps(obj, ensure_ascii=False)))
                        elif t == "error":
                            print("[mock] <- error %s" % msg)
                        else:
                            print("[mock] <- %s" % msg[:160])
            except websockets.exceptions.ConnectionClosed as exc:
                print("[mock] 连接关闭: %s" % exc)
                rc = 0
            finally:
                stop["stop"] = True
                for t in tasks:
                    t.cancel()
                for t in tasks:
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass
    except Exception as exc:
        print("[mock] 异常: %s" % exc)
        rc = 1

    print(stats.report())
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mock_device", description="模拟一台 ESP32-S3 设备")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18860)
    ap.add_argument("--status-interval", type=float, default=30.0,
                    help="status 上报周期（秒），默认 30")
    ap.add_argument("--press", action="store_true", help="连上后发一次短按")
    ap.add_argument("--rotate", action="store_true", help="连上后发一次旋转")
    ap.add_argument("--once", action="store_true", help="发完交互就退出（自测用）")
    ap.add_argument("--once-wait", type=float, default=3.0,
                    help="--once 时触发后等待收帧的秒数，默认 3")
    ap.add_argument("--no-stdin", dest="stdin", action="store_false",
                    help="不读 stdin（无人值守）")
    ap.set_defaults(stdin=True)
    args = ap.parse_args(argv)

    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n[mock] 中断")
        return 130
    except Exception as exc:
        print("[mock] 异常: %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
