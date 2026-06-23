"""Клиент для Prometheus HTTP API v1 (node_exporter + windows_hyperv_exporter)."""
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

    # ─── Обнаружение инстансов ────────────────────────────────────────────────

    async def list_instances(self) -> list[str]:
        """Возвращает все инстансы кроме self-monitoring Prometheus."""
        results = await self._query_all('up{job!="prometheus"}')
        instances = []
        for r in results:
            labels = r.get("labels", r.get("metric", {}))
            inst = labels.get("instance", "")
            if inst:
                instances.append(inst)
        return instances

    # ─── CPU ──────────────────────────────────────────────────────────────────

    async def cpu_usage_percent(self, instance: str = "") -> Optional[float]:
        """Общая загрузка CPU хоста, %. Поддерживает node_exporter и HyperV."""
        flt = f'instance="{instance}",' if instance else ""
        # node_exporter
        val = await self._query(
            f'100 - (avg by (instance) (rate(node_cpu_seconds_total{{{flt}mode="idle"}}[5m])) * 100)'
        )
        if val is not None:
            return round(val, 1)
        # windows_hyperv_exporter
        flt_h = f'instance="{instance}",' if instance else ""
        val = await self._query(
            f'100 * (1 - '
            f'sum by (instance) (rate(windows_hyperv_hypervisor_logical_processor_time_total{{{flt_h}state="idle"}}[5m]))'
            f' / sum by (instance) (rate(windows_hyperv_hypervisor_logical_processor_time_total{{{flt_h}}}[5m])))'
        )
        return round(val, 1) if val is not None else None

    async def vm_cpu_usage_percent(self, instance: str = "") -> Optional[float]:
        """Загрузка CPU гостевыми ВМ, % (только HyperV)."""
        flt = f'instance="{instance}",' if instance else ""
        val = await self._query(
            f'100 * sum by (instance) (rate(windows_hyperv_hypervisor_logical_processor_time_total{{{flt}state="guest"}}[5m]))'
            f' / sum by (instance) (rate(windows_hyperv_hypervisor_logical_processor_time_total{{{flt}}}[5m]))'
        )
        return round(val, 1) if val is not None else None

    # ─── Память ───────────────────────────────────────────────────────────────

    async def memory_usage_percent(self, instance: str = "") -> Optional[float]:
        """Использование RAM, % (только node_exporter)."""
        flt = f'{{{f"instance=\"{instance}\""}}}' if instance else ""
        val = await self._query(
            f'100 - (node_memory_MemAvailable_bytes{flt} / node_memory_MemTotal_bytes{flt} * 100)'
        )
        return round(val, 1) if val is not None else None

    async def memory_total_gb(self, instance: str = "") -> Optional[float]:
        flt = f'{{{f"instance=\"{instance}\""}}}' if instance else ""
        val = await self._query(f'node_memory_MemTotal_bytes{flt}')
        return round(val / 1024**3, 2) if val is not None else None

    async def memory_available_gb(self, instance: str = "") -> Optional[float]:
        """Свободная RAM в ГБ. node_exporter или HyperV dynamic memory."""
        flt = f'{{{f"instance=\"{instance}\""}}}' if instance else ""
        val = await self._query(f'node_memory_MemAvailable_bytes{flt}')
        if val is not None:
            return round(val / 1024**3, 2)
        # HyperV: память, доступная для ВМ
        flt_h = f'{{instance="{instance}"}}' if instance else ""
        val = await self._query(
            f'windows_hyperv_dynamic_memory_balancer_available_memory_bytes{flt_h}'
        )
        return round(val / 1024**3, 2) if val is not None else None

    async def memory_pressure(self, instance: str = "") -> Optional[float]:
        """Среднее давление на память HyperV (0–1). Только HyperV."""
        flt = f'{{instance="{instance}"}}' if instance else ""
        val = await self._query(
            f'windows_hyperv_dynamic_memory_balancer_average_pressure_ratio{flt}'
        )
        return round(val, 2) if val is not None else None

    # ─── ВМ (только HyperV) ──────────────────────────────────────────────────

    async def vm_count(self, instance: str = "") -> tuple[int, int]:
        """Количество ВМ (healthy, critical). Только HyperV."""
        flt = f'instance="{instance}",' if instance else ""
        ok = await self._query(
            f'windows_hyperv_virtual_machine_health_total_count{{{flt}state="ok"}}'
        )
        crit = await self._query(
            f'windows_hyperv_virtual_machine_health_total_count{{{flt}state="critical"}}'
        )
        return (int(ok or 0), int(crit or 0))

    # ─── Прочие системные (node_exporter) ────────────────────────────────────

    async def uptime_seconds(self, instance: str = "") -> Optional[float]:
        flt = f'{{{f"instance=\"{instance}\""}}}' if instance else ""
        return await self._query(f'node_time_seconds{flt} - node_boot_time_seconds{flt}')

    async def load_avg_1m(self, instance: str = "") -> Optional[float]:
        flt = f'{{{f"instance=\"{instance}\""}}}' if instance else ""
        val = await self._query(f'node_load1{flt}')
        return round(val, 2) if val is not None else None

    # ─── Диски (node_exporter) ────────────────────────────────────────────────

    async def disk_usage_all(self) -> list[dict]:
        """Список разделов с % заполненности (node_exporter)."""
        results = await self._query_all(
            'node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs"}'
        )
        if not results:
            return []
        avail_results = await self._query_all(
            'node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs"}'
        )
        avail_map = {}
        for r in avail_results:
            labels = r.get("labels", r.get("metric", {}))
            key = (labels.get("instance"), labels.get("mountpoint"))
            avail_map[key] = float(r["value"][1])

        disks = []
        for r in results:
            labels = r.get("labels", r.get("metric", {}))
            inst = labels.get("instance", "?")
            mp = labels.get("mountpoint", "?")
            size = float(r["value"][1])
            avail = avail_map.get((inst, mp), 0)
            used_pct = round((size - avail) / size * 100, 1) if size else 0
            disks.append({
                "instance": inst,
                "mountpoint": mp,
                "device": labels.get("device", "?"),
                "used_pct": used_pct,
            })
        return disks

    async def disk_io_read_mb(self, instance: str = "") -> Optional[float]:
        flt = f'instance="{instance}",' if instance else ""
        # node_exporter
        val = await self._query(
            f'sum(rate(node_disk_read_bytes_total{{{flt}}}[5m])) / 1024 / 1024'
        )
        if val is not None:
            return round(val, 2)
        # HyperV virtual storage
        flt_h = f'{{instance="{instance}"}}' if instance else ""
        val = await self._query(
            f'sum by (instance) (rate(windows_hyperv_virtual_storage_device_bytes_read{flt_h}[5m])) / 1024 / 1024'
        )
        return round(val, 2) if val is not None else None

    async def disk_io_write_mb(self, instance: str = "") -> Optional[float]:
        flt = f'instance="{instance}",' if instance else ""
        # node_exporter
        val = await self._query(
            f'sum(rate(node_disk_written_bytes_total{{{flt}}}[5m])) / 1024 / 1024'
        )
        if val is not None:
            return round(val, 2)
        # HyperV virtual storage
        flt_h = f'{{instance="{instance}"}}' if instance else ""
        val = await self._query(
            f'sum by (instance) (rate(windows_hyperv_virtual_storage_device_bytes_written{flt_h}[5m])) / 1024 / 1024'
        )
        return round(val, 2) if val is not None else None

    # ─── Сеть ─────────────────────────────────────────────────────────────────

    async def net_rx_mb(self, instance: str = "") -> Optional[float]:
        flt = f'instance="{instance}",' if instance else ""
        # node_exporter
        val = await self._query(
            f'sum(rate(node_network_receive_bytes_total{{{flt}device!~"lo|veth.*"}}[5m])) / 1024 / 1024'
        )
        if val is not None:
            return round(val, 2)
        # HyperV virtual network adapters
        flt_h = f'{{instance="{instance}"}}' if instance else ""
        val = await self._query(
            f'sum by (instance) (rate(windows_hyperv_virtual_network_adapter_received_bytes_total{flt_h}[5m])) / 1024 / 1024'
        )
        return round(val, 2) if val is not None else None

    async def net_tx_mb(self, instance: str = "") -> Optional[float]:
        flt = f'instance="{instance}",' if instance else ""
        # node_exporter
        val = await self._query(
            f'sum(rate(node_network_transmit_bytes_total{{{flt}device!~"lo|veth.*"}}[5m])) / 1024 / 1024'
        )
        if val is not None:
            return round(val, 2)
        # HyperV virtual network adapters
        flt_h = f'{{instance="{instance}"}}' if instance else ""
        val = await self._query(
            f'sum by (instance) (rate(windows_hyperv_virtual_network_adapter_sent_bytes_total{flt_h}[5m])) / 1024 / 1024'
        )
        return round(val, 2) if val is not None else None
