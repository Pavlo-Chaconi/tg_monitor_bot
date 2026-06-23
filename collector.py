"""Сборщик данных: запрашивает Prometheus и TrueNAS и возвращает готовые dict'ы."""
import asyncio
import logging
from clients.prometheus import PrometheusClient
from clients.truenas import TrueNASClient

logger = logging.getLogger(__name__)


async def collect_prometheus(prom: PrometheusClient) -> dict:
    instances_list = await prom.list_instances()
    # Если node_exporter не настроен — пробуем собрать без фильтра по инстансу
    if not instances_list:
        instances_list = [""]

    async def fetch_instance(inst: str) -> dict:
        cpu, mem_pct, mem_total, mem_avail, load1, uptime, rx, tx, io_r, io_w = await asyncio.gather(
            prom.cpu_usage_percent(inst),
            prom.memory_usage_percent(inst),
            prom.memory_total_gb(inst),
            prom.memory_available_gb(inst),
            prom.load_avg_1m(inst),
            prom.uptime_seconds(inst),
            prom.net_rx_mb(inst),
            prom.net_tx_mb(inst),
            prom.disk_io_read_mb(inst),
            prom.disk_io_write_mb(inst),
        )
        return {
            "cpu": cpu,
            "mem_pct": mem_pct,
            "mem_total": mem_total,
            "mem_avail": mem_avail,
            "load1": load1,
            "uptime": uptime,
            "net_rx": rx,
            "net_tx": tx,
            "io_read": io_r,
            "io_write": io_w,
        }

    instances_data, disks = await asyncio.gather(
        asyncio.gather(*[fetch_instance(i) for i in instances_list]),
        prom.disk_usage_all(),
    )

    return {
        "instances": {
            (inst if inst else "default"): data
            for inst, data in zip(instances_list, instances_data)
        },
        "disks": disks,
    }


async def collect_truenas(tn: TrueNASClient) -> dict:
    sysinfo, pools, temps, alerts = await asyncio.gather(
        tn.system_info(),
        tn.pools(),
        tn.disk_temperatures(),
        tn.alerts(),
    )
    return {
        "system": sysinfo,
        "pools": pools,
        "temperatures": temps,
        "alerts": alerts,
    }
