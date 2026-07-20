"""
Silicon Radar — Main Pipeline Runner

Run modes:
  python scripts/run_pipeline.py collect       # pull new items from all sources
  python scripts/run_pipeline.py process       # generate intelligence cards
  python scripts/run_pipeline.py notify        # push pending notifications to Telegram
  python scripts/run_pipeline.py digest        # send morning digest
  python scripts/run_pipeline.py all           # collect → process → notify
  python scripts/run_pipeline.py quick         # RSS + Tier1 Twitter → process → notify
  python scripts/run_pipeline.py map           # send weekly intelligence map to Telegram
  python scripts/run_pipeline.py bot           # run interactive Telegram bot

Cron example (add to crontab with: crontab -e):
  */30 * * * * cd /path/to/silicon-radar && python scripts/run_pipeline.py all >> logs/pipeline.log 2>&1
  0 9  * * * cd /path/to/silicon-radar && python scripts/run_pipeline.py digest >> logs/pipeline.log 2>&1
"""

import sys
import asyncio
import logging
import httpx
from datetime import datetime
from pathlib import Path

# Make sure imports work from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env before any config import (config reads os.getenv at instantiation time)
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("silicon-radar")


# ---------------------------------------------------------------------------
# Telegram alerts
# ---------------------------------------------------------------------------

async def send_error_alert(error_msg: str):
    from app.config import config
    text = (
        f"🚨 Silicon Radar pipeline error\n\n"
        f"{error_msg}\n\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Action needed: check logs"
    )
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
                timeout=10,
            )
    except Exception as e:
        log.error(f"Failed to send error alert: {e}")


async def send_success_ping(collected: int, cards: int):
    from app.config import config
    text = (
        f"✅ Silicon Radar ran successfully\n\n"
        f"Collected: {collected} items\n"
        f"Cards generated: {cards}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    try:
        async with httpx.AsyncClient() as client_http:
            await client_http.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
                timeout=10,
            )
    except Exception as e:
        log.error(f"Failed to send success ping: {e}")


# ---------------------------------------------------------------------------
# Config check
# ---------------------------------------------------------------------------

def check_config():
    """Verify required environment variables are set."""
    from app.config import config
    missing = []
    if not config.GEMINI_API_KEYS:
        missing.append("GEMINI_API_KEY or GEMINI_API_KEYS")
    if not config.SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not config.SUPABASE_KEY:
        missing.append("SUPABASE_KEY")
    if not config.TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not config.TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        log.error(f"Missing required environment variables: {', '.join(missing)}")
        log.error("Copy .env.example to .env and fill in your values.")
        sys.exit(1)

    log.info("Config OK.")


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------

def run_collect():
    try:
        log.info("=== PHASE 1: Collecting from all sources ===")
        from collectors.collector import run_all_collectors
        n = run_all_collectors()
        log.info(f"Collected {n} new items total.")
        return n
    except Exception as e:
        log.error(f"Collect failed: {e}")
        asyncio.run(send_error_alert(
            f"Collector failed\n{type(e).__name__}: {str(e)[:300]}"
        ))
        return 0


def run_process():
    try:
        log.info("=== PHASE 2: Generating intelligence cards ===")
        from processing.card_generator import process_unprocessed_items
        n = process_unprocessed_items(max_items=50)
        log.info(f"Generated {n} intelligence cards.")
        return n
    except Exception as e:
        log.error(f"Process failed: {e}")
        asyncio.run(send_error_alert(
            f"Card generator failed\n{type(e).__name__}: {str(e)[:300]}"
        ))
        return 0


def run_quick() -> int:
    """Fast pipeline: RSS sources + Tier1 Twitter only. Target: under 5 minutes."""
    log.info("=== QUICK RUN: RSS + Tier1 Twitter ===")
    from collectors.collector import collect_rss, get_sources
    from collectors.twitter_collector import collect_twitter
    from app.config import TWITTER_TIER1
    from db.models import get_client

    sources = get_sources()
    total = 0

    for s in [s for s in sources if s['type'] == 'rss']:
        n = collect_rss(s['id'], s['url'])
        log.info(f"  → {n} new from {s['name']}")
        total += n

    client = get_client()
    # Hub rows only — probation twitter/youtube rows have their own source ids
    src = client.table('sources').select('id').eq('type', 'twitter').order('id').execute()
    twitter_src_id = src.data[0]['id'] if src.data else 18

    tw_count = collect_twitter(source_id=twitter_src_id, accounts=TWITTER_TIER1)
    log.info(f"Twitter Tier1: {tw_count} new items")
    total += tw_count

    try:
        from collectors.twitter_collector import collect_probation_twitter
        pt_count = collect_probation_twitter()
        if pt_count:
            log.info(f"Twitter probation: {pt_count} new items")
        total += pt_count
    except Exception as e:
        log.error(f"Probation twitter collect failed: {e}")

    try:
        from collectors.youtube_collector import collect_youtube
        yt_src = client.table('sources').select('id').eq('type', 'youtube').order('id').execute()
        if yt_src.data:
            yt_count = collect_youtube(source_id=yt_src.data[0]['id'])
            log.info(f"YouTube: {yt_count} new videos")
            total += yt_count
    except Exception as e:
        log.error(f"YouTube collect failed: {e}")

    log.info(f"=== Quick collect done: {total} new items ===")
    return total


def run_notify():
    log.info("=== PHASE 3: Sending pending notifications ===")
    from notifications.telegram_bot import send_pending_notifications
    asyncio.run(send_pending_notifications())


def run_probation_eval():
    """Apply probation rules after notifications go out. Never fails the run."""
    try:
        from intelligence.probation import evaluate_probation
        decisions = evaluate_probation()
        if decisions:
            log.info(f"Probation decisions: {[(d['name'], d['verdict']) for d in decisions]}")
    except Exception as e:
        log.warning(f"Probation evaluation skipped: {e}")


def run_digest():
    log.info("=== Sending daily digest ===")
    from notifications.telegram_bot import send_daily_digest
    asyncio.run(send_daily_digest())


async def send_weekly_map():
    from app.config import config
    from db.models import get_client
    from datetime import timezone, timedelta
    from google import genai
    from google.genai import types

    client_db = get_client()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    cards = (
        client_db.table('intelligence_cards')
        .select('one_line_summary,why_strategic,tech_layer')
        .gte('generated_at', week_ago)
        .gte('importance_score', 0.65)
        .order('importance_score', desc=True)
        .limit(50)
        .execute()
    )

    if not cards.data:
        log.info("No cards this week — skipping weekly map.")
        return

    items_text = "\n".join(
        f"- {c['one_line_summary']}"
        for c in cards.data if c.get('one_line_summary')
    )

    prompt = f"""You are a senior semiconductor industry analyst.

Here are the most important semiconductor/AI hardware events from the past 7 days:

{items_text}

Write a concise weekly intelligence summary (max 400 words).
Structure it as:

\U0001f3ed Process & Foundry: [what changed]
\U0001f4be Memory & Packaging: [what changed]
\U0001f916 AI Hardware & ASICs: [what changed]
\U0001f513 RISC-V & Open Silicon: [what changed]
\U0001f30f Geopolitics & Supply Chain: [what changed]
\U0001f680 Startups & Research: [what changed]

End with one sentence: "The week's biggest signal: ..."

Be specific. Name companies, products, numbers.
Skip categories with no relevant news."""

    api_key = config.GEMINI_API_KEYS[0]
    gemini = genai.Client(api_key=api_key)
    response = gemini.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.4,
            max_output_tokens=1024,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    text = (
        f"\U0001f5fa️ Silicon Radar Weekly Map\n"
        f"Week of {datetime.now().strftime('%B %d, %Y')}\n\n"
        f"{response.text}"
    )

    async with httpx.AsyncClient() as http:
        await http.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text[:4000]},
            timeout=15,
        )
    log.info("Weekly map sent.")


def run_bot():
    log.info("=== Starting interactive Telegram bot ===")
    from notifications.telegram_bot import run_bot as _run_bot
    _run_bot()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    check_config()

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "quick":
        collected = run_quick()
        cards = 0
        if collected > 0:
            cards = run_process()
        run_notify()
        run_probation_eval()
        if cards > 0:
            asyncio.run(send_success_ping(collected, cards))
    elif mode == "collect":
        run_collect()
    elif mode == "process":
        run_process()
    elif mode == "notify":
        run_notify()
    elif mode == "digest":
        run_digest()
    elif mode == "map":
        asyncio.run(send_weekly_map())
    elif mode == "learn":
        from intelligence.learning_track import run_learning_track
        n = run_learning_track(max_cards=1)
        log.info(f"Learning track: {n} concept card(s) generated")
        if n > 0:
            run_notify()
    elif mode == "youtube":
        from collectors.youtube_collector import collect_youtube
        from db.models import get_client
        yt_src = get_client().table('sources').select('id').eq('type', 'youtube').execute()
        n = collect_youtube(source_id=yt_src.data[0]['id'])
        log.info(f"YouTube: {n} new videos collected")
        if n > 0:
            run_process()
            run_notify()
    elif mode == "promote":
        from intelligence.probation import promote_verified, evaluate_probation
        promoted = promote_verified()
        log.info(f"Promoted {len(promoted)} verified source(s) to probation")
        evaluate_probation()
    elif mode == "bot":
        run_bot()
    elif mode == "all":
        collected = run_collect()
        cards = 0
        if collected > 0:
            cards = run_process()
        run_notify()
        run_probation_eval()
        if cards > 0:
            asyncio.run(send_success_ping(collected, cards))
    else:
        print(__doc__)
        sys.exit(1)
