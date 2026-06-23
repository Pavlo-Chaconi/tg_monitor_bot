"""Мониторинг почтовых ящиков — поиск писем об оплате Яндекс 360."""
import asyncio
import email
import imaplib
import logging
import re
from datetime import date, timedelta
from email.header import decode_header
from typing import Optional

from telegram import Bot
from telegram.constants import ParseMode

from config import MailboxConfig

logger = logging.getLogger(__name__)

SENDER_FILTER = "business-info@360.yandex.ru"
SUBJECT_KEYWORDS = ["закончатся средства"]

_alerted_ids: set[str] = set()

_WORDS_TO_NUM: dict[str, int] = {
    "один": 1, "одного": 1,
    "два": 2, "двух": 2,
    "три": 3, "трёх": 3, "трех": 3,
    "четыре": 4, "четырёх": 4,
    "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6,
    "семь": 7, "семи": 7,
    "восемь": 8, "восьми": 8,
    "девять": 9, "девяти": 9,
    "десять": 10,
    "тридцать": 30, "тридцати": 30,
}


def _decode_header_str(raw: str) -> str:
    parts = decode_header(raw)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _get_body_text(msg: email.message.Message) -> str:
    parts = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if ctype == "text/html":
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text)
        parts.append(text)
    return "\n".join(parts)


def _extract_deadline(text: str) -> tuple[Optional[int], Optional[str]]:
    days: Optional[int] = None
    deadline: Optional[str] = None

    words_pat = "|".join(re.escape(w) for w in _WORDS_TO_NUM)
    m = re.search(
        r"[Чч]ерез\s+(\d+|" + words_pat + r")\s+(?:день|дня|дней)",
        text, re.IGNORECASE,
    )
    if m:
        val = m.group(1)
        days = int(val) if val.isdigit() else _WORDS_TO_NUM.get(val.lower())

    m = re.search(r"до\s+(\d{2}\.\d{2}\.\d{4})", text, re.IGNORECASE)
    if not m:
        m = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
    if m:
        deadline = m.group(1)

    return days, deadline


def _check_mailbox_sync(
    cfg: MailboxConfig, lookback_days: int = 7, skip_seen: bool = True
) -> list[dict]:
    found: list[dict] = []
    try:
        conn = imaplib.IMAP4_SSL(cfg.imap_server, cfg.imap_port, timeout=30)
        try:
            conn.login(cfg.username, cfg.password)
            conn.select("INBOX")

            since = (date.today() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
            _, nums = conn.search(None, f'(FROM "{SENDER_FILTER}" SINCE {since})')

            for num in (nums[0].split() if nums[0] else []):
                _, data = conn.fetch(num, "(RFC822)")
                if not data or not data[0] or not isinstance(data[0], tuple):
                    continue
                raw = data[0][1]
                if not isinstance(raw, bytes):
                    continue

                msg = email.message_from_bytes(raw)
                msg_id = msg.get("Message-ID", "").strip()

                if skip_seen and msg_id and msg_id in _alerted_ids:
                    continue

                subject_raw = msg.get("Subject", "")
                subject = _decode_header_str(subject_raw)

                if not any(kw.lower() in subject.lower() for kw in SUBJECT_KEYWORDS):
                    continue

                body = _get_body_text(msg)
                days_left, deadline = _extract_deadline(body)

                if skip_seen and msg_id:
                    _alerted_ids.add(msg_id)

                found.append({
                    "mailbox": cfg.label,
                    "subject": subject,
                    "days_left": days_left,
                    "deadline": deadline,
                })
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except OSError as e:
        logger.error("IMAP соединение (%s / %s): %s", cfg.label, cfg.imap_server, e)
    except imaplib.IMAP4.error as e:
        logger.error("IMAP ошибка (%s / %s): %s", cfg.label, cfg.username, e)
    except Exception:
        logger.exception("IMAP неожиданная ошибка (%s)", cfg.label)
    return found


def _format_alert(item: dict) -> str:
    lines = ["<b>Яндекс 360 — требуется оплата</b>"]
    lines.append(f"Ящик: <code>{item['mailbox']}</code>")
    if item["days_left"] is not None:
        lines.append(f"Осталось: <b>{item['days_left']} дней</b>")
    if item["deadline"]:
        lines.append(f"Срок: до {item['deadline']}")
    lines.append(f"Тема: {item['subject']}")
    return "⚠️ " + "\n".join(lines)


async def check_all_mailboxes(
    mailboxes: list[MailboxConfig], bot: Bot, chat_id: str
) -> None:
    """Плановая проверка ящиков — шлёт алерты только для новых писем."""
    loop = asyncio.get_running_loop()
    for cfg in mailboxes:
        if not cfg.enabled:
            continue
        found = await loop.run_in_executor(None, _check_mailbox_sync, cfg, 7, True)
        for item in found:
            days_left = item["days_left"]
            if days_left is not None and days_left > 7:
                continue
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=_format_alert(item),
                    parse_mode=ParseMode.HTML,
                )
                logger.info("Email алерт отправлен: %s / %s", item["mailbox"], item["subject"])
            except Exception as e:
                logger.error("Ошибка отправки email алерта: %s", e)


async def get_billing_summary(mailboxes: list[MailboxConfig]) -> str:
    """Проверка всех ящиков за 7 дней — без cooldown, для команды /billing."""
    loop = asyncio.get_running_loop()
    lines = ["<b>Мониторинг оплаты Яндекс 360</b>\n"]

    for cfg in mailboxes:
        if not cfg.enabled:
            lines.append(f"⚪ <code>{cfg.label}</code> — нет учётных данных")
            continue
        try:
            found = await loop.run_in_executor(None, _check_mailbox_sync, cfg, 7, False)
            if found:
                for item in found:
                    days_str = f"осталось {item['days_left']} дн." if item["days_left"] else "срок неизвестен"
                    dl = f" (до {item['deadline']})" if item["deadline"] else ""
                    lines.append(f"⚠️ <code>{cfg.label}</code> — {days_str}{dl}")
            else:
                lines.append(f"✅ <code>{cfg.label}</code> — писем об оплате нет (7 дней)")
        except Exception as e:
            lines.append(f"❌ <code>{cfg.label}</code> — ошибка подключения: {e}")

    return "\n".join(lines)
