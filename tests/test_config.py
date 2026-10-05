"""The credentials config loader: file fills gaps, env wins, keys are filtered."""
import os
import tempfile
import unittest
from pathlib import Path

from pycomeca.remote.__main__ import load_config


class ConfigLoaderTests(unittest.TestCase):
    def setUp(self):
        for k in ("COMELIT_USER", "COMELIT_PASS", "COMELIT_DEVICE_UUID",
                  "COMELIT_TOKEN", "PYCOMECA_RELAY_ONLY", "PYCOMECA_CONFIG"):
            os.environ.pop(k, None)

    def _write(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / "c.conf"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_fills_missing_and_filters_unknown_keys(self):
        path = self._write(
            "# commento\nCOMELIT_USER=a@b.c\nCOMELIT_TOKEN='deadbeef'\n"
            "EVIL=should-not-load\n\nPYCOMECA_RELAY_ONLY=1\n")
        used = load_config(path)
        self.assertEqual(used, path)
        self.assertEqual(os.environ["COMELIT_USER"], "a@b.c")
        self.assertEqual(os.environ["COMELIT_TOKEN"], "deadbeef")  # quotes stripped
        self.assertEqual(os.environ["PYCOMECA_RELAY_ONLY"], "1")
        self.assertNotIn("EVIL", os.environ)

    def test_env_takes_precedence(self):
        os.environ["COMELIT_USER"] = "env@wins.com"
        path = self._write("COMELIT_USER=file@loses.com\n")
        load_config(path)
        self.assertEqual(os.environ["COMELIT_USER"], "env@wins.com")

    def test_missing_file_is_harmless(self):
        self.assertIsNone(load_config("/no/such/file.conf"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
