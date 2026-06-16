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


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from db.models import get_client
    from datetime import timezone, timedelta

    client = get_client()
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    cards_today = client.table('intelligence_cards').select('id', count='exact').gte('generated_at', today_start).execute()
    cards_total = client.table('intelligence_cards').select('id', count='exact').execute()
    notifs_today = client.table('notifications').select('id', count='exact').gte('sent_at', today_start).execute()

    usage = client.table('api_usage').select('key_index,model').gte('logged_at', today_start).execute()
    n_keys = len(config.GEMINI_API_KEYS)
    key_counts = {i: 0 for i in range(n_keys)}
    key_exhausted = {i: False for i in range(n_keys)}
    for row in (usage.data or []):
        k = row['key_index']
        if row['model'].endswith(':exhausted'):
            key_exhausted[k] = True
        else:
            key_counts[k] = key_counts.get(k, 0) + 1
    total_today = sum(key_counts.values())

    items = client.table('raw_items').select('source_id').gte('fetched_at', week_start).execute()
    src_counts = {}
    for item in (items.data or []):
        s = item['source_id']
        src_counts[s] = src_counts.get(s, 0) + 1
    top_src_id = max(src_counts, key=src_counts.get) if src_counts else None

    top_src_name = "unknown"
    if top_src_id:
        src = client.table('sources').select('name').eq('id', top_src_id).execute()
        if src.data:
            top_src_name = src.data[0]['name']

    feedback = client.table('feedback').select('reaction').gte('reacted_at', week_start).execute()
    fb_counts = {'fire': 0, 'brain': 0, 'rabbit_hole': 0, 'trash': 0}
    for row in (feedback.data or []):
        r = row['reaction']
        fb_counts[r] = fb_counts.get(r, 0) + 1

    text = (
        f"📊 Silicon Radar Stats\n\n"
        f"Today:\n"
        f"  Cards generated: {cards_today.count or 0}\n"
        f"  Notifications sent: {notifs_today.count or 0}\n"
        f"  API calls logged: {total_today}\n\n"
        f"API keys today:\n" +
        "".join(
            f"  Key {i+1}: {key_counts[i]} cards {'🔴 exhausted' if key_exhausted[i] else '🟢'}\n"
            for i in range(n_keys)
        ) +
        "\n"
        f"All time:\n"
        f"  Total cards: {cards_total.count or 0}\n\n"
        f"This week:\n"
        f"  Top source: {top_src_name} ({src_counts.get(top_src_id, 0)} items)\n"
        f"  Feedback: 🔥{fb_counts['fire']} "
        f"🧠{fb_counts['brain']} "
        f"🕳️{fb_counts['rabbit_hole']} "
        f"🗑️{fb_counts['trash']}"
    )

    await update.message.reply_text(text)


async def cmd_health(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from db.models import get_client
    from datetime import timezone

    client = get_client()
    issues = []

    try:
        client.table('sources').select('id').limit(1).execute()
        db_status = "✅ connected"
    except Exception as e:
        db_status = f"❌ error: {str(e)[:50]}"
        issues.append("Database unreachable")

    try:
        last_item = client.table('raw_items').select('fetched_at').order('fetched_at', desc=True).limit(1).execute()
        if last_item.data:
            fetched = datetime.fromisoformat(last_item.data[0]['fetched_at'].replace('Z', '+00:00'))
            mins_ago = int((datetime.now(timezone.utc) - fetched).total_seconds() / 60)
            collect_status = f"✅ {mins_ago} min ago"
            if mins_ago > 180:
                issues.append(f"No collection in {mins_ago} min")
                collect_status = f"⚠️ {mins_ago} min ago"
        else:
            collect_status = "❓ no data"
    except Exception as e:
        collect_status = "❌ error"
        issues.append("Cannot check collection")

    try:
        last_card = client.table('intelligence_cards').select('generated_at').order('generated_at', desc=True).limit(1).execute()
        if last_card.data:
            generated = datetime.fromisoformat(last_card.data[0]['generated_at'].replace('Z', '+00:00'))
            mins_ago = int((datetime.now(timezone.utc) - generated).total_seconds() / 60)
            card_status = f"✅ {mins_ago} min ago"
            if mins_ago > 360:
                issues.append(f"No cards in {mins_ago} min")
                card_status = f"⚠️ {mins_ago} min ago"
        else:
            card_status = "❓ no cards yet"
    except Exception:
        card_status = "❌ error"

    overall = "✅ All systems go" if not issues else "⚠️ " + "; ".join(issues)

    text = (
        f"🏥 Silicon Radar Health\n\n"
        f"Database: {db_status}\n"
        f"Last collection: {collect_status}\n"
        f"Last card: {card_status}\n\n"
        f"Status: {overall}"
    )

    await update.message.reply_text(text)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Silicon Radar Commands*\n\n"
        "/digest — Today's top signals\n"
        "/quiz — Test your knowledge\n"
        "/answer — Reveal quiz answer\n"
        "/rabbit — Deep dive topics\n"
        "/flashcards — Spaced repetition cards\n"
        "/stats — API usage and pipeline stats\n"
        "/health — System health check\n"
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
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(handle_feedback, pattern="^fb:"))

    log.info("Silicon Radar bot is running. Press Ctrl+C to stop.")
    app.run_polling()
