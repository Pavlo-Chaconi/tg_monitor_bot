# ============================================================
#  Test restic webhook endpoint
#  Usage:
#    .\test_webhook.ps1          -> ok
#    .\test_webhook.ps1 error    -> triggers Telegram alert
# ============================================================

param(
    [ValidateSet("ok","error")]
    [string]$Status = "ok"
)

$webhookUrl = "http://192.168.14.179:8080/api/restic"
$hostName   = "TEST-HOST-1c-backup"

if ($Status -eq "ok") {
    $logText = "=== Backup started 23.06.2026 03:00:00 ===`n" +
               "net use \\192.168.14.57\backup /persistent:no -> OK`n" +
               "restic unlock -> no lock`n" +
               "restic backup --tag 1c-bak`n" +
               "Files: 1234 new, 56 changed, 78901 unmodified`n" +
               "Added to repo: 512.345 MiB`n" +
               "snapshot abc12345 saved`n" +
               "OK: 1C backup succeeded 23.06 03:03`n" +
               "=== Backup finished 23.06.2026 03:03:42 ==="
} else {
    $logText = "=== Backup started 23.06.2026 03:00:00 ===`n" +
               "net use \\192.168.14.57\backup -> System error 53`n" +
               "ERROR: The network path was not found.`n" +
               "restic backup failed with exit code 1`n" +
               "ERROR: 1C backup failed (code 1) 23.06 03:00`n" +
               "=== Backup finished 23.06.2026 03:00:05 ==="
}

$payload = [ordered]@{
    host      = $hostName
    status    = $Status
    log       = $logText
    timestamp = Get-Date -Format "dd.MM.yyyy HH:mm:ss"
} | ConvertTo-Json -Compress -Depth 5

Write-Host "-> POST $webhookUrl"
Write-Host "   host:   $hostName"
Write-Host "   status: $Status"
Write-Host ""

try {
    $bytes    = [System.Text.Encoding]::UTF8.GetBytes($payload)
    $response = Invoke-RestMethod -Uri $webhookUrl -Method Post `
                    -Body $bytes -ContentType "application/json; charset=utf-8"
    Write-Host "[OK] Server response: $($response | ConvertTo-Json -Compress)" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] Error: $_" -ForegroundColor Red
}

$healthUrl = $webhookUrl -replace "/api/restic", "/health"
Write-Host ""
Write-Host "-> GET $healthUrl"
try {
    $health = Invoke-RestMethod -Uri $healthUrl
    Write-Host "[OK] Health: $($health | ConvertTo-Json -Compress)" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] Health unreachable: $_" -ForegroundColor Red
}
