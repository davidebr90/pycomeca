"""Synchronous, single-owner ICONA session with a whole-session deadline."""

from __future__ import annotations

from collections import deque
import ipaddress
import logging
import re
import secrets
import socket
import struct
import time

from .profile import DeviceConfig, Profile, Target
from .protocol import (COMMAND, END, Frame, FrameDecoder, ProtocolError,
                       close_channel, ctpp_registration, decode_ctpp, decode_json,
                       door_sequence, json_frame, open_channel, open_confirmations)

LOG = logging.getLogger(__name__)


class AuthenticationError(ProtocolError):
    pass


class SessionTimeout(TimeoutError):
    pass


class IconaClient:
    """Exactly one reader and one outstanding operation; no automatic retries.

    All calls on an instance must run on the same thread. Multiplexed packets
    not belonging to the current operation are retained in a bounded queue.
    A timed-out partial frame stays in FrameDecoder, not in a discarded local.
    """

    def __init__(self, profile: Profile):
        self.profile = profile
        self.sock = None
        self.decoder = FrameDecoder()
        self.channels: dict[str, int] = {}
        self.observations = deque(maxlen=64)
        self.deadline = 0.0
        self._next_id = secrets.randbelow(30000) + 1000
        self.authenticated = False
        self.control_attempted = False
        self.frames_sent = 0
        self.frames_received = 0
        self.live_config: DeviceConfig | None = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    def connect(self):
        if self.sock is not None:
            raise ProtocolError("Sessione gia connessa")
        family = socket.AF_INET6 if ipaddress.ip_address(self.profile.host).version == 6 else socket.AF_INET
        self.deadline = time.monotonic() + self.profile.timeout
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(self.profile.timeout)
        try:
            sock.connect((self.profile.host, self.profile.port))
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except BaseException:
            sock.close()
            raise
        self.sock = sock
        self.decoder = FrameDecoder()
        self.observations.clear()
        self.live_config = None
        self.control_attempted = False
        self.frames_sent = self.frames_received = 0

    def remaining(self, deadline: float | None = None) -> float:
        remaining = min(self.deadline, deadline if deadline is not None else self.deadline) - time.monotonic()
        if remaining <= 0:
            raise SessionTimeout("Deadline della sessione ICONA raggiunta")
        return remaining

    def _send(self, frame: Frame):
        if self.sock is None:
            raise ProtocolError("Sessione disconnessa")
        wire = frame.encode()
        self.sock.settimeout(self.remaining())
        self.sock.sendall(wire)
        self.frames_sent += 1
        # Never log bodies: UAUT and configuration can carry credentials.
        LOG.debug("TX channel=%d bytes=%d", frame.channel_id, len(frame.body))

    def _read(self, deadline: float | None = None) -> Frame:
        if self.sock is None:
            raise ProtocolError("Sessione disconnessa")
        while True:
            self.remaining(deadline)
            frame = self.decoder.pop()
            if frame is not None:
                self.frames_received += 1
                LOG.debug("RX channel=%d bytes=%d", frame.channel_id, len(frame.body))
                return frame
            self.sock.settimeout(self.remaining(deadline))
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout as exc:
                raise SessionTimeout("Timeout in attesa di un frame ICONA") from exc
            if not chunk:
                self.decoder.finish()
                raise ConnectionError("Il dispositivo ha chiuso la connessione")
            self.decoder.feed(chunk)

    def _observe(self, frame: Frame):
        if len(self.observations) == self.observations.maxlen:
            raise ProtocolError("Troppi frame non correlati: sessione interrotta")
        self.observations.append(frame)

    def _channel_closed(self, frame: Frame):
        if len(frame.body) >= 4 and frame.body[:2] == struct.pack("<H", END):
            if frame.channel_id != 0:
                closed = frame.channel_id
            elif len(frame.body) >= 10:
                closed = struct.unpack_from("<H", frame.body, 8)[0]
            else:
                raise ProtocolError("Risposta END malformata")
            if closed in self.channels.values():
                raise ProtocolError("Il dispositivo ha chiuso un canale attivo")

    def _maybe_ack_channel_open(self, frame: Frame) -> bool:
        """Answer a device-initiated channel open (COMMAND seq=1 on channel 0).

        On the cloud P2P path the device opens channels toward us (e.g. ECHO,
        RTPC) and withholds our own responses until each open is acknowledged.
        We reply with COMMAND seq=2, type 4, echoing the device's channel id
        (the LE16 before the final pad byte). The LAN path never sends these, so
        this is inert there. PCAP-verified format (see docs/PROTOCOL.md).
        """
        if frame.channel_id != 0 or frame.body[:2] != struct.pack("<H", COMMAND):
            return False
        if len(frame.body) < 15 or struct.unpack_from("<H", frame.body, 2)[0] != 1:
            return False
        request_id = struct.unpack_from("<H", frame.body, len(frame.body) - 3)[0]
        self._send(Frame(0, struct.pack("<HHIHH", COMMAND, 2, 4, request_id, 0)))
        LOG.debug("ACK apertura canale avviata dal device req_id=%d", request_id)
        return True

    def channel(self, name: str, extra: str | None = None) -> int:
        if name in self.channels:
            return self.channels[name]
        local_id = self._next_id
        self._next_id += 1
        self._send(open_channel(name, local_id, extra, self.profile.wire_profile))
        while True:
            frame = self._read()
            self._channel_closed(frame)
            if frame.channel_id == 0 and frame.body[:2] == struct.pack("<H", COMMAND):
                # sequence 2 is the response to OUR open. Other COMMANDs on
                # channel 0 are device-initiated channel opens (observed on the
                # P2P path: the device opens a channel toward us, e.g. RTPC),
                # not our answer; skip them rather than misreading a response.
                sequence = struct.unpack_from("<H", frame.body, 2)[0] if len(frame.body) >= 4 else 0
                if sequence != 2:
                    if not self._maybe_ack_channel_open(frame):
                        self._observe(frame)
                    continue
                if len(frame.body) != 12:
                    raise ProtocolError("COMMAND response inattesa (canale non aperto)")
                _, sequence, size, server_id, status = struct.unpack("<HHIHH", frame.body)
                if size != 4 or not server_id or status != 0:
                    raise ProtocolError("Apertura canale rifiutata o non riconosciuta")
                if server_id in self.channels.values():
                    raise ProtocolError("ID di canale duplicato")
                self.channels[name] = server_id
                return server_id
            self._observe(frame)

    def request(self, name: str, message: str, message_id: int, **fields) -> dict:
        channel_id = self.channel(name)
        self._send(json_frame(channel_id, {"message": message, "message-type": "request",
                                          "message-id": message_id, **fields}))
        while True:
            frame = self._read()
            self._channel_closed(frame)
            if frame.channel_id == channel_id:
                result = decode_json(frame.body)
                if (result.get("message") == message and result.get("message-type") == "response"
                        and type(result.get("message-id")) is int and result["message-id"] == message_id):
                    return result
            elif self._maybe_ack_channel_open(frame):
                continue
            self._observe(frame)

    def authenticate(self, token: str):
        self.authenticated = False
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", token):
            raise ValueError("Formato token VIP non valido")
        response = self.request("UAUT", "access", 2, **{"user-token": token})
        if type(response.get("response-code")) is not int or response["response-code"] != 200:
            raise AuthenticationError("UAUT: autenticazione rifiutata")
        if response.get("encryption-required", False) is not False:
            raise AuthenticationError("UAUT: cifratura richiesta ma non implementata")
        self.authenticated = True

    def _require_auth(self):
        if not self.authenticated:
            raise AuthenticationError("Autenticazione necessaria")

    def configuration(self) -> DeviceConfig:
        self._require_auth()
        raw = self.request("UCFG", "get-configuration", 3, addressbooks="all")
        if type(raw.get("response-code")) is not int or raw["response-code"] != 200:
            raise ProtocolError("UCFG: lettura configurazione rifiutata")
        self.live_config = DeviceConfig.parse(raw)
        return self.live_config

    def info(self) -> dict:
        self._require_auth()
        raw = self.request("INFO", "server-info", 20)
        if type(raw.get("response-code")) is not int or raw["response-code"] != 200:
            raise ProtocolError("INFO: server-info rifiutato")
        return raw

    def _drain(self, channel_id: int, seconds: float, maximum: int = 32) -> list[dict]:
        observations = []
        deadline = min(self.deadline, time.monotonic() + seconds)
        for _ in range(maximum):
            try:
                frame = self._read(deadline)
            except SessionTimeout:
                break
            self._channel_closed(frame)
            if frame.channel_id == channel_id:
                event = decode_ctpp(frame.body)
                observations.append(event or {"bytes": len(frame.body), "interpretation": "unknown_body"})
            elif not self._maybe_ack_channel_open(frame):
                self._observe(frame)
        return observations

    def open_target(self, config: DeviceConfig, target: Target) -> dict:
        self._require_auth()
        if config is not self.live_config or target not in config.targets:
            raise ProtocolError("L'apertura richiede una rubrica letta nella sessione corrente")
        if self.control_attempted:
            raise ProtocolError("Un solo comando per sessione; replay non consentito")
        if target.secure:
            raise ProtocolError("Target secure-mode: sequenza non ancora implementata")
        payloads = door_sequence(config.apartment, target.address, target.relay, target.kind, target.module)
        channel_id = self.channel("CTPP", f"{config.apartment}{config.subaddress}")
        self._send(Frame(channel_id, ctpp_registration(config.apartment, config.subaddress, self.profile.wire_profile)))
        observations = self._drain(channel_id, 2.0)
        pre_command_count = len(observations)
        self.remaining()
        result = {"target": target.public(), "status": "sent_unconfirmed", "physical_state": "unknown",
                  "wire_profile": self.profile.wire_profile, "experimental_on_msvf": True,
                  "frames_sent": 0, "observations": observations}
        # Mark BEFORE sendall: an exception can mean a partially delivered command.
        self.control_attempted = True
        try:
            for body in payloads:
                self._send(Frame(channel_id, body))
                result["frames_sent"] += 1
                if body[:2] == b"\xc0\x18":
                    observations.extend(self._drain(channel_id, 2.0))
            observations.extend(self._drain(channel_id, 1.0))
        except (OSError, ProtocolError) as exc:
            result["status"] = "delivery_uncertain"
            result["error_type"] = type(exc).__name__
        # Device-level confirmation: a VIP 'door opened' event (0x1860/0x0003)
        # naming the target. This is the event the native app treats as the
        # open; it reports device state, not a proven causal transaction. It is NOT
        # proof the physical latch moved (wiring/power), so physical_state stays
        # a separate, honest field rather than claiming 'physically open'.
        confirmations = open_confirmations(observations[pre_command_count:], target.address)
        result["pre_command_events"] = pre_command_count
        if confirmations:
            result["status"] = "opened_confirmed"
            result["physical_state"] = "device_reported_open"
            result["confirmation"] = {"source": "vip_door_opened_event",
                                      "prefix": "0x1860", "action": "0x0003",
                                      "correlation": "target_and_receive_window_not_transaction_id",
                                      "events": len(confirmations)}
        return result

    def close(self):
        sock, self.sock = self.sock, None
        if sock is None:
            return
        try:
            # Bounded best effort. Cleanup does not consume another operation timeout.
            cleanup_end = time.monotonic() + 0.5
            for channel_id in reversed(list(self.channels.values())):
                remaining = cleanup_end - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    sock.settimeout(remaining)
                    sock.sendall(close_channel(channel_id).encode())
                except OSError:
                    break
        finally:
            sock.close()
            self.channels.clear()
            self.authenticated = False
            self.live_config = None
