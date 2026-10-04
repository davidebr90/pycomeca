import json
from pathlib import Path
import struct
import unittest

from pycomeca.profile import DeviceConfig, Profile, redact
from pycomeca.protocol import (Frame, FrameDecoder, ProtocolError, decode_ctpp, decode_rtp,
                              door_sequence, open_channel, open_confirmations)


class ProtocolTests(unittest.TestCase):
    def test_incremental_and_coalesced_frames(self):
        wire = Frame(4, b"a").encode() + Frame(5, b"bc").encode()
        decoder = FrameDecoder()
        for chunk in (wire[:2], wire[2:9], wire[9:]):
            decoder.feed(chunk)
        self.assertEqual(decoder.pop(), Frame(4, b"a"))
        self.assertEqual(decoder.pop(), Frame(5, b"bc"))
        self.assertIsNone(decoder.pop())

    def test_invalid_header_and_truncated_finish(self):
        decoder = FrameDecoder(); decoder.feed(b"bad-header")
        with self.assertRaises(ProtocolError): decoder.pop()
        decoder = FrameDecoder(); decoder.feed(Frame(1, b"x").encode()[:-1])
        with self.assertRaises(ProtocolError): decoder.finish()

    def test_channel_has_full_uint16_values(self):
        body = open_channel("UAUT", 117).body
        self.assertEqual(body[:8], bytes.fromhex("cdab010007000000"))
        self.assertEqual(body[8:12], b"UAUT")

    def test_door_and_actuator_validation(self):
        self.assertEqual(len(door_sequence("SB000042", "SB100007", 1, "door")), 5)
        self.assertEqual(len(door_sequence("SB000042", "SBIO0255", 1, "actuator", 255)), 3)
        with self.assertRaises(ProtocolError): door_sequence("SB000042", "SBIO0255", 2, "actuator", 255)

    def test_rtp_extension_padding(self):
        # V=2, P=1, X=1, one CSRC, PT=8, extension length=1 word, 2-byte padding.
        packet = bytes.fromhex("b18800010000000200000003") + b"csrc" + bytes.fromhex("00010001") + b"abcd" + b"xy" + bytes([0, 2])
        parsed = decode_rtp(packet)
        self.assertEqual(parsed["payload_type"], 8)
        self.assertEqual(parsed["payload_bytes"], 2)
        with self.assertRaises(ProtocolError): decode_rtp(packet[:-1] + b"\x09")

    def test_config_parser_rejects_ambiguous_target(self):
        raw = {"vip": {"enabled": True, "apt-address": "SB000042", "apt-subaddress": 1,
                        "user-parameters": {"opendoor-address-book": [], "actuator-address-book": []}}}
        config = DeviceConfig.parse(raw)
        with self.assertRaises(ProtocolError): config.select("missing")

    def test_ctpp_door_opened_event_is_classified_with_target(self):
        # 0x1860 prefix, 0x0003 action (BE), FFFFFFFF separator, then the target.
        body = (struct.pack("<HI", 0x1860, 715107312) + struct.pack(">H", 0x0003)
                + b"\xff\xff\xff\xff" + b"SB100007\x00")
        event = decode_ctpp(body)
        self.assertEqual(event["interpretation"], "door_opened_event")
        self.assertEqual(event["action"], "0x0003")
        self.assertEqual(event["addresses"], ["SB100007"])

    def test_open_confirmations_matches_only_target_door_opened(self):
        observations = [
            {"interpretation": "door_opened_event", "addresses": ["SB100007", "SB0000421"]},
            {"interpretation": "registration_renewal", "addresses": ["SB000042", "SB0000421"]},
            {"interpretation": "unknown_body", "bytes": 20},  # no addresses key
        ]
        self.assertEqual(len(open_confirmations(observations, "SB100007")), 1)
        self.assertEqual(open_confirmations(observations, "SBIO0255"), [])
        self.assertEqual(open_confirmations(observations, "SB000042"), [])

    def test_redaction_is_recursive_and_non_mutating(self):
        source = {"token": "0123456789abcdef0123456789abcdef", "nested": ["secret"]}
        clean = redact(source)
        self.assertEqual(source["token"], "0123456789abcdef0123456789abcdef")
        self.assertEqual(clean["token"], "<redacted>")


if __name__ == "__main__": unittest.main()
