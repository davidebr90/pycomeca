# Relay: aprire da fuori senza il cloud del produttore

Alternativa al percorso remoto P2P. Usa due pezzi:

- `bridge.php`, una pagina su un hosting qualsiasi con HTTPS. Non parla mai con il citofono: tiene in coda un solo tipo di richiesta, "apri", e ne conserva l'esito.
- `postino.py`, un piccolo agente che gira in casa su un dispositivo sempre acceso (anche un vecchio telefono Android con Termux). Interroga la pagina ogni due secondi con sole connessioni in uscita e, quando trova una richiesta, apre il portone in rete locale.

In casa non si apre nessuna porta sul router. Se le chiavi trapelano, il danno massimo è l'apertura del portone configurato: l'agente ignora qualsiasi parametro e apre solo quell'obiettivo.

## Configurazione

Genera due chiavi lunghe e diverse, per esempio con `openssl rand -hex 24`.

Sull'hosting, come variabili d'ambiente del sito:

| Variabile | Significato |
|---|---|
| `CLIENT_KEY` | chiave di chi chiede l'apertura (telefono) |
| `AGENT_KEY` | chiave dell'agente in casa |

Carica `bridge.php` e `.htaccess` in una cartella dal nome non ovvio. Il file `.htaccess` nega l'accesso al file di stato su Apache; su altri server replica la regola dal pannello.

In casa, come variabili d'ambiente dell'agente:

| Variabile | Significato |
|---|---|
| `BRIDGE_URL` | indirizzo completo di `bridge.php` |
| `AGENT_KEY` | la stessa dell'hosting |
| `COMELIT_TOKEN` | user-token del citofono, 32 caratteri esadecimali |
| `CITOFONO_HOST` | IP del citofono in LAN, per esempio `192.168.1.50` |
| `BRIDGE_TARGET` | nome dell'obiettivo da aprire, come mostrato da `--list` |

Copia accanto a `postino.py` la cartella `pycomeca/` e avvia con `python postino.py`.

## Chiamate

Tutte con l'intestazione `X-Auth` e solo in HTTPS.

| Azione | Metodo | Chiave | Effetto |
|---|---|---|---|
| `?a=open` | POST | `CLIENT_KEY` | mette in coda un'apertura |
| `?a=status` | GET | `CLIENT_KEY` | ultimo esito noto |
| `?a=poll` | GET | `AGENT_KEY` | l'agente preleva la richiesta |
| `?a=result` | POST | `AGENT_KEY` | l'agente riporta l'esito |

Una richiesta non prelevata entro 45 secondi scade. Tra due aperture accettate devono passare almeno 3 secondi. Ogni richiesta viene eseguita al massimo una volta, anche se l'agente si riavvia a metà.

## Dal telefono

Su iPhone, in Comandi Rapidi: azione "Ottieni contenuto di URL", indirizzo di `bridge.php?a=open`, metodo POST, intestazione `X-Auth` con la `CLIENT_KEY`. Il comando si può poi aggiungere alla schermata Home o richiamare con Siri usando il suo nome.
