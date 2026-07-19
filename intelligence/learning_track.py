"""
Silicon Radar — Learning Track

The news feed teaches you WHAT is happening; this track teaches you the
CONCEPTS the news keeps referencing. It mines textbook_concepts from
your recent high-signal cards, finds the best lecture/explainer on
YouTube for the most-referenced concept not yet covered, and generates
a 📚 learning card from the video's transcript. Learning cards flow
into the normal notification feed.

Covered concepts are tracked in learning_concepts so each is taught once.
"""

import json
import logging
import re
import urllib.parse
from collections import Counter
from pathlib import Path

from ddgs import DDGS

from db.models import get_client, insert_raw_item, insert_intelligence_card
from intelligence.source_discovery import _gemini_json
from collectors.youtube_collector import fetch_transcript

log = logging.getLogger(__name__)

CONCEPT_PROMPT = (Path(__file__).parent.parent / "prompts" / "concept_card_v1.txt").read_text()

MIN_LECTURE_CHARS = 3000     # a real lecture/explainer, not a teaser
MIN_DURATION_MIN = 6
MAX_DURATION_MIN = 75        # cap: full 3h course lectures overflow the transcript budget anyway
TRANSCRIPT_BUDGET = 9000

# Concepts too generic to teach as a single card
GENERIC_CONCEPTS = {
    "moore's law", "semiconductors", "chips", "ai", "machine learning",
    "computer architecture", "hardware", "software", "innovation",
}


def _video_id_from_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("youtube.com"):
        return urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
    if parsed.netloc.endswith("youtu.be"):
        return parsed.path.lstrip("/") or None
    return None


def _duration_minutes(duration: str) -> float | None:
    parts = duration.strip().split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 3:
        return parts[0] * 60 + parts[1] + parts[2] / 60
    if len(parts) == 2:
        return parts[0] + parts[1] / 60
    return None


def mine_concepts(days: int = 14, min_score: float = 0.7) -> list[tuple[str, int]]:
    """
    Return (concept, frequency) for concepts referenced by recent
    high-signal cards, most-referenced first, excluding already-covered.
    """
    from datetime import datetime, timezone, timedelta
    client = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cards = (
        client.table("intelligence_cards")
        .select("textbook_concepts,importance_score")
        .gte("generated_at", cutoff)
        .gte("importance_score", min_score)
        .execute()
        .data or []
    )

    counts: Counter = Counter()
    for card in cards:
        for concept in card.get("textbook_concepts") or []:
            c = concept.strip().lower()
            if c and c not in GENERIC_CONCEPTS and len(c) > 3:
                counts[c] += 1

    covered = set()
    try:
        rows = client.table("learning_concepts").select("concept").execute().data or []
        covered = {r["concept"].lower() for r in rows}
    except Exception as e:
        log.warning(f"learning_concepts table unreadable ({e}) — treating all as uncovered")

    return [(c, n) for c, n in counts.most_common() if c not in covered]


def find_lecture(concept: str, max_candidates: int = 8) -> dict | None:
    """
    Search for the best lecture/explainer video on a concept.
    The video search backend is flaky (same query can fail then succeed),
    so we try several query variants with a retry each.
    Returns {'video_id', 'url', 'title', 'transcript'} or None.
    """
    import time

    queries = [
        f"{concept} lecture explained computer architecture",
        f"{concept} lecture computer architecture",
        f"{concept} explained tutorial",
    ]
    results = []
    for query in queries:
        for attempt in range(2):
            try:
                results = list(DDGS().videos(query, max_results=max_candidates))
            except Exception as e:
                log.info(f"  video search miss ('{query[:40]}', try {attempt + 1}): {e}")
                time.sleep(2)
                continue
            if results:
                break
        if results:
            break
    if not results:
        log.warning(f"  video search failed for '{concept}' after all variants")
        return None

    for r in results:
        url = r.get("content", "")
        vid = _video_id_from_url(url)
        if not vid:
            continue
        mins = _duration_minutes(r.get("duration", ""))
        if mins is None or mins < MIN_DURATION_MIN or mins > MAX_DURATION_MIN:
            continue
        transcript = fetch_transcript(vid)
        if not transcript or len(transcript) < MIN_LECTURE_CHARS:
            continue
        return {
            "video_id": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": r.get("title", concept),
            "transcript": transcript,
        }
    return None


def generate_learning_card(concept: str, video: dict) -> dict | None:
    prompt = CONCEPT_PROMPT.replace("{concept}", concept) \
                           .replace("{raw_text}", video["transcript"][:TRANSCRIPT_BUDGET]) \
                           .replace("{url}", video["url"])
    try:
        card = _gemini_json(prompt, temperature=0.3)
    except Exception as e:
        log.error(f"  learning card generation failed for '{concept}': {e}")
        return None

    score = card.get("importance_score", 0)
    if score < 0.5:
        log.info(f"  '{concept}': video judged low-value ({score}) — skipping")
        return None
    card["notify"] = score >= 0.65
    card["notification_level"] = "brief" if card["notify"] else "none"
    return card


def run_learning_track(max_cards: int = 1) -> int:
    """
    Teach up to max_cards uncovered concepts. Returns cards generated.
    Learning cards enter intelligence_cards and flow through the normal
    notification path.
    """
    client = get_client()
    concepts = mine_concepts()
    if not concepts:
        log.info("Learning track: no uncovered concepts found.")
        return 0

    log.info(f"Learning track: top uncovered concepts: {concepts[:5]}")
    generated = 0

    for concept, freq in concepts:
        if generated >= max_cards:
            break

        video = find_lecture(concept)
        if not video:
            log.info(f"  '{concept}': no suitable lecture found — marking skipped")
            try:
                client.table("learning_concepts").insert({
                    "concept": concept, "status": "no_video",
                }).execute()
            except Exception:
                pass
            continue

        log.info(f"  '{concept}' ({freq} refs) → {video['title'][:60]}")
        card = generate_learning_card(concept, video)
        if not card:
            continue

        item_id = insert_raw_item(
            source_id=_youtube_source_id(),
            title=f"[Learning] {concept}: {video['title'][:100]}",
            url=video["url"],
            raw_text=f"LEARNING TRACK — concept: {concept}\n\nTRANSCRIPT:\n{video['transcript'][:8000]}",
        )
        if not item_id:
            log.info(f"  '{concept}': video already used — skipping")
            continue

        insert_intelligence_card(item_id, card)
        try:
            client.table("learning_concepts").insert({
                "concept": concept,
                "video_url": video["url"],
                "video_title": video["title"][:200],
                "status": "covered",
            }).execute()
        except Exception as e:
            log.warning(f"  couldn't mark '{concept}' covered: {e}")

        log.info(f"  📚 Learning card generated: {concept} (score {card.get('importance_score')})")
        generated += 1

    return generated


def _youtube_source_id() -> int:
    client = get_client()
    r = client.table("sources").select("id").eq("type", "youtube").execute()
    return r.data[0]["id"] if r.data else 24
