"""Offline tests: SDP parse/build vs real capture; PseudoTCP wire + loopback."""
import os
import random
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pycomeca.remote import sdp
from pycomeca.remote.pseudotcp import (PseudoTcp, HEADER, HEADER_SIZE, CONNECT_PAYLOAD,
                                       FLAG_CTL, STATE_ESTABLISHED)

# Real device answer SDP from docs/REMOTE_P2P.md (decoded), IPs as captured.
ANSWER = (
    "v=0\r\n"
    "o=- 1200345678 1200345678 IN IP4 0.0.0.0\r\n"
    "s=ice\r\nt=0 0\r\na=nego-wait:0\r\n"
    "a=comelit-legacy-session:TCP\r\na=comelit-session-id:MUX\r\n"
    "m=audio 51534 RTP/SAVPF 8\r\nc=IN IP4 198.51.100.200\r\na=sendrecv\r\n"
    "a=candidate:Sc0a80559 1 UDP 1694498815 203.0.113.25 21429 typ srflx raddr 192.168.1.50 rport 58293\r\n"
    "a=candidate:Hc0a80559 1 UDP 2130706431 192.168.1.50 58293 typ host\r\n"
    "a=candidate:Rc0f8b7d5 1 UDP 16777215 198.51.100.200 51534 typ relay raddr 203.0.113.25 rport 19742\r\n"
    "a=ice-role:o\r\na=ice-ufrag:5d1c9a70\r\na=ice-pwd:9b2e47c1d05f8a36e1c7b204\r\n"
)


class TestSdp(unittest.TestCase):
    def test_parse_answer(self):
        s = sdp.SessionDescription.parse(ANSWER)
        self.assertEqual(s.ice_ufrag, "5d1c9a70")
        self.assertEqual(s.ice_pwd, "9b2e47c1d05f8a36e1c7b204")
        self.assertEqual(s.ice_role, "o")
        self.assertEqual(len(s.candidates), 3)
        relay = [c for c in s.candidates if c.typ == "relay"][0]
        self.assertEqual(relay.ip, "198.51.100.200")
        self.assertEqual(relay.port, 51534)
        self.assertEqual(relay.raddr, "203.0.113.25")
        host = [c for c in s.candidates if c.typ == "host"][0]
        self.assertEqual((host.ip, host.port), ("192.168.1.50", 58293))

    def test_build_offer_roundtrip(self):
        cands = [sdp.Candidate("Ha000210", 1, "UDP", 2130706431, "10.0.2.16", 46737, "host")]
        offer = sdp.build_offer(700123456, "c41f08e2", "3fa90d5b7c2e61840bd9a7e5",
                                cands, "198.51.100.77", 62559)
        self.assertIn("a=comelit-legacy-session:TCP", offer)
        self.assertIn("a=comelit-session-id:MUX", offer)
        self.assertIn("a=comelit-nego-aggressive:true", offer)
        self.assertIn("a=ice-role:a", offer)
        self.assertTrue(offer.endswith("\r\n"))
        back = sdp.SessionDescription.parse(offer)
        self.assertEqual(back.ice_ufrag, "c41f08e2")
        self.assertEqual(back.candidates[0].port, 46737)

    def test_reject_bad_credentials(self):
        with self.assertRaises(sdp.SdpError):
            sdp.build_offer(1, "x", "short", [], "0.0.0.0", 9)


class TestPseudoTcpWire(unittest.TestCase):
    def test_connect_header_matches_capture(self):
        out = []
        p = PseudoTcp(out.append, now_ms=0x1c25b3)
        p.connect()
        self.assertEqual(len(out), 1)
        pkt = out[0]
        conv, seq, ack, b12, flags, wnd, tsval, tsecr = HEADER.unpack_from(pkt, 0)
        self.assertEqual((conv, seq, ack, b12, flags, wnd), (0, 0, 0, 0, FLAG_CTL, 61440))
        self.assertEqual(pkt[HEADER_SIZE:], CONNECT_PAYLOAD)
        # First 16 header bytes must equal the captured connect segment prefix.
        self.assertEqual(pkt[:16].hex(), "0000000000000000000000000002f000")

    def test_control_consumes_seven_seq(self):
        out = []
        p = PseudoTcp(out.append, now_ms=1000)
        p.connect()
        self.assertEqual(p.snd_nxt, 7)   # 7-byte connect occupies seq 0..6


class _Link:
    """In-memory lossy, reordering datagram link between two engines."""
    def __init__(self, drop=0.0, seed=0):
        self.rng = random.Random(seed)
        self.drop = drop
        self.a = None
        self.b = None
        self.qab = []
        self.qba = []

    def send_from_a(self, pkt):
        if self.rng.random() >= self.drop:
            self.qab.append(pkt)

    def send_from_b(self, pkt):
        if self.rng.random() >= self.drop:
            self.qba.append(pkt)

    def pump(self):
        moved = False
        for pkt in self.qab:
            self.b.handle_input(pkt); moved = True
        self.qab = []
        for pkt in self.qba:
            self.a.handle_input(pkt); moved = True
        self.qba = []
        return moved


class TestPseudoTcpLoopback(unittest.TestCase):
    def _run(self, drop, seed, payload_a, payload_b):
        link = _Link(drop=drop, seed=seed)
        a = PseudoTcp(link.send_from_a, now_ms=0)
        b = PseudoTcp(link.send_from_b, now_ms=0)
        link.a, link.b = a, b
        a.connect()
        b.connect()
        now = 0
        got_a = bytearray()
        got_b = bytearray()
        a_written = b_written = False
        for step in range(4000):
            now += 10
            link.pump()
            if a.is_connected and b.is_connected and not a_written:
                a.write(payload_a); b.write(payload_b)
                a_written = b_written = True
            a.clock(now); b.clock(now)
            got_a.extend(a.read()); got_b.extend(b.read())
            if a_written and bytes(got_a) == payload_b and bytes(got_b) == payload_a:
                break
        self.assertTrue(a.is_connected and b.is_connected, "handshake non completato")
        self.assertEqual(bytes(got_b), payload_a, "A->B stream corrotto")
        self.assertEqual(bytes(got_a), payload_b, "B->A stream corrotto")

    def test_clean_link(self):
        self._run(0.0, 1, b"OPEN-COMMAND-FRAME" * 20, b"ACK-AND-EVENTS" * 15)

    def test_lossy_link(self):
        # 30% loss: retransmission must still deliver the full stream in order.
        self._run(0.30, 7, bytes(range(256)) * 4, b"door opened event stream " * 30)

    def test_lossy_link_other_seed(self):
        self._run(0.25, 99, b"x" * 2000, b"y" * 1500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
