from dataclasses import dataclass, field
from typing import List
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass
class PrometheusConfig:
    url: str = ""
    username: str = ""
    password: str = ""


@dataclass
class TrueNASConfig:
    url: str = ""
    api_key: str = ""
    # Можно использовать логин/пароль вместо API-ключа
    username: str = ""
    password: str = ""


@dataclass
class BotConfig:
    token: str = ""
    chat_id: str = ""
    admin_ids: List[str] = field(default_factory=list)
    # Прокси для Telegram API (нужен, если api.telegram.org заблокирован)
    # Форматы: socks5://host:port  http://host:port  socks5://user:pass@host:port
    proxy_url: str = ""


@dataclass
class SchedulerConfig:
    # Расписание отчётов в формате cron (часы, минуты)
    # По умолчанию: каждый час в :00
    report_hour: str = "*"
    report_minute: str = "0"
    # Часовой пояс
    timezone: str = "Europe/Moscow"
    # Порт HTTP-вебхука для приёма событий от restic и др.
    webhook_port: int = 8080


def load_config() -> tuple[BotConfig, PrometheusConfig, TrueNASConfig, SchedulerConfig]:
    bot = BotConfig(
        token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        admin_ids=[x.strip() for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip()],
        proxy_url=os.getenv("TELEGRAM_PROXY_URL", ""),
    )
    prometheus = PrometheusConfig(
        url=os.getenv("PROMETHEUS_URL", "http://localhost:9090"),
        username=os.getenv("PROMETHEUS_USERNAME", ""),
        password=os.getenv("PROMETHEUS_PASSWORD", ""),
    )
    truenas = TrueNASConfig(
        url=os.getenv("TRUENAS_URL", "http://truenas.local"),
        api_key=os.getenv("TRUENAS_API_KEY", ""),
        username=os.getenv("TRUENAS_USERNAME", ""),
        password=os.getenv("TRUENAS_PASSWORD", ""),
    )
    scheduler = SchedulerConfig(
        report_hour=os.getenv("REPORT_HOUR", "*"),
        report_minute=os.getenv("REPORT_MINUTE", "0"),
        timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        webhook_port=int(os.getenv("WEBHOOK_PORT", "8080")),
    )
    return bot, prometheus, truenas, scheduler
