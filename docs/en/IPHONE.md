# Open the gate from your iPhone, one tap

Goal: an icon (or "Hey Siri, open the gate") that opens the gate from any network, without the official app. Italian version: [docs/IPHONE.md](../IPHONE.md).

The client is Python, so you need an app that runs Python on the iPhone: **a-Shell** (free). No other hardware, no hosting.

> Honest note: this path (a-Shell running the client) has not been verified by the author yet. The uncertain point is whether a-Shell allows the UDP sockets and STUN that are needed. The test in step 4 (`--list`) tells you at once: if it prints the address book, everything works. If a-Shell blocks something, the safe alternative is the `relay/` path on an old Android.

## 1. Install a-Shell

From the App Store install **a-Shell** (by Nicolas Holzschuch). It is a terminal with Python included.

## 2. Download PyCOMECA in a-Shell

Open a-Shell and type:

```
curl -LO https://github.com/davidebr90/pycomeca/archive/refs/heads/main.zip
unzip main.zip
cd pycomeca-main
```

You are now in the project folder (`~/Documents/pycomeca-main`).

## 3. The four parameters: what they are and where to get them

All values are fictitious, they only show you the format.

| Parameter | What it is | Where to get it |
|---|---|---|
| `COMELIT_USER` | your Comelit account email | the same you use to sign in to the official app |
| `COMELIT_PASS` | account password | the same as the official app |
| `COMELIT_DEVICE_UUID` | the intercom identifier (e.g. `1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d-00001`) | you discover it yourself in step 5 with the `--devices` command |
| `COMELIT_TOKEN` | the intercom's user-token, 32 hex characters (e.g. `0123456789abcdef0123456789abcdef`) | from the intercom's web page on port 8080 (settings backup, `users.cfg` file, a line like `9:4:"<32 hex>"`), or from the Android app database (`systems.token`). Details in [DATA](DATA.md) |

## 4. Create the credentials file (first with 3 values)

In the `pycomeca-main` folder create a `pycomeca.conf` file. The easiest way: open the **Files** app → **On My iPhone** → **a-Shell** → `pycomeca-main`, create `pycomeca.conf` there and paste these lines with YOUR values. For now **leave out** the deviceUuid line: you fill it in the next step.

```
COMELIT_USER=your-email@comelit.example
COMELIT_PASS=your-password
COMELIT_TOKEN=0123456789abcdef0123456789abcdef
```

Alternatively, from a-Shell, use the built-in editor: `vim pycomeca.conf` (`i` to type, `Esc` then `:wq` to save). The file stays on the phone, it goes nowhere.

## 5. Discover the deviceUuid

In a-Shell, inside `pycomeca-main`:

```
python -m pycomeca.remote --devices
```

With the login alone it prints the list of your intercoms, each with its `uuid`, name and model. Copy your intercom's `uuid` and add it to `pycomeca.conf`:

```
COMELIT_DEVICE_UUID=<the-uuid-you-copied>
```

Now the file has all four values.

## 6. Test it (without opening anything)

In a-Shell, inside `pycomeca-main`:

```
python -m pycomeca.remote --list
```

If it prints the configuration with `Portone principale` (or your own name), you are connected to the intercom from the phone: everything works. If it errors, run `python -m pycomeca.remote --list --verbose` and see where it stops (login, ICE, PseudoTCP).

## 7. Create the "open" command

a-Shell provides a Shortcuts action.

1. Open the **Shortcuts** app → **+** (new).
2. Add a-Shell's **"Execute Command"** action (search "a-Shell").
3. As the command, on a single line:

   ```
   cd ~/Documents/pycomeca-main && python -m pycomeca.remote --open "Portone principale"
   ```

4. Name it **"Apri portone"** at the top and save. The name becomes the Siri phrase.

On first run iOS may ask for network permission once: allow it.

## 8. Make it one tap, your choice

- **Home Screen icon**: in the shortcut, share menu → **Add to Home Screen**. One tap on the icon opens.
- **Siri**: say **"Hey Siri, apri portone"**, even on the lock screen.
- **Action Button** (iPhone 15 Pro and later): Settings → Action Button → Shortcut → "Apri portone".
- **Back Tap**: Settings → Accessibility → Touch → Back Tap → Double Tap → "Apri portone". Two taps on the back.

## What to expect

- The opening goes through the Comelit cloud and the relay, so it takes a few seconds (typically 4-8 s).
- a-Shell may appear for a moment while running: that is normal, not a menu.
- The expected answer is `"status": "opened_confirmed"`. If `sent_unconfirmed` comes out, the command was sent but the intercom did not return the event: check whether the gate opened.
- To always force the external path, add the line `PYCOMECA_RELAY_ONLY=1` to `pycomeca.conf`.

## If a-Shell does not work

If step 4 fails because a-Shell blocks the sockets, use the [relay/](../relay/README.en.md) path: a page on hosting and an always-on old Android at home. In that case the shortcut becomes a simple HTTP request, which a-Shell (or even plain Shortcuts) handle without trouble.
