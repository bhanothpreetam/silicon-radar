"""
Silicon Radar — YouTube Collector

Pulls new videos from curated semiconductor channels via their public
RSS feeds (no API key), fetches each video's transcript, and stores it
as a raw item so the card generator can produce an intelligence card
from the video's actual content — not just its title.

Videos without a transcript yet (captions can lag upload by hours) are skipped
so they retry naturally. If YouTube blocks the runner IP entirely, the
collector falls back to explicitly labelled RSS metadata instead of repeatedly
making requests that cannot succeed.
"""

import logging
import os
from datetime import datetime, timezone, timedelta

import feedparser
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    IpBlocked, NoTranscriptFound, RequestBlocked, TranscriptsDisabled,
    VideoUnavailable,
)
from youtube_transcript_api.proxies import GenericProxyConfig

from app.config import YOUTUBE_CHANNELS
from db.models import insert_raw_item, get_client

log = logging.getLogger(__name__)

MAX_TRANSCRIPT_CHARS = 40_000  # v2 needs the lecture's complete causal arc where available
MIN_TRANSCRIPT_CHARS = 1200  # skips Shorts/teasers — not enough content for a real card
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
METADATA_ONLY_MARKER = "TRANSCRIPT STATUS: metadata-only"

# Once YouTube rejects the GitHub runner's cloud IP, every later transcript
# request in that job will fail for the same reason. Remember the state so all
# configured channels do not repeat the same doomed request.
_transcript_access_blocked = False
_transcript_api: YouTubeTranscriptApi | None = None


def _video_exists(url: str) -> bool:
    client = get_client()
    r = client.table("raw_items").select("id").eq("url", url).limit(1).execute()
    return bool(r.data)


def _get_transcript_api() -> YouTubeTranscriptApi:
    """Build one transcript client, optionally routed through a user proxy."""
    global _transcript_api
    if _transcript_api is None:
        proxy_url = os.getenv("YOUTUBE_TRANSCRIPT_PROXY_URL", "").strip()
        proxy_config = None
        if proxy_url:
            proxy_config = GenericProxyConfig(
                http_url=proxy_url,
                https_url=proxy_url,
            )
        _transcript_api = YouTubeTranscriptApi(proxy_config=proxy_config)
    return _transcript_api


def fetch_transcript(video_id: str) -> str | None:
    global _transcript_access_blocked

    if _transcript_access_blocked:
        return None

    try:
        transcript = _get_transcript_api().fetch(video_id)
        return " ".join(seg.text for seg in transcript)
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        return None
    except (IpBlocked, RequestBlocked):
        _transcript_access_blocked = True
        log.warning(
            "  [YouTube] transcript access is blocked from this runner IP; "
            "using RSS metadata for this run. Set YOUTUBE_TRANSCRIPT_PROXY_URL "
            "to restore transcript-first ingestion."
        )
        return None
    except Exception as e:
        log.warning(f"  [YouTube] transcript error for {video_id}: {e}")
        return None


def _entry_description(entry) -> str:
    """Extract the richest text exposed by YouTube's public RSS entry."""
    candidates = [
        getattr(entry, "media_description", "") or "",
        entry.get("summary", "") or "",
        entry.get("description", "") or "",
    ]
    candidates.extend(
        part.get("value", "")
        for part in (entry.get("content", []) or [])
        if isinstance(part, dict)
    )
    cleaned = [
        BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
        for value in candidates
        if value
    ]
    return max(cleaned, key=len, default="")


def _metadata_raw_text(channel_name: str, handle: str, title: str, description: str) -> str:
    limitation = (
        "The video transcript was unavailable because YouTube blocked the "
        "cloud runner IP. Treat this as an announcement-level source: use only "
        "the title and description below, lower confidence, and do not invent "
        "claims, measurements, mechanisms, or quotations."
    )
    return (
        f"YOUTUBE VIDEO by {channel_name} (@{handle})\n"
        f"Title: {title}\n"
        f"{METADATA_ONLY_MARKER}\n"
        f"Source limitation: {limitation}\n\n"
        f"DESCRIPTION:\n{description[:4000] if description else '(not supplied by the RSS feed)'}"
    )


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
            if not _transcript_access_blocked:
                log.info(f"  [YouTube] no transcript yet: {title[:60]} — will retry next run")
                continue

            description = _entry_description(entry)
            item_id = insert_raw_item(
                source_id=source_id,
                title=f"[YouTube] {channel_name}: {title}",
                url=url,
                raw_text=_metadata_raw_text(
                    channel_name, handle, title, description
                ),
                published_at=published,
            )
            if item_id:
                new_here += 1
                log.info(
                    f"  [YouTube] New metadata-only item: "
                    f"{channel_name} — {title[:60]}"
                )
            continue
        if len(transcript) < MIN_TRANSCRIPT_CHARS:
            log.info(f"  [YouTube] skipping Short/teaser ({len(transcript)} chars): {title[:60]}")
            continue

        description = _entry_description(entry)

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
