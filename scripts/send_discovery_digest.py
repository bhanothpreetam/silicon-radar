"""
Silicon Radar — Weekly Discovery Digest

Sends a Telegram summary of newly verified sources found by the
discovery loop (search-based + citation-graph). Run after
run_discovery.py and run_citations.py in the discovery workflow.

Sources found here are NOT auto-added to the live collector — this is
a review digest only, until the probation/promotion system exists.
"""

import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("discovery-digest")

from app.config import config
from db.models import get_client


def escape_html(text: str) -> str:
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_digest() -> tuple[str, list[int]]:
    client = get_client()
    rows = (
        client.table("discovered_sources")
        .select("id,domain,name,audition_score,audition,discovery_query")
        .eq("status", "verified")
        .is_("notified_at", "null")
        .order("audition_score", desc=True)
        .execute()
        .data or []
    )

    if not rows:
        return "", []

    lines = [f"🔭 <b>Weekly Source Discovery</b>\n{len(rows)} new source(s) verified this week:\n"]
    for r in rows:
        domain = r["domain"]
        is_twitter = domain.startswith("@")
        icon = "🐦" if is_twitter else "📡"
        name = escape_html(r.get("name") or domain)
        score = r.get("audition_score") or 0
        verdict = escape_html((r.get("audition") or {}).get("verdict", ""))
        via = "citation graph" if "citation-graph" in (r.get("discovery_query") or "") else "search"
        lines.append(
            f"{icon} <b>{escape_html(domain)}</b> ({name})\n"
            f"   Score: {score:.2f} · found via {via}\n"
            f"   {verdict}\n"
        )

    lines.append(
        "\n<i>Not live yet — these sit in review until the probation system "
        "promotes or drops them.</i>"
    )
    return "\n".join(lines), [r["id"] for r in rows]


def send_digest() -> None:
    text, ids = build_digest()
    if not ids:
        log.info("No new verified sources this week — skipping digest.")
        return

    with httpx.Client(timeout=15) as http:
        resp = http.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text[:4096], "parse_mode": "HTML"},
        )
        resp.raise_for_status()

    client = get_client()
    now = datetime.now(timezone.utc).isoformat()
    client.table("discovered_sources").update({"notified_at": now}).in_("id", ids).execute()
    log.info(f"Sent digest for {len(ids)} sources and marked them notified.")


if __name__ == "__main__":
    send_digest()
