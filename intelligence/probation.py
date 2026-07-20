"""
Silicon Radar — Source Probation System

Discovery finds and verifies candidate sources; this module gives them a
probation trial in the real rotation and turns your Telegram reactions
into a permanent keep/drop decision.

Lifecycle (status column on sources):
  trusted    — full member of the rotation (default for original sources)
  probation  — on trial: collected + notified with a 🧪 marker
  blacklisted— removed permanently; discovery won't re-propose it
  shelved    — removed for now, but MAY be re-proposed later (no explicit
               negative signal — just didn't prove itself in the window)

Rules (evaluated after each notify run):
  graduate   score >= +3                        → trusted
  execute    score <= -2                        → blacklisted
  quota      strike rate < 5% after >= 15 items → blacklisted
  window     >= 5 pushed articles, score in between → shelved
  timeout    30 days with nothing pushed        → shelved

score = Σ reactions on the source's cards since probation started:
  🔥 +2   🧠 +1   🕳️ +1   🗑️ -2   (no reaction = 0; silence is not evidence)
"""

import logging
import re
from datetime import datetime, timezone, timedelta

from db.models import get_client

log = logging.getLogger(__name__)

REACTION_POINTS = {"fire": 2, "brain": 1, "rabbit_hole": 1, "trash": -2}

GRADUATE_AT = 3
BLACKLIST_AT = -2
EVAL_WINDOW_PUSHES = 5
TIMEOUT_DAYS = 30
STRIKE_RATE_MIN = 0.05
STRIKE_RATE_MIN_SAMPLE = 15
PUSH_THRESHOLD = 0.65   # importance score that counts as "pushed-quality"


def _parse_iso(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    s = re.sub(r"(\.\d+)(?=[+-])", lambda m: m.group(1).ljust(7, "0")[:7], s)
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------------------
# Promotion: verified discoveries → probation rotation
# ---------------------------------------------------------------------------

def promote_verified(max_promotions: int = 3) -> list[dict]:
    """
    Move top verified discovered_sources into the sources table with
    status='probation' so collectors start pulling them. Capped per run
    so the feed never floods with unproven sources at once.
    """
    client = get_client()
    rows = (
        client.table("discovered_sources")
        .select("*")
        .eq("status", "verified")
        .order("audition_score", desc=True)
        .limit(max_promotions)
        .execute()
        .data or []
    )

    promoted = []
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        domain = row["domain"]
        name = row.get("name") or domain

        if domain.startswith("@"):
            stype, url = "twitter", f"https://x.com/{domain.lstrip('@')}"
        elif domain.startswith("channel:"):
            cid = domain.split(":", 1)[1]
            stype, url = "youtube", f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
        elif row.get("feed_url"):
            stype, url = "rss", row["feed_url"]
        else:
            log.info(f"  {domain}: verified but no feed — cannot promote, skipping")
            continue

        try:
            client.table("sources").insert({
                "name": name[:100],
                "url": url,
                "type": stype,
                "credibility": 6,
                "status": "probation",
                "probation_started_at": now,
            }).execute()
            client.table("discovered_sources").update({"status": "promoted"}).eq("id", row["id"]).execute()
            promoted.append({"name": name, "type": stype, "url": url})
            log.info(f"  🧪 promoted to probation: {name} ({stype})")
        except Exception as e:
            log.warning(f"  {domain}: promotion failed: {e}")

    return promoted


# ---------------------------------------------------------------------------
# Evaluation: reactions → keep/drop decisions
# ---------------------------------------------------------------------------

def _probation_stats(client, source_id: int, since: str) -> dict:
    """Compute scraped/passed/pushed/score for one probation source."""
    items = (
        client.table("raw_items").select("id")
        .eq("source_id", source_id).gte("fetched_at", since)
        .execute().data or []
    )
    item_ids = [i["id"] for i in items]
    cards, card_ids, passed = [], [], 0
    if item_ids:
        cards = (
            client.table("intelligence_cards").select("id,importance_score")
            .in_("raw_item_id", item_ids).execute().data or []
        )
        card_ids = [c["id"] for c in cards]
        passed = sum(1 for c in cards if (c.get("importance_score") or 0) >= PUSH_THRESHOLD)

    pushed = 0
    score = 0
    if card_ids:
        notifs = (
            client.table("notifications").select("id,message_text")
            .in_("card_id", card_ids).execute().data or []
        )
        pushed = sum(1 for n in notifs if not (n.get("message_text") or "").startswith("[FAILED"))
        feedback = (
            client.table("feedback").select("reaction")
            .in_("card_id", card_ids).execute().data or []
        )
        score = sum(REACTION_POINTS.get(f["reaction"], 0) for f in feedback)

    return {"scraped": len(item_ids), "passed": passed, "pushed": pushed, "score": score}


def evaluate_probation() -> list[dict]:
    """
    Apply the probation rules to every source on trial.
    Returns decisions made this run.
    """
    client = get_client()
    try:
        probation = (
            client.table("sources").select("id,name,probation_started_at")
            .eq("status", "probation").execute().data or []
        )
    except Exception as e:
        log.warning(f"probation evaluation skipped (schema not ready?): {e}")
        return []

    if not probation:
        return []

    decisions = []
    now = datetime.now(timezone.utc)
    for src in probation:
        started = src.get("probation_started_at")
        since = started or (now - timedelta(days=TIMEOUT_DAYS)).isoformat()
        stats = _probation_stats(client, src["id"], since)
        days_in = (now - _parse_iso(since)).days if started else 0

        verdict = None
        if stats["score"] >= GRADUATE_AT:
            verdict = "trusted"
        elif stats["score"] <= BLACKLIST_AT:
            verdict = "blacklisted"
        elif stats["scraped"] >= STRIKE_RATE_MIN_SAMPLE and \
                stats["passed"] / stats["scraped"] < STRIKE_RATE_MIN:
            verdict = "blacklisted"   # burns quota, produces nothing
        elif stats["pushed"] >= EVAL_WINDOW_PUSHES:
            verdict = "shelved"       # full window, no clear signal
        elif days_in >= TIMEOUT_DAYS and stats["pushed"] == 0:
            verdict = "shelved"       # too quiet to judge

        if verdict:
            client.table("sources").update({"status": verdict}).eq("id", src["id"]).execute()
            decision = {"name": src["name"], **stats, "days": days_in, "verdict": verdict}
            decisions.append(decision)
            icon = {"trusted": "🎓", "blacklisted": "⛔", "shelved": "📦"}[verdict]
            log.info(f"  {icon} {src['name']}: {verdict} "
                     f"(score {stats['score']}, {stats['pushed']} pushed, "
                     f"{stats['passed']}/{stats['scraped']} strike, {days_in}d)")
        else:
            log.info(f"  🧪 {src['name']}: still on trial "
                     f"(score {stats['score']}, {stats['pushed']}/{EVAL_WINDOW_PUSHES} pushed, {days_in}d)")

    return decisions
