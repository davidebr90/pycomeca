"""Operational runner for the remote (cloud P2P) path.

    python -m pycomeca.remote --list
    python -m pycomeca.remote --open "Portone principale"

Credentials come from the environment, never the command line:
    COMELIT_USER / COMELIT_PASS   OAuth2 account login
    COMELIT_DEVICE_UUID           deviceUuid (from jfs/get; identifies the device)
    COMELIT_TOKEN                 viper user-token (32 hex); else read from the DB

Nothing opens the door unless --open is given. The door command physically
opens the entrance, so it is never the default.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys

from ..profile import Profile, redact
from .session import RemoteIconaClient
from . import p2p


def _ice_credentials() -> tuple[str, str]:
    # Comelit style: 8-hex ufrag, 24-hex pwd. Regenerated every session.
    return secrets.token_hex(4), secrets.token_hex(12)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pycomeca.remote",
                                     description="Apertura/consultazione via cloud P2P (viper_p2p_v2)")
    parser.add_argument("--list", action="store_true", help="autentica e mostra la rubrica, senza aprire")
    parser.add_argument("--open", metavar="TARGET", help="apri il target indicato (chiave door:N o nome)")
    parser.add_argument("--relay-only", action="store_true",
                        help="forza il percorso esterno: solo candidato relay del device, niente LAN")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if not args.list and not args.open:
        parser.error("specifica --list oppure --open TARGET")

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    user = os.environ.get("COMELIT_USER")
    password = os.environ.get("COMELIT_PASS")
    device_uuid = os.environ.get("COMELIT_DEVICE_UUID")
    if not user or not password:
        print("Imposta COMELIT_USER e COMELIT_PASS.", file=sys.stderr)
        return 2
    if not device_uuid:
        print("Imposta COMELIT_DEVICE_UUID (deviceUuid del citofono).", file=sys.stderr)
        return 2

    profile = Profile(host="192.0.2.1")   # host nominale: in remoto non viene contattato
    viper_token = profile.token()
    ufrag, pwd = _ice_credentials()

    try:
        oauth_token = p2p.oauth_login(user, password)
    except p2p.SignalingError as exc:
        print(f"Login OAuth fallito: {exc}", file=sys.stderr)
        return 1

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
