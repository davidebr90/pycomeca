"""Comelit viper_p2p_v2 SDP: build the offer, parse the device answer.

The SDP is the non-standard "s=ice" dialect Comelit uses as the ICE signalling
envelope inside POST /servicerest/p2p/start. Only the fields the transport needs
are modelled: ice-ufrag/ice-pwd, ice-role and the candidate list. Media (m=/RTP)
lines are nominal; the real payload is PseudoTCP + ICONA, not RTP.

Shapes verified against docs/REMOTE_P2P.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re


class SdpError(ValueError):
    """Malformed or unexpected SDP; never guess on the wire."""


@dataclass(frozen=True)
class Candidate:
    foundation: str
    component: int
    transport: str
    priority: int
    ip: str
    port: int
    typ: str                      # host | srflx | relay | prflx
    raddr: str | None = None
    rport: int | None = None

    def to_sdp(self) -> str:
        line = (f"candidate:{self.foundation} {self.component} {self.transport} "
                f"{self.priority} {self.ip} {self.port} typ {self.typ}")
        if self.raddr is not None and self.rport is not None:
            line += f" raddr {self.raddr} rport {self.rport}"
        return line

    @classmethod
    def parse(cls, value: str) -> "Candidate":
        # value starts after "candidate:"
        parts = value.split()
        if len(parts) < 8 or parts[6] != "typ":
            raise SdpError(f"candidate malformato: {value!r}")
        raddr = rport = None
        extra = parts[8:]
        for i in range(0, len(extra) - 1, 2):
            if extra[i] == "raddr":
                raddr = extra[i + 1]
            elif extra[i] == "rport":
                rport = int(extra[i + 1])
        try:
            return cls(parts[0], int(parts[1]), parts[2].upper(), int(parts[3]),
                       parts[4], int(parts[5]), parts[7], raddr, rport)
        except ValueError as exc:
            raise SdpError(f"candidate con campi non numerici: {value!r}") from exc


@dataclass
class SessionDescription:
    ice_ufrag: str
    ice_pwd: str
    ice_role: str                 # "a" (app/offer) or "o" (device/answer)
    candidates: list[Candidate] = field(default_factory=list)
    connection_ip: str = "0.0.0.0"
    media_port: int = 9

    @classmethod
    def parse(cls, text: str) -> "SessionDescription":
        if "v=0" not in text:
            raise SdpError("SDP privo di v=0")
        ufrag = pwd = role = None
        cands: list[Candidate] = []
        conn_ip = "0.0.0.0"
        media_port = 9
        for raw in text.replace("\r\n", "\n").split("\n"):
            line = raw.strip()
            if not line or "=" not in line:
                continue
            kind, body = line.split("=", 1)
            if kind == "a":
                if body.startswith("ice-ufrag:"):
                    ufrag = body[len("ice-ufrag:"):]
                elif body.startswith("ice-pwd:"):
                    pwd = body[len("ice-pwd:"):]
                elif body.startswith("ice-role:"):
                    role = body[len("ice-role:"):]
                elif body.startswith("candidate:"):
                    cands.append(Candidate.parse(body[len("candidate:"):]))
            elif kind == "m":
                fields = body.split()
                if len(fields) >= 2 and fields[1].isdigit():
                    media_port = int(fields[1])
            elif kind == "c":
                fields = body.split()
                if len(fields) == 3:
                    conn_ip = fields[2]
        if not ufrag or not pwd:
            raise SdpError("SDP senza ice-ufrag/ice-pwd")
        return cls(ufrag, pwd, role or "", cands, conn_ip, media_port)


# ufrag/pwd charset per RFC 5245 (ice-char); Comelit uses lowercase hex in captures.
_ICE_CHAR = re.compile(r"[0-9A-Za-z+/]+")


def validate_ice_credentials(ufrag: str, pwd: str) -> None:
    if not (4 <= len(ufrag) <= 256 and _ICE_CHAR.fullmatch(ufrag)):
        raise SdpError("ice-ufrag non valido")
    if not (22 <= len(pwd) <= 256 and _ICE_CHAR.fullmatch(pwd)):
        raise SdpError("ice-pwd non valido")


def build_offer(session_id: int, ufrag: str, pwd: str,
                candidates: list[Candidate], srflx_ip: str, media_port: int) -> str:
    """Compose the offer SDP in Comelit's exact line order and dialect.

    `media_port` is the UDP port our single ICE component listens on; `srflx_ip`
    is our server-reflexive address (the second c= line), 0.0.0.0 if unknown.
    """
    validate_ice_credentials(ufrag, pwd)
    lines = [
        "v=0",
        f"o=- {session_id} {session_id} IN IP4 0.0.0.0",
        "s=ice",
        "t=0 0",
        "a=nego-wait:0",
        "a=comelit-legacy-session:TCP",
        "a=comelit-session-id:MUX",
        "a=comelit-nego-aggressive:true",
        "c=IN IP4 0.0.0.0",
        f"m=audio {media_port} RTP/SAVPF 0 8",
        "b=RS:0",
        "b=RR:0",
        f"c=IN IP4 {srflx_ip}",
        "a=sendrecv",
    ]
    lines += ["a=" + c.to_sdp() for c in candidates]
    lines += [
        "a=ice-role:a",
        f"a=ice-ufrag:{ufrag}",
        f"a=ice-pwd:{pwd}",
    ]
    # Comelit SDP uses CRLF line endings.
    return "\r\n".join(lines) + "\r\n"
