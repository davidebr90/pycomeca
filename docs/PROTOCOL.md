# Protocollo locale ICONA (porta 64100)

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

## Non coperto

Ascolto continuo degli eventi con rinnovo della registrazione, chiamata video e audio (RTP, H.264, G.711 A-law). I riferimenti pubblici per il 6701W li descrivono; qui non sono implementati né verificati.
