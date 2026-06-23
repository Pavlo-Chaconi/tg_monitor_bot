"""Точка входа: Telegram-бот с плановыми отчётами."""
import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from clients.prometheus import PrometheusClient
from clients.truenas import TrueNASClient
from collector import collect_prometheus, collect_truenas
from config import load_config
from reports.formatter import format_full_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Подавляем лишние логи httpx
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)


async def send_report(bot: Bot, chat_id: str, prom: PrometheusClient, tn: TrueNASClient):
    """Собирает данные и отправляет отчёт в чат."""
    logger.info("Сбор данных для отчёта...")
    try:
        prom_data, tn_data = await asyncio.gather(
            collect_prometheus(prom),
            collect_truenas(tn),
            return_exceptions=True,
        )

        if isinstance(prom_data, Exception):
            logger.error("Prometheus сбор упал: %s", prom_data)
            prom_data = {"instances": {}, "disks": []}

        if isinstance(tn_data, Exception):
            logger.error("TrueNAS сбор упал: %s", tn_data)
            tn_data = {"system": {}, "pools": [], "temperatures": [], "alerts": []}

        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        text = format_full_report(prom_data, tn_data, now)

        # Telegram ограничивает длину сообщения — делим на части по 4096 символов
        for chunk in _split_message(text):
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
            )
        logger.info("Отчёт отправлен в чат %s", chat_id)

    except TelegramError as e:
        logger.error("Ошибка отправки в Telegram: %s", e)
    except Exception as e:
        logger.exception("Непредвиденная ошибка при отправке отчёта: %s", e)


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        chunk = text[:max_len]
        # Стараемся не разрезать посередине тега — режем по последнему \n
        cut = chunk.rfind("\n")
        if cut > 0:
            chunk = chunk[:cut]
        chunks.append(chunk)
        text = text[len(chunk):]
    return chunks


async def main():
    bot_cfg, prom_cfg, tn_cfg, sched_cfg = load_config()

    if not bot_cfg.token:
        raise ValueError("TELEGRAM_BOT_TOKEN не задан в .env")
    if not bot_cfg.chat_id:
        raise ValueError("TELEGRAM_CHAT_ID не задан в .env")

    bot = Bot(token=bot_cfg.token)
    prom = PrometheusClient(prom_cfg)
    tn = TrueNASClient(tn_cfg)

    me = await bot.get_me()
    logger.info("Бот запущен: @%s", me.username)

    scheduler = AsyncIOScheduler(timezone=sched_cfg.timezone)
    scheduler.add_job(
        send_report,
        trigger=CronTrigger(
            hour=sched_cfg.report_hour,
            minute=sched_cfg.report_minute,
            timezone=sched_cfg.timezone,
        ),
        args=[bot, bot_cfg.chat_id, prom, tn],
        id="hourly_report",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Планировщик запущен: отчёт в %s:%s (%s)",
        sched_cfg.report_hour,
        sched_cfg.report_minute,
        sched_cfg.timezone,
    )

    # Отправляем первый отчёт сразу при старте
    await send_report(bot, bot_cfg.chat_id, prom, tn)

    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown()
        await prom.close()
        await tn.close()


if __name__ == "__main__":
    asyncio.run(main())
