"""Minimal STUN (RFC 5389) for ICE connectivity checks, short-term credentials.

Only what ICE needs: Binding request/response, USERNAME, MESSAGE-INTEGRITY
(HMAC-SHA1), FINGERPRINT (CRC32), XOR-MAPPED-ADDRESS, PRIORITY,
ICE-CONTROLLED/CONTROLLING and USE-CANDIDATE. Pure standard library.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import ipaddress
import os
import struct
import zlib

MAGIC_COOKIE = 0x2112A442
_COOKIE_BE = struct.pack(">I", MAGIC_COOKIE)

# message classes/methods
BINDING_REQUEST = 0x0001
BINDING_SUCCESS = 0x0101
BINDING_ERROR = 0x0111
BINDING_INDICATION = 0x0011

# attributes
ATTR_MAPPED_ADDRESS = 0x0001
ATTR_USERNAME = 0x0006
ATTR_MESSAGE_INTEGRITY = 0x0008
ATTR_ERROR_CODE = 0x0009
ATTR_XOR_MAPPED_ADDRESS = 0x0020
ATTR_PRIORITY = 0x0024
ATTR_USE_CANDIDATE = 0x0025
ATTR_FINGERPRINT = 0x8028
ATTR_ICE_CONTROLLED = 0x8029
ATTR_ICE_CONTROLLING = 0x802A


class StunError(ValueError):
    pass


def _pad(n: int) -> int:
    return (4 - (n % 4)) % 4


@dataclass
class Message:
    message_type: int
    transaction_id: bytes
    attributes: list[tuple[int, bytes]] = field(default_factory=list)

    def get(self, attr_type: int) -> bytes | None:
        for t, v in self.attributes:
            if t == attr_type:
                return v
        return None

    def has(self, attr_type: int) -> bool:
        return any(t == attr_type for t, _ in self.attributes)

    # ---- encode ----
    def _encode_head_and_attrs(self, attrs: list[tuple[int, bytes]], extra_len: int) -> bytes:
        body = bytearray()
        for t, v in attrs:
            body += struct.pack(">HH", t, len(v)) + v + b"\x00" * _pad(len(v))
        length = len(body) + extra_len
        head = struct.pack(">HH", self.message_type, length) + _COOKIE_BE + self.transaction_id
        return bytes(head + body)

    def encode(self, integrity_key: bytes | None = None, fingerprint: bool = True) -> bytes:
        attrs = list(self.attributes)
        data = self._encode_head_and_attrs(attrs, 0)
        if integrity_key is not None:
            # length must count the upcoming MESSAGE-INTEGRITY attribute (24 bytes)
            partial = self._encode_head_and_attrs(attrs, 24)
            mac = hmac.new(integrity_key, partial, hashlib.sha1).digest()
            attrs.append((ATTR_MESSAGE_INTEGRITY, mac))
            data = self._encode_head_and_attrs(attrs, 0)
        if fingerprint:
            partial = self._encode_head_and_attrs(attrs, 8)
            crc = (zlib.crc32(partial) & 0xFFFFFFFF) ^ 0x5354554E
            attrs.append((ATTR_FINGERPRINT, struct.pack(">I", crc)))
            data = self._encode_head_and_attrs(attrs, 0)
        return data

    # ---- decode ----
    @classmethod
    def decode(cls, data: bytes) -> "Message":
        if len(data) < 20:
            raise StunError("messaggio STUN troppo corto")
        mtype, length = struct.unpack_from(">HH", data, 0)
        if data[4:8] != _COOKIE_BE:
            raise StunError("magic cookie STUN assente")
        txid = data[8:20]
        if 20 + length > len(data):
            raise StunError("lunghezza STUN incoerente")
        attrs = []
        off = 20
        end = 20 + length
        while off + 4 <= end:
            t, alen = struct.unpack_from(">HH", data, off)
            off += 4
            if off + alen > end:
                raise StunError("attributo STUN troncato")
            attrs.append((t, data[off:off + alen]))
            off += alen + _pad(alen)
        return cls(mtype, txid, attrs)

    def verify_integrity(self, integrity_key: bytes, raw: bytes) -> bool:
        """Verify MESSAGE-INTEGRITY of a received message against its raw bytes."""
        # locate MI attribute position in raw
        off = 20
        while off + 4 <= len(raw):
            t, alen = struct.unpack_from(">HH", raw, off)
            if t == ATTR_MESSAGE_INTEGRITY:
                mi_value = raw[off + 4:off + 4 + alen]
                # recompute over message truncated at MI, length field set to
                # (offset_after_MI - 20)
                truncated = bytearray(raw[:off])
                new_len = (off + 24) - 20
                struct.pack_into(">H", truncated, 2, new_len)
                mac = hmac.new(integrity_key, bytes(truncated), hashlib.sha1).digest()
                return hmac.compare_digest(mac, mi_value)
            off += 4 + alen + _pad(alen)
        return False


def xor_mapped_address(value: bytes, txid: bytes) -> tuple[str, int]:
    if len(value) < 8 or value[1] != 0x01:
        raise StunError("XOR-MAPPED-ADDRESS non IPv4")
    xport = struct.unpack_from(">H", value, 2)[0]
    port = xport ^ (MAGIC_COOKIE >> 16)
    raw = bytes(a ^ b for a, b in zip(value[4:8], _COOKIE_BE))
    return str(ipaddress.IPv4Address(raw)), port


def encode_xor_mapped_address(ip: str, port: int, txid: bytes) -> bytes:
    xport = port ^ (MAGIC_COOKIE >> 16)
    raw = ipaddress.IPv4Address(ip).packed
    xaddr = bytes(a ^ b for a, b in zip(raw, _COOKIE_BE))
    return struct.pack(">BBH", 0, 0x01, xport) + xaddr


def new_transaction_id() -> bytes:
    return os.urandom(12)


def short_term_key(password: str) -> bytes:
    # RFC 5389 short-term credentials: key = SASLprep(password); hex ascii here.
    return password.encode("utf-8")
