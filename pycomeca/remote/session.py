"""Glue: run the existing ICONA client over the remote PseudoTCP/ICE transport.

`connect_remote` performs the whole bring-up (gather, p2p/start, ICE, PseudoTCP
handshake) and returns a socket-like object. `RemoteIconaClient` plugs that into
the unchanged `IconaClient`, so authenticate/configuration/open_target work the
same as on the LAN.

Only the signalling (p2p.py) touches Comelit's servers; everything else is this
machine talking UDP to the device's ICE candidates.
"""
from __future__ import annotations

import logging
import socket
import time

from ..client import IconaClient
from ..profile import Profile
from . import p2p
from .ice import IceAgent, IceStream, gather_srflx
from .pseudotcp import PseudoTcp, STATE_CLOSED
from .sdp import Candidate, SessionDescription, build_offer, validate_ice_credentials

LOG = logging.getLogger(__name__)

MASK32 = 0xFFFFFFFF
STUN_SERVER = ("turn-r1de.cloud.comelitgroup.com", 3478)


def _now_ms() -> int:
    return int(time.monotonic() * 1000) & MASK32


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 53))   # no packet sent; just picks the egress interface
        return s.getsockname()[0]
    except OSError:
        return "0.0.0.0"
    finally:
        s.close()


class PseudoTcpSocket:
    """socket-like reliable stream: sendall/recv/settimeout/setsockopt/close.

    Pumps the PseudoTCP clock and the ICE datagram path on every recv so
    retransmissions and acks progress while the ICONA client blocks on reads.
    """

    def __init__(self, stream: IceStream, pt: PseudoTcp):
        self._stream = stream
        self._pt = pt
        self._timeout = 30.0
        self._inbuf = bytearray()

    def settimeout(self, value: float) -> None:
        self._timeout = float(value) if value is not None else 30.0

    def setsockopt(self, *_args) -> None:
        pass

    def _pump_once(self, budget: float) -> None:
        data = self._stream.recv(max(0.0, min(budget, 0.1)))
        if data:
            self._pt.handle_input(data)
        self._pt.clock(_now_ms())
        chunk = self._pt.read()
        if chunk:
            self._inbuf.extend(chunk)

    def sendall(self, data: bytes) -> None:
        self._pt.write(data)
        self._pt.clock(_now_ms())

    def recv(self, bufsize: int) -> bytes:
        end = time.monotonic() + self._timeout
        while not self._inbuf:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise socket.timeout("timeout PseudoTCP")
            if self._pt.state == STATE_CLOSED:
                return b""      # EOF -> IconaClient raises ConnectionError
            self._pump_once(remaining)
        out = bytes(self._inbuf[:bufsize])
        del self._inbuf[:len(out)]
        return out

    def close(self) -> None:
        try:
            self._pt.close()
        finally:
            self._stream.close()


def connect_remote(oauth_token: str, device_uuid: str, viper_token: str,
                   *, ice_ufrag: str, ice_pwd: str, handshake_timeout: float = 20.0,
                   ice_timeout: float = 15.0,
                   relay_only: bool = False) -> PseudoTcpSocket:
    """Full remote bring-up. Returns a connected PseudoTcpSocket."""
    validate_ice_credentials(ice_ufrag, ice_pwd)

    # 1. Gather our host + server-reflexive candidate (reuses the socket/mapping).
    try:
        stun_addr = (socket.gethostbyname(STUN_SERVER[0]), STUN_SERVER[1])
    except OSError as exc:
        raise p2p.SignalingError(f"STUN DNS fallita: {exc}") from None
    sock, local_addr, srflx = gather_srflx(stun_addr)
    host_ip = _local_ip()
    local_port = sock.getsockname()[1]
    # relay_only: do not advertise our LAN address, so the device cannot reach us directly.
    candidates = [] if relay_only else [
        Candidate("H00000001", 1, "UDP", 2130706431, host_ip, local_port, "host")]
    srflx_ip = "0.0.0.0"
    if srflx:
        srflx_ip = srflx[0]
        candidates.append(Candidate("S00000001", 1, "UDP", 1862270975, srflx[0], srflx[1],
                                    "srflx", raddr=host_ip, rport=local_port))

    # 2. Signalling: offer -> answer.
    session_id = int.from_bytes(_now_ms().to_bytes(4, "big"), "big")
    offer = build_offer(session_id, ice_ufrag, ice_pwd, candidates, srflx_ip, local_port)
    answer_text = p2p.p2p_start(oauth_token, device_uuid, viper_token, offer)
    answer = SessionDescription.parse(answer_text)
    LOG.info("p2p/start ok: %d candidati remoti, ice-role=%s",
             len(answer.candidates), answer.ice_role or "?")

    # 3. ICE connectivity (we are controlled; the device nominates).
    remote = answer.candidates
    if relay_only:
        remote = [c for c in remote if c.typ == "relay"]
        if not remote:
            raise p2p.SignalingError("relay_only: il device non offre candidati relay")
        if not srflx:
            raise p2p.SignalingError("relay_only: candidato srflx non ottenuto dallo STUN")
    agent = IceAgent(sock, ice_ufrag, ice_pwd, answer.ice_ufrag, answer.ice_pwd,
                     remote, controlling=False, restrict=relay_only)
    selected = agent.connect(timeout=ice_timeout)
    LOG.info("ICE: coppia selezionata %s", selected)
    stream = IceStream(agent)

    # 4. PseudoTCP handshake over the nominated path.
    pt = PseudoTcp(stream.send, now_ms=_now_ms())
    pt.connect()
    end = time.monotonic() + handshake_timeout
    while not pt.is_connected:
        if time.monotonic() > end:
            stream.close()
            raise TimeoutError("PseudoTCP: handshake non completato")
        data = stream.recv(0.1)
        if data:
            pt.handle_input(data)
        pt.clock(_now_ms())
    LOG.info("PseudoTCP stabilito")
    return PseudoTcpSocket(stream, pt)


class RemoteIconaClient(IconaClient):
    """IconaClient that connects through the cloud P2P transport instead of TCP."""

    def __init__(self, profile: Profile, oauth_token: str, device_uuid: str,
                 viper_token: str, ice_ufrag: str, ice_pwd: str,
                 relay_only: bool = False):
        super().__init__(profile)
        self._relay_only = relay_only
        self._oauth_token = oauth_token
        self._device_uuid = device_uuid
        self._viper_token = viper_token
        self._ice_ufrag = ice_ufrag
        self._ice_pwd = ice_pwd

    def connect(self):
        if self.sock is not None:
            raise RuntimeError("Sessione gia connessa")
        self.deadline = time.monotonic() + self.profile.timeout
        self.sock = connect_remote(
            self._oauth_token, self._device_uuid, self._viper_token,
            ice_ufrag=self._ice_ufrag, ice_pwd=self._ice_pwd,
            relay_only=self._relay_only)
        # mirror the base-class per-connection resets
        from ..protocol import FrameDecoder
        self.decoder = FrameDecoder()
        self.observations.clear()
        self.live_config = None
        self.control_attempted = False
        self.frames_sent = self.frames_received = 0
        # On the P2P path the device speaks first: it opens an ECHO channel and
        # drops anything we send before that open is acknowledged (order
        # verified against the official app's capture).
        greeting_deadline = time.monotonic() + 10.0
        while True:
            frame = self._read(greeting_deadline)
            if self._maybe_ack_channel_open(frame):
                break
            self._observe(frame)
