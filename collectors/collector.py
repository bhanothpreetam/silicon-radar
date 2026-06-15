"""
Silicon Radar — Collectors
Pulls raw items from RSS feeds, HN, Reddit, ArXiv.
All free, no paid API keys needed.
"""

import time
import httpx
import feedparser
from datetime import datetime, timezone
from typing import Optional
import logging

from app.config import config
from db.models import insert_raw_item, get_sources

log = logging.getLogger(__name__)


def _truncate(text: str, max_chars: int = 8000) -> str:
    """Truncate text to avoid massive token usage on Gemini."""
    return text[:max_chars] if text else ""


# ---------------------------------------------------------------------------
# RSS Collector
# ---------------------------------------------------------------------------

def collect_rss(source_id: int, feed_url: str, max_items: int = 20) -> int:
    """
    Pull articles from an RSS feed and store new ones.
    Returns count of new items stored.
    """
    new_count = 0
    try:
        feed = feedparser.parse(feed_url)
        entries = feed.entries[:max_items]

        for entry in entries:
            title = entry.get("title", "")
            url = entry.get("link", "")
            if not url:
                continue

            # Get body text — different feeds use different fields
            raw_text = (
                entry.get("summary", "")
                or entry.get("content", [{}])[0].get("value", "")
                or entry.get("description", "")
            )
            raw_text = _truncate(f"{title}\n\n{raw_text}")

            # Parse published date
            published = None
            if entry.get("published_parsed"):
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            item_id = insert_raw_item(source_id, title, url, raw_text, published)
            if item_id:
                new_count += 1
                log.info(f"  [RSS] New: {title[:60]}")

    except Exception as e:
        log.error(f"RSS collect error for {feed_url}: {e}")

    return new_count


# ---------------------------------------------------------------------------
# Hacker News Collector (via Algolia API — completely free, no auth)
# ---------------------------------------------------------------------------

def collect_hn(source_id: int, max_items: int = 30) -> int:
    """
    Search HN for semiconductor/AI hardware stories.
    Uses Algolia's HN search API — completely free.
    """
    new_count = 0
    base_url = "https://hn.algolia.com/api/v1/search_by_date"

    for keyword in config.HN_KEYWORDS[:8]:  # limit keywords per run
        try:
            resp = httpx.get(
                base_url,
                params={
                    "query": keyword,
                    "tags": "story",
                    "numericFilters": "points>5",  # filter out low-engagement posts
                    "hitsPerPage": 10,
                },
                timeout=15,
            )
            data = resp.json()

            for hit in data.get("hits", []):
                url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
                title = hit.get("title", "")
                if not title or not url:
                    continue

                # Build text from HN metadata
                raw_text = _truncate(
                    f"{title}\n\nHN Points: {hit.get('points', 0)} | "
                    f"Comments: {hit.get('num_comments', 0)}\n"
                    f"Keywords context: {keyword}"
                )

                ts_str = hit.get("created_at")
                published = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else None

                item_id = insert_raw_item(source_id, title, url, raw_text, published)
                if item_id:
                    new_count += 1
                    log.info(f"  [HN] New: {title[:60]}")

            time.sleep(0.5)  # be polite to Algolia

        except Exception as e:
            log.error(f"HN collect error for keyword '{keyword}': {e}")

    return new_count


# ---------------------------------------------------------------------------
# Reddit Collector (JSON API — no auth needed for public subreddits)
# ---------------------------------------------------------------------------

def collect_reddit(source_id: int, subreddit: str, max_items: int = 25) -> int:
    """
    Pull top posts from a subreddit using Reddit's public JSON API.
    No auth needed — just adds .json to any Reddit URL.
    """
    new_count = 0
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={max_items}"

    try:
        # Reddit requires a User-Agent, otherwise blocks with 429
        resp = httpx.get(
            url,
            headers={"User-Agent": "SiliconRadar/0.1 (personal research tool)"},
            timeout=15,
        )
        data = resp.json()
        posts = data.get("data", {}).get("children", [])

        for post in posts:
            d = post.get("data", {})
            title = d.get("title", "")
            post_url = d.get("url", "")
            selftext = d.get("selftext", "")
            score = d.get("score", 0)

            if not title or score < 10:  # filter low-signal posts
                continue

            # Use permalink as canonical URL if it's a discussion post
            permalink = f"https://reddit.com{d.get('permalink', '')}"
            canonical_url = post_url if post_url and not post_url.startswith("https://www.reddit.com") else permalink

            raw_text = _truncate(
                f"{title}\n\n{selftext}\n\n"
                f"Reddit r/{subreddit} | Score: {score} | Comments: {d.get('num_comments', 0)}"
            )

            published = datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc)
            item_id = insert_raw_item(source_id, title, canonical_url, raw_text, published)
            if item_id:
                new_count += 1
                log.info(f"  [Reddit] New: {title[:60]}")

    except Exception as e:
        log.error(f"Reddit collect error for r/{subreddit}: {e}")

    return new_count


# ---------------------------------------------------------------------------
# ArXiv Collector (official API — completely free)
# ---------------------------------------------------------------------------

def collect_arxiv(source_id: int, category: str, max_results: int = 20) -> int:
    """
    Pull recent papers from ArXiv using their official API.
    No auth needed. Focuses on cs.AR (computer architecture) primarily.
    """
    new_count = 0
    url = "https://export.arxiv.org/api/query"

    try:
        resp = httpx.get(
            url,
            params={
                "search_query": f"cat:{category}",
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": max_results,
            },
            timeout=30,
        )

        # ArXiv returns Atom XML — parse with feedparser
        feed = feedparser.parse(resp.text)

        for entry in feed.entries:
            title = entry.get("title", "").replace("\n", " ").strip()
            arxiv_url = entry.get("link", "")
            abstract = entry.get("summary", "")
            authors = ", ".join(a.get("name", "") for a in entry.get("authors", [])[:5])

            raw_text = _truncate(
                f"ARXIV PAPER: {title}\n\n"
                f"Authors: {authors}\n\n"
                f"Abstract: {abstract}\n\n"
                f"Category: {category}"
            )

            published = None
            if entry.get("published_parsed"):
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            item_id = insert_raw_item(source_id, title, arxiv_url, raw_text, published)
            if item_id:
                new_count += 1
                log.info(f"  [ArXiv] New: {title[:60]}")

    except Exception as e:
        log.error(f"ArXiv collect error for {category}: {e}")

    return new_count


# ---------------------------------------------------------------------------
# Main collection runner
# ---------------------------------------------------------------------------

def run_all_collectors() -> int:
    """Run all collectors and return total new items."""
    sources = get_sources()
    total_new = 0

    # Build lookup by name for special collectors
    source_map = {s["name"]: s for s in sources}

    log.info("=== Starting collection run ===")

    for source in sources:
        sid = source["id"]
        stype = source["type"]
        name = source["name"]
        url = source["url"]

        log.info(f"Collecting: {name}")

        if stype == "rss":
            n = collect_rss(sid, url)
        elif stype == "hn":
            n = collect_hn(sid)
        elif stype == "reddit":
            # Extract subreddit name from URL pattern
            subreddit = name.split("r/")[-1] if "r/" in name else "hardware"
            n = collect_reddit(sid, subreddit)
        elif stype == "arxiv":
            # Extract category from name
            category = name.split(" ")[-1]  # e.g. "ArXiv cs.AR" -> "cs.AR"
            n = collect_arxiv(sid, category)
        elif stype == "twitter":
            from collectors.twitter_collector import collect_twitter
            n = collect_twitter(sid)
        else:
            n = 0

        log.info(f"  → {n} new items from {name}")
        total_new += n
        time.sleep(1)  # be polite between sources

    log.info(f"=== Collection complete: {total_new} total new items ===")
    return total_new
