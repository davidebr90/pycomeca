# The official app from the inside (reverse)

What we understood about the official Android app by studying it with static analysis, mitmproxy and Frida. It explains why the protocol looks the way it does and helps if you want to repeat or extend the study. Italian version: [docs/APP_UFFICIALE.md](../APP_UFFICIALE.md).

These are observations of behaviour and the names of classes and methods, not a copy of the code. The names are the real ones found in the app; the addresses in the examples are fictitious.

## Identity and distribution

- Android package: `com.comelit.bigapp`, observed version 7.5.0.
- Distributed as an Android App Bundle: a base APK plus separate configuration APKs for language, screen density and architecture (`config.it.apk`, `config.xxxhdpi.apk`, `config.arm64_v8a.apk`, ...). To install it in the emulator they are needed together (`install-multiple`).

## Observed technologies

| Layer | Technology |
|---|---|
| Cloud network (HTTP) | **Ktor** client (User-Agent `ktor-client`) to `api.comelitgroup.com`, HTTP/2 |
| Authentication | OAuth 2 with PKCE (S256); public client `kgDV0WRlQcSF4jPsz887lOTPyVVtP7Oh`, no secret |
| P2P signalling | MQTT over TLS (**Paho** client) to a cloud broker, used only as a rendezvous point |
| P2P transport | ICE + PseudoTCP (**libnice** style) with STUN/TURN; muxed session |
| ViP engine | native `comelitvipkit` library (.so): ICONA framing, channels, media |
| Media | RTP, H.264 (video), G.711 PCMA (audio) |
| Local data | the app's SQLite database (`bigapp_db.db`): systems, token, address books |
| Notifications | Firebase Cloud Messaging for the incoming call |

The language is Kotlin (Ktor, class style) with a substantial part in native code for the ViP engine and the media.

## Layered architecture

```
+-------------------------------------------------------------+
|  App UI (call, open door, configuration)                    |
+-------------------------------------------------------------+
|  Cloud CCAPI (Ktor)        |  Incoming-call SDK (FCM)        |
|  OAuth, profile, jfs,      |  com.comelitgroup.sdk.incomingcall
|  p2p/start                 |                                 |
+-------------------------------------------------------------+
|  ViP engine  (com.comelitgroup.comelitvipkit, native)       |
|  VipEngine / VipMessageParser: ICONA channels, opening, media
+-------------------------------------------------------------+
|  Transport: direct LAN | direct public IP | cloud P2P       |
|  (ICE + PseudoTCP, MQTT as rendezvous)                      |
+-------------------------------------------------------------+
```

The app chooses the transport in this order: direct LAN to the gateway (no cloud), direct public IP (if a port forward is configured, usually absent), cloud P2P when the first two are not reachable.

## Key classes and methods

### `com.comelitgroup.comelitvipkit.VipEngine`

The heart of the dialogue with the intercom. Methods observed (with Frida, during opening and a video call):

| Method | What it does |
|---|---|
| `createViperTunnel(...)` | opens the tunnel: on the LAN with `(ip, tcpPort, udpPort, timeout)`, in the cloud with a P2P parameters object |
| `createVipUnit(sysId, aptAddress, ...)` | creates your own user unit in the session |
| `openChannel(sysId, channelType)` | opens an ICONA channel (UAUT, UCFG, CTPP, ...) |
| `sendOnChannel(sysId, channelType, json)` | sends a JSON message on the channel |
| `closeChannel(sysId, channelType)` | closes the channel |
| `sendOpenDoorCommand(sysId, unitId, vipAddress, relays)` | door opening (entrance panel + relay) |
| `sendActuatorCommand(sysId, unit, vipAddress, module, relay, action)` | actuator command |
| `setVipUnitCallTimeParam(sysId, unit, key, value)` | call timers |
| `setVipUnitBitrate(sysId, unit, hd, kbps)` | video bitrate (HD flag) |
| `setVipUnitRtpMaxVideoResolution(sysId, unit, w, h, ...)` | maximum resolution |
| `setVipUnitRtpPreferredVideoResolution(sysId, unit, w, h)` | preferred resolution (SD/HD) |
| `answerCall(sysId, unit, fsm)` | answers the call |
| `requestVideo` / `requestVideoKeyFrameGeneration` | requests the video / a keyframe |
| `releaseCall(sysId, unit, fsm)` | ends the call |
| `addReceivedPacketFromSocket(sysId, bytes)` | entry point of the raw received packets |

### `com.comelitgroup.comelitvipkit.VipMessageParser`

`parse(...)` turns received packets into an object with the fields `unit_type`, `system_id`, `unit_id`, `msg_type`, `msg_type_id`, `msg_data`. It is where events (call state, opening, media) become readable.

### `com.comelitgroup.sdk.incomingcall`

Incoming-call handling, separate from the engine:

| Class | Role |
|---|---|
| `CallService` | service handling the incoming call |
| `CallConnection` | the call connection (integration with Android telephony) |
| `CallRegistry` | call registry |
| `CallRinger` | ringtone |
| `CallNotificationHandler` | call notification |

### App

| Class | Role |
|---|---|
| `com.comelit.bigapp.call.manager.AudioVideoManager` | audio and video start/stop; `start()`, `startAudio()`, `setMicrophoneState(bool)`, `stop()`, `stopRecording()`; `decodeFrame`/`getVideoFrame` for the video |
| `com.comelit.bigapp.call.NotificationCenter` | routing of internal events |
| `com.comelit.bigapp.notification.ComelitFirebaseMessagingService` | reception of FCM push (incoming call) |

## Observed flows

### Login and device discovery
OAuth (PKCE) to `api.comelitgroup.com` for the `access_token`; then profile, list and device configuration via `jfs`. Message detail in [MESSAGES](MESSAGES.md), path detail in [REMOTE_P2P](REMOTE_P2P.md).

### Door opening
Pressing "Entrance lock" the app runs a full ViP session and then the opening: `createVipUnit`, session setup, opening channels (INFO, PUSH, UCFG), `sendOpenDoorCommand`, opening UAUT with the `access` message and the token. On the wire it is the CTPP sequence described in [PROTOCOL](PROTOCOL.md).

### Video call
`createVipUnit` and session setup (timers, bitrate, resolutions), opening the media channels, codec negotiation, `answerCall`, then the switch to HD with `setVipUnitRtpPreferredVideoResolution` and `setVipUnitBitrate`, `requestVideo`. The on-the-wire flow is in [CALL](CALL.md).

### Incoming call
The intercom rings the app through an FCM push received by `ComelitFirebaseMessagingService`, which activates the `incomingcall` SDK (`CallService`, `CallRinger`). Answering starts audio and video via `AudioVideoManager`.

## How it was observed

- static analysis of the bundle with jadx for the names and the login flow;
- mitmproxy for the HTTPS traffic to the cloud;
- Frida to hook the methods above and see arguments and timings at runtime (scripts in `tools/frida/`);
- in the emulator the native video decoder crashes the app: the `hook_bypass.js` script steps over `decodeFrame`/`getVideoFrame` so audio, events and opening stay observable.

The full method, with the mistakes made, is in [DEBUG_FLOW](DEBUG_FLOW.md).
