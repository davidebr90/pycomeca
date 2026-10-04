import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from relay import postino


class WorkerTests(unittest.TestCase):
    def job(self):
        now = int(time.time())
        return {"id": "abcdef0123456789", "command": "open", "created": now, "expires": now + 45}

    def test_durable_claim_prevents_duplicate_actuation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(postino, "JOURNAL", Path(directory) / "jobs.db"), patch.object(postino, "open_door", return_value={"status": "sent_unconfirmed"}) as control, patch.object(postino, "_call"):
            postino.handle(self.job())
            postino.handle(self.job())
            control.assert_called_once()

    def test_invalid_or_expired_jobs_never_actuate(self):
        with patch.object(postino, "open_door") as control:
            for changes in ({"command": "other"}, {"id": "../bad"}, {"expires": 1}, {"created": True}, {"expires": int(time.time()) + 1000}):
                job = self.job() | changes
                with self.assertRaises(ValueError):
                    postino.handle(job)
            control.assert_not_called()

    def test_failed_actuation_remains_claimed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(postino, "JOURNAL", Path(directory) / "jobs.db"), patch.object(postino, "open_door", side_effect=OSError) as control, patch.object(postino, "_call"):
            postino.handle(self.job())
            postino.handle(self.job())
            control.assert_called_once()


if __name__ == "__main__":
    unittest.main()
