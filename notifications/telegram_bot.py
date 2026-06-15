"""
Silicon Radar — Telegram Bot
Sends intelligence cards as push notifications.
Handles /digest, /quiz, /rabbit-hole, /explain commands.
Feedback buttons (🔥 🧠 🕳️ 🗑️) are handled here and stored to DB.
"""

import logging
import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

from app.config import config
from db.models import (
    get_pending_notifications, get_daily_digest_cards,
    log_notification, save_feedback
)

log = logging.getLogger(__name__)

# Emoji map for tech layers — makes messages scannable on mobile
LAYER_EMOJI = {
    "process_node": "⚙️",
    "microarchitecture": "🏗️",
    "memory_hbm": "💾",
    "chiplets_ucie": "🔗",
    "advanced_packaging": "📦",
    "interconnect": "🌐",
    "ai_accelerator_asic": "🤖",
    "eda_vlsi": "🔬",
    "software_stack": "💻",
    "geopolitics_policy": "🌏",
    "startups": "🚀",
    "research_paper": "📄",
    "india_semiconductor": "🇮🇳",
    "risc_v": "🔓",
    "co_packaged_optics": "💡",
    "foundry": "🏭",
}

NOTIFICATION_HEADER = {
    "wake_up": "🚨 MAJOR SIGNAL",
    "brief": "📡 Silicon Radar",
    "ping": "💬 Quick ping",
}


def format_intelligence_card(card: dict, level: str, url: str) -> str:
    """Format a card into Telegram markdown message."""

    # Tech layer badges
    layers = card.get("tech_layer") or []
    layer_str = " ".join(LAYER_EMOJI.get(l, "•") for l in layers[:4]) if layers else ""

    header = NOTIFICATION_HEADER.get(level, "📡 Silicon Radar")
    score_bar = "█" * int(card.get("importance_score", 0.5) * 10) + "░" * (10 - int(card.get("importance_score", 0.5) * 10))

    msg = f"""
{header} {layer_str}

*{card.get('one_line_summary', 'New signal')}*

*What happened:*
{card.get('what_happened', '')}

*Why it matters technically:*
{card.get('why_technical', '')}

*Why it matters strategically:*
{card.get('why_strategic', '')}

*ELI-New-Grad explanation:*
{card.get('eli5_explanation', '')}

*Textbook connection:*
{card.get('textbook_bridge', '')}

*Rabbit hole →* {card.get('rabbit_hole', '')}

📊 Signal strength: [{score_bar}] {card.get('importance_score', 0):.0%}

[Read source]({url})
"""
    return msg.strip()


def format_ping(card: dict, url: str) -> str:
    """Short format for low-importance ping notifications."""
    layers = card.get("tech_layer") or []
    layer_str = " ".join(LAYER_EMOJI.get(l, "•") for l in layers[:3]) if layers else ""

    return (
        f"💬 {layer_str}\n"
        f"*{card.get('one_line_summary', 'New signal')}*\n\n"
        f"{card.get('why_technical', '')[:200]}...\n\n"
        f"[Read]({url})"
    )


def make_feedback_keyboard(card_id: int) -> InlineKeyboardMarkup:
    """Inline buttons for user feedback — trains the ranking model."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔥 Important", callback_data=f"fb:fire:{card_id}"),
            InlineKeyboardButton("🧠 Learned", callback_data=f"fb:brain:{card_id}"),
        ],
        [
            InlineKeyboardButton("🕳️ Rabbit hole", callback_data=f"fb:rabbit_hole:{card_id}"),
            InlineKeyboardButton("🗑️ Noise", callback_data=f"fb:trash:{card_id}"),
        ],
    ])


async def send_notification(bot: Bot, card: dict, card_id: int, url: str):
    """Send one intelligence card as a Telegram notification."""
    level = card.get("notification_level", "ping")

    if level in ("brief", "wake_up"):
        text = format_intelligence_card(card, level, url)
    else:
        text = format_ping(card, url)

    # Telegram hard limit is 4096 chars; truncate gracefully
    MAX_LEN = 4000
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN] + "\n…_(truncated)_"

    try:
        msg = await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=make_feedback_keyboard(card_id),
            disable_web_page_preview=True,
        )
        log_notification(card_id, level, text, msg.message_id)
        log.info(f"  Sent notification: card_id={card_id}, level={level}")
    except Exception as e:
        log.error(f"Telegram send error: {e}")
        # Log as sent anyway so it doesn't block the queue forever
        log_notification(card_id, level, f"[FAILED: {e}]", None)


# ---------------------------------------------------------------------------
# Bot command handlers
# ---------------------------------------------------------------------------

async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Send today's top 10 items as a digest."""
    cards = get_daily_digest_cards(limit=10)

    if not cards:
        await update.message.reply_text("No high-signal items in the last 24 hours. Check back later!")
        return

    lines = ["*🧠 Silicon Radar Daily Digest*\n"]
    for i, card in enumerate(cards, 1):
        layers = card.get("tech_layer") or []
        emoji = LAYER_EMOJI.get(layers[0], "•") if layers else "•"
        score = card.get("importance_score", 0)
        lines.append(
            f"{i}. {emoji} *{card.get('one_line_summary', card.get('title', ''))[:80]}*\n"
            f"   _{card.get('why_strategic', '')[:100]}..._\n"
            f"   [Source]({card.get('url', '')}) | Signal: {score:.0%}\n"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def cmd_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Send a quiz question from a recent high-signal item."""
    cards = get_daily_digest_cards(limit=20)
    quiz_cards = [c for c in cards if c.get("quiz_question")]

    if not quiz_cards:
        await update.message.reply_text("No quiz questions ready yet. Run the pipeline first!")
        return

    import random
    card = random.choice(quiz_cards[:5])

    text = (
        f"*🧠 Quiz Time*\n\n"
        f"Context: _{card.get('one_line_summary', '')}._\n\n"
        f"*Question:*\n{card.get('quiz_question', '')}\n\n"
        f"_Reply /answer to see the answer._"
    )
    ctx.user_data["pending_answer"] = card.get("quiz_answer", "")
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Reveal the answer to the last quiz question."""
    answer = ctx.user_data.get("pending_answer")
    if not answer:
        await update.message.reply_text("No pending question. Use /quiz first!")
        return

    await update.message.reply_text(
        f"*Answer:*\n{answer}",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_rabbit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show rabbit holes from recent items — deep dives."""
    cards = get_daily_digest_cards(limit=15)
    rabbits = [(c.get("rabbit_hole"), c.get("one_line_summary"), c.get("url"))
               for c in cards if c.get("rabbit_hole")]

    if not rabbits:
        await update.message.reply_text("No rabbit holes queued. Run the pipeline first!")
        return

    lines = ["*🕳️ This Week's Rabbit Holes*\n"]
    for i, (hole, context, url) in enumerate(rabbits[:5], 1):
        lines.append(f"{i}. {hole}\n   ↳ From: [{context[:60]}...]({url})\n")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def cmd_flashcards(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Send today's flashcards for spaced repetition."""
    cards = get_daily_digest_cards(limit=10)
    flashcards = []
    for c in cards:
        if c.get("flashcard_q1"):
            flashcards.append((c["flashcard_q1"], c["flashcard_a1"]))
        if c.get("flashcard_q2"):
            flashcards.append((c["flashcard_q2"], c["flashcard_a2"]))
        if c.get("flashcard_q3"):
            flashcards.append((c["flashcard_q3"], c["flashcard_a3"]))

    if not flashcards:
        await update.message.reply_text("No flashcards ready. Run the pipeline first!")
        return

    import random
    sample = random.sample(flashcards, min(3, len(flashcards)))
    lines = ["*📇 Today's Flashcards*\n"]
    for i, (q, a) in enumerate(sample, 1):
        lines.append(f"*Q{i}:* {q}\n_A:_ ||{a}||\n")  # Telegram spoiler for answer

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Silicon Radar Commands*\n\n"
        "/digest — Today's top signals\n"
        "/quiz — Test your knowledge\n"
        "/answer — Reveal quiz answer\n"
        "/rabbit — Deep dive topics\n"
        "/flashcards — Spaced repetition cards\n"
        "/help — This message",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Feedback handler
# ---------------------------------------------------------------------------

async def handle_feedback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle 🔥🧠🕳️🗑️ button taps from notification cards."""
    query = update.callback_query
    await query.answer()

    data = query.data  # format: "fb:reaction:card_id"
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "fb":
        return

    _, reaction, card_id = parts
    save_feedback(int(card_id), reaction)

    reaction_labels = {
        "fire": "🔥 Marked as important",
        "brain": "🧠 Marked as educational",
        "rabbit_hole": "🕳️ Added to rabbit holes",
        "trash": "🗑️ Marked as noise",
    }
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(reaction_labels.get(reaction, "Saved!"))


# ---------------------------------------------------------------------------
# Notification sender (runs standalone to push pending cards)
# ---------------------------------------------------------------------------

async def send_pending_notifications():
    """Push all pending high-signal notifications. Run every 30 min via cron."""
    bot = Bot(token=config.TELEGRAM_TOKEN)
    cards = get_pending_notifications()

    if not cards:
        log.info("No pending notifications.")
        return

    log.info(f"Sending {len(cards)} pending notifications...")
    for card in cards:
        await send_notification(bot, dict(card), card["id"], card["url"])
        await asyncio.sleep(1)  # small delay between messages


async def send_daily_digest():
    """Send the daily digest. Run at 9 AM via cron."""
    bot = Bot(token=config.TELEGRAM_TOKEN)
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()

    # Simulate the /digest command
    cards = get_daily_digest_cards(limit=10)
    if not cards:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text="*🧠 Silicon Radar Daily*\n\nNo high-signal items in the last 24 hours. The industry slept.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = ["*🧠 Silicon Radar Daily Digest*\n", f"_{datetime.now().strftime('%B %d, %Y')}_\n"]
    for i, card in enumerate(cards, 1):
        layers = card.get("tech_layer") or []
        emoji = LAYER_EMOJI.get(layers[0], "•") if layers else "•"
        score = card.get("importance_score", 0)
        lines.append(
            f"{i}. {emoji} *{card.get('one_line_summary', card.get('title', ''))[:80]}*\n"
            f"   _{card.get('why_strategic', '')[:120]}..._\n"
            f"   [Source]({card.get('url', '')}) | {score:.0%} signal\n"
        )

    await bot.send_message(
        chat_id=config.TELEGRAM_CHAT_ID,
        text="\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
    log.info("Daily digest sent.")


# ---------------------------------------------------------------------------
# Start the interactive bot (for running locally)
# ---------------------------------------------------------------------------

def run_bot():
    """Start the bot for interactive /commands. Run this once, keep it alive."""
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("quiz", cmd_quiz))
    app.add_handler(CommandHandler("answer", cmd_answer))
    app.add_handler(CommandHandler("rabbit", cmd_rabbit))
    app.add_handler(CommandHandler("flashcards", cmd_flashcards))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(handle_feedback, pattern="^fb:"))

    log.info("Silicon Radar bot is running. Press Ctrl+C to stop.")
    app.run_polling()
