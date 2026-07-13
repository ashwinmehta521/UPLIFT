"""
telegram_bot.py
----------------
Chat-driven front end for equity-agent — analysis only, no order placement.

Talk to your bot on Telegram:
    /analyze SBIN            -> runs signal_engine.analyze("SBIN", "NSE") and
                                 sends you the formatted verdict
    /analyze SBIN BSE        -> same, on a specific exchange
    SBIN                     -> plain symbol also triggers analysis
    /start or /help          -> usage

This script never touches kite.place_order() — it only fetches data and
returns a BUY / SELL / HOLD verdict with reasoning. Nothing gets executed
on the market from here.

Requires (add to requirements.txt):
    python-telegram-bot>=21.0
    python-dotenv
    kiteconnect
    requests

.env should contain (in addition to signal_engine's vars):
    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_ALLOWED_CHAT_ID=...   # your personal chat id — bot ignores everyone else
"""

import os
import logging

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from signal_engine import analyze

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("telegram_bot")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Lock the bot down to just you. Anyone else who finds the bot's username
# gets ignored rather than being able to trigger Kite calls under your account.
_allowed = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID")
TELEGRAM_ALLOWED_CHAT_ID = int(_allowed) if _allowed else None


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

def _is_authorized(update: Update) -> bool:
    if TELEGRAM_ALLOWED_CHAT_ID is None:
        log.warning("TELEGRAM_ALLOWED_CHAT_ID not set — bot is open to any chat that finds it!")
        return True
    return update.effective_chat.id == TELEGRAM_ALLOWED_CHAT_ID


async def _reject(update: Update) -> None:
    log.warning("Unauthorized chat_id=%s tried to use the bot", update.effective_chat.id)
    # Deliberately vague — don't confirm this is a trading bot to strangers.
    await update.message.reply_text("Not authorized.")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_verdict(v: dict) -> str:
    factors = v.get("factors", {})

    def factor_line(name: str, label: str) -> str:
        f = factors.get(name, {})
        score = f.get("score")
        note = f.get("note", "")
        arrow = "🟢" if isinstance(score, int) and score > 15 else "🔴" if isinstance(score, int) and score < -15 else "⚪"
        return f"{arrow} <b>{label}</b>: {score}\n   {note}"

    verdict = v.get("verdict")
    verdict_emoji = {"BUY": "📈", "SELL": "📉", "HOLD": "⏸️"}.get(verdict, "")

    # Verdict leads the message, front and center — this is the thing you
    # actually came here for.
    lines = [
        f"{verdict_emoji} <b>{verdict}</b> — {v.get('symbol')}",
        f"Confidence: {v.get('confidence')}%   |   LTP: {v.get('_ltp_at_analysis')}",
        "",
        f"<b>Reasoning</b>\n{v.get('reasoning', '')}",
        "",
        "<b>Five-factor breakdown</b>",
        factor_line("fundamentals", "Fundamentals"),
        factor_line("macro", "Macro"),
        factor_line("sentiment", "Sentiment"),
        factor_line("industry_trends", "Industry trends"),
        factor_line("institutional_flows", "Institutional flows"),
        "",
        f"<b>Technical summary</b>\n{v.get('technical_summary', '')}",
        "",
        f"<b>News summary</b>\n{v.get('news_summary', '')}",
    ]

    entry, stop, target = v.get("suggested_entry"), v.get("suggested_stop"), v.get("suggested_target")
    if entry or stop or target:
        lines += [
            "",
            f"<b>Suggested levels</b>\nEntry: {entry}  |  Stop: {stop}  |  Target: {target}",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram message chunking
# ---------------------------------------------------------------------------

TELEGRAM_MAX_LEN = 4096

def chunk_message(text: str, max_len: int = TELEGRAM_MAX_LEN) -> list[str]:
    """
    Split text into Telegram-safe chunks, breaking on blank lines where
    possible so we don't cut a section in half. Falls back to a hard split
    if a single paragraph is itself longer than max_len.
    """
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(paragraph) <= max_len:
                current = paragraph
            else:
                # a single paragraph is itself too long — hard-split it
                for i in range(0, len(paragraph), max_len):
                    chunks.append(paragraph[i:i + max_len])
                current = ""
    if current:
        chunks.append(current)
    return chunks


async def send_long_message(update: Update, text: str, parse_mode=None) -> None:
    for i, chunk in enumerate(chunk_message(text), start=1):
        await update.message.reply_text(chunk, parse_mode=parse_mode)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return await _reject(update)
    await update.message.reply_text(
        "equity-agent bot online.\n\n"
        "/analyze SYMBOL [EXCHANGE] — run analysis and get a BUY/SELL/HOLD verdict\n"
        "or just send a symbol like SBIN\n\n"
        "This bot only analyzes — it never places orders."
    )


async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return await _reject(update)

    if not context.args:
        return await update.message.reply_text("Usage: /analyze SYMBOL [EXCHANGE]")

    symbol = context.args[0].upper()
    exchange = context.args[1].upper() if len(context.args) > 1 else "NSE"

    await update.message.reply_text(f"Analyzing {symbol} ({exchange})… this can take up to a minute.")

    try:
        verdict = analyze(symbol, exchange)
        await send_long_message(update, format_verdict(verdict), parse_mode=ParseMode.HTML)
    except Exception as e:
        log.exception("Analysis failed for %s", symbol)
        await update.message.reply_text(f"Analysis failed for {symbol}: {e}")


async def plain_symbol_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lets you just type a bare symbol like 'SBIN' instead of /analyze SBIN."""
    if not _is_authorized(update):
        return await _reject(update)

    text = update.message.text.strip()
    if not text or " " in text or not text.replace("-", "").replace("&", "").isalnum():
        return  # not something that looks like a plain symbol; ignore silently

    context.args = [text]
    await analyze_cmd(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Update %s caused error %s", update, context.error)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", start_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, plain_symbol_handler))
    app.add_error_handler(error_handler)

    log.info("Bot starting (polling)…")
    app.run_polling()


if __name__ == "__main__":
    main()