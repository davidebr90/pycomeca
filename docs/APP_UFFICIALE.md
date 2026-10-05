# L'app ufficiale vista da dentro (reverse)

Cosa abbiamo capito dell'app Android ufficiale studiandola con analisi statica, mitmproxy e Frida. Serve a spiegare perché il protocollo è fatto così e a orientarsi se si vuole ripetere o estendere lo studio. English version: [docs/en/OFFICIAL_APP.md](en/OFFICIAL_APP.md).

Sono osservazioni di comportamento e nomi di classi e metodi, non copia del codice. I nomi sono quelli reali trovati nell'app; gli indirizzi negli esempi sono fittizi.

## Identità e distribuzione

- Pacchetto Android: `com.comelit.bigapp`, versione osservata 7.5.0.
- Distribuita come Android App Bundle: un APK base più APK di configurazione separati per lingua, densità schermo e architettura (`config.it.apk`, `config.xxxhdpi.apk`, `config.arm64_v8a.apk`, ...). Per installarla nell'emulatore servono tutti insieme (`install-multiple`).

## Tecnologie osservate

| Livello | Tecnologia |
|---|---|
| Rete cloud (HTTP) | client **Ktor** (User-Agent `ktor-client`) verso `api.comelitgroup.com`, HTTP/2 |
| Autenticazione | OAuth 2 con PKCE (S256); client pubblico `kgDV0WRlQcSF4jPsz887lOTPyVVtP7Oh`, senza segreto |
| Segnalazione P2P | MQTT su TLS (client **Paho**) verso un broker del cloud, usato solo come punto di incontro |
| Trasporto P2P | ICE + PseudoTCP (stile **libnice**) con STUN/TURN; sessione muxata |
| Motore ViP | libreria nativa `comelitvipkit` (.so): framing ICONA, canali, media |
| Media | RTP, H.264 (video), G.711 PCMA (audio) |
| Dati locali | database SQLite dell'app (`bigapp_db.db`): sistemi, token, rubriche |
| Notifiche | Firebase Cloud Messaging per la chiamata entrante |

Il linguaggio è Kotlin (Ktor, stile delle classi) con una parte consistente in codice nativo per il motore ViP e il media.

## Architettura a livelli

```
+-------------------------------------------------------------+
|  UI dell'app (chiamata, apri porta, configurazione)         |
+-------------------------------------------------------------+
|  CCAPI cloud (Ktor)        |  SDK chiamata entrante (FCM)    |
|  OAuth, profilo, jfs,      |  com.comelitgroup.sdk.incomingcall
|  p2p/start                 |                                 |
+-------------------------------------------------------------+
|  Motore ViP  (com.comelitgroup.comelitvipkit, nativo)       |
|  VipEngine / VipMessageParser: canali ICONA, apertura, media|
+-------------------------------------------------------------+
|  Trasporto: LAN diretta | IP pubblico diretto | P2P cloud   |
|  (ICE + PseudoTCP, MQTT come rendezvous)                    |
+-------------------------------------------------------------+
```

L'app sceglie il trasporto in quest'ordine: LAN diretta sul gateway (nessun cloud), IP pubblico diretto (se configurato un port forward, di norma assente), P2P via cloud quando i primi due non sono raggiungibili.

## Classi e metodi chiave

### `com.comelitgroup.comelitvipkit.VipEngine`

Il cuore del dialogo col citofono. Metodi osservati (con Frida, durante apertura e videochiamata):

| Metodo | Cosa fa |
|---|---|
| `createViperTunnel(...)` | apre il tunnel: in LAN con `(ip, tcpPort, udpPort, timeout)`, in cloud con un oggetto di parametri P2P |
| `createVipUnit(sysId, aptAddress, ...)` | crea la propria unità utente nella sessione |
| `openChannel(sysId, channelType)` | apre un canale ICONA (UAUT, UCFG, CTPP, ...) |
| `sendOnChannel(sysId, channelType, json)` | invia un messaggio JSON sul canale |
| `closeChannel(sysId, channelType)` | chiude il canale |
| `sendOpenDoorCommand(sysId, unitId, vipAddress, relays)` | apertura serratura (posto esterno + relè) |
| `sendActuatorCommand(sysId, unit, vipAddress, module, relay, action)` | comando attuatore |
| `setVipUnitCallTimeParam(sysId, unit, key, value)` | timer della chiamata |
| `setVipUnitBitrate(sysId, unit, hd, kbps)` | bitrate video (flag HD) |
| `setVipUnitRtpMaxVideoResolution(sysId, unit, w, h, ...)` | risoluzione massima |
| `setVipUnitRtpPreferredVideoResolution(sysId, unit, w, h)` | risoluzione preferita (SD/HD) |
| `answerCall(sysId, unit, fsm)` | risponde alla chiamata |
| `requestVideo` / `requestVideoKeyFrameGeneration` | richiede il video / un keyframe |
| `releaseCall(sysId, unit, fsm)` | chiude la chiamata |
| `addReceivedPacketFromSocket(sysId, bytes)` | punto d'ingresso dei pacchetti grezzi ricevuti |

### `com.comelitgroup.comelitvipkit.VipMessageParser`

`parse(...)` trasforma i pacchetti ricevuti in un oggetto con i campi `unit_type`, `system_id`, `unit_id`, `msg_type`, `msg_type_id`, `msg_data`. È il punto dove gli eventi (stato chiamata, apertura, media) diventano leggibili.

### `com.comelitgroup.sdk.incomingcall`

Gestione della chiamata entrante, separata dal motore:

| Classe | Ruolo |
|---|---|
| `CallService` | servizio che gestisce la chiamata in arrivo |
| `CallConnection` | la connessione di chiamata (integrazione con il sistema telefonico Android) |
| `CallRegistry` | registro delle chiamate |
| `CallRinger` | suoneria |
| `CallNotificationHandler` | notifica di chiamata |

### App

| Classe | Ruolo |
|---|---|
| `com.comelit.bigapp.call.manager.AudioVideoManager` | avvio e stop di audio e video; `start()`, `startAudio()`, `setMicrophoneState(bool)`, `stop()`, `stopRecording()`; `decodeFrame`/`getVideoFrame` per il video |
| `com.comelit.bigapp.call.NotificationCenter` | smistamento degli eventi interni |
| `com.comelit.bigapp.notification.ComelitFirebaseMessagingService` | ricezione delle push FCM (chiamata entrante) |

## Flussi osservati

### Login e scoperta del dispositivo
OAuth (PKCE) verso `api.comelitgroup.com` per l'`access_token`; poi profilo, elenco e configurazione del dispositivo via `jfs`. Dettaglio dei messaggi in [MESSAGGI](MESSAGGI.md), del percorso in [REMOTE_P2P](REMOTE_P2P.md).

### Apertura porta
Premendo "Serratura ingresso" l'app esegue una sessione ViP completa e poi l'apertura: `createVipUnit`, impostazione sessione, apertura canali (INFO, PUSH, UCFG), `sendOpenDoorCommand`, apertura di UAUT con il messaggio `access` e il token. A livello di filo è la sequenza CTPP descritta in [PROTOCOLLO](PROTOCOL.md).

### Videochiamata
`createVipUnit` e impostazione sessione (timer, bitrate, risoluzioni), apertura dei canali media, negoziazione del codec, `answerCall`, poi passaggio a HD con `setVipUnitRtpPreferredVideoResolution` e `setVipUnitBitrate`, `requestVideo`. Il flusso sul filo è in [CHIAMATA](CHIAMATA.md).

### Chiamata entrante
Il citofono fa squillare l'app tramite una push FCM ricevuta da `ComelitFirebaseMessagingService`, che attiva l'SDK `incomingcall` (`CallService`, `CallRinger`). La risposta avvia audio e video via `AudioVideoManager`.

## Come è stato osservato

- analisi statica del bundle con jadx per i nomi e il flusso di login;
- mitmproxy per il traffico HTTPS verso il cloud;
- Frida per agganciare i metodi sopra e vedere argomenti e tempi in esecuzione (script in `tools/frida/`);
- nell'emulatore il decoder video nativo fa cadere l'app: lo script `hook_bypass.js` scavalca `decodeFrame`/`getVideoFrame` così audio, eventi e apertura restano osservabili.

Il metodo completo, con gli errori fatti, è in [DEBUG_FLOW](DEBUG_FLOW.md).
