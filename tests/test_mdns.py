"""mDNS 广播器的单测。

不碰组播端口 —— 5353 上可能已经有 avahi，CI 也不一定有组播权限。
报文编码是纯函数，网络收发只在 loopback 上走一次普通 UDP。
"""
import pathlib
import socket
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import mdns  # noqa: E402


IP1 = "192.168.31.193"
IP2 = "192.168.28.194"


def make_query(name, qtype=mdns.TYPE_A, txid=0x1234, qclass=1):
    """手工拼一条 DNS 查询 —— 就是 lwIP 发出来的那种。"""
    body = mdns.encode_name(name) + struct.pack("!HH", qtype, qclass)
    return struct.pack("!HHHHHH", txid, 0x0000, 1, 0, 0, 0) + body


def parse_response(packet):
    """把应答报文拆开，返回 (txid, flags, questions, records)。"""
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


@pytest.fixture
def responder():
    return mdns.MdnsResponder(hostname="petd.local", service="_petd._tcp.local",
                              instance="petd", port=18860, addresses=[IP1, IP2])


# ---------- 名编码 ----------
def test_encode_name_roundtrip(responder):
    raw = mdns.encode_name("petd.local")
    assert raw == b"\x04petd\x05local\x00"
    assert mdns.decode_name(raw) == ("petd.local", len(raw))


def test_encode_name_rejects_empty_label():
    with pytest.raises(ValueError):
        mdns.encode_name("petd..local")


def test_encode_name_rejects_too_long_label():
    with pytest.raises(ValueError):
        mdns.encode_name("a" * 64 + ".local")


# ---------- A 查询 ----------
def test_a_query_answers_with_local_ip(responder):
    """固件问 petd.local，要能答出本机 IP。"""
    out = responder.answers_for(make_query("petd.local", mdns.TYPE_A))
    assert len(out) == 1
    txid, flags, questions, records = parse_response(out[0])
    assert txid == 0x1234
    assert flags & 0x8000  # QR 位：这是应答
    assert questions == [("petd.local", mdns.TYPE_A, 1)]
    ips = [socket.inet_ntoa(r["rdata"]) for r in records if r["type"] == mdns.TYPE_A]
    assert IP1 in ips and IP2 in ips
    assert all(r["ttl"] == 120 for r in records)


def test_a_record_class_is_exactly_in(responder):
    """lwIP 做的是相等判断，多带 cache-flush 位它就不认。"""
    out = responder.answers_for(make_query("petd.local", mdns.TYPE_A))
    _txid, _flags, _q, records = parse_response(out[0])
    assert all(r["class"] == 1 for r in records)


def test_question_section_is_echoed_without_compression(responder):
    """lwIP 逐字比对问名，question 里出现压缩指针会被整包丢弃。"""
    packet = responder.answers_for(make_query("petd.local", mdns.TYPE_A))[0]
    name_len = len(mdns.encode_name("petd.local"))
    for byte in packet[12:12 + name_len]:
        assert not (byte & 0xC0 == 0xC0)


def test_txid_is_echoed(responder):
    out = responder.answers_for(make_query("petd.local", mdns.TYPE_A, txid=0xBEEF))
    assert parse_response(out[0])[0] == 0xBEEF


def test_unrelated_name_is_ignored(responder):
    assert responder.answers_for(make_query("other.local", mdns.TYPE_A)) == []


def test_response_to_a_response_is_ignored(responder):
    """别人发来的应答不是查询，不能再答一遍。"""
    out = responder.answers_for(make_query("petd.local", mdns.TYPE_A))
    assert responder.answers_for(out[0]) == []


def test_garbage_packet_is_ignored(responder):
    assert responder.answers_for(b"\x00\x01") == []
    assert responder.answers_for(b"") == []


def test_aaaa_query_gets_empty_answer(responder):
    """没 IPv6 就回空应答，别让客户端干等到超时。"""
    out = responder.answers_for(make_query("petd.local", mdns.TYPE_AAAA))
    assert len(out) == 1
    _txid, _flags, _q, records = parse_response(out[0])
    assert records == []


# ---------- PTR / SRV / TXT ----------
def test_ptr_query_answers_full_service_set(responder):
    """PTR 查询要回 PTR + SRV + TXT + A。"""
    out = responder.answers_for(make_query("_petd._tcp.local", mdns.TYPE_PTR))
    assert len(out) == 1
    _txid, _flags, questions, records = parse_response(out[0])
    assert questions == [("_petd._tcp.local", mdns.TYPE_PTR, 1)]
    types = set(r["type"] for r in records)
    assert types == set([mdns.TYPE_PTR, mdns.TYPE_SRV, mdns.TYPE_TXT, mdns.TYPE_A])
    # 每个本机地址一条 A 记录
    a_records = [r for r in records if r["type"] == mdns.TYPE_A]
    assert len(a_records) == 2


def test_ptr_target_points_at_instance(responder):
    out = responder.answers_for(make_query("_petd._tcp.local", mdns.TYPE_PTR))
    _txid, _flags, _q, records = parse_response(out[0])
    ptr = [r for r in records if r["type"] == mdns.TYPE_PTR][0]
    target, _end = mdns.decode_name(ptr["rdata"])
    assert target == "petd._petd._tcp.local"


def test_srv_record_carries_port_and_target(responder):
    out = responder.answers_for(make_query("_petd._tcp.local", mdns.TYPE_PTR))
    _txid, _flags, _q, records = parse_response(out[0])
    srv = [r for r in records if r["type"] == mdns.TYPE_SRV][0]
    priority, weight, port = struct.unpack("!HHH", srv["rdata"][:6])
    assert (priority, weight) == (0, 0)
    assert port == 18860
    target, _end = mdns.decode_name(srv["rdata"], 6)
    assert target == "petd.local"


def test_txt_record_has_version(responder):
    out = responder.answers_for(make_query("_petd._tcp.local", mdns.TYPE_PTR))
    _txid, _flags, _q, records = parse_response(out[0])
    txt = [r for r in records if r["type"] == mdns.TYPE_TXT][0]
    items = []
    offset = 0
    while offset < len(txt["rdata"]):
        length = txt["rdata"][offset]
        items.append(txt["rdata"][offset + 1:offset + 1 + length].decode())
        offset += 1 + length
    assert "v=1" in items


def test_srv_query_directly(responder):
    out = responder.answers_for(make_query("petd._petd._tcp.local", mdns.TYPE_SRV))
    assert len(out) == 1
    _txid, _flags, _q, records = parse_response(out[0])
    assert any(r["type"] == mdns.TYPE_SRV for r in records)


# ---------- 地址枚举 ----------
def test_local_ipv4_addresses_excludes_loopback():
    addrs = mdns.local_ipv4_addresses()
    assert "127.0.0.1" not in addrs
    assert all(not a.startswith("127.") for a in addrs)


def test_local_ipv4_addresses_are_valid():
    import ipaddress
    for addr in mdns.local_ipv4_addresses():
        ipaddress.IPv4Address(addr)


# ---------- 网络收发（loopback，不碰组播） ----------
def test_loopback_roundtrip():
    """起一个应答器，用普通 UDP 在 loopback 上问一问。

    用的是普通端口而不是 5353 —— CI 里 5353 可能被 avahi 占着，
    而且组播在 CI 上不一定能加。
    """
    port = 15353
    adv = mdns.MdnsAdvertiser(port=18860, addresses=[IP1], mdns_port=port,
                             multicast=False)
    assert adv.start() is True
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(3.0)
        client.sendto(make_query("petd.local", mdns.TYPE_A), ("127.0.0.1", port))
        data, _addr = client.recvfrom(4096)
        client.close()
        _txid, _flags, _q, records = parse_response(data)
        ips = [socket.inet_ntoa(r["rdata"]) for r in records if r["type"] == mdns.TYPE_A]
        assert IP1 in ips
    finally:
        adv.stop()


def test_start_is_idempotent_and_stop_is_safe():
    adv = mdns.MdnsAdvertiser(port=18860, addresses=[IP1], mdns_port=15354,
                             multicast=False)
    assert adv.start() is True
    assert adv.start() is True   # 再来一次不报错
    assert adv.running is True
    adv.stop()
    adv.stop()                    # 停两遍也不报错
    assert adv.running is False


def test_start_failure_does_not_raise():
    """端口被占也要活着返回 False —— mDNS 是增强功能，不能把 petd 带崩。"""
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", 15355))
    adv = mdns.MdnsAdvertiser(port=18860, addresses=[IP1], mdns_port=15355,
                             multicast=False)
    try:
        assert adv.start() is False
    finally:
        adv.stop()
        blocker.close()


def test_advertiser_addresses_falls_back_to_local():
    adv = mdns.MdnsAdvertiser(port=18860, multicast=False)
    assert isinstance(adv.addresses(), list)
