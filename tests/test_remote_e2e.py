"""End-to-end offline proof: the real ICONA client over the remote transport.

A fake ICONA device runs behind a mirrored ICE+PseudoTCP endpoint on localhost.
The real IconaClient (via the remote PseudoTcpSocket) authenticates, reads the
configuration and opens a door, getting an opened_confirmed. This exercises the
whole remote stack driving the unchanged client, without any network or hardware.
"""
import os
import socket
import struct
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pycomeca.profile import Profile
from pycomeca.protocol import COMMAND, Frame, FrameDecoder, json_frame
from pycomeca.client import IconaClient
from pycomeca.remote.ice import IceAgent, IceStream
from pycomeca.remote.sdp import Candidate
from pycomeca.remote.pseudotcp import PseudoTcp
from pycomeca.remote.session import PseudoTcpSocket

TARGET_ADDR = "SB100007"
APT = "SB000042"

UCFG = {
    "message": "get-configuration", "message-type": "response", "message-id": 3,
    "response-code": 200,
    "vip": {"enabled": True, "apt-address": APT, "apt-subaddress": 1,
            "user-parameters": {"opendoor-address-book": [
                {"id": 0, "name": "Portone principale", "apt-address": TARGET_ADDR,
                 "output-index": 1}]}},
}


class FakeDevice(threading.Thread):
    """Minimal device side: replies to channel opens, UAUT/UCFG, and emits a
    door-opened event when it sees the CTPP open sequence."""
    def __init__(self, stream, pt):
        super().__init__(daemon=True)
        self._stream = stream
        self._pt = pt
        self.decoder = FrameDecoder()
        self.names: dict[int, str] = {}
        self.next_id = 100
        self.stop = False
        self.opened = False
        self.ctpp_channel = None

    def _now(self):
        return int(time.monotonic() * 1000) & 0xFFFFFFFF

    def _reply(self, frame: Frame):
        self._pt.write(frame.encode())
        self._pt.clock(self._now())

    def run(self):
        while not self.stop:
            data = self._stream.recv(0.05)
            if data:
                self._pt.handle_input(data)
            self._pt.clock(self._now())
            chunk = self._pt.read()
            if chunk:
                self.decoder.feed(chunk)
            while True:
                frame = self.decoder.pop()
                if frame is None:
                    break
                self._handle(frame)

    def _handle(self, frame: Frame):
        if frame.channel_id == 0 and frame.body[:2] == struct.pack("<H", COMMAND):
            name = frame.body[8:12].decode("ascii", "replace")
            server_id = self.next_id
            self.next_id += 1
            self.names[server_id] = name
            if name == "CTPP":
                self.ctpp_channel = server_id
            self._reply(Frame(0, struct.pack("<HHIHH", COMMAND, 2, 4, server_id, 0)))
            return
        name = self.names.get(frame.channel_id)
        if name in ("UAUT", "UCFG", "INFO"):
            import json
            req = json.loads(frame.body.decode("utf-8"))
            if req.get("message") == "access":
                self._reply(json_frame(frame.channel_id, {
                    "message": "access", "message-type": "response",
                    "message-id": 2, "response-code": 200, "encryption-required": False}))
            elif req.get("message") == "get-configuration":
                self._reply(json_frame(frame.channel_id, UCFG))
            elif req.get("message") == "server-info":
                self._reply(json_frame(frame.channel_id, {
                    "message": "server-info", "message-type": "response",
                    "message-id": 20, "response-code": 200, "model": "MSVF"}))
        elif frame.channel_id == self.ctpp_channel and not self.opened:
            # Emit the door-opened event on the OPEN REQUEST (0x1800), not on the
            # CTPP registration/init (also 0xc018) which precedes the command.
            if frame.body[:2] == b"\x00\x18":
                self.opened = True
                event = (struct.pack("<H", 0x1860) + struct.pack("<I", 1)
                         + struct.pack(">H", 0x0003) + b"\xff\xff\xff\xff"
                         + TARGET_ADDR.encode() + b"\x00")
                self._reply(Frame(frame.channel_id, event))


def _handshake_pair():
    sa = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sa.bind(("127.0.0.1", 0))
    sb = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sb.bind(("127.0.0.1", 0))
    addr_a, addr_b = sa.getsockname(), sb.getsockname()
    # client = controlled (a); device = controlling + aggressive (b)
    client_agent = IceAgent(sa, "ufC", "pwC_padded_12345678", "ufD", "pwD_padded_12345678",
                            [Candidate("H", 1, "UDP", 2130706431, addr_b[0], addr_b[1], "host")], controlling=False)
    device_agent = IceAgent(sb, "ufD", "pwD_padded_12345678", "ufC", "pwC_padded_12345678",
                            [Candidate("H", 1, "UDP", 2130706431, addr_a[0], addr_a[1], "host")], controlling=True)
    res = {}

    def run(name, agent):
        try:
            res[name] = agent.connect(timeout=8.0)
        except Exception as exc:  # noqa: BLE001
            res[name] = exc
    t1 = threading.Thread(target=run, args=("c", client_agent))
    t2 = threading.Thread(target=run, args=("d", device_agent))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert res["c"] == addr_b and res["d"] == addr_a, res
    return client_agent, device_agent


class TestRemoteEndToEnd(unittest.TestCase):
    def test_open_door_over_remote_transport(self):
        client_agent, device_agent = _handshake_pair()
        client_stream, device_stream = IceStream(client_agent), IceStream(device_agent)

        # PseudoTCP both ends
        client_pt = PseudoTcp(client_stream.send, now_ms=0)
        device_pt = PseudoTcp(device_stream.send, now_ms=0)
        client_pt.connect(); device_pt.connect()

        device = FakeDevice(device_stream, device_pt)

        # Drive the client PseudoTcp handshake in a thread while device pumps.
        client_sock = PseudoTcpSocket(client_stream, client_pt)
        device.start()
        end = time.monotonic() + 8.0
        while not client_pt.is_connected and time.monotonic() < end:
            d = client_stream.recv(0.05)
            if d:
                client_pt.handle_input(d)
            client_pt.clock(int(time.monotonic() * 1000) & 0xFFFFFFFF)
        self.assertTrue(client_pt.is_connected, "handshake client non completato")

        # Build a RemoteIconaClient but inject the already-connected socket.
        profile = Profile(host="192.168.1.50")
        client = IconaClient(profile)
        client.sock = client_sock
        client.deadline = time.monotonic() + 20
        client.decoder = FrameDecoder()

        token = "0123456789abcdef0123456789abcdef"  # 32-hex shape; fake device ignores value
        client.authenticate(token)
        self.assertTrue(client.authenticated)
        config = client.configuration()
        target = config.select("door:0")
        result = client.open_target(config, target)
        device.stop = True
        device.join(timeout=2.0)
        client_sock.close()
        device_stream.close()

        self.assertEqual(result["status"], "opened_confirmed", result)
        self.assertEqual(result["physical_state"], "device_reported_open")


if __name__ == "__main__":
    unittest.main(verbosity=2)
