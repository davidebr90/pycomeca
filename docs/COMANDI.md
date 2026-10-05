# Riferimento dei comandi

Spiegazione puntuale di ogni opzione dei due strumenti. English version: [docs/en/COMMANDS.md](en/COMMANDS.md).

Ci sono due eseguibili:

- **`pycomeca_ctl.py`** - percorso **locale** (stessa rete del citofono, porta 64100);
- **`python -m pycomeca.remote`** - percorso **remoto** (da qualsiasi rete, via cloud P2P).

Nessuno dei due apre il portone senza un'azione di apertura esplicita (`--open`).

---

## 1. Percorso locale: `pycomeca_ctl.py`

Diagnostica e controllo sulla rete di casa. Richiede un profilo (`installation.local.json`) con l'IP del citofono, e il token via ambiente o database.

### Azioni (sceglierne una; senza nulla vale `--list`)

| Opzione | Cosa fa | Tocca il citofono |
|---|---|---|
| `--list` | legge la configurazione e la rubrica (UCFG). È il default | sì (lettura) |
| `--info` | legge modello, versione, capacità (INFO) | sì (lettura) |
| `--inventory` | mostra i dati salvati nel database dell'app, senza connettersi | no |
| `--probe` | verifica solo se la porta 64100 risponde (TCP), senza autenticare | sì (solo TCP) |
| `--discover` | invia un INFO UDP alla porta 24199 e mostra la risposta | sì (UDP) |
| `--open TARGET` | **apre** la serratura o l'attuatore indicato (chiave `door:0` / `actuator:0` o nome) | sì, apre |
| `--decode-hex HEX` | decodifica una stringa esadecimale come frame ICONA, offline | no |
| `--analyze-captures` | analizza le catture `.mitm`/`.pcap` in una cartella, offline | no |

### Opzioni comuni

| Opzione | Significato | Default |
|---|---|---|
| `--profile FILE` | file di installazione da usare | `installation.local.json` |
| `--host IP` | forza l'IP del citofono (sovrascrive il profilo) | dal profilo |
| `--port N` | porta ICONA | 64100 |
| `--timeout SEC` | timeout di sessione | 30 |
| `--wire-profile {classic,community}` | variante di codifica del campo "tipo" dei canali | classic |
| `--system-id N` | quale sistema del database usare | 1 |
| `--from-config FILE` | lavora offline su una configurazione salvata (solo con `--list` o `--open --dry-run`) | - |
| `--dry-run` | con `--open --from-config`: mostra i byte del comando **senza inviare niente** | - |
| `--output FILE` | scrive l'esito (JSON) in un nuovo file, oltre che a schermo | - |
| `--captures-dir DIR` | cartella per `--analyze-captures` | `captures/` |
| `--debug` | log dettagliato | - |

### Variabili d'ambiente

| Variabile | Uso |
|---|---|
| `COMELIT_TOKEN` | user-token 32 esadecimali; se assente, viene letto dal database del profilo |

### Codici di uscita

| Codice | Significato |
|---|---|
| 0 | tutto ok |
| 2 | autenticazione rifiutata, errore, o uso non valido delle opzioni |
| 3 | citofono non raggiungibile (`--probe` / `--discover`) |
| 4 | comando inviato ma esito incerto (`delivery_uncertain`) |
| 130 | interrotto da tastiera |

### Esempi

```
# leggere la configurazione in LAN
python pycomeca_ctl.py --list

# aprire la serratura
python pycomeca_ctl.py --open "Portone principale"

# vedere i byte del comando senza inviarlo (offline)
python pycomeca_ctl.py --from-config config.json --open "Portone principale" --dry-run
```

---

## 2. Percorso remoto: `python -m pycomeca.remote`

Apertura e consultazione da qualsiasi rete, via cloud. Le credenziali arrivano dall'ambiente o da un file di configurazione.

### Azioni (sceglierne una)

| Opzione | Cosa fa | Serve |
|---|---|---|
| `--devices` | elenca i citofoni dell'account con il loro `uuid`, nome e modello | solo USER e PASS |
| `--list` | autentica e mostra la rubrica, senza aprire | USER, PASS, DEVICE_UUID, TOKEN |
| `--open TARGET` | **apre** il target (chiave `door:0` o nome) | USER, PASS, DEVICE_UUID, TOKEN |

### Opzioni

| Opzione | Significato |
|---|---|
| `--relay-only` | forza il percorso esterno: usa solo il candidato relay del citofono, ignora la LAN. Utile per provare da casa ciò che succederebbe da fuori |
| `--config FILE` | file `KEY=VALUE` con le credenziali |
| `--verbose` | mostra la sequenza dei passaggi (login, ICE, PseudoTCP) |

### Credenziali (da ambiente o da file)

| Chiave | Cos'è | Dove si prende |
|---|---|---|
| `COMELIT_USER` | email dell'account Comelit | la stessa dell'app ufficiale |
| `COMELIT_PASS` | password dell'account | la stessa dell'app ufficiale |
| `COMELIT_DEVICE_UUID` | identificativo del citofono | con `--devices` |
| `COMELIT_TOKEN` | user-token 32 esadecimali | pagina web del citofono (porta 8080) o database dell'app; vedi [DATI](DATI.md) |
| `PYCOMECA_RELAY_ONLY` | `1` per forzare sempre il relay (come `--relay-only`) | opzionale |

Una variabile d'ambiente già impostata ha la precedenza sul file.

### File di configurazione

Cercato in quest'ordine: `--config`, poi `PYCOMECA_CONFIG`, poi `~/.pycomeca.conf`, poi `pycomeca.conf` nella cartella corrente. Formato: righe `CHIAVE=valore`, righe vuote e `#` ignorate. Modello in `pycomeca.conf.example`.

### Codici di uscita

| Codice | Significato |
|---|---|
| 0 | tutto ok |
| 1 | errore (login, rete, o apertura non riuscita) |
| 2 | credenziali mancanti |

### Esempi

```
# scoprire il deviceUuid (bastano email e password)
python -m pycomeca.remote --devices

# leggere la rubrica dal cloud
python -m pycomeca.remote --list

# aprire da fuori, forzando il relay, con log
python -m pycomeca.remote --open "Portone principale" --relay-only --verbose

# usando un file di credenziali esplicito
python -m pycomeca.remote --open "Portone principale" --config ~/pycomeca.conf
```

Per l'uso da iPhone con un tap, vedi [IPHONE](IPHONE.md).
