# Remote path: cloud P2P (`viper_p2p_v2`)

How the app reaches the monitor from outside the home, and how this client redoes it. All addresses and credentials in the examples are fictitious. Italian version: [docs/REMOTE_P2P.md](../REMOTE_P2P.md).

## The core idea

The monitor keeps a connection open to the manufacturer's cloud by itself. The cloud does not execute commands: it puts client and monitor in contact and, when needed, relays the packets. The open command always starts from the client and reaches the monitor inside a direct channel between the two.

```
client                          cloud                         monitor
  | 1. OAuth login  ------------> |                               |
  | 2. p2p/start (SDP offer) ---> | --- relay -->                 |
  |    <- SDP answer ------------ | <-- answer --                 |
  | 3. ICE: STUN checks over UDP   <---------------------------->  |
  | 4. PseudoTCP over the chosen path <------------------------->  |
  | 5. ICONA frames, the same as on the LAN <------------------->  |
```

## 1. Login

OAuth 2 with PKCE (S256) on `https://api.comelitgroup.com`:

- `POST /o-auth-2/auth` with a JSON body (`username`, `password`, `responseType: code`, `clientId`, `redirectUri`, `scope: all`, `state`, `codeChallenge`, `codeChallengeMethod`). The response contains a `location` field with `code` and `state`.
- `POST /o-auth-2/token` as a form, with `grant_type=authorization_code`, `code` and `code_verifier`. It returns `access_token`, valid for 7 days.

The client id is the app's public one, with no secret.

## 2. `POST /servicerest/p2p/start`

```json
{
  "deviceUuid": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d-00001",
  "data": {
    "authMode": "user_viper_token",
    "secret": "<user-token, 32 hex>",
    "timeout": 10,
    "sdp": "<SDP offer in base64>"
  },
  "protocol": { "name": "viper_p2p_v2", "version": 1 }
}
```

Response: `{"result":"SUCCESS","data":{"sdp":"<SDP answer in base64>"}}`.

### Offer (client)

```
v=0
o=- 700123456 700123456 IN IP4 0.0.0.0
s=ice
t=0 0
a=nego-wait:0
a=comelit-legacy-session:TCP
a=comelit-session-id:MUX
a=comelit-nego-aggressive:true
c=IN IP4 0.0.0.0
m=audio 62559 RTP/SAVPF 0 8
b=RS:0
b=RR:0
c=IN IP4 198.51.100.77
a=sendrecv
a=candidate:S00000001 1 UDP 1862270975 198.51.100.77 62559 typ srflx raddr 10.0.2.16 rport 46737
a=candidate:H00000001 1 UDP 2130706431 10.0.2.16 46737 typ host
a=ice-role:a
a=ice-ufrag:c41f08e2
a=ice-pwd:3fa90d5b7c2e61840bd9a7e5
```

### Answer (monitor)

```
v=0
o=- 1200345678 1200345678 IN IP4 0.0.0.0
s=ice
t=0 0
a=nego-wait:0
a=comelit-legacy-session:TCP
a=comelit-session-id:MUX
m=audio 51534 RTP/SAVPF 8
c=IN IP4 198.51.100.200
a=sendrecv
a=candidate:Sc0a80132 1 UDP 1694498815 203.0.113.25 21429 typ srflx raddr 192.168.1.50 rport 58293
a=candidate:Hc0a80132 1 UDP 2130706431 192.168.1.50 58293 typ host
a=candidate:Rc6336464 1 UDP 16777215 198.51.100.200 51534 typ relay raddr 203.0.113.25 rport 19742
a=ice-role:o
a=ice-ufrag:5d1c9a70
a=ice-pwd:9b2e47c1d05f8a36e1c7b204
```

Observations:

- the `m=audio ... RTP/SAVPF` lines are only formal: no RTP flows and there is no DTLS (no `fingerprint` line);
- the monitor offers three candidate types: `host` (useful only on the LAN), `srflx` (its public address) and `relay` (on a manufacturer TURN server). The relay is what lets it work behind restrictive NATs;
- the lines must be terminated with CRLF.

## 3. ICE

STUN connectivity checks (RFC 5389 and RFC 8445) with short-term credentials:

- username `remote_ufrag:local_ufrag`, HMAC-SHA1 integrity with the destination's `ice-pwd`, `FINGERPRINT` at the end;
- the monitor is the controlling agent and nominates aggressively: it puts `USE-CANDIDATE` in its checks. The client answers, runs its own checks with `ICE-CONTROLLED` and accepts the nominated pair;
- the client does not allocate its own relay: it always initiates, and the monitor answers to the address the checks come from.

Before the offer the client asks a STUN server for its own public address, to have a `srflx` candidate.

## 4. PseudoTCP

Over the chosen UDP path runs libnice's PseudoTCP, a reliable stream over datagrams. A 24-byte, big-endian header:

```
conversation (4)   always 0
sequence     (4)
acknowledge  (4)
byte 12      (1)   always 0
flags        (1)   0 = data, 2 = control (observed); 4 = reset (from libnice, not observed)
window       (2)   initial 61440
timestamp    (4)   sender's milliseconds
echo ts      (4)   last timestamp received
```

Open: each side sends a control segment with sequence 0 and a 7-byte body, `00 03 01 00 fe 01 00`. Those 7 bytes occupy sequence space: the first usable byte has sequence 7.

## 5. ICONA over PseudoTCP

From byte 7 onward the stream carries the same frames described in [PROTOCOL.md](PROTOCOL.md), in clear text. Two differences from the local network:

1. **The monitor speaks first.** As soon as the stream is established, it opens an `ECHO` channel toward the client:
   `cd ab 01 00 07 00 00 00 45 43 48 4f <id LE16> 00`
2. **The client must acknowledge before doing anything else**, with
   `cd ab 02 00 04 00 00 00 <id LE16> 00 00`
   Everything the client sends before this acknowledgement is ignored.

After the acknowledgement it proceeds as on the LAN: UAUT, UCFG, and possibly CTPP for opening.

Roughly every 15 seconds the monitor sends a 29-byte frame on the `ECHO` channel. The client ignores it for now; for sessions of a few seconds there are no observed consequences.

## Test status

| Step | Status |
|---|---|
| SDP, PseudoTCP, STUN, ICE | automated tests without a device |
| Login, `p2p/start`, ICE, PseudoTCP, UAUT, UCFG | tested on the real monitor |
| Same test going through the `relay` candidate only | tested (client and monitor came out of the same public IP, though) |
| From a network other than home | not tested |
| Opening the gate over this path | not tested |

## Limits and risks

- It depends on the manufacturer's infrastructure: login, `p2p/start` and relay. If something changes, the remote path stops. The local path has no such dependency.
- The content is not encrypted by the protocol: the user-token crosses the relay in clear text.
- With a symmetric NAT on the client side, a relay of our own might be needed, which is not implemented here.
- Addresses, ports, `ufrag` and `pwd` are valid for a single session.
