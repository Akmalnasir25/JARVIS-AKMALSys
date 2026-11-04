#!/bin/sh
# Jalankan harness browser dalam Chrome headless dan pulangkan baris RESULT
# sahaja. --allow-file-access-from-files perlu kerana setiap harness memuatkan
# ui/stage.html dalam iframe melalui file://; tanpanya skrip iframe tak jalan
# dan --dump-dom hanya memulangkan sumber skrip, bukan hasilnya.
CHROME="/c/Program Files/Google/Chrome/Application/chrome.exe"
[ -f "$CHROME" ] || CHROME="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
for f in "$@"; do
  printf '=== %s ===\n' "$(basename "$f")"
  "$CHROME" --headless=new --disable-gpu --no-sandbox --allow-file-access-from-files \
    --virtual-time-budget=15000 --dump-dom "file:///C:/Users/akmal/jarvis-desktop/ui/$f" 2>/dev/null \
    | grep -o 'id="R">RESULT{[^<]*}' | sed 's/^id="R">//' | head -1
done
