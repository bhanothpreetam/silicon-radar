"""
Silicon Radar — YouTube Collector

Pulls new videos from curated semiconductor channels via their public
RSS feeds (no API key), fetches each video's transcript, and stores it
as a raw item so the card generator can produce an intelligence card
from the video's actual content — not just its title.

Videos without a transcript yet (captions can lag upload by hours) are
skipped without inserting, so they retry naturally on the next run.
"""

import logging
from datetime import datetime, timezone, timedelta

import feedparser
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, NoTranscriptFound, VideoUnavailable,
)

from app.config import YOUTUBE_CHANNELS
from db.models import insert_raw_item, get_client

log = logging.getLogger(__name__)

MAX_TRANSCRIPT_CHARS = 40_000  # v2 needs the lecture's complete causal arc where available
MIN_TRANSCRIPT_CHARS = 1200  # skips Shorts/teasers — not enough content for a real card
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"


def _video_exists(url: str) -> bool:
    client = get_client()
    r = client.table("raw_items").select("id").eq("url", url).limit(1).execute()
    return bool(r.data)


def fetch_transcript(video_id: str) -> str | None:
    try:
        transcript = YouTubeTranscriptApi().fetch(video_id)
        return " ".join(seg.text for seg in transcript)
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        return None
    except Exception as e:
        log.warning(f"  [YouTube] transcript error for {video_id}: {e}")
        return None


def _collect_channel(channel_id: str, handle: str, source_id: int, cutoff: datetime) -> int:
    """Collect new transcribed videos from one channel into one source row."""
    feed = feedparser.parse(FEED_URL.format(cid=channel_id))
    channel_name = feed.feed.get("title", handle)
    new_here = 0

    for entry in feed.entries:
        video_id = getattr(entry, "yt_videoid", None)
        url = entry.get("link", "")
        title = entry.get("title", "")
        if not video_id or not url:
            continue

        published = None
        if entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        if published and published < cutoff:
            continue

        if _video_exists(url):
            continue

        transcript = fetch_transcript(video_id)
        if not transcript:
            log.info(f"  [YouTube] no transcript yet: {title[:60]} — will retry next run")
            continue
        if len(transcript) < MIN_TRANSCRIPT_CHARS:
            log.info(f"  [YouTube] skipping Short/teaser ({len(transcript)} chars): {title[:60]}")
            continue

        description = ""
        if hasattr(entry, "media_description"):
            description = entry.media_description or ""

        raw_text = (
            f"YOUTUBE VIDEO by {channel_name} (@{handle})\n"
            f"Title: {title}\n"
            f"{('Description: ' + description[:500]) if description else ''}\n\n"
            f"TRANSCRIPT:\n{transcript[:MAX_TRANSCRIPT_CHARS]}"
        )

        item_id = insert_raw_item(
            source_id=source_id,
            title=f"[YouTube] {channel_name}: {title}",
            url=url,
            raw_text=raw_text,
            published_at=published,
        )
        if item_id:
            new_here += 1
            log.info(f"  [YouTube] New: {channel_name} — {title[:60]} ({len(transcript)} chars)")

    log.info(f"  @{handle} → {new_here} new videos")
    return new_here


def _probation_channels() -> list[dict]:
    """Probation YouTube channels from the sources table (own source rows)."""
    import urllib.parse
    client = get_client()
    try:
        rows = (
            client.table("sources").select("id,name,url")
            .eq("type", "youtube").eq("status", "probation")
            .execute().data or []
        )
    except Exception:
        return []
    out = []
    for r in rows:
        cid = urllib.parse.parse_qs(urllib.parse.urlparse(r["url"]).query).get("channel_id", [None])[0]
        if cid:
            out.append({"channel_id": cid, "handle": r["name"], "source_id": r["id"]})
    return out


def collect_youtube(source_id: int, max_age_days: int = 7) -> int:
    """
    Collect new videos with transcripts from all configured channels,
    plus any channels currently on probation (stored under their own
    source rows so the evaluator can attribute reactions).
    Returns count of new items stored.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    total_new = 0

    for handle, channel_id in YOUTUBE_CHANNELS.items():
        try:
            total_new += _collect_channel(channel_id, handle, source_id, cutoff)
        except Exception as e:
            log.error(f"  [YouTube] channel error @{handle}: {e}")

    for ch in _probation_channels():
        try:
            log.info(f"  [YouTube] 🧪 probation channel: {ch['handle']}")
            total_new += _collect_channel(ch["channel_id"], ch["handle"], ch["source_id"], cutoff)
        except Exception as e:
            log.error(f"  [YouTube] probation channel error {ch['handle']}: {e}")

    return total_new
