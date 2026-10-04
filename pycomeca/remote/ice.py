"""Small ICE agent for the Comelit viper_p2p_v2 case.

Scope: a single component (RTP, component 1) over one UDP socket, acting as the
CONTROLLED agent. The device is the controlling agent and uses aggressive
nomination (it stamps USE-CANDIDATE on its checks), so our job is to answer its
binding requests and run our own triggered checks until a pair is nominated.

We reach the device through its offered candidates (host/srflx/relay); the TURN
relay candidate is the reliable fallback under CGNAT. We do not allocate our own
TURN relay: we always initiate, so the device learns our mapped address from the
source of our checks and can reply there.

Pure standard library. STUN wire handled by `stun.py`.
"""
from __future__ import annotations

import logging
import socket
import time

from . import stun
from .sdp import Candidate

LOG = logging.getLogger(__name__)

_CHECK_INTERVAL = 0.2    # seconds between retransmitted checks
_MAX_PACKET = 2048


def gather_srflx(stun_server: tuple[str, int], timeout: float = 3.0):
    """Query a STUN server for our server-reflexive (ip, port) and keep the socket.

    Returns (socket, local_addr, srflx_addr). The socket stays bound so the
    mapping is reused for the ICE checks. srflx_addr is None on failure.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.settimeout(timeout)
    req = stun.Message(stun.BINDING_REQUEST, stun.new_transaction_id())
    try:
        sock.sendto(req.encode(integrity_key=None, fingerprint=True), stun_server)
        while True:
            data, _ = sock.recvfrom(_MAX_PACKET)
            try:
                msg = stun.Message.decode(data)
            except stun.StunError:
                continue
            if msg.message_type == stun.BINDING_SUCCESS:
                value = msg.get(stun.ATTR_XOR_MAPPED_ADDRESS)
                if value:
                    srflx = stun.xor_mapped_address(value, msg.transaction_id)
                    sock.settimeout(None)
                    return sock, sock.getsockname(), srflx
    except (socket.timeout, OSError) as exc:
        LOG.debug("STUN gather fallita: %s", exc)
    sock.settimeout(None)
    return sock, sock.getsockname(), None


class IceAgent:
    """Controlled-agent connectivity over one UDP socket."""

    def __init__(self, sock: socket.socket, local_ufrag: str, local_pwd: str,
                 remote_ufrag: str, remote_pwd: str,
                 remote_candidates: list[Candidate], controlling: bool = False,
                 restrict: bool = False):
        self.sock = sock
        # restrict=True: ignore STUN from any address outside the given candidates
        # (used to force the relay path and keep the LAN shortcut out).
        self.restrict = restrict
        self.local_ufrag = local_ufrag
        self.local_pwd = local_pwd
        self.remote_ufrag = remote_ufrag
        self.remote_pwd = remote_pwd
        self.controlling = controlling
        self.tie_breaker = stun.new_transaction_id()[:8]
        # unique ordered list of remote transport addresses to probe
        seen = set()
        self.remote_addrs: list[tuple[str, int]] = []
        for c in sorted(remote_candidates, key=lambda c: c.priority, reverse=True):
            addr = (c.ip, c.port)
            if addr not in seen:
                seen.add(addr)
                self.remote_addrs.append(addr)
        self.valid: set[tuple[str, int]] = set()      # we got a success response from here
        self.nominated: tuple[str, int] | None = None
        self.selected: tuple[str, int] | None = None

    # ---- check sending/answering ----

    def _send_check(self, addr: tuple[str, int]) -> None:
        txid = stun.new_transaction_id()
        attrs = [
            (stun.ATTR_USERNAME, f"{self.remote_ufrag}:{self.local_ufrag}".encode()),
            (stun.ATTR_PRIORITY, (110 << 24 | 0xFFFF << 8 | 0xFF).to_bytes(4, "big")),
        ]
        if self.controlling:
            attrs.append((stun.ATTR_ICE_CONTROLLING, self.tie_breaker))
            attrs.append((stun.ATTR_USE_CANDIDATE, b""))
        else:
            attrs.append((stun.ATTR_ICE_CONTROLLED, self.tie_breaker))
        msg = stun.Message(stun.BINDING_REQUEST, txid, attrs)
        key = stun.short_term_key(self.remote_pwd)
        try:
            self.sock.sendto(msg.encode(integrity_key=key, fingerprint=True), addr)
        except OSError as exc:
            LOG.debug("invio check fallito verso %s: %s", addr, exc)

    def _handle_request(self, msg: stun.Message, raw: bytes, addr: tuple[str, int]) -> None:
        key = stun.short_term_key(self.local_pwd)
        if not msg.verify_integrity(key, raw):
            LOG.debug("binding request con integrity errata da %s", addr)
            return
        # success response, echoing the peer's transaction id
        resp = stun.Message(stun.BINDING_SUCCESS, msg.transaction_id, [
            (stun.ATTR_XOR_MAPPED_ADDRESS,
             stun.encode_xor_mapped_address(addr[0], addr[1], msg.transaction_id)),
        ])
        self.sock.sendto(resp.encode(integrity_key=key, fingerprint=True), addr)
        # a controlling peer's USE-CANDIDATE nominates this pair
        if msg.has(stun.ATTR_USE_CANDIDATE):
            self.nominated = addr
        # trigger a check back toward this address if new
        if addr not in self.remote_addrs:
            self.remote_addrs.append(addr)

    def _handle_response(self, msg: stun.Message, raw: bytes, addr: tuple[str, int]) -> None:
        key = stun.short_term_key(self.remote_pwd)
        if not msg.verify_integrity(key, raw):
            return
        self.valid.add(addr)
        if self.controlling:
            # aggressive: our checks carried USE-CANDIDATE, so a success nominates
            self.nominated = self.nominated or addr

    def _dispatch(self, raw: bytes, addr: tuple[str, int]) -> None:
        if self.restrict and addr not in self.remote_addrs:
            return
        try:
            msg = stun.Message.decode(raw)
        except stun.StunError:
            return
        if msg.message_type == stun.BINDING_REQUEST:
            self._handle_request(msg, raw, addr)
        elif msg.message_type == stun.BINDING_SUCCESS:
            self._handle_response(msg, raw, addr)

    def connect(self, timeout: float = 15.0) -> tuple[str, int]:
        """Run checks until a pair is nominated and validated. Returns remote addr."""
        deadline = time.monotonic() + timeout
        last_check = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now - last_check >= _CHECK_INTERVAL:
                for addr in list(self.remote_addrs):
                    self._send_check(addr)
                last_check = now
            # selection: nominated pair that we have also validated (or relay fallback)
            if self.nominated and (self.nominated in self.valid or self.controlling):
                self.selected = self.nominated
                return self.selected
            self.sock.settimeout(max(0.0, min(_CHECK_INTERVAL, deadline - now)))
            try:
                raw, addr = self.sock.recvfrom(_MAX_PACKET)
            except (socket.timeout, OSError):
                continue
            if _is_stun(raw):
                self._dispatch(raw, addr)
        raise TimeoutError("ICE: nessuna coppia nominata entro il timeout")


def _is_stun(data: bytes) -> bool:
    return len(data) >= 8 and data[4:8] == stun._COOKIE_BE


class IceStream:
    """After ICE connects, a datagram channel pinned to the selected remote.

    Also answers any late STUN keepalive/checks so the pair stays alive, and
    returns only non-STUN (PseudoTCP) payloads to the caller.
    """

    def __init__(self, agent: IceAgent):
        if agent.selected is None:
            raise RuntimeError("IceStream richiede un ICE già connesso")
        self.sock = agent.sock
        self.peer = agent.selected
        self._agent = agent

    def send(self, data: bytes) -> None:
        self.sock.sendto(data, self.peer)

    def recv(self, timeout: float) -> bytes | None:
        self.sock.settimeout(max(0.0, timeout))
        try:
            raw, addr = self.sock.recvfrom(_MAX_PACKET)
        except (socket.timeout, OSError):
            return None
        if _is_stun(raw):
            self._agent._dispatch(raw, addr)
            return None
        return raw

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass
