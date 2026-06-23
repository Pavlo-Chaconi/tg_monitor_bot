# ============================================================
#  Restic retention/prune for 1C backups
#  Keeps: every daily snapshot for 31 days
#         + one weekly snapshot for 26 weeks (~6 months)
#  Run WEEKLY (e.g. Sunday 04:00)
# ============================================================

# --- Repository settings ---
$env:RESTIC_REPOSITORY    = "sftp:restic@192.168.14.163:/mnt/tank/backups/repo"
$env:RESTIC_PASSWORD_FILE = "C:\restic\repo_pass.txt"
$env:RESTIC_PROGRESS_FPS  = "1"

# SSH key from default location: %USERPROFILE%\.ssh\id_ed25519

$resticEx = "C:\restic\restic.exe"

# --- Logging ---
$logDir = "C:\restic\logs"
if (!(Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir ("prune_{0}.log" -f (Get-Date -Format "yyyy-MM-dd_HHmm"))

# --- Bot webhook (monitoring bot on Docker server) ---
$botWebhookUrl = "http://192.168.14.179:8080/api/restic"
$botHost       = "$env:COMPUTERNAME-1c-prune"   # отдельный ключ, не перезаписывает backup

function Send-BotWebhook($status) {
    try {
        $logContent = ""
        if (Test-Path $log) {
            $raw = Get-Content -Path $log -Raw -ErrorAction SilentlyContinue
            if ($raw.Length -gt 4000) { $raw = $raw.Substring($raw.Length - 4000) }
            $logContent = $raw
        }
        $payload = [ordered]@{
            host      = $botHost
            status    = $status
            log       = $logContent
            timestamp = Get-Date -Format "dd.MM.yyyy HH:mm:ss"
        } | ConvertTo-Json -Compress -Depth 5

        $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
        Invoke-RestMethod -Uri $botWebhookUrl -Method Post `
            -Body $bytes -ContentType "application/json; charset=utf-8" | Out-Null

        "Bot webhook: sent ($status)" | Tee-Object -Append $log
    } catch {
        "Bot webhook failed: $_" | Out-File -Append $log
    }
}

# ============================================================
"=== Prune started $(Get-Date -Format 'dd.MM.yyyy HH:mm:ss') ===" | Tee-Object -Append $log

# Remove stale lock if any
& $resticEx unlock 2>&1 | Tee-Object -Append $log

# Retention policy:
#   keep-last 3    -> always keep the 3 most recent snapshots (safety)
#   keep-daily 31  -> one per day for last 31 days
#   keep-weekly 26 -> one per week for last 26 weeks (~6 months)
#   tag 1c-bak     -> only 1C snapshots, not other repos
#   prune          -> physically free space
& $resticEx forget --tag 1c-bak --keep-last 3 --keep-daily 31 --keep-weekly 26 --prune `
    2>&1 | Tee-Object -Append $log
$code = $LASTEXITCODE

if ($code -eq 0) {
    "OK: prune done $(Get-Date -Format 'dd.MM HH:mm')" | Tee-Object -Append $log
    Send-BotWebhook "ok"
} else {
    "ERROR: prune failed (code $code) $(Get-Date -Format 'dd.MM HH:mm')" | Tee-Object -Append $log
    Send-BotWebhook "error"
}

"=== Prune finished $(Get-Date -Format 'dd.MM.yyyy HH:mm:ss') ===" | Tee-Object -Append $log
exit $code
