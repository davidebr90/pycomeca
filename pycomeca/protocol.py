"""Strict ICONA framing and independently implemented wire primitives.

Protocol references and unresolved firmware differences: docs/PROTOCOL.md.
Binary door layouts are experimental community-derived interoperability data.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import struct


class ProtocolError(Exception):
    """Malformed or unsupported protocol input; do not guess on the wire."""


MAGIC = b"\x00\x06"
MAX_BODY = 65535
COMMAND, END = 0xABCD, 0x01EF
COMMUNITY_FIELDS = {"UAUT": 7, "UCFG": 2, "INFO": 20, "CTPP": 16, "CSPB": 17}


@dataclass(frozen=True)
class Frame:
    channel_id: int
    body: bytes

    def encode(self) -> bytes:
        if not 0 <= self.channel_id <= 65535 or len(self.body) > MAX_BODY:
            raise ProtocolError("Frame ICONA fuori dai limiti uint16")
        return MAGIC + struct.pack("<HHH", len(self.body), self.channel_id, 0) + self.body


class FrameDecoder:
    """Incremental TCP decoder. Retains partial frames across read timeouts."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes) -> None:
        if len(self.buffer) + len(data) > 2 * (MAX_BODY + 8):
            raise ProtocolError("Buffer ICONA eccessivo")
        self.buffer.extend(data)

    def pop(self) -> Frame | None:
        if len(self.buffer) < 8:
            return None
        if self.buffer[:2] != MAGIC or self.buffer[6:8] != b"\x00\x00":
            raise ProtocolError("Header ICONA non valido")
        length, channel = struct.unpack_from("<HH", self.buffer, 2)
        if len(self.buffer) < 8 + length:
            return None
        body = bytes(self.buffer[8:8 + length])
        del self.buffer[:8 + length]
        return Frame(channel, body)

    def finish(self) -> None:
        if self.buffer:
            raise ProtocolError("Stream ICONA troncato")


def ascii_address(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9]{6,16}", value):
        raise ProtocolError("Indirizzo VIP non valido")
    return value.encode("ascii") + b"\x00"


def open_channel(name: str, local_id: int, extra: str | None = None,
                 profile: str = "classic") -> Frame:
    if name not in COMMUNITY_FIELDS or not 1 <= local_id <= 65535:
        raise ProtocolError("Canale o identificatore non supportato")
    if profile not in ("classic", "community"):
        raise ProtocolError("Profilo wire sconosciuto")
    wire_field = len(name) + 3 if profile == "classic" else COMMUNITY_FIELDS[name]
    body = struct.pack("<HHI", COMMAND, 1, wire_field)
    body += name.encode("ascii") + struct.pack("<HB", local_id, 0)
    if extra is not None:
        value = ascii_address(extra)
        body += b"\x00" + struct.pack("<I", len(value)) + value
    return Frame(0, body)


def json_frame(channel_id: int, value: dict) -> Frame:
    return Frame(channel_id, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def decode_json(body: bytes) -> dict:
    try:
        result = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ProtocolError("Risposta JSON non valida") from exc
    if not isinstance(result, dict):
        raise ProtocolError("La risposta JSON deve essere un oggetto")
    return result


def close_channel(channel_id: int) -> Frame:
    return Frame(channel_id, struct.pack("<HH", END, 3))


def ctpp_registration(apt: str, sub: int, profile: str = "classic") -> bytes:
    """Legacy transient registration; not a persistent event subscription."""
    if type(sub) is not int or not 0 <= sub <= 255:
        raise ProtocolError("Subaddress fuori intervallo")
    if profile not in ("classic", "community"):
        raise ProtocolError("Profilo wire sconosciuto")
    caller = ascii_address(f"{apt}{sub}")
    capability = bytes.fromhex("ac23" if profile == "classic" else "18c2")
    return (bytes.fromhex("c0185c8b2b7300110040") + capability + caller
            + bytes.fromhex("100e00000000ffffffff") + caller + ascii_address(apt) + b"\x00")


def door_sequence(apt: str, target: str, relay: int, kind: str,
                  module: int | None = None) -> list[bytes]:
    """Build community transient door sequence, WITHOUT claiming a physical ACK.

    The legacy caller suffix uses the relay (not the identity subaddress).
    This is preserved explicitly for reproducibility pending local capture.
    Actuator magic encodes module 255 / relay 1: reject other values.
    """
    if type(relay) is not int or not 1 <= relay <= 255:
        raise ProtocolError("Relay fuori intervallo")
    caller, destination = ascii_address(f"{apt}{relay}"), ascii_address(target)
    suffix = b"\xff" * 4 + caller + destination + b"\x00"
    if kind == "actuator":
        if module != 255 or relay != 1:
            raise ProtocolError("Sequenza attuatore verificabile solo per module=255, relay=1")
        init = bytes.fromhex("c01845be8f5c00040020ff01") + suffix
        request = bytes.fromhex("001845be8f5c0004") + suffix
        confirm = bytes.fromhex("201845be8f5c0004") + suffix
        return [init, request, confirm]
    if kind != "door":
        raise ProtocolError("Tipo target sconosciuto")
    # LE16 is intentional: Buffer.from([0x1800]) in an old reference truncates it.
    request = bytes.fromhex("00185c8b2c740000") + suffix
    confirm = bytes.fromhex("20185c8b2c740000") + suffix
    init = (bytes.fromhex("c01870ab299f000d002d") + destination + b"\x00"
            + struct.pack("<I", relay) + suffix)
    return [request, confirm, init, request, confirm]


_VIP_FSM_ACTIONS = {
    0x0000: "idle", 0x0001: "ring_in_alerting", 0x0002: "connected",
    0x0003: "door_opened_event", 0x0004: "out_alerting", 0x0005: "call_closed",
    0x000A: "call_terminated", 0x0010: "registration_renewal",
}


def decode_ctpp(body: bytes) -> dict | None:
    """Structural observations, not verified MSVF semantic/physical states."""
    if len(body) < 8:
        return None
    prefix, counter = struct.unpack_from("<HI", body)
    if prefix not in (0x18C0, 0x1800, 0x1820, 0x1840, 0x1860):
        return None
    action = struct.unpack_from(">H", body, 6)[0]
    result = {"prefix": f"0x{prefix:04x}", "counter": counter,
              "action": f"0x{action:04x}", "bytes": len(body),
              "physical_state": "unknown", "interpretation": "unclassified"}
    # Parse only the explicit address tail, not arbitrary hex runs in payloads.
    marker = body.find(b"\xff" * 4, 8)
    addresses = []
    if marker >= 0:
        for item in body[marker + 4:].split(b"\x00"):
            if re.fullmatch(rb"[A-Za-z0-9]{6,16}", item):
                addresses.append(item.decode("ascii"))
        tag = body[marker - 2:marker]
        if tag in (b"PP", b"FF"):
            result["origin_tag_candidate"] = "entrance" if tag == b"PP" else "floor"
    result["addresses"] = addresses
    # VIP FSM action semantics on 0x1860, cross-checked against the community
    # VIP listener: 0x0003 is the out-of-call door-opened event, 0x0010 the
    # registration renewal, 0x0001 an incoming ring.
    if prefix == 0x1860:
        result["interpretation"] = _VIP_FSM_ACTIONS.get(action, "vip_fsm_event")
    elif prefix == 0x18C0 and action == 0x28:
        result["interpretation"] = "call_init_ring"
    elif prefix in (0x1800, 0x1820):
        result["interpretation"] = "protocol_ack"
    elif prefix == 0x1840:
        result["interpretation"] = "video_call_event"
    return result


def open_confirmations(observations: list[dict], target_address: str) -> list[dict]:
    """Door-opened VIP events (0x1860/0x0003) naming the target address.

    This is the out-of-call 'door opened' FSM event the native app relies on.
    It reports the device's open event; on its own it is not
    proof the physical latch moved (wiring/power), so callers keep any physical
    state separate.
    """
    return [o for o in observations
            if o.get("interpretation") == "door_opened_event"
            and target_address in (o.get("addresses") or [])]


def decode_rtp(data: bytes) -> dict:
    """RFC 3550 header, including CSRC, extension and padding boundaries."""
    if len(data) < 12 or data[0] >> 6 != 2:
        raise ProtocolError("Header RTP non valido")
    offset = 12 + (data[0] & 15) * 4
    if offset > len(data):
        raise ProtocolError("Lista CSRC troncata")
    if data[0] & 0x10:
        if offset + 4 > len(data):
            raise ProtocolError("Estensione RTP troncata")
        words = struct.unpack_from(">H", data, offset + 2)[0]
        offset += 4 + words * 4
        if offset > len(data):
            raise ProtocolError("Dati estensione RTP troncati")
    end = len(data)
    if data[0] & 0x20:
        padding = data[-1]
        if not padding or padding > end - offset:
            raise ProtocolError("Padding RTP non valido")
        end -= padding
    seq, timestamp, ssrc = struct.unpack_from(">HII", data, 2)
    return {"payload_type": data[1] & 127, "marker": bool(data[1] & 128),
            "sequence": seq, "timestamp": timestamp, "ssrc": ssrc,
            "payload_bytes": end - offset, "payload_offset": offset}
