# ============================================================
#  Restic backup 1C databases -> TrueNAS
#  Runs under local server admin via Task Scheduler at 02:00
# ============================================================

# --- Repository settings ---
$env:RESTIC_REPOSITORY    = "sftp:restic@192.168.14.163:/mnt/tank/backups/repo"
$env:RESTIC_PASSWORD_FILE = "C:\restic\repo_pass.txt"
$env:RESTIC_PROGRESS_FPS  = "1"

# SSH key from default location: %USERPROFILE%\.ssh\id_ed25519

# --- Source and binary ---
$source   = "\\192.168.14.57\backup"
$resticEx = "C:\restic\restic.exe"

# --- Logging ---
$logDir = "C:\restic\logs"
if (!(Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir ("backup_{0}.log" -f (Get-Date -Format "yyyy-MM-dd_HHmm"))

# --- Bot webhook (monitoring bot on Docker server) ---
$botWebhookUrl = "http://192.168.14.179:8080/api/restic"
$botHost       = "$env:COMPUTERNAME-1c-backup"   # ключ в отчёте

function Send-BotWebhook($status) {
    try {
        $logContent = ""
        if (Test-Path $log) {
            $raw = Get-Content -Path $log -Raw -ErrorAction SilentlyContinue
            # Передаём последние 4000 символов — лог может быть большим
            if ($raw.Length -gt 4000) { $raw = $raw.Substring($raw.Length - 4000) }
            $logContent = $raw
        }
        $payload = [ordered]@{
            host      = $botHost
            status    = $status
            log       = $logContent
            timestamp = Get-Date -Format "dd.MM.yyyy HH:mm:ss"
        } | ConvertTo-Json -Compress -Depth 5

        # Явно UTF-8, чтобы кириллица в логах не ломалась
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
        Invoke-RestMethod -Uri $botWebhookUrl -Method Post `
            -Body $bytes -ContentType "application/json; charset=utf-8" | Out-Null

        "Bot webhook: sent ($status)" | Tee-Object -Append $log
    } catch {
        "Bot webhook failed: $_" | Out-File -Append $log
    }
}

# ============================================================
"=== Backup started $(Get-Date -Format 'dd.MM.yyyy HH:mm:ss') ===" | Tee-Object -Append $log

# 1) Mount the share
net use $source /persistent:no 2>&1 | Tee-Object -Append $log

# 2) Remove stale lock
& $resticEx unlock 2>&1 | Tee-Object -Append $log

# 3) Run backup
& $resticEx backup $source --tag 1c-bak 2>&1 | Tee-Object -Append $log
$backupCode = $LASTEXITCODE

# 4) Result
if ($backupCode -eq 0) {
    "OK: 1C backup succeeded $(Get-Date -Format 'dd.MM HH:mm')" | Tee-Object -Append $log
    Send-BotWebhook "ok"
} else {
    "ERROR: 1C backup failed (code $backupCode) $(Get-Date -Format 'dd.MM HH:mm')" | Tee-Object -Append $log
    Send-BotWebhook "error"
}

"=== Backup finished $(Get-Date -Format 'dd.MM.yyyy HH:mm:ss') ===" | Tee-Object -Append $log
exit $backupCode
