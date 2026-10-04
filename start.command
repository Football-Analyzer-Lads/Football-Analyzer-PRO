#!/bin/bash
cd "$(dirname "$0")"
# Check for a new Football Analyzer release before starting.
if [ -x ".venv/bin/python" ] && [ -f "update_manager.py" ]; then
  .venv/bin/python update_manager.py
fi
PORT=8787
if [ ! -x ".venv/bin/python" ]; then
  echo "Ambiente non installato. Esegui prima install.command."
  read -p "Premi Invio per chiudere..."
  exit 1
fi
# IMPORTANT: stop any older Football Analyzer process using the same port.
# This prevents macOS from reopening an older/broken installation.
OLD_PIDS=$(lsof -ti tcp:$PORT 2>/dev/null || true)
if [ -n "$OLD_PIDS" ]; then
  echo "Chiudo eventuale vecchia istanza sulla porta $PORT..."
  kill $OLD_PIDS 2>/dev/null || true
  sleep 1
fi
nohup .venv/bin/python app.py > football_analyzer.log 2>&1 &
PID=$!
echo $PID > football_analyzer.pid
for i in {1..20}; do
  if curl -s --max-time 1 http://127.0.0.1:$PORT/api/status >/dev/null 2>&1; then
    open http://127.0.0.1:$PORT
    exit 0
  fi
  sleep 0.5
done
echo "Il server non si è avviato. Controlla football_analyzer.log"
cat football_analyzer.log | tail -30
read -p "Premi Invio per chiudere..."
exit 1