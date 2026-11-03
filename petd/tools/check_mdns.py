#!/usr/bin/env python3
"""check_mdns.py —— 自测 mDNS 广播器。

没有硬件也能验：起一个广播器，用标准库 socket 手工拼一条 DNS A 查询
发给它，断言应答里有 petd.local 的 A 记录，且值是本机真实 IPv4。

检查项：
    1. A 查询 petd.local  →  应答含 A 记录，值 = 本机某个 IPv4
    2. 应答报文结构合法（带 question 段、QR 位置 1、class 正好是 IN）
    3. PTR 查询 _petd._tcp.local → 应答含 PTR + SRV（端口对）+ TXT + A
    4. 真发一个 UDP 包出去，收回来（loopback，不依赖组播）

退出码 0 = 通过；非 0 = 有问题。
"""
import argparse
import os
import socket
import struct
import sys
import time

# 仓库根在 petd/tools/ 上两级 —— 不依赖 PYTHONPATH 也能直接跑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from petd import mdns  # noqa: E402


def build_query(name, qtype, txid):
    body = mdns.encode_name(name) + struct.pack("!HH", qtype, 1)
    return struct.pack("!HHHHHH", txid, 0x0000, 1, 0, 0, 0) + body


def parse_answers(packet):
    """拆应答，返回 (问题段, [记录...])。"""
    txid, flags, qdcount, ancount = struct.unpack("!HHHH", packet[:8])
    offset = 12
    questions = []
    for _ in range(qdcount):
        name, offset = mdns.decode_name(packet, offset)
        qtype, qclass = struct.unpack("!HH", packet[offset:offset + 4])
        offset += 4
        questions.append((name, qtype, qclass))
    records = []
    for _ in range(ancount):
        name, offset = mdns.decode_name(packet, offset)
        rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", packet[offset:offset + 10])
        offset += 10
        rdata = packet[offset:offset + rdlen]
        offset += rdlen
        records.append({"name": name, "type": rtype, "class": rclass,
                        "ttl": ttl, "rdata": rdata})
    return txid, flags, questions, records


def check_a_record(addresses):
    """A 查询：应答里的 IP 必须是本机真实的 IPv4。"""
    errors = []
    responder = mdns.MdnsResponder(port=18860, addresses=addresses)
    out = responder.answers_for(build_query("petd.local", mdns.TYPE_A, 0x1111))
    if not out:
        return ["A 查询没有应答"], []
    txid, flags, questions, records = parse_answers(out[0])
    if txid != 0x1111:
        errors.append("txid 不对：期望 0x1111，实际 0x%04x" % txid)
    if not flags & 0x8000:
        errors.append("QR 位置 0 —— 这不是应答")
    if not questions or questions[0][0] != "petd.local":
        errors.append("question 段没有原样带回 petd.local：%r" % (questions,))
    a_records = [r for r in records if r["type"] == mdns.TYPE_A]
    if not a_records:
        errors.append("应答里没有 A 记录")
    for r in records:
        if r["class"] != 1:
            errors.append("class 必须是 1(IN)，实际 %d" % r["class"])
        if r["ttl"] != 120:
            errors.append("TTL 应该是 120，实际 %d" % r["ttl"])
    ips = [socket.inet_ntoa(r["rdata"]) for r in a_records]
    for ip in ips:
        if ip not in addresses:
            errors.append("A 记录的值 %s 不在本机地址列表里" % ip)
    if ips and addresses and not set(ips) & set(addresses):
        errors.append("应答的 IP %r 和本机地址 %r 没有交集" % (ips, addresses))
    notes = ["A 记录: %s" % ", ".join(ips)]
    return errors, notes


def check_service_records():
    """PTR 查询：PTR + SRV（端口要对）+ TXT + A。"""
    errors = []
    notes = []
    responder = mdns.MdnsResponder(port=18860, addresses=["127.0.0.1"])
    out = responder.answers_for(build_query("_petd._tcp.local", mdns.TYPE_PTR, 0x2222))
    if not out:
        return ["PTR 查询没有应答"], notes
    _txid, _flags, _questions, records = parse_answers(out[0])
    types = set(r["type"] for r in records)
    for want, label in ((mdns.TYPE_PTR, "PTR"), (mdns.TYPE_SRV, "SRV"),
                        (mdns.TYPE_TXT, "TXT"), (mdns.TYPE_A, "A")):
        if want not in types:
            errors.append("PTR 应答缺 %s 记录" % label)
    srv = [r for r in records if r["type"] == mdns.TYPE_SRV]
    if srv:
        _pri, _wgt, port = struct.unpack("!HHH", srv[0]["rdata"][:6])
        if port != 18860:
            errors.append("SRV 端口应该是 18860，实际 %d" % port)
        else:
            notes.append("SRV 端口: %d" % port)
    ptr = [r for r in records if r["type"] == mdns.TYPE_PTR]
    if ptr:
        target, _end = mdns.decode_name(ptr[0]["rdata"])
        if target != "petd._petd._tcp.local":
            errors.append("PTR 目标不对：%s" % target)
        else:
            notes.append("PTR 目标: %s" % target)
    return errors, notes


def check_udp_roundtrip(port):
    """真发一个 UDP 包出去再收回来 —— loopback，不依赖组播。"""
    errors = []
    notes = []
    adv = mdns.MdnsAdvertiser(port=18860, addresses=mdns.local_ipv4_addresses(),
                             mdns_port=port, multicast=False)
    if not adv.start():
        return ["广播器起不来（端口 %d 被占？）" % port], notes
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(3.0)
        client.sendto(build_query("petd.local", mdns.TYPE_A, 0x3333),
                      ("127.0.0.1", port))
        try:
            data, src = client.recvfrom(4096)
        except socket.timeout:
            return ["等不到应答（UDP 收包超时）"], notes
        finally:
            client.close()
        _txid, _flags, _questions, records = parse_answers(data)
        ips = [socket.inet_ntoa(r["rdata"]) for r in records if r["type"] == mdns.TYPE_A]
        if not ips:
            errors.append("UDP 收到的应答里没有 A 记录")
        else:
            notes.append("UDP 收到应答，来自 %s，地址 %s" % (src[0], ", ".join(ips)))
    finally:
        adv.stop()
    return errors, notes


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check_mdns",
                                 description="自测 petd 的 mDNS 广播器")
    ap.add_argument("--port", type=int, default=15353,
                    help="回环自测用的 UDP 端口（不是 5353，避免和 avahi 撞）")
    args = ap.parse_args(argv)

    addresses = mdns.local_ipv4_addresses()
    print("本机 IPv4: %s" % (", ".join(addresses) or "（没有）"))
    if not addresses:
        print("查不到本机 IPv4 地址 —— mDNS 没有可广播的地址")
        return 2

    all_errors = []
    for label, errors, notes in (
            ("A 查询", ) + tuple(check_a_record(addresses)),
            ("PTR/SRV", ) + tuple(check_service_records()),
            ("UDP 收发", ) + tuple(check_udp_roundtrip(args.port))):
        print("")
        print("[%s]" % label)
        for note in notes:
            print("  " + note)
        for err in errors:
            print("  [错误] " + err)
        all_errors.extend(errors)

    print("")
    if all_errors:
        print("发现 %d 个问题：" % len(all_errors))
        for err in all_errors:
            print("  [错误] " + err)
        return 1
    print("mDNS 自测通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
