"""Attach Java hooks through frida-tools (Java bridge included with Frida 17).

Hook output can contain secrets: keep recordings private. Never starts or kills app.
"""
import argparse
import math
from pathlib import Path
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("--target", default="Comelit")
    parser.add_argument("--device", help="Frida device ID; default USB")
    parser.add_argument("--duration", type=float, default=30)
    args = parser.parse_args(argv)
    if not args.script.is_file():
        parser.error("Script inesistente")
    if not math.isfinite(args.duration) or not 0 < args.duration <= 3600:
        parser.error("Durata richiesta: 0 < secondi <= 3600")
    command = [sys.executable, "-m", "frida_tools.repl"]
    command += ["-D", args.device] if args.device else ["-U"]
    command += ["-n", args.target, "-l", str(args.script.resolve()), "-q",
                "-t", str(args.duration), "--exit-on-error", "--no-auto-reload"]
    try:
        return subprocess.run(command, check=False, timeout=args.duration + 30).returncode
    except subprocess.TimeoutExpired:
        print("Timeout del runner; nessun riavvio automatico.", file=sys.stderr)
        return 124
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
