"""
Silicon Radar — Main Pipeline Runner

Run modes:
  python scripts/run_pipeline.py collect       # pull new items from all sources
  python scripts/run_pipeline.py process       # generate intelligence cards
  python scripts/run_pipeline.py notify        # push pending notifications to Telegram
  python scripts/run_pipeline.py digest        # send morning digest
  python scripts/run_pipeline.py all           # collect → process → notify
  python scripts/run_pipeline.py bot           # run interactive Telegram bot

Cron example (add to crontab with: crontab -e):
  */30 * * * * cd /path/to/silicon-radar && python scripts/run_pipeline.py all >> logs/pipeline.log 2>&1
  0 9  * * * cd /path/to/silicon-radar && python scripts/run_pipeline.py digest >> logs/pipeline.log 2>&1
"""

import sys
import asyncio
import logging
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


def check_config():
    """Verify required environment variables are set."""
    from app.config import config
    missing = []
    if not config.GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
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


def run_collect():
    log.info("=== PHASE 1: Collecting from all sources ===")
    from collectors.collector import run_all_collectors
    n = run_all_collectors()
    log.info(f"Collected {n} new items total.")
    return n


def run_process():
    log.info("=== PHASE 2: Generating intelligence cards ===")
    from processing.card_generator import process_unprocessed_items
    n = process_unprocessed_items(max_items=30)
    log.info(f"Generated {n} intelligence cards.")
    return n


def run_notify():
    log.info("=== PHASE 3: Sending pending notifications ===")
    from notifications.telegram_bot import send_pending_notifications
    asyncio.run(send_pending_notifications())


def run_digest():
    log.info("=== Sending daily digest ===")
    from notifications.telegram_bot import send_daily_digest
    asyncio.run(send_daily_digest())


def run_bot():
    log.info("=== Starting interactive Telegram bot ===")
    from notifications.telegram_bot import run_bot as _run_bot
    _run_bot()


if __name__ == "__main__":
    check_config()

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "collect":
        run_collect()
    elif mode == "process":
        run_process()
    elif mode == "notify":
        run_notify()
    elif mode == "digest":
        run_digest()
    elif mode == "bot":
        run_bot()
    elif mode == "all":
        n = run_collect()
        if n > 0:
            run_process()
        run_notify()
    else:
        print(__doc__)
        sys.exit(1)
