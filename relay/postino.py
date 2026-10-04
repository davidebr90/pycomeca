#!/usr/bin/env python3
"""postino.py - gira sul vecchio Android (Termux), in casa, sempre acceso.

Fa da tramite fra la bacheca su hosting (bridge.php) e il citofono sulla LAN:
- interroga periodicamente bridge.php (solo connessioni in USCITA, nessuna porta
  aperta in casa);
- quando trova un comando, apre la serratura riusando il client gia' verificato
  (package pycomeca) e riporta l'esito alla bacheca.

Capacita' unica: apre SEMPRE E SOLO il target fisso (TARGET), ignora qualsiasi
parametro. Se la bacheca o il token trapelano, il danno massimo e' l'apertura del
portone.

Configurazione via variabili d'ambiente (impostale in Termux):
    BRIDGE_URL     URL completo di bridge.php  (es. https://tuodominio/percorso/bridge.php)
    AGENT_KEY      stesso AGENT_KEY di bridge.php
    COMELIT_TOKEN  token VIP 32-hex del citofono
    CITOFONO_HOST  IP del citofono in LAN      (default 192.168.1.50)
    POLL_SECONDS   intervallo di polling        (default 2)

Avvio:  python postino.py
"""
from __future__ import annotations

import json
from contextlib import closing
import os
import math
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

# Rende importabile il package `pycomeca` sia se questo file sta nel repo
# (accanto alla cartella pycomeca/) sia se copi pycomeca/ qui accanto sul telefono.
_HERE = Path(__file__).resolve().parent
for candidate in (_HERE, _HERE.parent):
    if (candidate / "pycomeca").is_dir():
        sys.path.insert(0, str(candidate))
        break

from pycomeca.client import IconaClient, AuthenticationError  # noqa: E402
from pycomeca.profile import Profile  # noqa: E402
from pycomeca.protocol import ProtocolError  # noqa: E402

BRIDGE_URL = os.environ.get("BRIDGE_URL", "").rstrip("/")
AGENT_KEY = os.environ.get("AGENT_KEY", "")
TOKEN = os.environ.get("COMELIT_TOKEN", "")
HOST = os.environ.get("CITOFONO_HOST", "192.168.1.50")
POLL_SECONDS = max(1.0, float(os.environ.get("POLL_SECONDS", "2")))
TARGET = os.environ.get("BRIDGE_TARGET", "Portone principale")

PROFILE = Profile(host=HOST)
JOURNAL = Path(os.environ.get("POSTINO_JOURNAL", _HERE / "postino_jobs.sqlite3"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _call(action: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{BRIDGE_URL}?a={action}", data=data, method=method,
                                 headers={"X-Auth": AGENT_KEY, "Content-Type": "application/json"})
    with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as resp:
        content = resp.read(65537)
        if len(content) > 65536:
            raise ValueError("Risposta troppo grande")
        answer = json.loads(content.decode("utf-8") or "{}")
        if not isinstance(answer, dict):
            raise ValueError("Risposta non oggetto")
        return answer


def open_door() -> dict:
    """Una singola apertura del target fisso, con l'esito onesto del client."""
    with IconaClient(PROFILE) as client:
        client.authenticate(TOKEN)
        config = client.configuration()
        return client.open_target(config, config.select(TARGET))


def handle(job: dict) -> None:
    now = time.time()
    if (not isinstance(job, dict) or job.get("command") != "open"
        or not isinstance(job.get("id"), str) or not re.fullmatch(r"[a-f0-9]{16}", job["id"])
        or type(job.get("created")) is not int or type(job.get("expires")) is not int
        or not job["created"] <= now <= job["expires"]
        or not 0 < job["expires"] - job["created"] <= 45):
        raise ValueError("Job non valido o scaduto")
    # Durable claim BEFORE contacting the device, including across worker restarts.
    with closing(sqlite3.connect(JOURNAL)) as journal, journal:
        journal.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, claimed REAL NOT NULL)")
        try:
            journal.execute("INSERT INTO jobs VALUES (?, ?)", (job["id"], now))
        except sqlite3.IntegrityError:
            return  # Never replay. Lost result requires manual reconciliation.
    outcome = "failed"
    try:
        result = open_door()
        outcome = str(result.get("status", "unknown"))
        print(f"[postino] job {job['id']} -> {outcome}", flush=True)
    except AuthenticationError:
        outcome = "authentication_rejected"
    except (OSError, sqlite3.Error, ProtocolError, ValueError, TypeError, KeyError) as exc:
        outcome = f"error:{type(exc).__name__}"
        print(f"[postino] job {job['id']} errore: {type(exc).__name__}", file=sys.stderr, flush=True)
    try:
        _call("result", method="POST", body={"id": job["id"], "outcome": outcome})
    except urllib.error.URLError as exc:
        print(f"[postino] impossibile riportare l'esito: {exc}", file=sys.stderr, flush=True)


def main() -> None:
    url = urllib.parse.urlsplit(BRIDGE_URL)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
        or url.query or url.fragment or len(AGENT_KEY) < 32
        or not re.fullmatch(r"[a-fA-F0-9]{32}", TOKEN)
        or not math.isfinite(POLL_SECONDS)):
        raise SystemExit("Configurare HTTPS senza query/credenziali, AGENT_KEY >=32 caratteri, token VIP e polling valido")
    print(f"[postino] avviato. Bacheca: {BRIDGE_URL} | citofono: {HOST} | ogni {POLL_SECONDS}s", flush=True)
    while True:
        try:
            answer = _call("poll")
            if answer.get("status") == "job":
                handle(answer)
                continue
        except urllib.error.URLError as exc:
            print(f"[postino] bacheca non raggiungibile: {exc}", file=sys.stderr, flush=True)
        except (ValueError, KeyError, sqlite3.Error) as exc:
            print(f"[postino] risposta bacheca non valida: {exc}", file=sys.stderr, flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
