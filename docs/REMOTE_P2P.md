# Percorso remoto: cloud P2P (`viper_p2p_v2`)

Come l'app raggiunge il monitor da fuori casa, e come lo rifà questo client. Tutti gli indirizzi e le credenziali negli esempi sono fittizi.

## Idea di fondo

Il monitor tiene aperta da sé una connessione verso il cloud del produttore. Il cloud non esegue comandi: mette in contatto client e monitor e, se serve, inoltra i pacchetti. Il comando di apertura parte sempre dal client e arriva al monitor dentro un canale diretto tra i due.

```
client                          cloud                         monitor
  | 1. login OAuth  ------------> |                               |
  | 2. p2p/start (offerta SDP) -> | --- inoltra -->               |
  |    <- risposta SDP ---------- | <-- risposta --               |
  | 3. ICE: controlli STUN su UDP  <---------------------------->  |
  | 4. PseudoTCP sul percorso scelto <-------------------------->  |
  | 5. frame ICONA, gli stessi della rete locale <-------------->  |
```

## 1. Login

OAuth 2 con PKCE (S256) su `https://api.comelitgroup.com`:

- `POST /o-auth-2/auth` con corpo JSON (`username`, `password`, `responseType: code`, `clientId`, `redirectUri`, `scope: all`, `state`, `codeChallenge`, `codeChallengeMethod`). La risposta contiene un campo `location` con `code` e `state`.
- `POST /o-auth-2/token` in formato modulo, con `grant_type=authorization_code`, `code` e `code_verifier`. Restituisce `access_token`, valido 7 giorni.

L'identificativo client è quello pubblico dell'app, senza segreto.

## 2. `POST /servicerest/p2p/start`

```json
{
  "deviceUuid": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d-00001",
  "data": {
    "authMode": "user_viper_token",
    "secret": "<user-token, 32 hex>",
    "timeout": 10,
    "sdp": "<offerta SDP in base64>"
  },
  "protocol": { "name": "viper_p2p_v2", "version": 1 }
}
```

Risposta: `{"result":"SUCCESS","data":{"sdp":"<risposta SDP in base64>"}}`.

### Offerta (client)

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

### Risposta (monitor)

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

Osservazioni:

- le righe `m=audio ... RTP/SAVPF` sono solo di forma: non passa RTP e non c'è DTLS (nessuna riga `fingerprint`);
- il monitor offre tre tipi di candidato: `host` (utile solo in LAN), `srflx` (il suo indirizzo pubblico) e `relay` (su un server TURN del produttore). Il relay è quello che permette di funzionare dietro NAT restrittivi;
- le righe vanno terminate con CRLF.

## 3. ICE

Controlli di connettività STUN (RFC 5389 e RFC 8445) con credenziali a breve termine:

- nome utente `ufrag_remoto:ufrag_locale`, integrità HMAC-SHA1 con la `ice-pwd` del destinatario, `FINGERPRINT` in coda;
- il monitor è l'agente che controlla e nomina in modo aggressivo: mette `USE-CANDIDATE` nei propri controlli. Il client risponde, fa i propri controlli con `ICE-CONTROLLED` e accetta la coppia nominata;
- il client non alloca un proprio relay: inizia sempre lui, e il monitor risponde all'indirizzo da cui arrivano i controlli.

Prima dell'offerta il client chiede a un server STUN il proprio indirizzo pubblico, per avere un candidato `srflx`.

## 4. PseudoTCP

Sul percorso UDP scelto gira il PseudoTCP di libnice, un flusso affidabile su datagrammi. Intestazione di 24 byte, big-endian:

```
conversazione (4)   sempre 0
sequenza      (4)
conferma      (4)
byte 12       (1)   sempre 0
flag          (1)   0 = dati, 2 = controllo (osservati); 4 = reset (da libnice, non osservato)
finestra      (2)   iniziale 61440
orario        (4)   millisecondi del mittente
eco orario    (4)   ultimo orario ricevuto
```

Apertura: ciascun lato invia un segmento di controllo con sequenza 0 e un corpo di 7 byte, `00 03 01 00 fe 01 00`. Quei 7 byte occupano spazio di sequenza: il primo byte utile ha sequenza 7.

## 5. ICONA sopra PseudoTCP

Dal byte 7 in poi il flusso contiene gli stessi frame descritti in [PROTOCOL.md](PROTOCOL.md), in chiaro. Due differenze rispetto alla rete locale:

1. **Parla prima il monitor.** Appena stabilito il flusso, apre un canale `ECHO` verso il client:
   `cd ab 01 00 07 00 00 00 45 43 48 4f <id LE16> 00`
2. **Il client deve confermare prima di fare altro**, con
   `cd ab 02 00 04 00 00 00 <id LE16> 00 00`
   Tutto ciò che il client invia prima di questa conferma viene ignorato.

Dopo la conferma si procede come in locale: UAUT, UCFG, ed eventualmente CTPP per l'apertura.

Ogni 15 secondi circa il monitor invia un frame di 29 byte sul canale `ECHO`. Il client per ora lo ignora; per sessioni di pochi secondi non ha conseguenze osservate.

## Stato delle prove

| Passaggio | Stato |
|---|---|
| SDP, PseudoTCP, STUN, ICE | test automatici senza dispositivo |
| Login, `p2p/start`, ICE, PseudoTCP, UAUT, UCFG | provati sul monitor reale |
| Stessa prova passando solo dal candidato `relay` | provata (client e monitor uscivano però dallo stesso IP pubblico) |
| Da una rete diversa da quella di casa | non provato |
| Apertura del portone su questo percorso | non provata |

## Limiti e rischi

- Dipende dall'infrastruttura del produttore: login, `p2p/start` e relay. Se cambia qualcosa, il percorso remoto si ferma. Il percorso locale non ha questa dipendenza.
- Il contenuto non è cifrato dal protocollo: il user-token attraversa il relay in chiaro.
- Con un NAT simmetrico dal lato del client potrebbe servire un relay proprio, che qui non è implementato.
- Indirizzi, porte, `ufrag` e `pwd` valgono per una sola sessione.
