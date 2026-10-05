# Required data and its format

All example values are fictitious. They have the same shape as real ones, so you can recognise yours. Italian version: [docs/DATI.md](../DATI.md).

## Data you provide

| Data | Shape | Fictitious example | Where to find it | Secret |
|---|---|---|---|---|
| Intercom IP on the LAN | private IPv4 | `192.168.1.50` | your router's device list, or the monitor's network settings | no |
| ICONA port | integer | `64100` (TCP and UDP) | fixed | no |
| user-token | 32 hexadecimal characters | `0123456789abcdef0123456789abcdef` | the Android app database (`systems.token`), or a backup from the monitor's web page on port 8080 (`users.cfg` file) | **yes** |
| Comelit account | email and password | `name@example.com` | the ones used in the app | **yes** |
| deviceUuid | a UUID followed by a 5-digit suffix | `1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d-00001` | the cloud's `jfs/get` response (`http.duuid` field), also visible in the `p2p/start` body | sensitive |

The user-token has no observed expiry. Anyone who holds it and is on the local network can open: treat it as a key.

### How to get the user-token

Two ways. The first needs neither the app nor a capture.

**A) From the intercom's web page (recommended)**

1. Find the intercom's IP on the local network (in your router's device list). In the examples we use `192.168.1.50`.
2. Open it in a browser, trying in this order:
   - `http://192.168.1.50:8080`
   - `https://192.168.1.50:8443` (the certificate is invalid: accept the browser warning to proceed)
3. A page called **"Extender"** opens. Access is by **password only**, with no username. The installer's factory password is **`comelit`**. If someone changed it, use the one set.
4. Go to the **Backup / Restore** section and download the configuration backup (a `.tar` or `.tar.gz` file).
5. Extract the archive; inside you find `users.cfg` (it may be gzip-compressed: decompress it). Look for a line in the format:

   ```
   9:4:"0123456789abcdef0123456789abcdef"
   ```

   The 32 hex characters in quotes are your `user-token`.

Verified on the 6741W: the "Extender" web UI answers on 8080 and 8443, password-only login. On other models the labels and paths may differ.

**B) From the Android app database**

If you have access to the app file (`bigapp_db.db`), the token is in the `systems` table, `token` column. It needs an Android device with the app and, usually, root permissions to read the file.

In both cases the token is a secret: do not publish or commit it.

## Data the intercom returns

The client reads these itself with `--list`; you do not configure them by hand.

| Data | Shape | Fictitious example | Meaning |
|---|---|---|---|
| ViP address of the internal unit | `SB` + 6 digits | `SB000042` | your monitor |
| Sub-address | integer 0..255 | `1` | distinguishes several devices in the same apartment |
| Entrance panel address | `SB` + 6 digits | `SB100007` | the panel at the gate |
| "open-door" entry | name, address, relay | `Portone principale`, `SB100007`, relay `1` | the lock driven by the entrance panel |
| "actuator" entry | name, address, module, relay | `Attuatore ausiliario`, `SBIO0255`, module `255`, relay `1` | output on an expansion module |
| Switchboard | `SBCPS` + 3 digits | `SBCPS003` | present only on some systems |
| Model and firmware | strings | `MSVF`, `2.1.0` | from the INFO channel |
| Serial number | 12 digits | `001122334455` | identifies the unit |

The address `SBIO0255` is not a personal identifier: it derives from the module number (255) and is the same across different systems.

In commands, a target is given by its key (`door:0`, `actuator:0`) or by the exact name shown by `--list`.

## Ephemeral data of the remote path

Generated per session; do not save or reuse.

| Data | Shape | Fictitious example |
|---|---|---|
| ice-ufrag | 8 hexadecimal characters | `c41f08e2` |
| ice-pwd | 24 hexadecimal characters | `3fa90d5b7c2e61840bd9a7e5` |
| ICE candidates | UDP IP and port with type `host`, `srflx` or `relay` | `203.0.113.25 21429 typ srflx` |
| Channel id | 16-bit integer | `22420` |
| OAuth access_token | opaque string, lasts 7 days | not shown |

## What never to publish

Network captures (`.pcap`, proxy flows), copies of the app database, the `installation.local.json` file, and any `--verbose` output you have not reviewed: the token appears in clear text inside the access message. The project's `.gitignore` already excludes these file types.
