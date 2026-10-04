# Complete message and parameter catalog

Every JSON message of the ICONA protocol and the cloud calls, with each field and its meaning. Italian version: [docs/MESSAGGI.md](../MESSAGGI.md). See also [PROTOCOL](PROTOCOL.md) for framing and [CALL](CALL.md) for video and audio.

Schemas are extracted from captures of the real device (6741W, `MSVF`) and shown as **keys and types**, never with values. Example values are fictitious.

Evidence level:

- **[D]** observed in clear text on the 6741W;
- **[R]** from public references for the 6701W, not re-tested here (see credits in the README).

## Common conventions

Every message on a channel carries these fields:

| Field | Type | Meaning |
|---|---|---|
| `message` | str | message name (`access`, `get-configuration`, ...) |
| `message-type` | str | `request`, `response` or `notification` |
| `message-id` | int | progressive number, correlates request and response |
| `response-code` | int | in responses: 200 = ok |
| `response-string` | str | textual description of the outcome |
| `notification-code` / `notification-string` | int / str | as above, for the device's spontaneous messages |

## UAUT - authentication [D]

Request:

```json
{ "message": "access", "user-token": "0123456789abcdef0123456789abcdef",
  "message-type": "request", "message-id": 2 }
```

Response: `response-code` 200 and `response-string` "Access Granted". The `user-token` is 32 hexadecimal characters, static. If the device requires encryption we refuse (see `server-info`).

## UCFG - configuration [D]

Request: `{ "message": "get-configuration", "addressbooks": "all" | "none", ... }`.

Response (real keys and types):

```
response-code        int
viper-server:
  local-address      str    the ViP gateway address on the LAN
  local-tcp-port     int    64100
  local-udp-port     int    64100
  remote-address     str    public IP, empty if not configured
  remote-tcp-port    int
  remote-udp-port    int
viper-client:
  description        str
viper-p2p:
  mqtt:
    role             str
    base             str
    server           str    the cloud TLS MQTT broker
    auth.method      [str]  broker authentication methods
  http:
    role             str
    duuid            str    device identifier (deviceUuid)
  stun:
    server           [str]  cloud STUN/TURN servers
sbc:
  pm-always-on       bool   false = the device sleeps when idle
vip:
  enabled            bool
  apt-address        str    your own unit's address (e.g. SB000042)
  apt-subaddress     int    sub-address (e.g. 1)
  logical-subaddress int
  apt-config:
    description          str
    call-divert-busy-en  bool   divert the call if busy
    call-divert-address  str    divert destination
    virtual-key-enabled  bool   open with a virtual key
building-config:
  description        str
```

With `addressbooks: all` the response also contains `vip.user-parameters`, the address books:

| Address book | Entries | Fields |
|---|---|---|
| `opendoor-address-book` | locks | `id`, `name`, `apt-address`, `output-index` (relay 1..255), `secure-mode` (bool, optional) |
| `actuator-address-book` | actuators | as above, plus `module-index` (0..255) |
| `entrance-address-book` | entrance panels | `id`, `name`, `apt-address` |
| `rtsp-camera-address-book` | RTSP cameras | `id`, `name`, `rtsp-url`, `rtsp-user`, `rtsp-password` |
| `apt-address-book` | other apartments | internal-call entries |
| `switchboard-address-book` | switchboards | `id`, `name`, `apt-address` |
| `camera-address-book` | ViP cameras | video entries |
| `direct-link-address-book` | quick links | up to 4 (Link 1..4) |

The client only accepts entries with an integer `id` >= 0 and `output-index` between 1 and 255; duplicate keys within the same type are rejected. A target is given by its key `door:<id>` or `actuator:<id>`, or by its exact name.

## INFO - server information [D]

Request: `{ "message": "server-info", ... }`. Response:

```
model                   str    internal model (e.g. MSVF)
version                 str    firmware (e.g. 2.1.0)
serial-code             str    serial number
capabilities            [str]  list of the device's capabilities
user-auth-channel:
  encryption-required   bool   if true, UAUT requires encryption
user-admin-channel:
  encryption-required   bool
  cloud-code-login      bool
configuration-channel:
  internal-unit-cfg     bool
  direct-link-cfg       bool
  iu-buttons-cfg        bool
  api-version           int    configuration API version
fast-activation-channel:
  app                   bool
  internal-unit         bool
  other-device          bool
cloud-activation:
  cloud-activation-enable bool
```

The `*-channel` blocks declare what each channel supports: useful to know in advance whether UAUT wants encryption or which UCFG version to use.

## PUSH - notification registration [D]

```json
{ "message": "push-info", "os-type": "android", "device-token": "<FCM token>",
  "bundle-id": "com.comelit.bigapp", "profile-id": "1",
  "apt-address": "SB000042", "apt-subaddress": 49, "message-type": "request", "message-id": 2 }
```

Registers the token for push notifications and acts as a keepalive (the app resends it roughly every 90 seconds). Not needed for opening.

## FRCG - face recognition [D]

Request `{ "message": "rcg-get-params", ... }`. The device replies and then sends a notification:

```
rcg-params-result (notification):
  parameters:
    enable     bool
    threshold  int
```

Present only on models with face recognition. [R] There are also `rcg-set-user`, `rcg-delete-user` and detection notifications with an image.

## Binary messages

These are not JSON and are described elsewhere:

- door and actuator opening, call and state events: CTPP channel, see [PROTOCOL](PROTOCOL.md);
- signalling and flow of a video call: UDPM and RTPC channels, see [CALL](CALL.md).

## Cloud calls (remote path)

Under `https://api.comelitgroup.com`, with a Bearer token. Flow detail in [REMOTE_P2P](REMOTE_P2P.md).

| Endpoint | Purpose | Main fields |
|---|---|---|
| `POST /o-auth-2/auth` + `/token` | login, returns `access_token` | see REMOTE_P2P |
| `POST /servicerest/jfs/lst` | list of the account's devices | per entry: `ownerUuid`, `name`, `metadata.model-id`, `permissions` |
| `POST /servicerest/jfs/get` | device configuration (the connection's "identity card") | `viper-server`, `viper-p2p` (mqtt, http.duuid, stun), as in UCFG |
| `GET /servicerest/directory/resources` | smart-home resources | `apartments`, `units`, `switchboards`, `credentials`: **empty** on a pure video-intercom system |
| `POST /servicerest/p2p/start` | starts the P2P session | see REMOTE_P2P |

The empty `directory/resources` list is the proof that on this kind of system there is no REST open command: opening always goes through the ICONA protocol inside the P2P session.
