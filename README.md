<p align="center"><img src="assets/icon.webp" width="180" alt="PyCOMECA"></p>

# PyCOMECA

Open your front gate with a single command, without going through the official video-intercom app.

🇬🇧 English (this page) · 🇮🇹 [Italiano](README.it.md)

PyCOMECA is a dependency-free Python client for Comelit ViP video intercoms. It talks to the intercom directly on your home network (ICONA protocol, port 64100) or from outside through the same cloud P2P path the app uses.

The name: **Py** for Python, **COME** from Comelit, **CA** from *casa* (home, in Italian). Start and end together read as PYCA, pronounced like Pica, the surname of the person who wrote it.

## Why it exists

The official app offers no quick action: to open the gate you launch it, wait for the connection and move through several screens. I wanted a single command, callable from a home-automation system, a script or a phone shortcut. Finding no official way, I studied how the app talks to the intercom and rewrote that conversation in Python.

The project collects both the code and the study notes: message format, open sequence, remote path and the method used to get there.

## Verification status

| Capability | Status |
|---|---|
| Read configuration and address book on the local network | tested on the real device |
| Open the gate on the local network, with a confirmation event from the intercom | tested on the real device |
| Remote path (OAuth, `p2p/start`, ICE, PseudoTCP): read configuration | tested on the real device, including forcing the public relay |
| Remote path from a network other than home | not yet tested |
| Opening the gate over the remote path | not yet tested |
| Continuous event listening (ring), audio and video | not implemented |

The automated tests (37) run without an intercom: they use a simulated device and fictitious data.

## Devices

| Device | Outcome |
|---|---|
| Comelit Mini Wi-Fi **6741W** (internal model `MSVF`, firmware 2.1.0), SimpleBus2 system | tested directly |
| Comelit **6701W** | not tested by me; the local protocol matches the one documented by the projects credited at the bottom |

The app used as a reference for the study is Comelit for Android, version 7.5.0.

## What you need

See [docs/en/DATA.md](docs/en/DATA.md) for every field, its expected format and where to find it. In short:

- the intercom's IP address on the local network (local path only);
- the intercom's **user-token**, 32 hexadecimal characters;
- for the remote path: your Comelit account credentials and the intercom's `deviceUuid`.

Every identifier that appears in this repository (addresses, tokens, UUIDs, IPs, names) is **fictitious**, but has the same shape as a real one.

## Usage

Python 3.11 or later. No packages to install.

Local path, from your home network:

```bash
# create your own config from the example, then edit it:
cp installation.example.json installation.local.json
# in installation.local.json replace the placeholder IP 192.168.1.50 with your intercom's

# the 32-hex token below is fictitious: use your own
export COMELIT_TOKEN=0123456789abcdef0123456789abcdef

python pycomeca_ctl.py --list
python pycomeca_ctl.py --open "Portone principale"
```

Remote path, from any network (the values below are fictitious, use your own):

```bash
export COMELIT_USER=name@example.com
export COMELIT_PASS=your-comelit-password
export COMELIT_DEVICE_UUID=1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d-00001
export COMELIT_TOKEN=0123456789abcdef0123456789abcdef

python -m pycomeca.remote --list
python -m pycomeca.remote --open "Portone principale"
```

`--relay-only` forces the public relay even when you are at home, useful to test the external path. `--verbose` prints the sequence of steps.

No command opens the gate without `--open`. Each session sends at most one open command and never repeats it on its own.

Tests:

```
python -m unittest discover -s tests
```

## Contents

- `pycomeca/` local client: ICONA framing, channels, authentication, configuration, opening.
- `pycomeca/remote/` remote transport: SDP, STUN, ICE, PseudoTCP, cloud calls.
- `pycomeca_bridge.py` small local HTTP service (`POST /open`) to keep behind a VPN.
- `relay/` an alternative without the Comelit cloud: a PHP page on shared hosting and a small in-home agent that only makes outbound connections. See [relay/README.md](relay/README.md).
- `tools/frida/` scripts used to observe the app during the study.
- `docs/` notes, in English under [docs/en/](docs/en/) and in Italian under [docs/](docs/): [protocol](docs/en/PROTOCOL.md), [message catalog](docs/en/MESSAGES.md), [video call](docs/en/CALL.md), [official app internals](docs/en/OFFICIAL_APP.md), [remote path](docs/en/REMOTE_P2P.md), [study method](docs/en/DEBUG_FLOW.md), [required data](docs/en/DATA.md), [one-tap from iPhone](docs/en/IPHONE.md).

## Warnings

- Independent project, not affiliated with or endorsed by Comelit Group. Trademarks belong to their respective owners.
- Intended for use on your own system. Do not use it on systems you do not own or are not authorised to operate.
- The user-token is static and travels in clear text on the wire: never expose port 64100 to the internet, and never publish network captures or copies of the app database.
- The protocol is not documented by the manufacturer. A firmware or cloud update can break everything without notice.
- The confirmation event means the intercom executed the command, not that the lock moved: that depends on the wiring.

## Credits

The study of the local protocol owes much to earlier public work: [comelit-client](https://github.com/madchicken/comelit-client) by Pierpaolo Follia, [ha-component-comelit-intercom](https://github.com/nicolas-fricke/ha-component-comelit-intercom) by Nicolas Fricke, the articles by [grdw](https://grdw.nl/2023/01/28/my-intercom-part-1.html) and the Home Assistant integrations with capture-verified references for the 6701W. The remote P2P path is the result of the study described in this repository.

## License

[AGPL-3.0](LICENSE). Copyright (C) 2026 davidebr90.
