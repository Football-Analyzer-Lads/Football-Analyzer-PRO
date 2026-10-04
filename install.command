#!/bin/bash
cd "$(dirname "$0")"
echo "Football Analyzer PRO — installazione"
echo "Versione: $(cat VERSION 2>/dev/null || echo 5.1.0)"
# Stop any previous instance on the application port before installing this copy.
OLD_PIDS=$(lsof -ti tcp:8787 2>/dev/null || true)
if [ -n "$OLD_PIDS" ]; then kill $OLD_PIDS 2>/dev/null || true; sleep 1; fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 non trovato. Installalo e riprova."
  read -p "Premi Invio per chiudere..."
  exit 1
fi
python3 -m venv .venv || exit 1
.venv/bin/python -m pip install --upgrade pip || exit 1
.venv/bin/python -m pip install -r requirements.txt || exit 1
PLIST="$HOME/Library/LaunchAgents/com.footballanalyzer.weeklyupdater.plist"
mkdir -p "$HOME/Library/LaunchAgents"
PYTHON="$PWD/.venv/bin/python"
SCRIPT="$PWD/weekly_updater.py"
LOG="$PWD/updater_launchd.log"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.footballanalyzer.weeklyupdater</string>
<key>ProgramArguments</key><array><string>$PYTHON</string><string>$SCRIPT</string></array>
<key>WorkingDirectory</key><string>$PWD</string>
<key>StartInterval</key><integer>21600</integer>
<key>StandardOutPath</key><string>$LOG</string>
<key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
# Run one immediate forced refresh; don't hide failures.
echo "Aggiornamento iniziale..."
.venv/bin/python weekly_updater.py
if [ $? -ne 0 ]; then
  echo "ERRORE: aggiornamento iniziale non riuscito. Controlla updater.log."
  read -p "Premi Invio per chiudere..."
  exit 1
fi
echo
echo "Installazione completata."
echo "Updater automatico: ogni 6 ore. Il programma forza inoltre il refresh dei dati quando la cache è più vecchia di 20 minuti."
echo "Ora puoi usare start.command."
read -p "Premi Invio per chiudere..."