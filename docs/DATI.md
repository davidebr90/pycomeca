# Dati necessari e loro formato

English version: [docs/en/DATA.md](en/DATA.md).

Tutti i valori di esempio sono inventati. Hanno però la stessa forma di quelli reali, così puoi riconoscere i tuoi.

## Dati che devi fornire

| Dato | Forma | Esempio fittizio | Dove si trova | Segreto |
|---|---|---|---|---|
| IP del citofono in LAN | IPv4 privato | `192.168.1.50` | elenco dispositivi del router, oppure impostazioni di rete del monitor | no |
| Porta ICONA | intero | `64100` (TCP e UDP) | fissa | no |
| user-token | 32 caratteri esadecimali | `0123456789abcdef0123456789abcdef` | database dell'app Android (`systems.token`), oppure backup dalla pagina web del monitor sulla porta 8080 (file `users.cfg`) | **sì** |
| Account Comelit | email e password | `nome@example.com` | quelle usate nell'app | **sì** |
| deviceUuid | UUID seguito da un suffisso a 5 cifre | `1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d-00001` | risposta di `jfs/get` del cloud (campo `http.duuid`), visibile anche nel corpo di `p2p/start` | riservato |

Il user-token non ha una scadenza osservata. Chi lo possiede ed è in rete locale può aprire: va trattato come una chiave.

### Come ottenere il user-token

Due strade. La prima non richiede né app né cattura.

**A) Dalla pagina web del citofono (consigliata)**

1. Trova l'IP del citofono in rete locale (nell'elenco dispositivi del router). Negli esempi usiamo `192.168.1.50`.
2. Aprilo in un browser, provando in quest'ordine:
   - `http://192.168.1.50:8080`
   - `https://192.168.1.50:8443` (il certificato non è valido: accetta l'avviso del browser per proseguire)
3. Si apre una pagina chiamata **"Extender"**. L'accesso è a **sola password**, senza nome utente. La password di fabbrica dell'installatore è **`comelit`**. Se qualcuno l'ha cambiata, usa quella impostata.
4. Vai nella sezione **Backup / Ripristino** e scarica il backup della configurazione (un file `.tar` o `.tar.gz`).
5. Estrai l'archivio; dentro trovi `users.cfg` (potrebbe essere compresso con gzip: decomprimilo). Cerca una riga con il formato:

   ```
   9:4:"0123456789abcdef0123456789abcdef"
   ```

   Le 32 cifre esadecimali tra virgolette sono il tuo `user-token`.

Verificato sul 6741W: la web UI "Extender" risponde su 8080 e 8443, login a sola password. Su modelli diversi etichette e percorsi possono cambiare.

**B) Dal database dell'app Android**

Se hai accesso al file dell'app (`bigapp_db.db`), il token è nella tabella `systems`, colonna `token`. Richiede un dispositivo Android con l'app e, di solito, i permessi di root per leggere il file.

In entrambi i casi il token è un segreto: non pubblicarlo e non committarlo.

## Dati che il citofono restituisce

Li legge il client da solo con `--list`; non vanno configurati a mano.

| Dato | Forma | Esempio fittizio | Significato |
|---|---|---|---|
| Indirizzo ViP dell'unità interna | `SB` + 6 cifre | `SB000042` | il tuo monitor |
| Sottoindirizzo | intero 0..255 | `1` | distingue più dispositivi dello stesso appartamento |
| Indirizzo del posto esterno | `SB` + 6 cifre | `SB100007` | la pulsantiera al portone |
| Voce "apriporta" | nome, indirizzo, relè | `Portone principale`, `SB100007`, relè `1` | la serratura comandata dal posto esterno |
| Voce "attuatore" | nome, indirizzo, modulo, relè | `Attuatore ausiliario`, `SBIO0255`, modulo `255`, relè `1` | uscita su modulo di espansione |
| Centralino | `SBCPS` + 3 cifre | `SBCPS003` | presente solo in alcuni impianti |
| Modello e firmware | stringhe | `MSVF`, `2.1.0` | dal canale INFO |
| Numero di serie | 12 cifre | `001122334455` | identifica l'apparecchio |

L'indirizzo `SBIO0255` non è un identificativo personale: deriva dal numero di modulo (255) ed è uguale su impianti diversi.

Nei comandi, un obiettivo si indica con la chiave (`door:0`, `actuator:0`) oppure con il nome esatto mostrato da `--list`.

## Dati effimeri del percorso remoto

Generati a ogni sessione, non vanno salvati né riusati.

| Dato | Forma | Esempio fittizio |
|---|---|---|
| ice-ufrag | 8 caratteri esadecimali | `c41f08e2` |
| ice-pwd | 24 caratteri esadecimali | `3fa90d5b7c2e61840bd9a7e5` |
| Candidati ICE | IP e porta UDP con tipo `host`, `srflx` o `relay` | `203.0.113.25 21429 typ srflx` |
| Identificativo di canale | intero a 16 bit | `22420` |
| access_token OAuth | stringa opaca, dura 7 giorni | non riportato |

## Cosa non pubblicare mai

Catture di rete (`.pcap`, flussi del proxy), copie del database dell'app, il file `installation.local.json` e qualsiasi output con `--verbose` che non sia stato ricontrollato: il token compare in chiaro nel messaggio di accesso. Il file `.gitignore` del progetto esclude già questi tipi di file.
