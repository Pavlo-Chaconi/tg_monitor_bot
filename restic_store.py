"""Хранилище результатов restic-бэкапов (in-memory + JSON-файл для персистентности)."""
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

_DATA_FILE = os.getenv("RESTIC_DATA_FILE", "/app/data/restic_results.json")
_store: dict[str, dict] = {}


def _load() -> None:
    global _store
    try:
        if os.path.exists(_DATA_FILE):
            with open(_DATA_FILE, encoding="utf-8") as f:
                _store = json.load(f)
            logger.info("restic_store: загружено %d записей", len(_store))
    except Exception as e:
        logger.warning("restic_store: ошибка загрузки: %s", e)
        _store = {}


def _persist() -> None:
    try:
        os.makedirs(os.path.dirname(_DATA_FILE), exist_ok=True)
        with open(_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(_store, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("restic_store: ошибка сохранения: %s", e)


def save(host: str, status: str, log: str, ts: str | None = None) -> None:
    _store[host] = {
        "host": host,
        "status": status,           # "ok" | "error"
        "log": log[:4000],          # обрезаем слишком длинные логи
        "timestamp": ts or datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
    }
    _persist()
    logger.info("restic_store: %s → %s", host, status)


def all_results() -> list[dict]:
    return list(_store.values())


_load()
