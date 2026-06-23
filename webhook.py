"""HTTP-сервер для приёма push-событий от внешних систем (restic и др.)."""
import html as html_mod
import logging

from aiohttp import web
from telegram import Bot
from telegram.constants import ParseMode

import restic_store

logger = logging.getLogger(__name__)


async def _handle_restic(request: web.Request) -> web.Response:
    bot: Bot     = request.app["bot"]
    chat_id: str = request.app["chat_id"]

    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text="Bad JSON")

    host   = str(body.get("host", "unknown"))
    status = str(body.get("status", "error")).lower()
    log    = str(body.get("log", ""))
    ts     = body.get("timestamp")

    restic_store.save(host, status, log, ts)

    if status != "ok":
        safe_host = html_mod.escape(host)
        log_tail  = html_mod.escape(log[-800:]) if log else "—"
        text = (
            f"🔴 <b>Restic бэкап ОШИБКА</b>\n"
            f"Хост: <code>{safe_host}</code>\n\n"
            f"<pre>{log_tail}</pre>"
        )
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error("Telegram alert (restic) failed: %s", e)

    return web.Response(text="ok")


async def _handle_health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def start_webhook_server(bot: Bot, chat_id: str, port: int = 8080) -> web.AppRunner:
    app = web.Application()
    app["bot"]     = bot
    app["chat_id"] = chat_id

    app.router.add_get("/health",      _handle_health)
    app.router.add_post("/api/restic", _handle_restic)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Webhook-сервер запущен на 0.0.0.0:%d", port)
    return runner
