# Come ci si è arrivati

English version: [docs/en/DEBUG_FLOW.md](en/DEBUG_FLOW.md).

Questo è il percorso di studio, in ordine, con gli strumenti usati e gli errori fatti. Può servire a chi vuole ripetere il lavoro su un altro modello.

## Strumenti

- Emulatore Android con accesso root e l'app ufficiale installata.
- [jadx](https://github.com/skylot/jadx) per leggere il codice dell'app.
- [mitmproxy](https://mitmproxy.org/) con certificato installato tra quelli di sistema, per il traffico HTTPS verso il cloud.
- [Frida](https://frida.re/) per osservare le chiamate dell'app mentre gira (script in `tools/frida/`).
- `tcpdump` nell'emulatore e Wireshark per il traffico UDP.
- Regole `iptables` temporanee nell'emulatore per togliere di mezzo la rete locale.

## 1. Lettura statica dell'app

Dal codice decompilato sono usciti l'indirizzo del cloud, il flusso di login OAuth con PKCE, i nomi dei canali (`UAUT`, `UCFG`, `INFO`, `CTPP`, ...) e le tre strategie di connessione che l'app prova in ordine: diretta in LAN, diretta su IP pubblico, P2P via cloud.

Primo errore: avevo concluso che l'apertura fosse una chiamata REST al cloud. Sul mio impianto l'elenco dei dispositivi "smart" restituito dal cloud è vuoto, quindi quella strada non esiste.

## 2. Traffico HTTPS

Con il proxy ho visto il login reale (endpoint, ambito, formato della risposta) e la chiamata `p2p/start`, che porta un'offerta SDP e riceve quella del citofono. Il comando di apertura però non passa da HTTP.

## 3. Osservazione con Frida

Agganciando la classe che l'app usa per parlare con il citofono ho visto in chiaro i messaggi JSON sui canali e la chiamata di apertura con indirizzo del posto esterno e relè.

Secondo errore: avevo scambiato il messaggio `access` sul canale `UAUT` per il comando di apertura. È solo l'autenticazione. L'apertura è una sequenza binaria sul canale `CTPP`.

Nota pratica: nell'emulatore il decodificatore video fa cadere l'app. Lo script `hook_bypass.js` lo scavalca, e tutto il resto (eventi, audio, apertura) resta osservabile.

## 4. Protocollo locale

Il formato dei frame sulla porta 64100 e la sequenza binaria di apertura erano già descritti da progetti pubblici per un modello vicino. Li ho riscritti in modo indipendente e provati sul mio monitor: autenticazione, lettura della configurazione, apertura, con il citofono che rimanda l'evento di porta aperta.

Da qui in poi l'apertura in casa funzionava. Restava il percorso da fuori.

## 5. Isolare il percorso remoto

Terzo errore: una prova di apertura dall'emulatore era riuscita e l'avevo presa per una conferma del percorso cloud. Guardando la tabella delle connessioni dell'emulatore c'era invece un collegamento TCP diretto verso il citofono: l'emulatore raggiunge la LAN di casa.

Per vedere davvero il percorso remoto ho bloccato nell'emulatore tutto il traffico verso l'IP locale del citofono, riavviato l'app e catturato l'UDP. Risultato:

- scambio STUN con un server pubblico e nomina di una coppia ICE;
- datagrammi con un'intestazione fissa di 24 byte, compatibile con il PseudoTCP di libnice;
- tolta l'intestazione e rimessi in ordine i segmenti, il contenuto è lo stesso flusso di frame del protocollo locale, **non cifrato**.

Quindi il percorso remoto non è un protocollo diverso: è lo stesso dialogo, trasportato su ICE e PseudoTCP.

## 6. Ricostruzione del trasporto

Dalle catture ho ricavato il testo esatto delle due SDP e la disposizione dei campi dell'intestazione PseudoTCP. Ho poi scritto SDP, STUN, ICE e PseudoTCP in Python e li ho verificati senza citofono: confronto con i byte catturati, scambio affidabile con il 30% di pacchetti persi, due agenti ICE reali su UDP, e infine il client vero che apre una porta su un dispositivo simulato.

## 7. Prima prova dal vivo e due sorprese

Alla prima prova il trasporto si è stabilito subito, ma il citofono non rispondeva. Due regole che in LAN non esistono:

1. Sul percorso remoto parla prima il citofono: apre lui un canale `ECHO` verso il client.
2. Finché quell'apertura non viene confermata, tutto ciò che il client invia viene ignorato.

L'ordine giusto l'ho trovato rileggendo la cattura dell'app: prima la conferma del canale `ECHO`, poi l'apertura di `UAUT`. Sistemato questo, la lettura della configurazione è andata a buon fine, anche forzando il passaggio dal relay pubblico.

## Lezioni utili

- Verificare sempre **quale** percorso di rete ha davvero usato una prova riuscita.
- Un valore di ritorno "ok" di una funzione dell'app non dimostra che la connessione sia operativa.
- Tenere le prove dal vivo in sola lettura finché non serve aprire, e aprire solo con qualcuno davanti alla porta.
- Annotare le ipotesi smentite: metà del tempo è andato a inseguire le prime due.
