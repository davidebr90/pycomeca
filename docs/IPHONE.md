# Aprire il portone dall'iPhone, un tap

Obiettivo: un'icona (o "Ehi Siri, apri portone") che apre il portone da qualsiasi rete, senza l'app ufficiale. English version: [docs/en/IPHONE.md](en/IPHONE.md).

Il client è Python, quindi serve un'app che esegua Python sull'iPhone: **a-Shell** (gratuita). Niente altro hardware, niente hosting.

> Nota onesta: questo percorso (a-Shell che esegue il client) non è ancora stato verificato da chi scrive. Il punto incerto è se a-Shell permette i socket UDP e lo STUN che servono. Il test del passo 4 (`--list`) lo dice subito: se stampa la rubrica, funziona tutto. Se a-Shell blocca qualcosa, l'alternativa sicura è il percorso `relay/` su un vecchio Android.

## 1. Installa a-Shell

Dall'App Store installa **a-Shell** (di Nicolas Holzschuch). È un terminale con Python incluso.

## 2. Scarica PyCOMECA in a-Shell

Apri a-Shell e scrivi:

```
curl -LO https://github.com/davidebr90/pycomeca/archive/refs/heads/main.zip
unzip main.zip
cd pycomeca-main
```

Ora sei nella cartella del progetto (`~/Documents/pycomeca-main`).

## 3. I quattro parametri: cosa sono e dove si prendono

Tutti i valori sono inventati, servono solo a farti riconoscere il formato.

| Parametro | Cos'è | Dove si prende |
|---|---|---|
| `COMELIT_USER` | email del tuo account Comelit | la stessa che usi per entrare nell'app ufficiale |
| `COMELIT_PASS` | password dell'account | la stessa dell'app ufficiale |
| `COMELIT_DEVICE_UUID` | identificativo del citofono (es. `1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d-00001`) | lo scopri da solo al passo 4 con il comando `--devices` |
| `COMELIT_TOKEN` | user-token del citofono, 32 cifre esadecimali (es. `0123456789abcdef0123456789abcdef`) | dalla pagina web del citofono sulla porta 8080 (backup impostazioni, file `users.cfg`, riga tipo `9:4:"<32 esadecimali>"`), oppure dal database dell'app Android (`systems.token`). Dettagli in [DATI](DATI.md) |

## 4. Crea il file delle credenziali (prima con 3 valori)

Nella cartella `pycomeca-main` crea un file `pycomeca.conf`. Il modo più comodo: apri l'app **File** → **Su iPhone** → **a-Shell** → `pycomeca-main`, crea lì `pycomeca.conf` e incolla queste righe, mettendo i TUOI valori. Per ora **lascia stare** la riga del deviceUuid: la riempi al passo dopo.

```
COMELIT_USER=tua-email@comelit.example
COMELIT_PASS=la-tua-password
COMELIT_TOKEN=0123456789abcdef0123456789abcdef
```

In alternativa, da a-Shell, usa l'editor integrato: `vim pycomeca.conf` (`i` per scrivere, `Esc` poi `:wq` per salvare). Il file resta sul telefono, non va da nessuna parte.

## 5. Scopri il deviceUuid

In a-Shell, dentro `pycomeca-main`:

```
python -m pycomeca.remote --devices
```

Con il solo login stampa l'elenco dei tuoi citofoni, ciascuno con il suo `uuid`, il nome e il modello. Copia l'`uuid` del tuo citofono e aggiungilo al file `pycomeca.conf`:

```
COMELIT_DEVICE_UUID=<l-uuid-che-hai-copiato>
```

Ora il file ha tutti e quattro i valori.

## 6. Prova (senza aprire niente)

In a-Shell, dentro `pycomeca-main`:

```
python -m pycomeca.remote --list
```

Se stampa la configurazione con `Portone principale` (o il nome del tuo), sei connesso al citofono dal telefono: tutto funziona. Se dà errore, lancia `python -m pycomeca.remote --list --verbose` e guarda a che punto si ferma (login, ICE, PseudoTCP).

## 7. Crea il comando "apri"

a-Shell mette a disposizione un'azione per i Comandi Rapidi.

1. Apri l'app **Comandi Rapidi** → **+** (nuovo).
2. Aggiungi l'azione **"Execute Command"** di a-Shell (cerca "a-Shell").
3. Come comando scrivi, su una riga sola:

   ```
   cd ~/Documents/pycomeca-main && python -m pycomeca.remote --open "Portone principale"
   ```

4. In alto dai il nome **"Apri portone"** e salva. Il nome diventa la frase per Siri.

Al primo avvio iOS potrebbe chiedere il permesso di rete una volta: consenti.

## 8. Rendilo un tap, come preferisci

- **Icona sulla Home**: nel comando, menu condividi → **Aggiungi a schermata Home**. Un tap sull'icona apre.
- **Siri**: di' **"Ehi Siri, apri portone"**, anche a schermo bloccato.
- **Tasto Azione** (iPhone 15 Pro e successivi): Impostazioni → Tasto Azione → Comando Rapido → "Apri portone".
- **Tocca indietro**: Impostazioni → Accessibilità → Tocco → Tocca indietro → doppio tocco → "Apri portone". Due colpetti sul retro.

## Cosa aspettarsi

- L'apertura passa dal cloud Comelit e dal relay, quindi impiega qualche secondo (tipicamente 4-8 s).
- a-Shell potrebbe comparire per un attimo mentre esegue: è normale, non è un menu.
- La risposta attesa è `"status": "opened_confirmed"`. Se esce `sent_unconfirmed` il comando è partito ma il citofono non ha rimandato l'evento: verifica se il portone è scattato.
- Se vuoi forzare sempre il percorso esterno, aggiungi al file `pycomeca.conf` la riga `PYCOMECA_RELAY_ONLY=1`.

## Se a-Shell non va

Se il passo 4 fallisce perché a-Shell blocca i socket, usa il percorso [relay/](../relay/README.md): una pagina su hosting e un vecchio Android sempre acceso in casa. In quel caso lo Shortcut diventa una semplice richiesta HTTP, che a-Shell (o anche i soli Comandi Rapidi) gestiscono senza problemi.
