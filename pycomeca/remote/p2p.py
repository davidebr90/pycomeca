"""Comelit cloud signalling: OAuth2 login and POST /servicerest/p2p/start.

These are the only steps that must talk to Comelit's servers. Parameters and
field shapes come from docs/REMOTE_P2P.md (OAuth) and docs/REMOTE_P2P.md
(p2p/start). Credentials are read from the caller, never hard-coded. Pure stdlib
(urllib). The viper user-token and OAuth secrets never appear in logs.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import urllib.parse
import urllib.request

LOG = logging.getLogger(__name__)

BASE = "https://api.comelitgroup.com"
CLIENT_ID = "kgDV0WRlQcSF4jPsz887lOTPyVVtP7Oh"
REDIRECT_URI = "https://app.comelitgroup.com/oauth_redirect/comelit"
USER_AGENT = "ktor-client"


class SignalingError(RuntimeError):
    pass


def _post(url: str, data: bytes, headers: dict, timeout: float) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise SignalingError(f"HTTP {exc.code} su {urllib.parse.urlparse(url).path}") from None
    except urllib.error.URLError as exc:
        raise SignalingError(f"rete non raggiungibile: {exc.reason}") from None


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(48)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    # Captures show the challenge sent WITH '=' padding.
    challenge = base64.urlsafe_b64encode(digest).decode()
    return verifier, challenge


def oauth_login(username: str, password: str, timeout: float = 15.0) -> str:
    """Return an OAuth2 access_token (bearer). Raises SignalingError on failure."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_hex(16)
    auth_body = json.dumps({
        "username": username, "password": password, "responseType": "code",
        "clientId": CLIENT_ID, "redirectUri": REDIRECT_URI, "scope": "all",
        "state": state, "codeChallenge": challenge, "codeChallengeMethod": "S256",
    }).encode()
    raw = _post(f"{BASE}/o-auth-2/auth", auth_body,
                {"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": USER_AGENT}, timeout)
    location = json.loads(raw).get("location", "")
    query = urllib.parse.urlparse(location).query
    params = urllib.parse.parse_qs(query)
    if params.get("state", [None])[0] != state:
        raise SignalingError("login OAuth: state non corrispondente")
    code = params.get("code", [None])[0]
    if not code:
        raise SignalingError("login OAuth: code assente nella risposta")
    token_body = urllib.parse.urlencode({
        "grant_type": "authorization_code", "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI, "code": code, "code_verifier": verifier,
    }).encode()
    raw = _post(f"{BASE}/o-auth-2/token", token_body,
                {"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json", "User-Agent": USER_AGENT}, timeout)
    token = json.loads(raw).get("access_token")
    if not token:
        raise SignalingError("login OAuth: access_token assente")
    return token


def p2p_start(access_token: str, device_uuid: str, viper_token: str,
              offer_sdp: str, timeout: float = 15.0) -> str:
    """Send the SDP offer, return the device's answer SDP (decoded text)."""
    body = json.dumps({
        "deviceUuid": device_uuid,
        "data": {
            "authMode": "user_viper_token",
            "secret": viper_token,
            "timeout": 10,
            "sdp": base64.b64encode(offer_sdp.encode()).decode(),
        },
        "protocol": {"name": "viper_p2p_v2", "version": 1},
    }).encode()
    raw = _post(f"{BASE}/servicerest/p2p/start", body,
                {"Content-Type": "application/json", "Accept": "application/json",
                 "Authorization": f"Bearer {access_token}", "User-Agent": USER_AGENT}, timeout)
    parsed = json.loads(raw)
    if parsed.get("result") != "SUCCESS":
        raise SignalingError(f"p2p/start: risultato {parsed.get('result')!r}")
    answer_b64 = (parsed.get("data") or {}).get("sdp")
    if not answer_b64:
        raise SignalingError("p2p/start: SDP di risposta assente")
    return base64.b64decode(answer_b64).decode("utf-8", "replace")
