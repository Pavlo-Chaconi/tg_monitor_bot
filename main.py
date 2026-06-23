"""Точка входа: Telegram-бот с плановыми отчётами и алертами."""
import asyncio
import functools
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, ApplicationBuilder, CommandHandler

from alerts import send_alerts
from clients.prometheus import PrometheusClient
from clients.truenas import TrueNASClient
from collector import collect_prometheus, collect_truenas
from commands import cmd_alerts, cmd_help, cmd_report, cmd_restic
from config import load_config
from reports.formatter import format_full_report
from webhook import start_webhook_server
import restic_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)


async def send_report(bot, chat_id: str, prom: PrometheusClient, tn: TrueNASClient, timezone: str = "Europe/Moscow"):
    """Собирает данные, проверяет пороги и отправляет плановый отчёт."""
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

        await send_alerts(bot, chat_id, prom_data, tn_data)

        now = datetime.now(tz=ZoneInfo(timezone)).strftime("%d.%m.%Y %H:%M")
        text = format_full_report(
            prom_data,
            tn_data,
            now,
            restic_results=restic_store.all_results(),
        )

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

    builder = ApplicationBuilder().token(bot_cfg.token)
    if bot_cfg.proxy_url:
        logger.info("Telegram Bot API через прокси: %s", bot_cfg.proxy_url)
        builder = builder.proxy(bot_cfg.proxy_url).get_updates_proxy(bot_cfg.proxy_url)
    application: Application = builder.build()
    bot = application.bot

    prom = PrometheusClient(prom_cfg)
    tn   = TrueNASClient(tn_cfg)

    me = await bot.get_me()
    logger.info("Бот запущен: @%s", me.username)

    application.bot_data.update({
        "chat_id":     bot_cfg.chat_id,
        "admin_ids":   bot_cfg.admin_ids,
        "prom":        prom,
        "tn":          tn,
        "send_report": functools.partial(
            send_report, bot, bot_cfg.chat_id, prom, tn, sched_cfg.timezone
        ),
    })

    application.add_handler(CommandHandler("help",   cmd_help))
    application.add_handler(CommandHandler("report", cmd_report))
    application.add_handler(CommandHandler("alerts", cmd_alerts))
    application.add_handler(CommandHandler("restic", cmd_restic))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    logger.info("Команды бота: /report /alerts /restic /help")

    webhook_runner = await start_webhook_server(bot, bot_cfg.chat_id, sched_cfg.webhook_port)

    scheduler = AsyncIOScheduler(timezone=sched_cfg.timezone)
    scheduler.add_job(
        send_report,
        trigger=CronTrigger(
            hour=sched_cfg.report_hour,
            minute=sched_cfg.report_minute,
            timezone=sched_cfg.timezone,
        ),
        args=[bot, bot_cfg.chat_id, prom, tn, sched_cfg.timezone],
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

    await send_report(bot, bot_cfg.chat_id, prom, tn, sched_cfg.timezone)

    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown()
        await webhook_runner.cleanup()
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await prom.close()
        await tn.close()


if __name__ == "__main__":
    asyncio.run(main())
