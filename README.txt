FOOTBALL ANALYZER PRO — MACHINE FINAL

Questa build mantiene il motore predittivo e la parte analitica, ma la Dashboard è stata riprogettata: niente più card "Opportunità" e niente schedina automatica in home.

HOME / DASHBOARD
- Struttura più pulita e moderna.
- KPI stagione e stato dati in alto.
- Hero grafico.
- Solo ultime news calcio nella home.
- Feed news aggiornabile.

PREDICTOR
- xG reali quando disponibili; se il provider xG non è raggiungibile, il programma mostra una stima trasparente da tiri/tiri in porta, senza presentarla come xG provider.
- xGF/xGA e split casa/trasferta; il periodo selezionato viene applicato anche al profilo della squadra.
- Gol, tiri, tiri in porta, forma e altri segnali.
- Matrice score e mercati coerenti.
- BEST separato dal semplice valore percentuale.
- Giornate mostra tutte le partite della giornata anche quando scegli una singola linea (es. O2.5): la selezione restringe le colonne, non le partite.

ALTRE SEZIONI
- Giornate
- Player Analyzer
- Squadre
- News
- Modello

AVVIO MAC
1. Esegui install.command la prima volta.
2. Esegui start.command.
3. Apri http://127.0.0.1:8787

NOTA
Il feed news usa Google News RSS. Le news sono contesto editoriale e non vengono trasformate automaticamente in probabilità del modello.

QUOTE DI RIFERIMENTO (opzionale)
-------------------------------
Per mostrare automaticamente quote reali sulle partite future, il software usa API-Football. Bet365 viene preferito quando disponibile; se non lo è, viene usato un altro bookmaker con la migliore copertura dei mercati supportati.
1) Crea una chiave API-Football gratuita. Il piano Free include pre-match odds, statistiche e infortuni con il limite di richieste giornaliere del provider.
2) Imposta la variabile d'ambiente API_FOOTBALL_KEY prima di avviare il programma.
   macOS/Linux: export API_FOOTBALL_KEY="LA_TUA_CHIAVE"
3) Riavvia Football Analyzer e premi "Aggiorna dati".

Il programma non effettua scraping diretto dei bookmaker. Se la chiave non è configurata, vengono usate solo eventuali quote già presenti nei dati Football-Data; il BEST richiede comunque una quota di riferimento reale >= 1.40.

CONFIG RAPIDA
-------------
Per usare le quote Bet365 senza impostare variabili di sistema, copia config.example.env in config.env e inserisci:
API_FOOTBALL_KEY=LA_TUA_CHIAVE
Poi riavvia start.command.

AGGIORNAMENTI AUTOMATICI
------------------------
Questa build supporta gli aggiornamenti automatici tramite GitHub Releases.
Il controllo viene eseguito ogni volta che avvii start.command.

PRIMA INSTALLAZIONE DEL CLIENTE:
1) Crea config.env copiando config.example.env.
2) Inserisci la tua API_FOOTBALL_KEY.
3) Inserisci UPDATE_REPO=PROPRIETARIO/REPOSITORY del progetto GitHub.
4) Esegui install.command una sola volta.

Quando pubblichi una nuova GitHub Release con uno ZIP del progetto e un tag piu' alto
(es. v5.2.0), al successivo avvio start.command il programma la scarica e aggiorna
automaticamente i file dell'applicazione.

IMPORTANTISSIMO: l'updater NON sostituisce config.env, .venv, cache e log locali.
Quindi l'API key non deve essere reinserita dopo gli aggiornamenti.

Nota: il repository GitHub deve contenere una Release con uno ZIP. Il repository
puo' essere pubblico o privato solo se il client viene configurato con un metodo
di autenticazione adatto; la build standard usa le GitHub Releases pubbliche.

V5.2.0
- Team Analyzer now applies the Casa/Trasferta selector to the actual profile calculations (GF/GA, xG/xGA, shots, shots on target, corners, fouls and cards), not only the match list.
- API endpoint /api/odds-status added for diagnosing API-Football bookmaker-odds configuration without exposing the API key.
- API-Football errors/status are now retained internally instead of being silently swallowed, making odds troubleshooting easier.

V6.0.0 — Complete model build
- API-Football: bookmaker odds, league injuries/suspensions and fixture context when API_FOOTBALL_KEY is configured.
- News: team-specific Google News RSS is used only as a secondary confirmation signal. Headlines are not treated as facts; only clear availability keywords affect the model and the effect is bounded.
- Player importance is estimated from recent player history; defensive and attacking absences are applied differently.
- Home/Away team analysis recalculates statistics on the selected venue.
- The model probabilities are calculated from the score distribution. Bookmaker odds are real provider quotes when available; fair odds are 1/probability and are kept separate.
- Automatic updates use UPDATE_REPO=Football-Analyzer-Lads/Football-Analyzer-PRO and preserve config.env and local caches.