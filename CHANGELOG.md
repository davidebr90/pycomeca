# Changelog

Tutte le modifiche rilevanti del progetto. / Notable changes to the project.

## 0.1.0 - 2026-10-05

Prima versione pubblica. / First public release.

### Aggiunto / Added

- Client locale ICONA (porta 64100): autenticazione, lettura configurazione, apertura porta e attuatore con evento di conferma. Verificato dal vivo su Comelit 6741W (`MSVF`). / Local ICONA client: authentication, configuration read, door and actuator opening with a confirmation event. Verified live on a Comelit 6741W (`MSVF`).
- Trasporto remoto `pycomeca.remote` (cloud P2P `viper_p2p_v2`): login OAuth, `p2p/start`, ICE, PseudoTCP compatibile libnice, tutto in libreria standard. Lettura configurazione verificata dal vivo, anche forzando il relay pubblico (`--relay-only`). / Remote transport over cloud P2P: OAuth login, `p2p/start`, ICE, libnice-compatible PseudoTCP, standard library only. Configuration read verified live, including forcing the public relay.
- `relay/`: alternativa senza cloud Comelit (pagina PHP su hosting + agente in casa con sole connessioni in uscita). / An alternative without the Comelit cloud (PHP page on hosting + in-home agent, outbound only).
- Documentazione bilingue (IT/EN): protocollo, catalogo messaggi e parametri, percorso remoto, videochiamata, metodo di studio, dati necessari. / Bilingual documentation (IT/EN): protocol, message and parameter catalog, remote path, video call, study method, required data.
- 37 test automatici che girano senza citofono. / 37 automated tests that run without an intercom.

### Note di studio / Study notes

- Specifica del protocollo ricavata da reverse engineering dell'app ufficiale (analisi statica, mitmproxy, Frida) e da catture del dispositivo reale, anonimizzate. / Protocol spec derived from reverse engineering of the official app (static analysis, mitmproxy, Frida) and from captures of the real device, anonymised.
- Dalla cattura di una videochiamata reale: segnalazione, codec, risoluzioni (800x480 / 320x240) e apertura durante la chiamata osservate [D]; video in arrivo (RTP PT99 H.264 incapsulato in ICONA su UDP grezzo) osservato [D]; audio bidirezionale non presente nella cattura, resta [R]. / From a real video-call capture: signalling, codec, resolutions and in-call opening observed [D]; incoming video observed [D]; bidirectional audio not present, stays [R].

Livelli di evidenza: **[D]** osservato sul 6741W, **[R]** da riferimenti pubblici per il 6701W non ancora riprovati. / Evidence levels: **[D]** observed on the 6741W, **[R]** from public 6701W references not yet re-tested.
