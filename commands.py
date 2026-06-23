"""Обработчики Telegram-команд: /report, /alerts, /restic, /billing, /help."""
import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from alerts import collect_alert_lines
from collector import collect_prometheus, collect_truenas
from email_monitor import get_billing_summary
from reports.formatter import format_restic_report
import restic_store

logger = logging.getLogger(__name__)


def _is_allowed(update: Update, chat_id: str, admin_ids: list[str]) -> bool:
    if str(update.effective_chat.id) != chat_id:
        return False
    if admin_ids:
        return str(update.effective_user.id) in admin_ids
    return True


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update, context.bot_data["chat_id"], context.bot_data["admin_ids"]):
        return
    text = (
        "<b>Команды бота</b>\n\n"
        "/report — полный отчёт прямо сейчас\n"
        "/alerts — текущее состояние по порогам\n"
        "/restic — статус резервных копий\n"
        "/billing — проверка писем об оплате Яндекс 360\n"
        "/help — эта справка"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update, context.bot_data["chat_id"], context.bot_data["admin_ids"]):
        return
    await update.message.reply_text("Собираю данные...")
    await context.bot_data["send_report"]()


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update, context.bot_data["chat_id"], context.bot_data["admin_ids"]):
        return
    prom = context.bot_data["prom"]
    tn   = context.bot_data["tn"]

    await update.message.reply_text("Проверяю...")

    prom_data, tn_data = await asyncio.gather(
        collect_prometheus(prom),
        collect_truenas(tn),
        return_exceptions=True,
    )
    if isinstance(prom_data, Exception):
        prom_data = {"instances": {}, "disks": []}
    if isinstance(tn_data, Exception):
        tn_data = {"system": {}, "pools": [], "temperatures": [], "alerts": []}

    lines = collect_alert_lines(prom_data, tn_data)
    if lines:
        text = "⚠️ <b>Текущие алерты</b>\n\n" + "\n".join(lines)
    else:
        text = "✅ <b>Алертов нет</b> — все метрики в норме"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_billing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update, context.bot_data["chat_id"], context.bot_data["admin_ids"]):
        return
    mailboxes = context.bot_data.get("mailboxes", [])
    if not mailboxes:
        await update.message.reply_text(
            "<i>Мониторинг почты не настроен — задайте MAIL1_USERNAME в .env</i>",
            parse_mode=ParseMode.HTML,
        )
        return
    await update.message.reply_text("Проверяю ящики...")
    text = await get_billing_summary(mailboxes)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_restic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update, context.bot_data["chat_id"], context.bot_data["admin_ids"]):
        return
    results = restic_store.all_results()
    if not results:
        await update.message.reply_text(
            "<i>Нет данных о бэкапах — ещё не получены от restic</i>",
            parse_mode=ParseMode.HTML,
        )
        return
    await update.message.reply_text(
        format_restic_report(results).strip(),
        parse_mode=ParseMode.HTML,
    )
