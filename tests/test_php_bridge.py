"""PHP loopback integration. No worker started; no physical commands executed."""
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest


@unittest.skipUnless(shutil.which("php"), "PHP runtime not installed")
class PhpBridgeTests(unittest.TestCase):
    def test_queue_method_auth_correlation_and_corrupt_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = os.environ | {"CLIENT_KEY": "c" * 32, "AGENT_KEY": "a" * 32,
                                "BRIDGE_STATE_FILE": str(state)}
            process = subprocess.Popen([shutil.which("php"), "-S", f"127.0.0.1:{port}",
                str(Path(__file__).with_name("php_router.php"))], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            def call(action, method="GET", body=None, agent=False):
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                try:
                    connection.request(method, "/?a=" + action,
                        json.dumps(body).encode() if body is not None else b"",
                        {"X-Auth": ("a" if agent else "c") * 32, "Content-Type": "application/json"})
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()
            try:
                for _ in range(50):
                    try:
                        call("status")
                        break
                    except OSError:
                        time.sleep(0.05)
                else:
                    self.fail("PHP server did not start")
                self.assertEqual(call("open")[0], 405)
                self.assertEqual(call("open", "POST", agent=True)[0], 401)
                status, queued = call("open", "POST")
                self.assertEqual(status, 200)
                self.assertEqual(call("open", "POST")[0], 409)
                status, job = call("poll", agent=True)
                self.assertEqual(job["id"], queued["id"])
                self.assertEqual(job["expires"] - job["created"], 45)
                self.assertEqual(call("poll", agent=True)[1]["status"], "empty")
                self.assertEqual(call("result", "POST", {"id": "0" * 16, "outcome": "opened_confirmed"}, True)[0], 409)
                self.assertEqual(call("open", "POST")[0], 409)
                self.assertEqual(call("result", "POST", {"id": job["id"], "outcome": "sent_unconfirmed"}, True)[0], 200)
                self.assertEqual(call("status")[1]["last_result"]["id"], job["id"])
                state.write_text("broken", encoding="utf-8")
                self.assertEqual(call("status")[1]["status"], "state_corrupt")
                self.assertEqual(state.read_text(), "broken")
            finally:
                process.terminate()
                process.wait(timeout=5)
