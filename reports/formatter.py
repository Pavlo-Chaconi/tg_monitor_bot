"""Форматирование данных в читаемые Telegram-сообщения (HTML)."""
import html
from datetime import timedelta
from typing import Optional


def _uptime_str(seconds: Optional[float]) -> str:
    if seconds is None:
        return "?"
    td = timedelta(seconds=int(seconds))
    days = td.days
    hours, rem = divmod(td.seconds, 3600)
    minutes = rem // 60
    return f"{days}д {hours}ч {minutes}м"


def _bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _pct_emoji(pct: float) -> str:
    if pct >= 90:
        return "🔴"
    if pct >= 70:
        return "🟡"
    return "🟢"


def _temp_emoji(temp: Optional[float]) -> str:
    if temp is None:
        return "❓"
    if temp >= 55:
        return "🔴"
    if temp >= 45:
        return "🟡"
    return "🟢"


def format_prometheus_report(data: dict) -> str:
    """Собирает раздел Prometheus в HTML-строку."""
    lines = ["<b>📊 Prometheus — системные метрики</b>"]

    instances = data.get("instances", {})
    if not instances:
        lines.append("  <i>Нет данных от node_exporter</i>")
        return "\n".join(lines)

    for inst, m in instances.items():
        lines.append(f"\n<b>🖥 {html.escape(inst)}</b>")

        cpu = m.get("cpu")
        vm_cpu = m.get("vm_cpu")
        if cpu is not None:
            vm_part = f"  (ВМ: {vm_cpu}%)" if vm_cpu is not None else ""
            lines.append(f"  CPU:    {_pct_emoji(cpu)} {cpu}%{vm_part} {_bar(cpu)}")

        # Стандартные метрики RAM (node_exporter)
        mem_pct = m.get("mem_pct")
        mem_total = m.get("mem_total")
        mem_avail = m.get("mem_avail")
        if mem_pct is not None:
            mem_info = f"{round(mem_total - mem_avail, 2)}/{mem_total} ГБ" if mem_total and mem_avail else ""
            lines.append(f"  RAM:    {_pct_emoji(mem_pct)} {mem_pct}% {_bar(mem_pct)}  {mem_info}")
        elif mem_avail is not None:
            # HyperV: только свободная память и давление
            pressure = m.get("mem_pressure")
            prs_str = f"  давление: {round(pressure * 100)}%" if pressure is not None else ""
            lines.append(f"  RAM св: {mem_avail} ГБ{prs_str}")

        load = m.get("load1")
        if load is not None:
            lines.append(f"  LA 1m:  {load}")

        uptime = m.get("uptime")
        if uptime is not None:
            lines.append(f"  Uptime: {_uptime_str(uptime)}")

        # ВМ (только HyperV)
        vm_ok = m.get("vm_ok", 0)
        vm_crit = m.get("vm_crit", 0)
        if vm_ok or vm_crit:
            vm_icon = "🟢" if vm_crit == 0 else "🔴"
            lines.append(f"  ВМ:     {vm_icon} {vm_ok} ok  {vm_crit} critical")

        rx = m.get("net_rx")
        tx = m.get("net_tx")
        if rx is not None or tx is not None:
            lines.append(f"  Сеть:   ↓{rx or 0} МБ/с  ↑{tx or 0} МБ/с")

        io_r = m.get("io_read")
        io_w = m.get("io_write")
        if io_r is not None or io_w is not None:
            lines.append(f"  Диск:   R {io_r or 0} МБ/с  W {io_w or 0} МБ/с")

    # Разделы дисков
    disks = data.get("disks", [])
    if disks:
        lines.append("\n<b>💾 Разделы (Prometheus)</b>")
        for d in disks:
            pct = d["used_pct"]
            lines.append(
                f"  {_pct_emoji(pct)} <code>{html.escape(d['mountpoint'])}</code> "
                f"на {html.escape(d['instance'])} — {pct}% {_bar(pct, 8)}"
            )

    return "\n".join(lines)


def format_truenas_report(data: dict) -> str:
    """Собирает раздел TrueNAS в HTML-строку."""
    lines = ["<b>🗄 TrueNAS — хранилище</b>"]

    sysinfo = data.get("system", {})
    if sysinfo:
        lines.append(
            f"  <b>{html.escape(str(sysinfo.get('hostname', '?')))}</b> | {html.escape(str(sysinfo.get('version', '?')))}\n"
            f"  Uptime: {_uptime_str(sysinfo.get('uptime_seconds'))}\n"
            f"  CPU: {html.escape(str(sysinfo.get('cpu_model', '?')))} ({sysinfo.get('physical_cores', '?')} ядер)"
        )

    # Пулы
    pools = data.get("pools", [])
    if pools:
        lines.append("\n<b>🏊 ZFS пулы</b>")
        for p in pools:
            health_icon = "🟢" if p["healthy"] else "🔴"
            lines.append(
                f"  {health_icon} <b>{html.escape(p['name'])}</b>  [{html.escape(p['status'])}]\n"
                f"    Использовано: {p['used_gb']}/{p['size_gb']} ГБ "
                f"({p['used_pct']}%) {_bar(p['used_pct'], 8)}\n"
                f"    Свободно: {p['free_gb']} ГБ"
            )

    # Температуры дисков
    temps = data.get("temperatures", [])
    if temps:
        lines.append("\n<b>🌡 Температура дисков</b>")
        for t in temps:
            temp = t.get("temp")
            icon = _temp_emoji(temp)
            temp_str = f"{temp}°C" if temp is not None else "—"
            lines.append(f"  {icon} <code>{html.escape(t['name'])}</code>: {temp_str}")

    # Алерты TrueNAS
    alerts = data.get("alerts", [])
    if alerts:
        lines.append("\n<b>⚠️ Активные алерты TrueNAS</b>")
        for a in alerts:
            level = a.get("level", "INFO")
            icon = {"CRITICAL": "🔴", "ERROR": "🔴", "WARNING": "🟡", "INFO": "ℹ️"}.get(level, "❔")
            lines.append(f"  {icon} [{html.escape(level)}] {html.escape(a.get('title', '?'))}")
    else:
        lines.append("\n  <i>Алертов нет</i>")

    return "\n".join(lines)


def format_full_report(prometheus_data: dict, truenas_data: dict, timestamp: str) -> str:
    parts = [
        f"<b>📋 Отчёт о состоянии инфраструктуры</b>\n🕐 {timestamp}",
        "",
        format_prometheus_report(prometheus_data),
        "",
        format_truenas_report(truenas_data),
    ]
    return "\n".join(parts)
