"""Клиент для TrueNAS SCALE/CORE REST API v2."""
import logging
from typing import Optional
import httpx
from config import TrueNASConfig

logger = logging.getLogger(__name__)


class TrueNASClient:
    def __init__(self, cfg: TrueNASConfig):
        self._base = cfg.url.rstrip("/") + "/api/v2.0"
        headers = {}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        auth = (cfg.username, cfg.password) if cfg.username and not cfg.api_key else None
        # verify=False допустимо для self-signed сертификатов в локальной сети
        self._client = httpx.AsyncClient(
            auth=auth,
            headers=headers,
            timeout=15,
            verify=False,
        )

    async def close(self):
        await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> Optional[dict | list]:
        try:
            r = await self._client.get(f"{self._base}{path}", params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning("TrueNAS GET %s failed: %s", path, e)
            return None

    async def _post(self, path: str, json=None) -> Optional[dict | list]:
        try:
            r = await self._client.post(f"{self._base}{path}", json=json)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning("TrueNAS POST %s failed: %s", path, e)
            return None

    # ─── Системная информация ─────────────────────────────────────────────────

    async def system_info(self) -> dict:
        """Возвращает hostname, версию, uptime и т.д."""
        data = await self._get("/system/info")
        if not data:
            return {}
        uptime_sec = data.get("uptimeEpoch") or data.get("uptime_seconds", 0)
        return {
            "hostname": data.get("hostname", "?"),
            "version": data.get("version", "?"),
            "uptime_seconds": uptime_sec,
            "cpu_model": data.get("cpu_model", "?"),
            "physical_cores": data.get("cores", "?"),
        }

    async def system_general(self) -> dict:
        data = await self._get("/system/general") or {}
        return {
            "timezone": data.get("timezone", "?"),
            "language": data.get("language", "?"),
        }

    # ─── Ресурсы CPU / RAM ────────────────────────────────────────────────────

    async def cpu_usage(self) -> Optional[float]:
        """Мгновенная загрузка CPU, %."""
        data = await self._get("/reporting/get_data", params={
            "graphs": '[{"name":"cpu","identifier":null}]',
            "reporting_query": '{"start":"now-30s","end":"now","aggregate":true}',
        })
        if not data:
            return None
        try:
            # TrueNAS SCALE возвращает average в поле aggregations
            agg = data[0].get("aggregations", {})
            mean = agg.get("mean", [])
            if mean:
                return round(sum(v for v in mean if v is not None) / len(mean), 1)
        except Exception:
            pass
        return None

    async def memory_info(self) -> dict:
        """Использование RAM в ГБ."""
        data = await self._get("/reporting/get_data", params={
            "graphs": '[{"name":"memory","identifier":null}]',
            "reporting_query": '{"start":"now-30s","end":"now","aggregate":true}',
        })
        if not data:
            return {}
        try:
            agg = data[0].get("aggregations", {})
            legends = data[0].get("legend", [])
            means = agg.get("mean", [])
            result = {}
            for name, val in zip(legends, means):
                if val is not None:
                    result[name] = round(val / 1024**3, 2)
            return result
        except Exception:
            return {}

    # ─── Пулы ZFS ─────────────────────────────────────────────────────────────

    async def pools(self) -> list[dict]:
        """Список ZFS пулов с состоянием и заполненностью."""
        data = await self._get("/pool") or []
        result = []
        for pool in data:
            size = pool.get("size", 0) or 0
            free = pool.get("free", 0) or 0
            used = size - free
            result.append({
                "name": pool.get("name", "?"),
                "status": pool.get("status", "?"),
                "healthy": pool.get("healthy", False),
                "size_gb": round(size / 1024**3, 2),
                "used_gb": round(used / 1024**3, 2),
                "free_gb": round(free / 1024**3, 2),
                "used_pct": round(used / size * 100, 1) if size else 0,
            })
        return result

    # ─── Диски ────────────────────────────────────────────────────────────────

    async def disks(self) -> list[dict]:
        """Список физических дисков с именем, серийником и размером."""
        data = await self._get("/disk") or []
        result = []
        for d in data:
            result.append({
                "name": d.get("name", "?"),
                "serial": d.get("serial", "?"),
                "model": d.get("model", "?"),
                "size_gb": round((d.get("size", 0) or 0) / 1024**3, 2),
                "type": d.get("type", "?"),        # HDD / SSD
                "rotationrate": d.get("rotationrate"),
            })
        return result

    async def disk_temperatures(self) -> list[dict]:
        """Температуры дисков через S.M.A.R.T."""
        disk_list = await self._get("/disk") or []
        names = [d["name"] for d in disk_list if d.get("name")]
        if not names:
            return []
        data = await self._post("/disk/temperatures", json=names) or {}
        temps = []
        if isinstance(data, dict):
            for disk_name, temp in data.items():
                temps.append({"name": disk_name, "temp": temp})
        return temps

    async def smart_results(self) -> list[dict]:
        """Последние результаты S.M.A.R.T. тестов."""
        data = await self._get("/smart/test/results") or []
        result = []
        for item in data:
            result.append({
                "disk": item.get("disk", "?"),
                "description": item.get("description", "?"),
                "status": item.get("status", "?"),
                "lifetime": item.get("lifetime", "?"),
            })
        return result

    # ─── Алерты ───────────────────────────────────────────────────────────────

    async def alerts(self) -> list[dict]:
        """Активные алерты TrueNAS."""
        data = await self._get("/alert/list") or []
        result = []
        for a in data:
            result.append({
                "level": a.get("level", "?"),
                "title": a.get("formatted", a.get("title", "?")),
                "datetime": a.get("datetime", {}).get("$date", ""),
            })
        return result
