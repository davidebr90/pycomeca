# Protocollo locale ICONA (porta 64100)

English version: [docs/en/PROTOCOL.md](en/PROTOCOL.md).

Appunti sul dialogo tra client e monitor in rete locale. Provato su 6741W (modello interno `MSVF`, firmware 2.1.0). Gli indirizzi negli esempi sono fittizi.

Dove un punto viene da riferimenti pubblici per il 6701W e non è stato riprovato sul 6741W, è indicato.

## Frame

Ogni messaggio, su TCP, ha un'intestazione di 8 byte:

```
00 06        costante
LL LL        lunghezza del corpo, uint16 little-endian
CC CC        identificativo di canale, uint16 little-endian (0 = gestione canali)
00 00        riempimento
...          corpo
```

Il corpo è JSON (inizia con `{`, UTF-8, senza spazi) oppure binario.

## Apertura di un canale

Il client chiede un canale per nome sul canale 0:

```
cd ab            COMMAND (0xABCD)
01 00            sequenza, deve valere 1
07 00 00 00      tipo
55 41 55 54      nome, 4 lettere ASCII (qui "UAUT")
94 57            identificativo scelto dal client
00
[00 + lunghezza LE32 + stringa + 00]   dato extra, solo per alcuni canali
```

Il monitor risponde, sempre sul canale 0:

```
cd ab 02 00 04 00 00 00  <id LE16>  00 00
```

Da quel momento i frame del canale portano quell'identificativo nell'intestazione.

Sul campo "tipo" esistono due convenzioni: lunghezza del nome più 3 (quindi 7 per tutti i nomi di quattro lettere) oppure un valore per canale (UAUT 7, UCFG 2, INFO 20, CTPP 16, CSPB 17). Sul 6741W hanno funzionato entrambe.

Chiusura: `ef 01 03 00 02 00 00 00 <id LE16>`.

### Canali aperti dal monitor

Anche il monitor può aprire un canale verso il client, con lo stesso messaggio a sequenza 1. Il client deve confermare con la risposta a sequenza 2 che riporta l'identificativo ricevuto. In rete locale, durante una semplice apertura, non succede. Sul percorso remoto succede sempre all'inizio (canale `ECHO`) ed è obbligatorio rispondere: vedi [REMOTE_P2P.md](REMOTE_P2P.md).

## Canali

| Nome | Contenuto | Uso |
|---|---|---|
| UAUT | JSON | autenticazione con user-token |
| UCFG | JSON | configurazione e rubrica |
| INFO | JSON | modello, versione, capacità |
| PUSH | JSON | registrazione notifiche |
| CTPP | binario | eventi di chiamata, apertura porta |
| CSPB | binario | accompagna CTPP nell'ascolto continuo |
| ECHO | binario | mantenimento della sessione remota |

## Sessione minima

```
UAUT  -> {"message":"access","user-token":"<32 hex>","message-type":"request","message-id":2}
      <- "response-code":200
UCFG  -> {"message":"get-configuration","addressbooks":"all","message-type":"request","message-id":3}
      <- "response-code":200 e oggetto "vip"
INFO  -> {"message":"server-info","message-type":"request","message-id":20}
```

Nella risposta di UCFG:

- `vip.apt-address` e `vip.apt-subaddress`: indirizzo della propria unità, per esempio `SB000042` e `1`;
- `vip.user-parameters.opendoor-address-book`: voci `{id, name, apt-address, output-index}`;
- `vip.user-parameters.actuator-address-book`: come sopra, con in più `module-index`.

Il client rifiuta la sessione se il monitor dichiara `encryption-required`.

## Messaggi CTPP

Forma generale:

```
[prefisso LE16][contatore LE32][azione BE16][parametro BE16] ... ff ff ff ff [chiamante\0][destinatario\0]
```

Attenzione: prefisso e contatore sono little-endian, azione e parametro big-endian. Gli indirizzi sono ASCII terminati da zero dopo il separatore `ff ff ff ff`.

| Prefisso | Significato |
|---|---|
| 0x18C0 | inizio (registrazione o chiamata) |
| 0x1800 | conferma |
| 0x1820 | conferma della conferma |
| 0x1840 | segnalazione di chiamata |
| 0x1860 | eventi di stato |

Azioni su 0x1860: `0x0001` squillo, `0x0003` porta aperta, `0x0010` rinnovo della registrazione. Solo `0x0003` è stato verificato sul 6741W; le altre vengono dai riferimenti pubblici.

## Apertura del portone

Con nessun canale CTPP già aperto:

1. aprire CTPP con dato extra uguale a indirizzo più sottoindirizzo (per esempio `SB0000421`);
2. inviare la registrazione (prefisso 0x18C0);
3. inviare la sequenza: richiesta (0x1800), conferma (0x1820), inizio apertura (0x18C0 con indirizzo del posto esterno e relè), richiesta, conferma;
4. leggere per un paio di secondi: il monitor emette `0x1860 / 0x0003` con l'indirizzo del posto esterno.

L'evento al punto 4 è ciò che il client riporta come `opened_confirmed`. Non va confermato a sua volta. Indica che il dispositivo ha eseguito, non che la serratura si sia mossa.

Per un attuatore la sequenza è più corta (inizio, richiesta, conferma) ed è stata ricavata solo per modulo 255 e relè 1: il client rifiuta altri valori invece di tentare.

Esiti possibili: `opened_confirmed`, `sent_unconfirmed` (inviato, nessun evento di ritorno), `delivery_uncertain` (errore durante l'invio: il comando non viene ripetuto).

## Altre porte del monitor

| Porta | Uso |
|---|---|
| 64100 TCP/UDP | ICONA |
| 24199 UDP | scoperta: inviando `INFO` il monitor risponde con i propri dati |
| 8080 / 8443 | pagina web di amministrazione |

## Sequenza di apertura byte per byte [D]

Questi sono i byte che il client invia davvero per aprire, verificati dal vivo sul 6741W. Indirizzi anonimizzati: unità interna `SB000042`, posto esterno `SB100007`, relè 1.

Elementi comuni:

```
caller      = "SB0000421" + 00      (indirizzo unita' + numero relè, poi zero)
destination = "SB100007"  + 00
suffix      = ff ff ff ff  + caller + destination + 00
```

Nota: il "caller" usa il numero di **relè** come suffisso, non il sottoindirizzo dell'unità. È una particolarità confermata sul filo.

Prima si apre il canale CTPP e si invia la **registrazione transiente**:

```
c0 18 5c 8b 2b 73 00 11 00 40  [capability]  caller  10 0e 00 00 00 00 ff ff ff ff  caller  "SB000042" 00  00
```

dove `capability` è `ac 23` (profilo classic) o `18 c2`. Poi la **sequenza porta** (5 frame), nell'ordine richiesta, conferma, init, richiesta, conferma:

```
richiesta : 00 18 5c 8b 2c 74 00 00                          suffix     (prefisso 0x1800)
conferma  : 20 18 5c 8b 2c 74 00 00                          suffix     (prefisso 0x1820)
init      : c0 18 70 ab 29 9f 00 0d 00 2d  destination 00  [relè LE32]  suffix   (prefisso 0x18C0, azione 0x000d)
```

Per un **attuatore** (solo modulo 255, relè 1) la sequenza è di 3 frame (init, richiesta, conferma):

```
init      : c0 18 45 be 8f 5c 00 04 00 20 ff 01   suffix
richiesta : 00 18 45 be 8f 5c 00 04               suffix
conferma  : 20 18 45 be 8f 5c 00 04               suffix
```

Dopo l'invio si legge per circa due secondi: la conferma è l'evento `0x1860 / 0x0003` che nomina il posto esterno. Quei frame iniziali con timestamp fisso (`5c 8b 2c 74`, `45 be 8f 5c`, ...) sono costanti riproducibili usate dal client; il dispositivo li accetta e apre.

## Elenco completo dei canali

Oltre a quelli usati nella sessione minima, l'app apre o incontra anche questi. Dove non ancora riprovato sul 6741W è marcato [R] (riferimento 6701W).

| Nome | Id enum | Campo "tipo" | Uso |
|---|---|---|---|
| INFO | 0 | 20 | informazioni sul server |
| PUSH | 1 | 2 | notifiche |
| ECHO | 2 | 7 | mantenimento sessione remota |
| UAUT | 3 | 7 | autenticazione |
| UADM | 4 | - | amministrazione utenti [R] |
| UCFG | 5 | 2 | configurazione |
| FACT | 6 | - | impostazioni di fabbrica [R] |
| CTPP | 7 | 16 | eventi e apertura |
| CSPB | 8 | 17 | accompagna CTPP |
| ECHO_SRV | 9 | - | eco lato server [R] |
| FRCG | 10 | 7 | riconoscimento facciale |
| UDPM | - | - | controllo media in chiamata [R] |
| RTPC, RTPC2 | - | - | flusso RTP in chiamata [R] |

Il campo "tipo" è quello osservato in chiaro (per nomi di quattro lettere vale spesso 7). I canali media si aprono con un byte finale a 1.

## Canale ECHO

Sul percorso remoto il dispositivo apre un canale ECHO verso il client e lo usa come keepalive. Osservato in chiaro sul 6741W [D]: scambia frame di testo.

- frame "echo" da 29 byte, ASCII, con un orario ISO 8601: `echo 2026-01-01T12:00:00.000Z`;
- un frame `KEEP-ALIVE` (testo ASCII) sul canale assegnato.

Il client deve confermare l'apertura del canale (vedi "Canali aperti dal monitor"). Per sessioni lunghe conviene rispondere ai frame echo; per una singola apertura basta confermarne l'apertura e ignorare i keepalive successivi.

## CTPP: i tre regimi di timestamp

Il canale CTPP usa tre modi diversi di calcolare l'orario nelle conferme. Mescolarli fa smettere il dispositivo di inviare eventi, in silenzio.

1. **Conferma di evento** (per ogni `0x18C0`, `0x1840`, `0x1860` che non sia un rinnovo): si deriva dall'orario del dispositivo, ponendo il bit alto del primo byte e scambiando due byte con un incremento. [R]
2. **Conferma di rinnovo** (`0x1860 / 0x0010`): si deriva dal proprio orario di init sommando una costante fissa (`0x01010000`); va risposta con la coppia `0x1800` poi `0x1820`. Mai derivarla dall'orario del dispositivo. Un errore qui spegne tutti gli eventi senza segnalazione. [R]
3. **Contatori di chiamata** (impostazione video): incrementi per singolo byte del campo a 32 bit; l'orario iniziale della chiamata deve differire da quello dell'init nei byte 2-3, o la chiamata è rifiutata. [R]

Regola d'oro: l'evento di porta aperta `0x1860 / 0x0003` non va mai confermato; ogni conferma viene rifiutata e il dispositivo lo ritrasmette qualche volta prima di smettere. Per questo se ne vedono circa tre. [D]

## Ascolto continuo degli eventi

Per ricevere squillo e apertura in modo continuo, invece di aprire un CTPP transiente per ogni apertura si tiene aperto un CTPP (più CSPB) e si gestisce il rinnovo della registrazione. [R]

1. aprire CTPP e CSPB;
2. inviare la registrazione iniziale (`0x18C0` con la capacità `0x18C2` sul 6741W [D], `0xAC23` su altri riferimenti);
3. il dispositivo risponde `0x1800` ed entra nel ciclo di rinnovo;
4. a ogni `0x1860 / 0x0010` rispondere con la coppia di conferme usando il regime 2 dei timestamp;
5. gli squilli arrivano come `0x18C0` oppure `0x1860 / 0x0001`; l'apertura come `0x1860 / 0x0003`.

Per un ascolto sempre attivo in casa conviene un sottoindirizzo dedicato, così il telefono che condivide lo stesso token non viene espulso. [R]

## Non coperto in PyCOMECA

L'ascolto continuo degli eventi e la chiamata video/audio (canali UDPM/RTPC, RTP, H.264, G.711 A-law) sono qui documentati ma non implementati. Il dettaglio è in [CHIAMATA](CHIAMATA.md). I riferimenti pubblici per il 6701W li descrivono; sul 6741W restano in gran parte da riprovare.
