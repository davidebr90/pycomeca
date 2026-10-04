"""Regression tests: mocked controls, no installation contacted."""
import http.client
import json
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import pycomeca_bridge as bridge
from pycomeca.cli import main
from pycomeca.client import AuthenticationError, IconaClient
from pycomeca.profile import DeviceConfig, Profile
from pycomeca.protocol import ProtocolError


def config():
    return DeviceConfig.parse({"vip": {"apt-address": "SB000042", "apt-subaddress": 1,
        "user-parameters": {"opendoor-address-book": [{"id": 0, "name": "Test",
            "apt-address": "SB100007", "output-index": 1}]}}})


class ClientSafetyTests(unittest.TestCase):
    def test_encryption_required_rejected(self):
        client = IconaClient(Profile("127.0.0.1"))
        with patch.object(client, "request", return_value={"response-code": 200, "encryption-required": True}):
            with self.assertRaises(AuthenticationError):
                client.authenticate("a" * 32)
        self.assertFalse(client.authenticated)

    def test_non_object_config_rejected(self):
        for value in (None, [], "secret"):
            with self.assertRaises(ProtocolError):
                DeviceConfig.parse(value)

    def run_open(self, drains, send_error=False):
        client = IconaClient(Profile("127.0.0.1"))
        client.authenticated = True
        client.live_config = cfg = config()
        client.deadline = time.monotonic() + 30
        with patch.object(client, "channel", return_value=1), patch.object(client, "_drain", side_effect=drains), patch.object(client, "_send", side_effect=[None, OSError()] if send_error else None):
            result = client.open_target(cfg, cfg.targets[0])
            with self.assertRaises(ProtocolError):
                client.open_target(cfg, cfg.targets[0])
        return result

    def test_pre_command_event_is_not_confirmation(self):
        event = {"interpretation": "door_opened_event", "addresses": ["SB100007"]}
        self.assertEqual(self.run_open([[event], [], []])["status"], "sent_unconfirmed")

    def test_post_command_target_event_is_confirmation(self):
        event = {"interpretation": "door_opened_event", "addresses": ["SB100007"]}
        result = self.run_open([[], [event], []])
        self.assertEqual(result["status"], "opened_confirmed")
        self.assertEqual(result["physical_state"], "device_reported_open")

    def test_partial_send_is_uncertain(self):
        self.assertEqual(self.run_open([[]], True)["status"], "delivery_uncertain")

    def test_cli_offline_control_requires_dryrun(self):
        with self.assertRaises(SystemExit):
            main(["--from-config", "nonexistent.json", "--open", "door:0"])

    def test_cli_conflicting_offline_action_rejected(self):
        with self.assertRaises(SystemExit):
            main(["--from-config", "nonexistent.json", "--info"])


class BridgeSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), bridge.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, body=b"", extra=None, key="test-key"):
        headers = {"Authorization": "Bearer " + key}
        headers.update(extra or {})
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        try:
            connection.request("POST", "/open", body, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_invalid_requests_never_actuate(self):
        with patch.object(bridge, "BRIDGE_KEY", "test-key"), patch.object(bridge, "_open") as control:
            for body in (b"[]", b"null", b'{"target":1}', b'{"target":""}', b'{"unexpected":true}', b"{"):
                self.assertEqual(self.request(body)[0], 400)
            for length in ("-1", "5000"):
                self.assertEqual(self.request(extra={"Content-Length": length})[0], 413)
            self.assertEqual(self.request(extra={"Content-Length": "abc"})[0], 400)
            self.assertEqual(self.request(extra={"Transfer-Encoding": "chunked"})[0], 400)
            self.assertEqual(self.request(b'{"target":"another"}')[0], 403)
            self.assertEqual(self.request(key="wrong")[0], 401)
            control.assert_not_called()

    def test_empty_body_uses_only_fixed_target(self):
        with patch.object(bridge, "BRIDGE_KEY", "test-key"), patch.object(bridge, "_open", return_value={"status": "sent_unconfirmed"}) as control:
            self.assertEqual(self.request()[0], 200)
            control.assert_called_once_with(bridge.BRIDGE_TARGET)


if __name__ == "__main__":
    unittest.main()
