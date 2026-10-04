"""STUN codec self-tests and a real-UDP ICE loopback carrying PseudoTCP."""
import os
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pycomeca.remote import stun
from pycomeca.remote.ice import IceAgent, IceStream
from pycomeca.remote.sdp import Candidate
from pycomeca.remote.pseudotcp import PseudoTcp


class TestStun(unittest.TestCase):
    def test_integrity_roundtrip(self):
        key = stun.short_term_key("9b2e47c1d05f8a36e1c7b204")
        msg = stun.Message(stun.BINDING_REQUEST, stun.new_transaction_id(), [
            (stun.ATTR_USERNAME, b"peer:me"),
            (stun.ATTR_PRIORITY, (0x6EFFFFFF).to_bytes(4, "big")),
        ])
        raw = msg.encode(integrity_key=key, fingerprint=True)
        back = stun.Message.decode(raw)
        self.assertEqual(back.message_type, stun.BINDING_REQUEST)
        self.assertTrue(back.verify_integrity(key, raw))
        self.assertFalse(back.verify_integrity(stun.short_term_key("wrong"), raw))

    def test_fingerprint_present(self):
        msg = stun.Message(stun.BINDING_SUCCESS, stun.new_transaction_id())
        raw = msg.encode(integrity_key=None, fingerprint=True)
        back = stun.Message.decode(raw)
        self.assertTrue(back.has(stun.ATTR_FINGERPRINT))

    def test_xor_mapped_address(self):
        txid = stun.new_transaction_id()
        enc = stun.encode_xor_mapped_address("192.168.1.50", 58293, txid)
        ip, port = stun.xor_mapped_address(enc, txid)
        self.assertEqual((ip, port), ("192.168.1.50", 58293))


def _agent(sock, local, remote, remote_addr, controlling):
    return IceAgent(sock, local[0], local[1], remote[0], remote[1],
                    [Candidate("H", 1, "UDP", 2130706431, remote_addr[0], remote_addr[1], "host")],
                    controlling=controlling)


class TestIceLoopback(unittest.TestCase):
    def test_nominate_and_carry_pseudotcp(self):
        sa = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sa.bind(("127.0.0.1", 0))
        sb = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sb.bind(("127.0.0.1", 0))
        addr_a, addr_b = sa.getsockname(), sb.getsockname()
        # A controlling+aggressive, B controlled (like the device vs our client,
        # but mirrored so we exercise both roles).
        a = _agent(sa, ("ufragA", "pwdAAAAAAAAAAAAAAAAAAAAA"), ("ufragB", "pwdBBBBBBBBBBBBBBBBBBBBB"), addr_b, True)
        b = _agent(sb, ("ufragB", "pwdBBBBBBBBBBBBBBBBBBBBB"), ("ufragA", "pwdAAAAAAAAAAAAAAAAAAAAA"), addr_a, False)
        results = {}

        def run(name, agent):
            try:
                results[name] = agent.connect(timeout=8.0)
            except Exception as exc:  # noqa: BLE001
                results[name] = exc

        ta = threading.Thread(target=run, args=("a", a)); tb = threading.Thread(target=run, args=("b", b))
        ta.start(); tb.start(); ta.join(); tb.join()
        self.assertEqual(results["a"], addr_b, f"A selected {results['a']}")
        self.assertEqual(results["b"], addr_a, f"B selected {results['b']}")

        # Now push PseudoTCP over the two IceStreams and exchange a payload.
        stream_a, stream_b = IceStream(a), IceStream(b)
        pa = PseudoTcp(stream_a.send, now_ms=0)
        pb = PseudoTcp(stream_b.send, now_ms=0)
        pa.connect(); pb.connect()
        payload_a = b"ICONA-open-frame" * 8
        payload_b = b"door-opened-event" * 6
        got_a, got_b = bytearray(), bytearray()
        written = False
        start = time.monotonic()
        now = 0
        while time.monotonic() - start < 8.0:
            now += 10
            for stream, pt in ((stream_a, pa), (stream_b, pb)):
                data = stream.recv(0.01)
                if data:
                    pt.handle_input(data)
            pa.clock(now); pb.clock(now)
            if pa.is_connected and pb.is_connected and not written:
                pa.write(payload_a); pb.write(payload_b); written = True
            got_a.extend(pa.read()); got_b.extend(pb.read())
            if written and bytes(got_a) == payload_b and bytes(got_b) == payload_a:
                break
        stream_a.close(); stream_b.close()
        self.assertEqual(bytes(got_b), payload_a, "A->B su ICE corrotto")
        self.assertEqual(bytes(got_a), payload_b, "B->A su ICE corrotto")


if __name__ == "__main__":
    unittest.main(verbosity=2)
