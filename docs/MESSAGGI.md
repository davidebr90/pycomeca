# Catalogo completo dei messaggi e dei parametri

Tutti i messaggi JSON del protocollo ICONA e le chiamate al cloud, con ogni campo e il suo significato. English version: [docs/en/MESSAGES.md](en/MESSAGES.md). Vedi anche [PROTOCOLLO](PROTOCOL.md) per il framing e [CHIAMATA](CHIAMATA.md) per video e audio.

Gli schemi sono estratti dalle catture del dispositivo reale (6741W, `MSVF`) e riportati come **chiavi e tipi**, mai con i valori. I valori di esempio sono inventati.

Livello di evidenza:

- **[D]** osservato in chiaro sul dispositivo 6741W;
- **[R]** da riferimenti pubblici per il 6701W, non riprovato qui (vedi crediti nel README).

## Convenzioni comuni

Ogni messaggio sul canale porta questi campi:

| Campo | Tipo | Significato |
|---|---|---|
| `message` | str | nome del messaggio (`access`, `get-configuration`, ...) |
| `message-type` | str | `request`, `response` o `notification` |
| `message-id` | int | numero progressivo, correla richiesta e risposta |
| `response-code` | int | nelle risposte: 200 = ok |
| `response-string` | str | descrizione testuale dell'esito |
| `notification-code` / `notification-string` | int / str | come sopra, per i messaggi spontanei del dispositivo |

## UAUT - autenticazione [D]

Richiesta:

```json
{ "message": "access", "user-token": "0123456789abcdef0123456789abcdef",
  "message-type": "request", "message-id": 2 }
```

Risposta: `response-code` 200 e `response-string` "Access Granted". Il `user-token` è 32 caratteri esadecimali, statico. Se il dispositivo richiede cifratura la rifiutiamo (vedi `server-info`).

## UCFG - configurazione [D]

Richiesta: `{ "message": "get-configuration", "addressbooks": "all" | "none", ... }`.

Risposta (chiavi e tipi reali):

```
response-code        int
viper-server:
  local-address      str    indirizzo del gateway ViP in LAN
  local-tcp-port     int    64100
  local-udp-port     int    64100
  remote-address     str    IP pubblico, vuoto se non configurato
  remote-tcp-port    int
  remote-udp-port    int
viper-client:
  description        str
viper-p2p:
  mqtt:
    role             str
    base             str
    server           str    broker MQTT TLS del cloud
    auth.method      [str]  metodi di autenticazione del broker
  http:
    role             str
    duuid            str    identificativo del dispositivo (deviceUuid)
  stun:
    server           [str]  server STUN/TURN del cloud
sbc:
  pm-always-on       bool   false = il dispositivo dorme da fermo
vip:
  enabled            bool
  apt-address        str    indirizzo della propria unita' (es. SB000042)
  apt-subaddress     int    sottoindirizzo (es. 1)
  logical-subaddress int
  apt-config:
    description          str
    call-divert-busy-en  bool   deviazione di chiamata se occupato
    call-divert-address  str    destinazione della deviazione
    virtual-key-enabled  bool   apertura con chiave virtuale
building-config:
  description        str
```

Con `addressbooks: all` la risposta contiene anche `vip.user-parameters`, le rubriche:

| Rubrica | Voci | Campi |
|---|---|---|
| `opendoor-address-book` | serrature | `id`, `name`, `apt-address`, `output-index` (relè 1..255), `secure-mode` (bool, opzionale) |
| `actuator-address-book` | attuatori | come sopra, più `module-index` (0..255) |
| `entrance-address-book` | posti esterni | `id`, `name`, `apt-address` |
| `rtsp-camera-address-book` | telecamere RTSP | `id`, `name`, `rtsp-url`, `rtsp-user`, `rtsp-password` |
| `apt-address-book` | altri appartamenti | voci di chiamata interna |
| `switchboard-address-book` | centralini | `id`, `name`, `apt-address` |
| `camera-address-book` | telecamere ViP | voci video |
| `direct-link-address-book` | collegamenti rapidi | fino a 4 (Link 1..4) |

Il client accetta solo voci con `id` intero >= 0 e `output-index` tra 1 e 255; i duplicati di chiave nello stesso tipo vengono rifiutati. Un obiettivo si indica con la chiave `door:<id>` o `actuator:<id>`, oppure con il nome esatto.

## INFO - informazioni sul server [D]

Richiesta: `{ "message": "server-info", ... }`. Risposta:

```
model                   str    modello interno (es. MSVF)
version                 str    firmware (es. 2.1.0)
serial-code             str    numero di serie
capabilities            [str]  elenco delle capacita' del dispositivo
user-auth-channel:
  encryption-required   bool   se true, UAUT richiede cifratura
user-admin-channel:
  encryption-required   bool
  cloud-code-login      bool
configuration-channel:
  internal-unit-cfg     bool
  direct-link-cfg       bool
  iu-buttons-cfg        bool
  api-version           int    versione dell'API di configurazione
fast-activation-channel:
  app                   bool
  internal-unit         bool
  other-device          bool
cloud-activation:
  cloud-activation-enable bool
```

I blocchi `*-channel` dichiarano cosa ogni canale supporta: utile per sapere in anticipo se UAUT vuole cifratura o quale versione di UCFG usare.

## PUSH - registrazione notifiche [D]

```json
{ "message": "push-info", "os-type": "android", "device-token": "<token FCM>",
  "bundle-id": "com.comelit.bigapp", "profile-id": "1",
  "apt-address": "SB000042", "apt-subaddress": 49, "message-type": "request", "message-id": 2 }
```

Serve a registrare il token per le notifiche push e come keepalive (l'app lo rimanda ogni 90 secondi circa). Non è necessario per aprire.

## FRCG - riconoscimento facciale [D]

Richiesta `{ "message": "rcg-get-params", ... }`. Il dispositivo risponde e poi invia una notifica:

```
rcg-params-result (notification):
  parameters:
    enable     bool
    threshold  int
```

Presente solo sui modelli con riconoscimento facciale. [R] Esistono anche `rcg-set-user`, `rcg-delete-user` e notifiche di rilevamento con immagine.

## Messaggi binari

Non sono JSON e sono descritti altrove:

- apertura porta e attuatore, eventi di chiamata e di stato: canale CTPP, vedi [PROTOCOLLO](PROTOCOL.md);
- segnalazione e flusso di una videochiamata: canali UDPM e RTPC, vedi [CHIAMATA](CHIAMATA.md).

## Chiamate al cloud (percorso remoto)

Sotto `https://api.comelitgroup.com`, con token Bearer. Dettaglio del flusso in [REMOTE_P2P](REMOTE_P2P.md).

| Endpoint | Scopo | Campi principali |
|---|---|---|
| `POST /o-auth-2/auth` + `/token` | login, restituisce `access_token` | vedi REMOTE_P2P |
| `POST /servicerest/jfs/lst` | elenco dei dispositivi dell'account | per ogni voce: `ownerUuid`, `name`, `metadata.model-id`, `permissions` |
| `POST /servicerest/jfs/get` | configurazione del dispositivo (la "carta d'identità" del collegamento) | `viper-server`, `viper-p2p` (mqtt, http.duuid, stun), come in UCFG |
| `GET /servicerest/directory/resources` | risorse smart-home | `apartments`, `units`, `switchboards`, `credentials`: **vuoti** su un impianto videocitofonico puro |
| `POST /servicerest/p2p/start` | avvia la sessione P2P | vedi REMOTE_P2P |

L'elenco `directory/resources` vuoto è la prova che su questo tipo di impianto non esiste un comando REST di apertura: l'apertura passa sempre dal protocollo ICONA dentro la sessione P2P.
