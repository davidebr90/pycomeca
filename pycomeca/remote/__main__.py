"""Operational runner for the remote (cloud P2P) path.

    python -m pycomeca.remote --list
    python -m pycomeca.remote --open "Portone principale"

Credentials come from the environment or from a config file (handy on a phone,
so they are not typed into a shortcut every time):
    COMELIT_USER / COMELIT_PASS   OAuth2 account login
    COMELIT_DEVICE_UUID           deviceUuid (from jfs/get; identifies the device)
    COMELIT_TOKEN                 viper user-token (32 hex); else read from the DB

The config file is a plain list of KEY=VALUE lines. It is looked up at --config,
then $PYCOMECA_CONFIG, then ~/.pycomeca.conf, then ./pycomeca.conf. Environment
variables take precedence over the file. See pycomeca.conf.example.

Nothing opens the door unless --open is given. The door command physically
opens the entrance, so it is never the default.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import secrets
import sys

from ..profile import Profile, redact
from .session import RemoteIconaClient
from . import p2p

_CONFIG_KEYS = {"COMELIT_USER", "COMELIT_PASS", "COMELIT_DEVICE_UUID",
                "COMELIT_TOKEN", "PYCOMECA_RELAY_ONLY"}


def _ice_credentials() -> tuple[str, str]:
    # Comelit style: 8-hex ufrag, 24-hex pwd. Regenerated every session.
    return secrets.token_hex(4), secrets.token_hex(12)


def load_config(explicit: str | None) -> str | None:
    """Fill missing env vars from a KEY=VALUE file. Returns the file used."""
    candidates = [explicit, os.environ.get("PYCOMECA_CONFIG"),
                  str(Path.home() / ".pycomeca.conf"), "pycomeca.conf"]
    for cand in candidates:
        if not cand:
            continue
        path = Path(cand).expanduser()
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in _CONFIG_KEYS and not os.environ.get(key):
                os.environ[key] = value
        return str(path)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pycomeca.remote",
                                     description="Apertura/consultazione via cloud P2P (viper_p2p_v2)")
    parser.add_argument("--list", action="store_true", help="autentica e mostra la rubrica, senza aprire")
    parser.add_argument("--open", metavar="TARGET", help="apri il target indicato (chiave door:N o nome)")
    parser.add_argument("--devices", action="store_true",
                        help="elenca i citofoni dell'account e il loro deviceUuid (serve solo USER/PASS)")
    parser.add_argument("--relay-only", action="store_true",
                        help="forza il percorso esterno: solo candidato relay del device, niente LAN")
    parser.add_argument("--config", metavar="FILE", help="file KEY=VALUE con le credenziali")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if not args.list and not args.open and not args.devices:
        parser.error("specifica --list, --open TARGET oppure --devices")

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    load_config(args.config)
    if not args.relay_only and os.environ.get("PYCOMECA_RELAY_ONLY", "").strip().lower() in ("1", "true", "yes"):
        args.relay_only = True

    user = os.environ.get("COMELIT_USER")
    password = os.environ.get("COMELIT_PASS")
    device_uuid = os.environ.get("COMELIT_DEVICE_UUID")
    if not user or not password:
        print("Imposta COMELIT_USER e COMELIT_PASS.", file=sys.stderr)
        return 2

    try:
        oauth_token = p2p.oauth_login(user, password)
    except p2p.SignalingError as exc:
        print(f"Login OAuth fallito: {exc}", file=sys.stderr)
        return 1

    # --devices needs only the login: discover the deviceUuid to put in the config.
    if args.devices:
        try:
            devices = p2p.jfs_list(oauth_token)
        except p2p.SignalingError as exc:
            print(f"Elenco dispositivi fallito: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(devices, indent=2, ensure_ascii=False))
        return 0

    if not device_uuid:
        print("Imposta COMELIT_DEVICE_UUID (deviceUuid del citofono). "
              "Puoi scoprirlo con: python -m pycomeca.remote --devices", file=sys.stderr)
        return 2

    profile = Profile(host="192.0.2.1")   # host nominale: in remoto non viene contattato
    viper_token = profile.token()
    ufrag, pwd = _ice_credentials()

    client = RemoteIconaClient(profile, oauth_token, device_uuid, viper_token, ufrag, pwd,
                               relay_only=args.relay_only)
    try:
        with client:
            client.authenticate(viper_token)
            config = client.configuration()
            if args.open:
                target = config.select(args.open)
                result = client.open_target(config, target)
                print(json.dumps(redact(result), indent=2, ensure_ascii=False))
                return 0 if result.get("status") in ("opened_confirmed", "sent_unconfirmed") else 1
            print(json.dumps(redact(config.public()), indent=2, ensure_ascii=False))
            return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Operazione remota fallita: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
