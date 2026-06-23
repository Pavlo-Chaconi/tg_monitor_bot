"""
Smoke-тест: проверяет импорты, конфигурацию и форматтер без реальных подключений.
Завершается с кодом 0 при успехе, 1 при ошибке.
"""
import sys
import os

# Минимальный .env чтобы config.py не падал
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:test")
os.environ.setdefault("TELEGRAM_CHAT_ID", "-1")
os.environ.setdefault("PROMETHEUS_URL", "http://localhost:9090")
os.environ.setdefault("TRUENAS_URL", "http://localhost")

errors = []

def check(name, fn):
    try:
        fn()
        print(f"  [OK]  {name}")
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        errors.append(name)

# ── Импорты ──────────────────────────────────────────────────────────────────
check("import config",          lambda: __import__("config"))
check("import collector",       lambda: __import__("collector"))
check("import clients.prometheus", lambda: __import__("clients.prometheus"))
check("import clients.truenas",    lambda: __import__("clients.truenas"))
check("import reports.formatter",  lambda: __import__("reports.formatter"))

# ── Конфигурация ─────────────────────────────────────────────────────────────
from config import load_config
check("load_config()", lambda: load_config())

# ── Форматтер ────────────────────────────────────────────────────────────────
from reports.formatter import format_full_report

def test_formatter():
    prom_data = {
        "instances": {
            "server1:9100": {
                "cpu": 42.3, "vm_cpu": 35.1,
                "mem_pct": None, "mem_total": None,
                "mem_avail": 436.2, "mem_pressure": 0.34,
                "vm_ok": 14, "vm_crit": 0,
                "load1": None, "uptime": None,
                "net_rx": 1.5, "net_tx": 0.3,
                "io_read": 0.8, "io_write": 0.2,
            }
        },
        "disks": [
            {"instance": "server1:9100", "mountpoint": "/", "device": "sda1", "used_pct": 55.0}
        ],
    }
    tn_data = {
        "system": {"hostname": "truenas", "version": "24.04", "uptime_seconds": 86400,
                   "cpu_model": "Intel Xeon", "physical_cores": 8},
        "pools": [{"name": "tank", "status": "ONLINE", "healthy": True,
                   "size_gb": 20.0, "used_gb": 8.0, "free_gb": 12.0, "used_pct": 40.0}],
        "temperatures": [{"name": "sda", "temp": 38}, {"name": "sdb", "temp": 52}],
        "alerts": [],
    }
    restic_data = [
        {"host": "backup-01", "status": "ok",    "timestamp": "23.06.2026 03:00:00", "log": "snapshot abc123 saved"},
        {"host": "backup-02", "status": "error",  "timestamp": "23.06.2026 03:05:00", "log": "Fatal: unable to open repo"},
    ]
    msg = format_full_report(prom_data, tn_data, "23.06.2026 12:00", restic_results=restic_data)
    assert "<b>📋 Отчёт" in msg
    assert "server1:9100" in msg
    assert "truenas" in msg
    assert "tank" in msg
    assert "backup-01" in msg
    assert "backup-02" in msg

check("format_full_report()", test_formatter)

# ── Итог ─────────────────────────────────────────────────────────────────────
print()
if errors:
    print(f"FAILED: {len(errors)} ошибок — {errors}")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
    sys.exit(0)
