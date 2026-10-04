"""Lock the auto-ACK of a device-initiated channel open, using captured bytes."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pycomeca.client import IconaClient
from pycomeca.profile import Profile
from pycomeca.protocol import Frame


class _FakeSock:
    def __init__(self):
        self.sent = []
    def settimeout(self, _):
        pass
    def sendall(self, data):
        self.sent.append(data)


class TestDeviceOpenAck(unittest.TestCase):
    def test_echo_open_is_acked(self):
        client = IconaClient(Profile(host="192.168.1.50"))
        client.sock = _FakeSock()
        client.deadline = time.monotonic() + 30
        # Real device-initiated ECHO open captured live (id 0xaeb0 = 44720).
        echo_open = Frame(0, bytes.fromhex("cdab0100070000004543484fb0ae00"))
        self.assertTrue(client._maybe_ack_channel_open(echo_open))
        self.assertEqual(len(client.sock.sent), 1)
        wire = client.sock.sent[0]
        # ICONA header (magic, len 12, channel 0) + COMMAND seq2 type4 id pad
        self.assertEqual(wire[:8].hex(), "00060c00" + "00000000")
        self.assertEqual(wire[8:].hex(), "cdab020004000000b0ae0000")

    def test_our_response_is_not_acked(self):
        client = IconaClient(Profile(host="192.168.1.50"))
        client.sock = _FakeSock()
        client.deadline = time.monotonic() + 30
        # A normal 12-byte response to OUR open (seq=2) must not be treated as a
        # device open.
        our_resp = Frame(0, bytes.fromhex("cdab020004000000" + "6400" + "0000"))
        self.assertFalse(client._maybe_ack_channel_open(our_resp))
        self.assertEqual(client.sock.sent, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
