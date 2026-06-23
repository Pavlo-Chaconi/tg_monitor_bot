#!/bin/bash
# Запускать после restic backup. Передаёт результат боту.
#
# Использование:
#   restic backup /data 2>&1 | tee /var/log/restic_last.log
#   bash restic_hook.sh
#
# Или однострочником:
#   restic backup /data > /var/log/restic_last.log 2>&1; bash restic_hook.sh $?

BOT_WEBHOOK="http://192.168.14.179:8080/api/restic"
LOG_FILE="${RESTIC_LOG_FILE:-/var/log/restic_last.log}"
HOST="$(hostname)"
EXIT_CODE="${1:-0}"  # передать $? после restic, иначе считаем успехом

if [ "$EXIT_CODE" -eq 0 ]; then
  STATUS="ok"
else
  STATUS="error"
fi

LOG=""
if [ -f "$LOG_FILE" ]; then
  LOG=$(tail -c 4000 "$LOG_FILE")
fi

TIMESTAMP="$(date '+%d.%m.%Y %H:%M:%S')"

# Собираем JSON и отправляем боту
python3 - <<EOF
import json, urllib.request, sys

payload = json.dumps({
    "host":      "$HOST",
    "status":    "$STATUS",
    "log":       """$LOG""",
    "timestamp": "$TIMESTAMP",
}).encode("utf-8")

req = urllib.request.Request(
    "$BOT_WEBHOOK",
    data=payload,
    headers={"Content-Type": "application/json"},
)
try:
    urllib.request.urlopen(req, timeout=10)
    print("restic_hook: отправлено ($STATUS)")
except Exception as e:
    print(f"restic_hook: ошибка отправки: {e}", file=sys.stderr)
    sys.exit(1)
EOF
