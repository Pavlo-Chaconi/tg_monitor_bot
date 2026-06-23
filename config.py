from dataclasses import dataclass, field
from typing import List
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass
class MailboxConfig:
    label: str
    imap_server: str
    imap_port: int
    username: str
    password: str

    @property
    def enabled(self) -> bool:
        return bool(self.username and self.password)


@dataclass
class EmailConfig:
    mailboxes: List[MailboxConfig]
    check_interval_hours: int = 6


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


def load_config() -> tuple[BotConfig, PrometheusConfig, TrueNASConfig, SchedulerConfig, EmailConfig]:
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

    mailboxes: List[MailboxConfig] = []
    for i in (1, 2):
        username = os.getenv(f"MAIL{i}_USERNAME", "")
        if not username:
            continue
        mailboxes.append(MailboxConfig(
            label=os.getenv(f"MAIL{i}_LABEL", username),
            imap_server=os.getenv(f"MAIL{i}_IMAP_SERVER", "imap.yandex.ru"),
            imap_port=int(os.getenv(f"MAIL{i}_IMAP_PORT", "993")),
            username=username,
            password=os.getenv(f"MAIL{i}_PASSWORD", ""),
        ))
    email_cfg = EmailConfig(
        mailboxes=mailboxes,
        check_interval_hours=int(os.getenv("MAIL_CHECK_INTERVAL_HOURS", "6")),
    )

    return bot, prometheus, truenas, scheduler, email_cfg
