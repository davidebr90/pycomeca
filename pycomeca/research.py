"""Offline capture inspection and scoped, read-only UDP discovery."""

from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
import struct

from .protocol import FrameDecoder, ProtocolError, decode_ctpp, decode_json, decode_rtp


def discover(host: str, timeout: float = 3) -> dict:
    """Unicast INFO to the configured device only; no subnet scan."""
    addr = ipaddress.ip_address(host)
    family = socket.AF_INET6 if addr.version == 6 else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.connect((host, 24199))
        sock.send(b"INFO")
        try:
            data = sock.recv(4096)
        except socket.timeout:
            return {"host": host, "port": 24199, "status": "no_response", "reachable": "unknown"}
    return {"host": host, "port": 24199, "status": "response_received", "bytes": len(data),
            "hex": data.hex(), "ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in data)}


def inspect_wire(data: bytes) -> list[dict]:
    decoder = FrameDecoder()
    result = []
    for pos in range(0, len(data), 4096):
        decoder.feed(data[pos:pos + 4096])
        while (frame := decoder.pop()) is not None:
            record = {"channel": frame.channel_id, "bytes": len(frame.body)}
            if frame.body.startswith(b"{"):
                value = decode_json(frame.body)
                # Whitelist diagnostics; do not output access/config payloads.
                record["json"] = {k: value[k] for k in ("message", "message-id", "message-type", "response-code") if k in value}
            elif (event := decode_ctpp(frame.body)) is not None:
                record["ctpp"] = event
            elif len(frame.body) >= 12 and frame.body[0] >> 6 == 2:
                record["rtp"] = decode_rtp(frame.body)
            else:
                record["kind"] = "unclassified_binary"
            result.append(record)
    decoder.finish()
    return result


def _tnet(data: bytes, offset: int = 0, depth: int = 0):
    """Bounded tnetstring parser for mitmproxy saved flows (no pickle/eval)."""
    if depth > 50:
        raise ValueError("Capture tnetstring troppo annidata")
    colon = data.find(b":", offset, offset + 12)
    if colon < 0 or not data[offset:colon].isdigit():
        raise ValueError("Lunghezza tnetstring non valida")
    length = int(data[offset:colon])
    end = colon + 1 + length
    if length > 16 * 1024 * 1024 or end >= len(data):
        raise ValueError("Capture tnetstring troncata o eccessiva")
    raw, kind = data[colon + 1:end], data[end:end + 1]
    if kind == b",":
        value = raw
    elif kind == b";":
        value = raw.decode("utf-8")
    elif kind == b"#":
        value = int(raw)
    elif kind == b"^":
        value = float(raw)
    elif kind == b"~" and not raw:
        value = None
    elif kind == b"!" and raw in (b"true", b"false"):
        value = raw == b"true"
    elif kind in (b"]", b"}"):
        values, cursor = [], 0
        while cursor < len(raw):
            item, cursor = _tnet(raw, cursor, depth + 1)
            values.append(item)
        if kind == b"}" and len(values) % 2:
            raise ValueError("Dizionario tnetstring incompleto")
        value = dict(zip(values[::2], values[1::2])) if kind == b"}" else values
    else:
        raise ValueError("Tipo tnetstring sconosciuto")
    return value, end + 1


def _get(mapping, key, default=None):
    if not isinstance(mapping, dict):
        return default
    return mapping.get(key, mapping.get(key.encode(), default))


def _text(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def iter_flows(path: Path):
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Capture MITM troppo grande per il lettore offline")
    data, offset = path.read_bytes(), 0
    while offset < len(data):
        flow, offset = _tnet(data, offset)
        if not isinstance(flow, dict):
            raise ValueError("Flow MITM non valido")
        yield flow


def _embedded_configs(value, depth=0):
    if depth > 12:
        return
    if isinstance(value, dict):
        if isinstance(value.get("vip"), dict) and "apt-address" in value["vip"]:
            yield value
        for item in value.values():
            yield from _embedded_configs(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _embedded_configs(item, depth + 1)
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except ValueError:
            return
        yield from _embedded_configs(parsed, depth + 1)


def inspect_mitm(path: Path) -> tuple[dict, list[dict]]:
    endpoints, configs, auth_shapes = Counter(), [], []
    count = 0
    for flow in iter_flows(path):
        request, response = _get(flow, "request", {}), _get(flow, "response", {})
        if not request:
            continue
        count += 1
        route = _text(_get(request, "path", "")).split("?", 1)[0]
        method = _text(_get(request, "method", ""))
        endpoints[(method, route, _get(response, "status_code", 0))] += 1
        if route.endswith("/o-auth-2/auth"):
            try:
                body = json.loads(_get(request, "content", b"{}"))
                auth_shapes.append({"fields": sorted(body), "scope": body.get("scope"),
                                    "challenge_padding": str(body.get("codeChallenge", "")).endswith("="),
                                    "has_state": bool(body.get("state"))})
            except (ValueError, TypeError):
                pass
        content = _get(response, "content")
        if not isinstance(content, bytes) or not content:
            continue
        try:
            if content.startswith(b"\x1f\x8b"):
                # Stream a bounded amount; compressed capture input is not trusted.
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(content)) as gz:
                    content = gz.read(4 * 1024 * 1024 + 1)
                if len(content) > 4 * 1024 * 1024:
                    raise ValueError("Risposta compressa eccessiva")
            parsed = json.loads(content)
            configs.extend(_embedded_configs(parsed))
        except (ValueError, UnicodeError, OSError, RecursionError):
            continue
    return {"file": path.name, "flows": count,
            "endpoints": [{"method": k[0], "path": k[1], "status": k[2], "count": n}
                          for k, n in endpoints.items()],
            "auth_shapes": auth_shapes, "configuration_candidates": len(configs)}, configs


def inspect_pcap(path: Path) -> dict:
    """PCAP IPv4 endpoint census, deliberately not a TCP reassembler.

    Counts local-port traffic accurately without pretending encrypted P2P is
    plaintext ICONA. Unsupported link layers and fragments are counted.
    """
    counts, links, ports, local_payloads = Counter(), Counter(), Counter(), Counter()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        header = stream.read(24)
        if len(header) != 24:
            raise ValueError("PCAP header troncato")
        orders = {b"\xd4\xc3\xb2\xa1": "<", b"\xa1\xb2\xc3\xd4": ">",
                  b"\x4d\x3c\xb2\xa1": "<", b"\xa1\xb2\x3c\x4d": ">"}
        order = orders.get(header[:4])
        if order is None:
            raise ValueError("Formato non PCAP classico (PCAPNG non supportato)")
        link = struct.unpack_from(order + "I", header, 20)[0]
        digest.update(header)
        while packet_header := stream.read(16):
            if len(packet_header) != 16:
                raise ValueError("PCAP record troncato")
            length = struct.unpack_from(order + "I", packet_header, 8)[0]
            if length > 4 * 1024 * 1024:
                raise ValueError("PCAP packet eccessivo")
            data = stream.read(length)
            if len(data) != length:
                raise ValueError("PCAP packet troncato")
            digest.update(packet_header + data)
            counts["packets"] += 1
            if link == 1 and len(data) >= 14:  # Ethernet, optional VLAN
                ether_type, offset = struct.unpack_from(">H", data, 12)[0], 14
                while ether_type in (0x8100, 0x88A8) and len(data) >= offset + 4:
                    ether_type, offset = struct.unpack_from(">H", data, offset + 2)[0], offset + 4
                if ether_type != 0x0800:
                    counts["non_ipv4"] += 1
                    continue
                data = data[offset:]
            elif link == 113 and len(data) >= 16 and data[14:16] == b"\x08\x00":
                data = data[16:]
            elif link not in (101, 228):
                counts["unsupported_link_or_network"] += 1
                continue
            if len(data) < 20 or data[0] >> 4 != 4:
                counts["non_ipv4_or_short"] += 1
                continue
            ihl = (data[0] & 15) * 4
            total = struct.unpack_from(">H", data, 2)[0]
            if ihl < 20 or total < ihl or len(data) < total:
                counts["truncated_ipv4"] += 1
                continue
            if struct.unpack_from(">H", data, 6)[0] & 0x3FFF:
                counts["fragmented_ipv4"] += 1
                continue
            proto, payload = data[9], data[ihl:total]
            if proto not in (6, 17) or len(payload) < (20 if proto == 6 else 8):
                continue
            sport, dport = struct.unpack_from(">HH", payload)
            src, dst = socket.inet_ntoa(data[12:16]), socket.inet_ntoa(data[16:20])
            transport = "TCP" if proto == 6 else "UDP"
            offset = (payload[12] >> 4) * 4 if proto == 6 else 8
            if offset < (20 if proto == 6 else 8) or offset > len(payload):
                counts["malformed_transport"] += 1
                continue
            ports[(transport, dport)] += 1
            if 64100 in (sport, dport) or 24199 in (sport, dport):
                key = (transport, src, sport, dst, dport)
                links[key] += 1
                local_payloads[key] += len(payload) - offset
    return {"file": path.name, "sha256": digest.hexdigest(), "link_type": link,
            "counts": dict(counts),
            "local_protocol_flows": [{"transport": k[0], "source": f"{k[1]}:{k[2]}",
                                       "destination": f"{k[3]}:{k[4]}", "packets": n,
                                       "payload_bytes": local_payloads[k]} for k, n in links.items()],
            "top_destination_ports": [{"transport": p[0], "port": p[1], "packets": n}
                                      for p, n in ports.most_common(12)]}
