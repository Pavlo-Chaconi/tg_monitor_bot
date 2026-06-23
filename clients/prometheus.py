"""Клиент для Prometheus HTTP API v1."""
import logging
from typing import Optional
import httpx
from config import PrometheusConfig

logger = logging.getLogger(__name__)


class PrometheusClient:
    def __init__(self, cfg: PrometheusConfig):
        self._base = cfg.url.rstrip("/")
        auth = (cfg.username, cfg.password) if cfg.username else None
        self._client = httpx.AsyncClient(auth=auth, timeout=10)

    async def close(self):
        await self._client.aclose()

    async def _query(self, promql: str) -> Optional[float]:
        """Выполняет instant-запрос и возвращает первое числовое значение."""
        try:
            r = await self._client.get(
                f"{self._base}/api/v1/query",
                params={"query": promql},
            )
            r.raise_for_status()
            data = r.json()
            results = data.get("data", {}).get("result", [])
            if results:
                return float(results[0]["value"][1])
        except Exception as e:
            logger.warning("Prometheus query failed [%s]: %s", promql, e)
        return None

    async def _query_all(self, promql: str) -> list[dict]:
        """Возвращает все результаты запроса."""
        try:
            r = await self._client.get(
                f"{self._base}/api/v1/query",
                params={"query": promql},
            )
            r.raise_for_status()
            return r.json().get("data", {}).get("result", [])
        except Exception as e:
            logger.warning("Prometheus query_all failed [%s]: %s", promql, e)
        return []

    # ─── Системные метрики ────────────────────────────────────────────────────

    async def cpu_usage_percent(self, instance: str = "") -> Optional[float]:
        """Средняя загрузка CPU за последние 5 минут, %."""
        flt = f'instance="{instance}"' if instance else ""
        q = f'100 - (avg by (instance) (rate(node_cpu_seconds_total{{mode="idle",{flt}}}[5m])) * 100)'
        val = await self._query(q)
        return round(val, 1) if val is not None else None

    async def memory_usage_percent(self, instance: str = "") -> Optional[float]:
        """Использование RAM, %."""
        flt = f'{{{f"instance=\"{instance}\""}}}' if instance else ""
        used = await self._query(
            f'100 - (node_memory_MemAvailable_bytes{flt} / node_memory_MemTotal_bytes{flt} * 100)'
        )
        return round(used, 1) if used is not None else None

    async def memory_total_gb(self, instance: str = "") -> Optional[float]:
        flt = f'{{{f"instance=\"{instance}\""}}}' if instance else ""
        val = await self._query(f'node_memory_MemTotal_bytes{flt}')
        return round(val / 1024**3, 2) if val is not None else None

    async def memory_available_gb(self, instance: str = "") -> Optional[float]:
        flt = f'{{{f"instance=\"{instance}\""}}}' if instance else ""
        val = await self._query(f'node_memory_MemAvailable_bytes{flt}')
        return round(val / 1024**3, 2) if val is not None else None

    async def uptime_seconds(self, instance: str = "") -> Optional[float]:
        flt = f'{{{f"instance=\"{instance}\""}}}' if instance else ""
        return await self._query(f'node_time_seconds{flt} - node_boot_time_seconds{flt}')

    async def load_avg_1m(self, instance: str = "") -> Optional[float]:
        flt = f'{{{f"instance=\"{instance}\""}}}' if instance else ""
        val = await self._query(f'node_load1{flt}')
        return round(val, 2) if val is not None else None

    # ─── Дисковые метрики ─────────────────────────────────────────────────────

    async def disk_usage_all(self) -> list[dict]:
        """Возвращает список разделов с процентом заполненности."""
        results = await self._query_all(
            '100 - (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs"} '
            '/ node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs"} * 100)'
        )
        disks = []
        for r in results:
            labels = r.get("labels", r.get("metric", {}))
            disks.append({
                "instance": labels.get("instance", "?"),
                "mountpoint": labels.get("mountpoint", "?"),
                "device": labels.get("device", "?"),
                "used_pct": round(float(r["value"][1]), 1),
            })
        return disks

    async def disk_io_read_mb(self, instance: str = "") -> Optional[float]:
        """Скорость чтения с диска за последние 5 минут, МБ/с."""
        flt = f'instance="{instance}",' if instance else ""
        val = await self._query(
            f'sum(rate(node_disk_read_bytes_total{{{flt}}}[5m])) / 1024 / 1024'
        )
        return round(val, 2) if val is not None else None

    async def disk_io_write_mb(self, instance: str = "") -> Optional[float]:
        """Скорость записи на диск за последние 5 минут, МБ/с."""
        flt = f'instance="{instance}",' if instance else ""
        val = await self._query(
            f'sum(rate(node_disk_written_bytes_total{{{flt}}}[5m])) / 1024 / 1024'
        )
        return round(val, 2) if val is not None else None

    # ─── Сетевые метрики ──────────────────────────────────────────────────────

    async def net_rx_mb(self, instance: str = "") -> Optional[float]:
        flt = f'instance="{instance}",' if instance else ""
        val = await self._query(
            f'sum(rate(node_network_receive_bytes_total{{{flt}device!~"lo|veth.*"}}[5m])) / 1024 / 1024'
        )
        return round(val, 2) if val is not None else None

    async def net_tx_mb(self, instance: str = "") -> Optional[float]:
        flt = f'instance="{instance}",' if instance else ""
        val = await self._query(
            f'sum(rate(node_network_transmit_bytes_total{{{flt}device!~"lo|veth.*"}}[5m])) / 1024 / 1024'
        )
        return round(val, 2) if val is not None else None

    # ─── Список инстансов ─────────────────────────────────────────────────────

    async def list_instances(self) -> list[str]:
        """Возвращает список всех node_exporter-инстансов."""
        results = await self._query_all('up{job="node"}')
        instances = []
        for r in results:
            labels = r.get("labels", r.get("metric", {}))
            inst = labels.get("instance", "")
            if inst:
                instances.append(inst)
        return instances
