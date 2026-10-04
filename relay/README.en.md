# Relay: opening from outside without the manufacturer's cloud

Italian version: [README.md](README.md).

An alternative to the remote P2P path. It uses two pieces:

- `bridge.php`, a page on any hosting with HTTPS. It never talks to the intercom: it keeps a single kind of request in a queue, "open", and stores its outcome.
- `postino.py`, a small agent running at home on an always-on device (even an old Android phone with Termux). It polls the page every two seconds with outbound connections only and, when it finds a request, opens the gate on the local network.

No port is opened on the home router. If the keys leak, the worst case is opening the configured gate: the agent ignores any parameter and opens only that target.

## Configuration

Generate two long, different keys, for example with `openssl rand -hex 24`.

On the hosting, as the site's environment variables:

| Variable | Meaning |
|---|---|
| `CLIENT_KEY` | key of whoever requests the opening (phone) |
| `AGENT_KEY` | key of the in-home agent |

Upload `bridge.php` and `.htaccess` into a folder with a non-obvious name. The `.htaccess` file denies access to the state file on Apache; on other servers replicate the rule from the panel.

At home, as the agent's environment variables:

| Variable | Meaning |
|---|---|
| `BRIDGE_URL` | full address of `bridge.php` |
| `AGENT_KEY` | the same as on the hosting |
| `COMELIT_TOKEN` | the intercom's user-token, 32 hexadecimal characters |
| `CITOFONO_HOST` | the intercom's IP on the LAN, for example `192.168.1.50` |
| `BRIDGE_TARGET` | name of the target to open, as shown by `--list` |

Copy the `pycomeca/` folder next to `postino.py` and start with `python postino.py`.

## Calls

All with the `X-Auth` header and only over HTTPS.

| Action | Method | Key | Effect |
|---|---|---|---|
| `?a=open` | POST | `CLIENT_KEY` | queues an opening |
| `?a=status` | GET | `CLIENT_KEY` | last known outcome |
| `?a=poll` | GET | `AGENT_KEY` | the agent picks up the request |
| `?a=result` | POST | `AGENT_KEY` | the agent reports the outcome |

A request not picked up within 45 seconds expires. At least 3 seconds must pass between two accepted openings. Each request is executed at most once, even if the agent restarts midway.

## From the phone

On iPhone, in Shortcuts: the "Get Contents of URL" action, address `bridge.php?a=open`, POST method, header `X-Auth` with the `CLIENT_KEY`. The shortcut can then be added to the Home Screen or invoked with Siri using its name.
