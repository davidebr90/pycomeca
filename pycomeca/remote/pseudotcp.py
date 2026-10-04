"""Minimal libnice-compatible PseudoTCP over an unreliable datagram path.

PseudoTCP is the reliable-stream protocol libnice/libjingle run inside an ICE
session; Comelit's viper_p2p_v2 carries the ICONA byte stream over it. This is
an independent re-implementation sized for small, bursty transfers (a session
handshake plus one door command), not a general high-throughput stack.

Wire format pinned from the ICE verify capture (big-endian 24-byte header):

    conv(4) seq(4) ack(4) byte12=0 flags(1) wnd(2) tsval(4) tsecr(4)

flags: 0 = data, 2 = control (CONNECT). The 7-byte CONNECT control payload
occupies sequence space 0..6 on each side; application bytes start at seq 7.
Sequence numbers start at 0 and conversation id is 0, as observed.

Engine is transport-agnostic: it emits segments through `send_packet` and is fed
inbound datagrams via `handle_input`. Drive timers with `clock`.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

HEADER = struct.Struct(">IIIBBHII")
HEADER_SIZE = 24

FLAG_DATA = 0x00
FLAG_CTL = 0x02
FLAG_RST = 0x04

# Observed CONNECT control payload (CTL_CONNECT + window-scale option, scale 0).
CONNECT_PAYLOAD = bytes.fromhex("00030100fe0100")
CTL_CONNECT = 0x00

DEFAULT_MSS = 1376
DEFAULT_RCV_WND = 61440           # 0xF000, matches the capture's initial window
MIN_RTO = 250
MAX_RTO = 60000
DEFAULT_RTO = 3000
MASK32 = 0xFFFFFFFF

STATE_LISTEN = "listen"
STATE_SYN_SENT = "syn-sent"
STATE_ESTABLISHED = "established"
STATE_CLOSED = "closed"


class PseudoTcpError(Exception):
    pass


def _mod_le(a: int, b: int) -> bool:
    """a <= b in 32-bit sequence arithmetic (wrap-safe)."""
    return ((a - b) & MASK32) >= 0x80000000 or a == b


def _mod_lt(a: int, b: int) -> bool:
    return a != b and ((a - b) & MASK32) >= 0x80000000


@dataclass
class _Segment:
    seq: int
    length: int
    flags: int
    xmit: int = 0          # transmit count
    when: int = 0          # last send time (ms)


class PseudoTcp:
    def __init__(self, send_packet, conv: int = 0, now_ms: int = 0):
        self._send_packet = send_packet
        self.conv = conv
        self.state = STATE_LISTEN
        self.error = 0

        # send side
        self._sbuf = bytearray()   # stream bytes from snd_una onward (unacked + unsent)
        self.snd_una = 0
        self.snd_nxt = 0
        self.snd_wnd = DEFAULT_RCV_WND
        self._control_end = 0      # stream offset where control bytes end (7 after connect)
        self._inflight: list[_Segment] = []

        # receive side
        self._rbuf = bytearray()   # delivered, app-readable bytes
        self.rcv_nxt = 0
        self.rcv_wnd = DEFAULT_RCV_WND
        self._ooo: dict[int, bytes] = {}

        # timers / rtt
        self._rto = DEFAULT_RTO
        self._srtt = 0
        self._rttvar = 0
        self._ts_recent = 0
        self._ack_pending = False
        self._rto_deadline = None
        self._now = now_ms & MASK32

        self.mss = DEFAULT_MSS

    # ---- public API -----------------------------------------------------

    def connect(self) -> None:
        if self.state != STATE_LISTEN:
            raise PseudoTcpError("connect() valido solo dallo stato iniziale")
        self._sbuf.extend(CONNECT_PAYLOAD)
        self._control_end = len(CONNECT_PAYLOAD)
        self.state = STATE_SYN_SENT
        self._attempt_send()

    def write(self, data: bytes) -> int:
        if self.state == STATE_CLOSED:
            raise PseudoTcpError("stream chiuso")
        self._sbuf.extend(data)
        self._attempt_send()
        return len(data)

    def read(self, maxlen: int = 65536) -> bytes:
        if not self._rbuf:
            return b""
        chunk = bytes(self._rbuf[:maxlen])
        del self._rbuf[:len(chunk)]
        return chunk

    @property
    def bytes_available(self) -> int:
        return len(self._rbuf)

    @property
    def is_connected(self) -> bool:
        return self.state == STATE_ESTABLISHED

    def close(self) -> None:
        # Best-effort reset so the peer tears down promptly.
        if self.state in (STATE_ESTABLISHED, STATE_SYN_SENT):
            self._transmit(self.snd_nxt, FLAG_RST, b"")
        self.state = STATE_CLOSED

    # ---- clock ----------------------------------------------------------

    def clock(self, now_ms: int):
        """Advance timers. Returns ms until next wakeup, or None if idle."""
        self._now = now_ms & MASK32
        if self._ack_pending:
            self._send_ack()
            self._ack_pending = False
        if self._inflight and self._rto_deadline is not None:
            if _mod_le(self._rto_deadline, self._now):
                self._retransmit()
        if self._inflight and self._rto_deadline is not None:
            delay = (self._rto_deadline - self._now) & MASK32
            return delay if delay < 0x80000000 else 0
        return None

    # ---- inbound --------------------------------------------------------

    def handle_input(self, packet: bytes) -> None:
        if len(packet) < HEADER_SIZE:
            raise PseudoTcpError("segmento PseudoTCP troppo corto")
        conv, seq, ack, b12, flags, wnd, tsval, tsecr = HEADER.unpack_from(packet, 0)
        if conv != self.conv or b12 != 0:
            raise PseudoTcpError("conversation id inatteso")
        payload = packet[HEADER_SIZE:]

        if flags & FLAG_RST:
            self.state = STATE_CLOSED
            self.error = 104  # ECONNRESET
            return

        self.snd_wnd = wnd
        self._process_ack(ack, tsecr)

        if flags & FLAG_CTL:
            self._process_control(seq, payload, tsval)
        elif payload:
            self._process_data(seq, payload, tsval)
        elif self.state == STATE_SYN_SENT and _mod_le(7, self.rcv_nxt):
            # pure ACK after both connects seen
            pass

        self._attempt_send()

    # ---- internals ------------------------------------------------------

    def _process_ack(self, ack: int, tsecr: int) -> None:
        if _mod_lt(self.snd_una, ack) and _mod_le(ack, self.snd_nxt):
            acked = (ack - self.snd_una) & MASK32
            del self._sbuf[:acked]
            self.snd_una = ack
            self._control_end = max(0, self._control_end - acked)
            # drop fully-acked in-flight segments and update RTT from them
            remaining = []
            for seg in self._inflight:
                if _mod_le((seg.seq + seg.length) & MASK32, ack):
                    if seg.xmit == 1:
                        self._update_rtt(((self._now - seg.when) & MASK32))
                else:
                    remaining.append(seg)
            self._inflight = remaining
            self._rto_deadline = (self._now + self._rto) & MASK32 if self._inflight else None
            if self.state == STATE_SYN_SENT and _mod_le(self._control_end_abs(), ack):
                self.state = STATE_ESTABLISHED

    def _control_end_abs(self) -> int:
        # absolute seq where our control region ends (7)
        return len(CONNECT_PAYLOAD) & MASK32

    def _process_control(self, seq: int, payload: bytes, tsval: int) -> None:
        if payload[:1] == bytes([CTL_CONNECT]):
            if seq == self.rcv_nxt:
                self.rcv_nxt = (self.rcv_nxt + len(payload)) & MASK32
                self._ts_recent = tsval
                if self.state in (STATE_SYN_SENT, STATE_LISTEN):
                    # Peer connect accepted; become established once ours is acked.
                    if self.state == STATE_LISTEN:
                        self.state = STATE_SYN_SENT
                self._ack_pending = True
                if self.state == STATE_SYN_SENT and self.snd_una >= self._control_end_abs():
                    self.state = STATE_ESTABLISHED
        else:
            # unknown control: ack to keep the stream moving, do not deliver
            if seq == self.rcv_nxt:
                self.rcv_nxt = (self.rcv_nxt + len(payload)) & MASK32
                self._ack_pending = True

    def _process_data(self, seq: int, payload: bytes, tsval: int) -> None:
        if _mod_lt(seq, self.rcv_nxt):
            # already have it (retransmit); re-ack
            self._ack_pending = True
            return
        if seq == self.rcv_nxt:
            self._rbuf.extend(payload)
            self.rcv_nxt = (self.rcv_nxt + len(payload)) & MASK32
            self._ts_recent = tsval
            # pull any contiguous out-of-order segments
            while self.rcv_nxt in self._ooo:
                nxt = self._ooo.pop(self.rcv_nxt)
                self._rbuf.extend(nxt)
                self.rcv_nxt = (self.rcv_nxt + len(nxt)) & MASK32
            if self.state == STATE_SYN_SENT:
                self.state = STATE_ESTABLISHED
        else:
            # out of order, buffer if window allows
            if len(self._ooo) < 256:
                self._ooo[seq] = payload
        self._ack_pending = True

    def _attempt_send(self) -> None:
        # window = min(peer advertised, our data available)
        while True:
            offset = (self.snd_nxt - self.snd_una) & MASK32
            available = len(self._sbuf) - offset
            if available <= 0:
                break
            window = self.snd_wnd
            inflight = (self.snd_nxt - self.snd_una) & MASK32
            allowed = window - inflight
            if allowed <= 0:
                break
            seg_len = min(available, self.mss, allowed)
            # never mix control and data in one segment
            if offset < self._control_end:
                seg_len = min(seg_len, self._control_end - offset)
                flags = FLAG_CTL
            else:
                flags = FLAG_DATA
            chunk = bytes(self._sbuf[offset:offset + seg_len])
            self._transmit(self.snd_nxt, flags, chunk)
            self.snd_nxt = (self.snd_nxt + seg_len) & MASK32
            self._inflight.append(_Segment(seq=(self.snd_nxt - seg_len) & MASK32,
                                           length=seg_len, flags=flags,
                                           xmit=1, when=self._now))
            if self._rto_deadline is None:
                self._rto_deadline = (self._now + self._rto) & MASK32

    def _retransmit(self) -> None:
        if not self._inflight:
            self._rto_deadline = None
            return
        seg = self._inflight[0]
        offset = (seg.seq - self.snd_una) & MASK32
        chunk = bytes(self._sbuf[offset:offset + seg.length])
        self._transmit(seg.seq, seg.flags, chunk)
        seg.xmit += 1
        seg.when = self._now
        self._rto = min(self._rto * 2, MAX_RTO)   # exponential backoff
        self._rto_deadline = (self._now + self._rto) & MASK32

    def _send_ack(self) -> None:
        self._transmit(self.snd_nxt, FLAG_DATA, b"")

    def _transmit(self, seq: int, flags: int, payload: bytes) -> None:
        header = HEADER.pack(self.conv, seq & MASK32, self.rcv_nxt & MASK32,
                             0, flags, self._recv_window(),
                             self._now & MASK32, self._ts_recent & MASK32)
        self._send_packet(header + payload)

    def _recv_window(self) -> int:
        free = self.rcv_wnd - len(self._rbuf)
        return max(0, min(0xFFFF, free))

    def _update_rtt(self, rtt: int) -> None:
        if rtt <= 0:
            rtt = 1
        if self._srtt == 0:
            self._srtt = rtt
            self._rttvar = rtt // 2
        else:
            self._rttvar = (3 * self._rttvar + abs(self._srtt - rtt)) // 4
            self._srtt = (7 * self._srtt + rtt) // 8
        self._rto = max(MIN_RTO, min(MAX_RTO, self._srtt + 4 * self._rttvar))
