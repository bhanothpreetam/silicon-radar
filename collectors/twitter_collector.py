"""
Silicon Radar — Twitter/X Collector
Uses twscrape to pull tweets from curated semiconductor/AI-hardware accounts.
Accounts stored in data/twscrape_accounts.db (persists login sessions).
"""

import asyncio
import base64
import logging
import os
import re
import random
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import twscrape

from app.config import config, TWITTER_ACCOUNTS
from db.models import insert_raw_item, get_client

log = logging.getLogger(__name__)


def _patch_xclid() -> None:
    """
    Monkey-patch twscrape's XClIdGenStore.get() to skip the brittle X.com
    script-parsing step (broken as of 2026-05 when X changed their JS bundle
    format). We return a minimal stub whose calc() produces a plausible
    base64-encoded transaction ID so requests aren't rejected outright.
    """
    from twscrape import queue_client as qc

    class _StubGen:
        def calc(self, method: str, path: str) -> str:
            # Produce a random-looking base64 string of reasonable length
            return base64.b64encode(os.urandom(80)).decode()

    _stub = _StubGen()

    async def _patched_get(username: str, fresh: bool = False):
        return _stub

    qc.XClIdGenStore.get = _patched_get  # type: ignore[assignment]


_patch_xclid()

# Path for twscrape's account/session database
_DB_PATH = Path(__file__).parent.parent / "data" / "twscrape_accounts.db"

# Credibility by tier (username → score)
_TIER_MAP: dict[str, int] = {}

def _build_tier_map() -> dict[str, int]:
    m: dict[str, int] = {}
    for u in config.TWITTER_TIER1:
        m[u.lower()] = 10
    for u in config.TWITTER_TIER2:
        m[u.lower()] = 9
    for u in (
        list(config.TWITTER_TIER3) +
        list(config.TWITTER_VLSI_EDA) +
        list(config.TWITTER_DIGITAL_DESIGN) +
        list(config.TWITTER_OPEN_SILICON) +
        list(config.TWITTER_CHIP_ARCH)
    ):
        m[u.lower()] = 8
    # everything else defaults to 7
    return m

_TIER_MAP = _build_tier_map()


def tier_credibility(username: str) -> int:
    return _TIER_MAP.get(username.lower(), 7)


async def _get_api() -> twscrape.API:
    """Return an authenticated twscrape API instance.

    Prefers cookie-based auth (TWITTER_COOKIES in .env) because X.com blocks
    password logins from datacenter/VPS IPs via Cloudflare. Cookie auth works
    from any IP by reusing an existing browser session.
    """
    _DB_PATH.parent.mkdir(exist_ok=True)

    # Delete stale DB so cookie changes in .env always take effect
    if _DB_PATH.exists() and config.TWITTER_COOKIES:
        existing = twscrape.API(str(_DB_PATH))
        accts = await existing.pool.get_all()
        needs_reset = not accts or not any(a.active for a in accts)
        if needs_reset:
            _DB_PATH.unlink()

    api = twscrape.API(str(_DB_PATH))

    if config.TWITTER_COOKIES:
        # Cookie-based: bypasses password login entirely
        await api.pool.add_account_cookies(
            username=config.TWITTER_USERNAME or "x_user",
            cookies=config.TWITTER_COOKIES,
        )
    else:
        # Password login (may be blocked by Cloudflare on VPS/home IPs)
        await api.pool.add_account(
            username=config.TWITTER_USERNAME,
            password=config.TWITTER_PASSWORD,
            email=config.TWITTER_EMAIL,
            email_password=config.TWITTER_PASSWORD,
        )
        await api.pool.login_all()

    return api


def _parse_iso(s: str) -> datetime:
    """Parse ISO datetime strings from Supabase, which sometimes return
    5-digit fractional seconds that Python <3.11 fromisoformat rejects."""
    s = s.replace('Z', '+00:00')
    # Pad fractional seconds to 6 digits (e.g. .96655 → .966550)
    s = re.sub(r'(\.\d+)(?=[+-])', lambda m: m.group(1).ljust(7, '0')[:7], s)
    return datetime.fromisoformat(s)


def get_cached_user_id(username: str) -> str | None:
    client = get_client()
    result = client.table('twitter_user_cache') \
        .select('user_id,cached_at') \
        .eq('username', username.lower()) \
        .execute()
    if not result.data:
        return None
    cached_at = _parse_iso(result.data[0]['cached_at'])
    if (datetime.now(timezone.utc) - cached_at).days > 7:
        return None
    return result.data[0]['user_id']


def cache_user_id(username: str, user_id: str) -> None:
    client = get_client()
    client.table('twitter_user_cache').upsert({
        'username': username.lower(),
        'user_id': user_id,
        'cached_at': datetime.now(timezone.utc).isoformat(),
    }).execute()


# Platform domains that carry no endorsement signal when linked from a tweet
_LINK_SKIP = {
    "x.com", "twitter.com", "t.co", "youtube.com", "youtu.be", "reddit.com",
    "linkedin.com", "facebook.com", "instagram.com", "github.com",
    "wikipedia.org", "google.com", "amazon.com", "t.me",
    "bit.ly", "tinyurl.com", "buff.ly", "ow.ly", "goo.gl",
    "pinterest.com", "bsky.app", "flipboard.com", "whatsapp.com",
}


def _youtube_video_id(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.removeprefix("www.").lower()
    if host.endswith("youtube.com"):
        return urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
    if host == "youtu.be":
        return parsed.path.lstrip("/").split("/")[0] or None
    return None


def _mine_endorsements(username: str, tweets: list) -> list[dict]:
    """
    Extract endorsement edges from a batch of tweets:
    retweets/quotes of other accounts, mentions, and outbound article links.
    This is the raw material for citation-graph source discovery.
    """
    me = username.lower()
    events = []
    for t in tweets:
        try:
            rt = t.retweetedTweet
            if rt is not None and rt.user and rt.user.username.lower() != me:
                events.append({
                    "endorser": me, "endorser_type": "twitter",
                    "target": rt.user.username.lower(), "target_type": "twitter",
                    "kind": "retweet", "evidence": t.url,
                })
            qt = getattr(t, "quotedTweet", None)
            if qt is not None and qt.user and qt.user.username.lower() != me:
                events.append({
                    "endorser": me, "endorser_type": "twitter",
                    "target": qt.user.username.lower(), "target_type": "twitter",
                    "kind": "quote", "evidence": t.url,
                })
            # Mentions only in original tweets (reply mentions are conversation noise)
            if getattr(t, "inReplyToUser", None) is None:
                for mu in getattr(t, "mentionedUsers", None) or []:
                    if mu.username.lower() != me:
                        events.append({
                            "endorser": me, "endorser_type": "twitter",
                            "target": mu.username.lower(), "target_type": "twitter",
                            "kind": "mention", "evidence": t.url,
                        })
            for link in getattr(t, "links", None) or []:
                url = getattr(link, "url", None)
                if not url:
                    continue
                domain = urllib.parse.urlparse(url).netloc.removeprefix("www.").lower()
                if not domain:
                    continue
                # YouTube links are channel-discovery signal, not domain noise:
                # log the video id; citation graph resolves video → channel later
                video_id = _youtube_video_id(url)
                if video_id:
                    events.append({
                        "endorser": me, "endorser_type": "twitter",
                        "target": video_id, "target_type": "youtube_video",
                        "kind": "link", "evidence": t.url,
                    })
                    continue
                if domain in _LINK_SKIP or any(
                        domain == s or domain.endswith("." + s) for s in _LINK_SKIP):
                    continue
                events.append({
                    "endorser": me, "endorser_type": "twitter",
                    "target": domain, "target_type": "domain",
                    "kind": "link", "evidence": t.url,
                })
        except Exception:
            continue
    return events


def _log_endorsements(events: list[dict]) -> None:
    if not events:
        return
    try:
        client = get_client()
        client.table("endorsements").upsert(
            events,
            on_conflict="endorser,target,kind,evidence",
            ignore_duplicates=True,
        ).execute()
    except Exception as e:
        log.debug(f"  endorsement logging skipped: {e}")


def _get_twitter_source_id() -> int | None:
    """Look up the Twitter/X source row in Supabase."""
    client = get_client()
    resp = client.table("sources").select("id").eq("name", "Twitter/X").limit(1).execute()
    if not resp.data:
        log.error("Twitter/X source not found in sources table. Run the INSERT SQL first.")
        return None
    return resp.data[0]["id"]


async def collect_twitter_accounts(
    accounts: list[str],
    source_id: int,
    tweets_per_account: int = 10,
    max_age_hours: int = 168,  # 7 days — low-frequency posters covered by keyword filter
) -> int:
    """
    Collect tweets from the given accounts list.
    Skips retweets, old tweets, and low-engagement tweets.
    Returns count of new items stored.
    """
    api = await _get_api()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    total_new = 0

    for username in accounts:
        credibility = tier_credibility(username)
        # Tier 1 requires more engagement before we care
        min_likes = 20 if credibility == 10 else 5

        try:
            cached_id = get_cached_user_id(username)
            if cached_id:
                user_id = cached_id
                log.info(f"  [Twitter] Cache hit: @{username}")
            else:
                user = await api.user_by_login(username)
                if user is None:
                    log.warning(f"  [Twitter] @{username} not found, skipping")
                    continue
                user_id = str(user.id)
                cache_user_id(username, user_id)
                log.info(f"  [Twitter] Cached new ID: @{username} → {user_id}")

            collected = 0
            async def _fetch_tweets():
                results = []
                async for tweet in api.user_tweets(int(user_id), limit=tweets_per_account):
                    results.append(tweet)
                return results

            try:
                tweet_list = await asyncio.wait_for(_fetch_tweets(), timeout=45.0)
            except asyncio.TimeoutError:
                log.warning(f"  [Twitter] @{username} timed out after 45s — skipping")
                tweet_list = []

            # Mine endorsement edges (retweets/quotes/mentions/links) before
            # the storage loop discards retweets — fuel for source discovery
            _log_endorsements(_mine_endorsements(username, tweet_list))

            for tweet in tweet_list:
                # Skip retweets
                if tweet.retweetedTweet is not None:
                    continue

                # Skip old tweets
                tweet_dt = tweet.date
                if tweet_dt.tzinfo is None:
                    tweet_dt = tweet_dt.replace(tzinfo=timezone.utc)
                if tweet_dt < cutoff:
                    continue

                # Skip low-engagement tweets
                if tweet.likeCount < min_likes:
                    continue

                raw_text = (
                    f"TWEET by @{tweet.user.username} "
                    f"({tweet.user.followersCount:,} followers)\n\n"
                    f"{tweet.rawContent}\n\n"
                    f"Likes: {tweet.likeCount} | Retweets: {tweet.retweetCount}"
                )

                item_id = insert_raw_item(
                    source_id=source_id,
                    title=f"@{tweet.user.username}: {tweet.rawContent[:120]}",
                    url=tweet.url,
                    raw_text=raw_text,
                    published_at=tweet_dt,
                )
                if item_id:
                    collected += 1
                    total_new += 1
                    log.info(f"  [Twitter] @{username}: {tweet.rawContent[:70]}")

            log.info(f"  @{username} → {collected} new tweets")

        except Exception as e:
            log.error(f"  [Twitter] Error scraping @{username}: {e}")

    return total_new


def collect_twitter(source_id: int, accounts: list[str] | None = None) -> int:
    """Sync wrapper — runs the async collector. Uses all accounts if none specified."""
    if accounts is None:
        accounts = TWITTER_ACCOUNTS
    return asyncio.run(collect_twitter_accounts(accounts, source_id))


def collect_probation_twitter() -> int:
    """
    Collect from Twitter accounts currently on probation (rows in the
    sources table, type='twitter', status='probation'). Each account's
    items are stored under its own source row so the probation evaluator
    can attribute reactions to the right source.
    """
    client = get_client()
    try:
        rows = (
            client.table("sources").select("id,name,url")
            .eq("type", "twitter").eq("status", "probation")
            .execute().data or []
        )
    except Exception as e:
        log.debug(f"probation twitter skipped: {e}")
        return 0

    total = 0
    for r in rows:
        handle = urllib.parse.urlparse(r["url"]).path.strip("/").split("/")[0]
        if not handle:
            continue
        log.info(f"  [Twitter] 🧪 probation: @{handle}")
        try:
            total += asyncio.run(collect_twitter_accounts([handle], source_id=r["id"]))
        except Exception as e:
            log.error(f"  [Twitter] probation @{handle} failed: {e}")
    return total
