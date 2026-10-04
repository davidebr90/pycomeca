#!/usr/bin/env python3
"""Ponte HTTP locale per aprire la porta Comelit da uno Shortcut iOS.

Gira sul dispositivo SEMPRE ACCESO in casa, sulla stessa LAN del citofono
(192.168.1.x). Espone due endpoint minimi:

    POST /open        -> apre il target configurato; risponde con l'esito
    GET  /health      -> "ok" senza toccare il citofono (per lo Shortcut/monitor)

Riusa il client gia' verificato (package `pycomeca`): connette a 64100,
autentica con il token, invia la sequenza CTPP e attende la conferma
`door_opened`. L'esito puo' essere `opened_confirmed`, `sent_unconfirmed` o
`delivery_uncertain` (in quest'ultimo caso il comando NON viene ripetuto).

SICUREZZA - leggere prima di usare:
- Va esposto SOLO dietro VPN (WireGuard/Tailscale). Mai port-forward diretto su
  internet: il token del citofono e' statico.
- Ogni richiesta deve portare l'header `Authorization: Bearer <BRIDGE_KEY>`.
  Se `BRIDGE_KEY` non e' impostata, il ponte si rifiuta di partire.
- Il token del citofono non viene mai incluso nelle risposte.

Configurazione (variabili d'ambiente):
    BRIDGE_KEY      (obbligatoria) segreto che lo Shortcut deve presentare
    BRIDGE_BIND     interfaccia di ascolto (default 127.0.0.1; VPN/reverse proxy espliciti)
    BRIDGE_PORT     porta HTTP del ponte (default 8090)
    BRIDGE_TARGET   target da aprire (default "Portone principale"; accetta anche
                    una chiave tipo "door:0")
    BRIDGE_PROFILE  percorso di installation.local.json (default: accanto al progetto)
    COMELIT_TOKEN   opzionale: token 32-hex; se assente si legge dal DB del profilo

Avvio:
    BRIDGE_KEY="una-chiave-lunga-e-casuale" python pycomeca_bridge.py

Esempio Shortcut iOS ("Ottieni contenuto di URL"):
    URL     http://<indirizzo-privato-di-casa-in-VPN>:8090/open
    Metodo  POST
    Header  Authorization: Bearer una-chiave-lunga-e-casuale
    (http va bene perche' il canale e' gia' cifrato dalla VPN; usa https solo se
     metti davanti un reverse proxy TLS come caddy/nginx.)
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pycomeca.client import IconaClient, AuthenticationError
from pycomeca.profile import Profile, ROOT, redact
from pycomeca.protocol import ProtocolError

LOG = logging.getLogger("pycomeca_bridge")

BRIDGE_KEY = os.environ.get("BRIDGE_KEY", "")
BRIDGE_BIND = os.environ.get("BRIDGE_BIND", "127.0.0.1")
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "8090"))
BRIDGE_TARGET = os.environ.get("BRIDGE_TARGET", "Portone principale")
BRIDGE_PROFILE = Path(os.environ.get("BRIDGE_PROFILE", ROOT / "installation.local.json"))

# Il citofono gestisce una negoziazione CTPP per volta: serializziamo le aperture.
_LOCK = threading.Lock()


def _open(target_key: str) -> dict:
    """Esegue una singola apertura riusando il client verificato."""
    profile = Profile.load(BRIDGE_PROFILE)
    token = profile.token()
    with IconaClient(profile) as client:
        client.authenticate(token)
        config = client.configuration()
        result = client.open_target(config, config.select(target_key))
        result["transport"] = {"frames_sent": client.frames_sent,
                               "frames_received": client.frames_received}
        return result


class Handler(BaseHTTPRequestHandler):
    server_version = "pycomeca-bridge/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def _reply(self, code: int, payload: dict):
        body = json.dumps(redact(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return bool(BRIDGE_KEY) and hmac.compare_digest(header[len(prefix):].encode(), BRIDGE_KEY.encode())

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self._reply(200, {"status": "ok", "service": "pycomeca-bridge"})
        else:
            self._reply(404, {"status": "not_found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/open":
            self._reply(404, {"status": "not_found"})
            return
        if not self._authorized():
            self._reply(401, {"status": "unauthorized"})
            return
        # target opzionale nel corpo JSON; altrimenti quello di default
        target_key = BRIDGE_TARGET
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) > 1:
            self._reply(400, {"status": "bad_request"})
            return
        try:
            length = int(lengths[0]) if lengths else 0
        except ValueError:
            self._reply(400, {"status": "bad_request"})
            return
        if not 0 <= length <= 4096:
            self._reply(413, {"status": "invalid_body_length"})
            return
        if 0 < length <= 4096:
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(data, dict) or set(data) - {"target"}:
                    raise ValueError("Invalid schema")
                if "target" in data:
                    if not isinstance(data["target"], str) or not data["target"].strip():
                        raise ValueError("Invalid target")
                    target_key = data["target"]
            except (ValueError, UnicodeError, OSError):
                self._reply(400, {"status": "bad_request"})
                return
        if target_key != BRIDGE_TARGET:
            self._reply(403, {"status": "target_not_allowed"})
            return
        if not _LOCK.acquire(blocking=False):
            self._reply(409, {"status": "busy", "detail": "apertura gia' in corso"})
            return
        try:
            result = _open(target_key)
            code = 200 if result.get("status") in ("opened_confirmed", "sent_unconfirmed") else 502
            self._reply(code, result)
        except AuthenticationError:
            self._reply(502, {"status": "authentication_rejected"})
        except (OSError, sqlite3.Error, ProtocolError, ValueError, TypeError, KeyError) as exc:
            self._reply(502, {"status": "failed", "error_type": type(exc).__name__})
        finally:
            _LOCK.release()

    def log_message(self, fmt, *args):  # niente token/segreti nei log di accesso
        LOG.info("HTTP request from %s", self.address_string())


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(BRIDGE_KEY) < 16:
        raise SystemExit("Imposta BRIDGE_KEY con un segreto di almeno 16 caratteri.")
    server = ThreadingHTTPServer((BRIDGE_BIND, BRIDGE_PORT), Handler)
    LOG.info("pycomeca-bridge in ascolto su %s:%s (target predefinito: %r)",
             BRIDGE_BIND, BRIDGE_PORT, BRIDGE_TARGET)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
