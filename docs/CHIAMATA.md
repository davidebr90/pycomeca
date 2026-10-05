# Videochiamata: segnalazione, video e audio

Come avviene una chiamata completa col posto esterno (video e audio bidirezionale) e come scorre il media. English version: [docs/en/CALL.md](en/CALL.md).

Questa parte **non è implementata** in PyCOMECA, ma la **segnalazione** è stata osservata in chiaro su una videochiamata reale catturata sul 6741W (percorso cloud): avvio chiamata, codec, configurazione video con le risoluzioni, e apertura porta durante la chiamata. Restano da riferimento 6701W i dettagli di decodifica del media (H.264, PCMA). Livello di evidenza:

- **[D]** osservato sul 6741W (byte reali);
- **[R]** riferimento 6701W, non riprovato qui.

I frame reali (anonimizzati) sono in fondo, nella sezione "Frame osservati sul 6741W".

Il framing dei frame e i canali base sono in [PROTOCOLLO](PROTOCOL.md); i messaggi JSON in [MESSAGGI](MESSAGGI.md).

## Canali usati in chiamata

| Nome | Note |
|---|---|
| CTPP | segnalazione della chiamata e apertura porta durante la chiamata |
| UDPM | controllo del media [R] |
| RTPC, RTPC2 | flusso RTP; uno lo apre il dispositivo verso il client [R] |

I canali media si aprono come un canale di tipo UAUT ma con un byte finale (`trailing_byte`) a 1. [R]

## Avvio dal client (outbound) [D] (segnalazione)

Sequenza, a chiamata uscente verso il posto esterno:

1. `call_init` CTPP `0x18C0 / 0x0028`, con orario di chiamata uguale all'orario di init più 1;
2. apertura di UDPM, avvio del ricevitore RTP, due pacchetti di scoperta e un keepalive ogni 1,5 s;
3. negoziazione del codec: `0x1840 / 0x0008` con parametro `0x27`, scambio e conferma;
4. apertura di RTPC e RTPC2, `rtpc_link` `0x1840 / 0x000A` (senza incremento del contatore);
5. `VIDEO_CONFIG` `0x1840 / 0x001A` a 800x480: è il messaggio che fa partire il flusso RTP del dispositivo;
6. si attende l'RTPC che il dispositivo apre verso di noi e si conferma il suo link (con incremento `BYTE5`);
7. `HANGUP/ZERO` `0x1840 / 0x0000` avvia un contratto di durata di circa 30 s;
8. avvio del media, ed eventualmente `answer_peer` `0x1840 / 0x0070`.

Rinnovo del contratto (~30 s, il dispositivo invia `0x1840 / 0x0003`): si rifà la sequenza sulla stessa connessione TCP, senza riconnettere.

## Chiamata entrante (inbound) [D] segnalazione / [R] inbound non ricatturato

- **passiva**: si conferma lo squillo con un orario derivato da quello dello squillo; raffica di RTPC, UDPM e codec (parametro `0x07`); `rtpc2_ready` `0x1840 / 0x0003` con flag `0x000A` (obbligatorio); `VIDEO_CONFIG` a 320x240. Il video scorre ma la chiamata non è ancora risposta;
- **risposta**: `answer_peer` più `call_accepted` `0x1840 / 0x0002` (ruoli invertiti: qui lo manda il client). Parte l'audio (PCMA) sul canale RTPC aperto dal dispositivo.

Differenze principali tra uscente ed entrante: codec `0x27` contro `0x07`; risoluzione 800x480 contro 320x240; media di norma su UDP in uscita, su TCP in entrata per questa integrazione.

## Video [R] (parziale [D])

- parte in SD (320x240 a 192 kbps) e, dopo la risposta, l'app passa a HD 800x480 a 1000 kbps; [D] lo switch SD/HD è stato osservato;
- il tasto HD alterna a mano le due risoluzioni, cambiando risoluzione preferita e bitrate;
- il video è H.264. I NAL singoli (tipi 1..23, IDR 5, SPS 7, PPS 8) diventano Annex-B con prefisso `00 00 00 01`; i frammenti FU-A (tipo 28) si riassemblano con i bit di inizio e fine e l'header NAL ricostruito.

## Audio [R] (non presente nella nostra cattura)

Dai riferimenti 6701W, non ancora osservato sul 6741W:

- G.711 **PCMA** (A-law), 8 kHz, frame da 20 ms uguali a 160 byte esatti;
- il microfono parte muto; lo si attiva con il comando di stato del microfono;
- in uscita: timestamp +160 per frame, sequenza +1 per frame, silenzio come byte `0xD5` ripetuto.

Per vederlo dal vivo serve una chiamata realmente **risposta** con audio attivo: nella cattura di studio l'audio non è mai partito.

## RTP e media [D parziale]

Header standard RFC 3550, 12 byte, big-endian. Tipo di payload nel secondo byte: `PT=8` PCMA (audio), un tipo dinamico per H.264 (video).

Cosa è stato **osservato** sul 6741W, dalla cattura di una videochiamata sul percorso cloud:

- il media NON passa dal flusso affidabile PseudoTCP: viaggia come **UDP grezzo sullo stesso percorso ICE**, ogni pacchetto incapsulato nel framing ICONA (8 byte di header, poi l'RTP che inizia con `0x80`);
- **video dal dispositivo verso l'app**: presente, con payload type dinamico `PT=99` (H.264). [D]
- **audio**: nella nostra cattura **non presente** in nessuna direzione; nessun media è partito dall'app verso il dispositivo. La sessione era una videochiamata a senso unico (solo video in arrivo), tipica dell'emulatore dove la "risposta" con audio non viene completata.

Quindi: il trasporto del media (ICONA su UDP grezzo) e il video in arrivo sono [D]; l'audio bidirezionale e il media in uscita restano [R], da catturare su una chiamata realmente risposta.

## Esposizione

Due strade, entrambe non incluse qui: un server RTSP locale che offre H.264 e PCMA a un lettore come VLC o a go2rtc, oppure il consumo diretto delle code di NAL e audio in un'interfaccia propria.

## Frame osservati sul 6741W [D]

Da una videochiamata reale catturata sul percorso cloud. Indirizzi anonimizzati (unità interna `SB000042`, posto esterno `SB100007`), contatori e orari sostituiti con `..`. Tutti sul canale CTPP della chiamata.

`call_init` 0x18C0 / 0x0028, 72 byte:

```
c018 ....  0028 0001  SB000042\0  SB100007\0  0001 ..........  SB000042\0  4949  ffffffff  SB100007\0  SB100007\0\0
```

`codec` 0x1840 / 0x0008, 40 byte - il parametro codec è `0x0027`:

```
4018 ....  0008 0003 49  0027  000000 00  ffffffff  SB100007\0  SB100007\0\0
```

`VIDEO_CONFIG` 0x1840 / 0x001A, 60 byte - contiene le due risoluzioni, **800x480** (0x0320 x 0x01E0) e **320x240** (0x0140 x 0x00F0):

```
4018 ....  001a 0011 1432 ........  ....  ffff 00000000  [03 20][01 e0]  [01 40][00 f0]  0010 00000000  ffffffff  SB100007\0  SB100007\0\0
```

`apertura durante la chiamata` 0x1840 / 0x000D, 48 byte - singolo messaggio, param `0x002D`:

```
4018 ....  000d 002d  SB100007\0  0001 000000  ffffffff  SB100007\0  SB100007\0\0
```

`registrazione CTPP` 0x18C0 / 0x0011, 52 byte, con capacità `0x0040`:

```
c018 ....  0011 0040 ....  SB000042\0  100e 00000000  ffffffff  SB100007\0  SB000042\0\0
```

Confermati inoltre dal vivo: rinnovo registrazione 0x1860 / 0x0010, fine chiamata 0x1860 / 0x000A, `rtpc_link` 0x1840 / 0x000A, e l'ACK di apertura canale quando è il dispositivo ad aprire (`cd ab 02 00 04 00 00 00 <id> 00 00`).

## Ancora da validare sul 6741W

Il bitrate effettivo (SD/HD), il valore reale dell'incremento di rinnovo della registrazione (un valore errato spegne gli eventi in silenzio), e la decodifica del media vero (H.264 FU-A, PCMA) restano [R] finché non ripresi su cattura dedicata.
