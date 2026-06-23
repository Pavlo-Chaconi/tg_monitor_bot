"""Проверка порогов метрик и отправка экстренных алертов в Telegram."""
import html as html_mod
import logging
from datetime import datetime, timedelta

from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# ── Пороги ────────────────────────────────────────────────────────────────────
CPU_CRIT       = 90.0   # %
MEM_PCT_CRIT   = 90.0   # % (node_exporter)
MEM_PRES_WARN  = 0.70   # ratio HyperV (70%)
MEM_PRES_CRIT  = 0.85   # ratio HyperV (85%)
DISK_WARN      = 85.0   # %
DISK_CRIT      = 95.0   # %
TEMP_WARN      = 45     # °C
TEMP_CRIT      = 55     # °C
COOLDOWN_HOURS = 2

_last_alerted: dict[str, datetime] = {}


def _ok(key: str) -> bool:
    """Возвращает True и сбрасывает таймер если cooldown истёк."""
    now = datetime.now()
    last = _last_alerted.get(key)
    if last is None or now - last >= timedelta(hours=COOLDOWN_HOURS):
        _last_alerted[key] = now
        return True
    return False


async def send_alerts(bot: Bot, chat_id: str, prom_data: dict, tn_data: dict) -> None:
    msgs: list[str] = []

    # ── Prometheus: инстансы ──────────────────────────────────────────────────
    for inst, m in prom_data.get("instances", {}).items():
        si = html_mod.escape(inst)

        cpu = m.get("cpu")
        if cpu is not None and cpu >= CPU_CRIT and _ok(f"cpu:{inst}"):
            msgs.append(f"🔴 <b>CPU критично</b> на <code>{si}</code>: {cpu}%")

        vm_crit = m.get("vm_crit", 0)
        if vm_crit and _ok(f"vm:{inst}"):
            msgs.append(f"🔴 <b>ВМ в критическом состоянии</b> на <code>{si}</code>: {vm_crit} шт")

        pressure = m.get("mem_pressure")
        if pressure is not None:
            if pressure >= MEM_PRES_CRIT and _ok(f"mempres_c:{inst}"):
                msgs.append(f"🔴 <b>RAM давление критично</b> на <code>{si}</code>: {round(pressure*100)}%")
            elif pressure >= MEM_PRES_WARN and _ok(f"mempres_w:{inst}"):
                msgs.append(f"🟡 <b>RAM давление высокое</b> на <code>{si}</code>: {round(pressure*100)}%")

        mem_pct = m.get("mem_pct")
        if mem_pct is not None and mem_pct >= MEM_PCT_CRIT and _ok(f"mempct:{inst}"):
            msgs.append(f"🔴 <b>RAM критично</b> на <code>{si}</code>: {mem_pct}%")

    # ── Prometheus: разделы ───────────────────────────────────────────────────
    for d in prom_data.get("disks", []):
        pct = d.get("used_pct", 0)
        mp  = html_mod.escape(d.get("mountpoint", "?"))
        si  = html_mod.escape(d.get("instance", "?"))
        key = f"{d.get('instance','')}:{d.get('mountpoint','')}"
        if pct >= DISK_CRIT and _ok(f"disk_c:{key}"):
            msgs.append(f"🔴 <b>Диск почти полон</b> <code>{mp}</code> ({si}): {pct}%")
        elif pct >= DISK_WARN and _ok(f"disk_w:{key}"):
            msgs.append(f"🟡 <b>Диск заполнен</b> <code>{mp}</code> ({si}): {pct}%")

    # ── TrueNAS: пулы ─────────────────────────────────────────────────────────
    for p in tn_data.get("pools", []):
        if (not p.get("healthy") or p.get("status") != "ONLINE") and _ok(f"pool:{p['name']}"):
            msgs.append(
                f"🔴 <b>ZFS пул деградирован</b>: "
                f"<code>{html_mod.escape(p['name'])}</code> [{html_mod.escape(p.get('status','?'))}]"
            )

    # ── TrueNAS: температуры ──────────────────────────────────────────────────
    for t in tn_data.get("temperatures", []):
        temp = t.get("temp")
        name = t.get("name", "?")
        sn   = html_mod.escape(name)
        if temp is None:
            continue
        if temp >= TEMP_CRIT and _ok(f"temp_c:{name}"):
            msgs.append(f"🔴 <b>Диск перегрет</b> <code>{sn}</code>: {temp}°C")
        elif temp >= TEMP_WARN and _ok(f"temp_w:{name}"):
            msgs.append(f"🟡 <b>Температура диска высокая</b> <code>{sn}</code>: {temp}°C")

    # ── TrueNAS: системные алерты ─────────────────────────────────────────────
    for a in tn_data.get("alerts", []):
        if a.get("level") in ("CRITICAL", "ERROR") and _ok(f"tn:{a.get('title','')}"):
            msgs.append(f"🔴 <b>TrueNAS алерт</b>: {html_mod.escape(a.get('title','?'))}")

    if not msgs:
        return

    text = "⚠️ <b>МОНИТОРИНГ — АЛЕРТЫ</b>\n\n" + "\n".join(msgs)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        logger.warning("Отправлено %d алертов", len(msgs))
    except Exception as e:
        logger.error("Ошибка отправки алертов: %s", e)
