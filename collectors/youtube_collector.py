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

MAX_TRANSCRIPT_CHARS = 8000
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


def collect_youtube(source_id: int, max_age_days: int = 7) -> int:
    """
    Collect new videos with transcripts from all configured channels.
    Returns count of new items stored.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    total_new = 0

    for handle, channel_id in YOUTUBE_CHANNELS.items():
        try:
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
                media = entry.get("media_group") or {}
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
                    total_new += 1
                    log.info(f"  [YouTube] New: {channel_name} — {title[:60]} ({len(transcript)} chars)")

            log.info(f"  @{handle} → {new_here} new videos")

        except Exception as e:
            log.error(f"  [YouTube] channel error @{handle}: {e}")

    return total_new
