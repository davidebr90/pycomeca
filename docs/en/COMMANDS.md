# Command reference

A precise explanation of every option of the two tools. Italian version: [docs/COMANDI.md](../COMANDI.md).

There are two executables:

- **`pycomeca_ctl.py`** - the **local** path (same network as the intercom, port 64100);
- **`python -m pycomeca.remote`** - the **remote** path (from any network, via cloud P2P).

Neither opens the gate without an explicit open action (`--open`).

---

## 1. Local path: `pycomeca_ctl.py`

Diagnostics and control on the home network. It needs a profile (`installation.local.json`) with the intercom's IP, and the token via environment or database.

### Actions (choose one; with none it defaults to `--list`)

| Option | What it does | Touches the intercom |
|---|---|---|
| `--list` | reads the configuration and the address book (UCFG). This is the default | yes (read) |
| `--info` | reads model, version, capabilities (INFO) | yes (read) |
| `--inventory` | shows the data saved in the app database, without connecting | no |
| `--probe` | only checks whether port 64100 answers (TCP), without authenticating | yes (TCP only) |
| `--discover` | sends a UDP INFO to port 24199 and shows the reply | yes (UDP) |
| `--open TARGET` | **opens** the given lock or actuator (key `door:0` / `actuator:0` or name) | yes, opens |
| `--decode-hex HEX` | decodes a hex string as an ICONA frame, offline | no |
| `--analyze-captures` | analyses the `.mitm`/`.pcap` captures in a folder, offline | no |

### Common options

| Option | Meaning | Default |
|---|---|---|
| `--profile FILE` | installation file to use | `installation.local.json` |
| `--host IP` | force the intercom's IP (overrides the profile) | from the profile |
| `--port N` | ICONA port | 64100 |
| `--timeout SEC` | session timeout | 30 |
| `--wire-profile {classic,community}` | encoding variant of the channel "type" field | classic |
| `--system-id N` | which system in the database to use | 1 |
| `--from-config FILE` | work offline on a saved configuration (only with `--list` or `--open --dry-run`) | - |
| `--dry-run` | with `--open --from-config`: show the command bytes **without sending anything** | - |
| `--output FILE` | write the result (JSON) to a new file, in addition to the screen | - |
| `--captures-dir DIR` | folder for `--analyze-captures` | `captures/` |
| `--debug` | verbose logging | - |

### Environment variables

| Variable | Use |
|---|---|
| `COMELIT_TOKEN` | 32-hex user-token; if absent, it is read from the profile's database |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | all ok |
| 2 | authentication refused, error, or invalid use of options |
| 3 | intercom unreachable (`--probe` / `--discover`) |
| 4 | command sent but outcome uncertain (`delivery_uncertain`) |
| 130 | interrupted from the keyboard |

### Examples

```
# read the configuration on the LAN
python pycomeca_ctl.py --list

# open the lock
python pycomeca_ctl.py --open "Portone principale"

# see the command bytes without sending them (offline)
python pycomeca_ctl.py --from-config config.json --open "Portone principale" --dry-run
```

---

## 2. Remote path: `python -m pycomeca.remote`

Opening and reading from any network, via the cloud. Credentials come from the environment or from a config file.

### Actions (choose one)

| Option | What it does | Needs |
|---|---|---|
| `--devices` | lists the account's intercoms with their `uuid`, name and model | only USER and PASS |
| `--list` | authenticates and shows the address book, without opening | USER, PASS, DEVICE_UUID, TOKEN |
| `--open TARGET` | **opens** the target (key `door:0` or name) | USER, PASS, DEVICE_UUID, TOKEN |

### Options

| Option | Meaning |
|---|---|
| `--relay-only` | force the external path: use only the intercom's relay candidate, ignore the LAN. Useful to test from home what would happen from outside |
| `--config FILE` | `KEY=VALUE` file with the credentials |
| `--verbose` | show the sequence of steps (login, ICE, PseudoTCP) |

### Credentials (from environment or file)

| Key | What it is | Where to get it |
|---|---|---|
| `COMELIT_USER` | Comelit account email | the same as the official app |
| `COMELIT_PASS` | account password | the same as the official app |
| `COMELIT_DEVICE_UUID` | the intercom identifier | with `--devices` |
| `COMELIT_TOKEN` | 32-hex user-token | the intercom's web page (port 8080) or the app database; see [DATA](DATA.md) |
| `PYCOMECA_RELAY_ONLY` | `1` to always force the relay (like `--relay-only`) | optional |

An environment variable that is already set takes precedence over the file.

### Config file

Looked up in this order: `--config`, then `PYCOMECA_CONFIG`, then `~/.pycomeca.conf`, then `pycomeca.conf` in the current folder. Format: `KEY=value` lines, blank lines and `#` ignored. Template in `pycomeca.conf.example`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | all ok |
| 1 | error (login, network, or opening failed) |
| 2 | missing credentials |

### Examples

```
# discover the deviceUuid (email and password are enough)
python -m pycomeca.remote --devices

# read the address book from the cloud
python -m pycomeca.remote --list

# open from outside, forcing the relay, with logging
python -m pycomeca.remote --open "Portone principale" --relay-only --verbose

# using an explicit credentials file
python -m pycomeca.remote --open "Portone principale" --config ~/pycomeca.conf
```

For one-tap use from an iPhone, see [IPHONE](IPHONE.md).
