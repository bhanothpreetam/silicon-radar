"""
Silicon Radar — Citation-Graph Source Discovery

Discovers new sources the way humans do: by following who your trusted
sources cite. Two edge types feed a shared `endorsements` table:

  - Twitter amplification (retweets/quotes/mentions/links), mined live
    by the collector on every run
  - Article outbound links, mined here by fetching recent raw_items'
    pages and extracting in-content external links

Candidates are ranked by trust-weighted endorsement mass (who endorsed
them × how strong the endorsement kind is), then auditioned by their
actual content before entering discovered_sources.
"""

import asyncio
import logging
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import httpx
from bs4 import BeautifulSoup

from app.config import config, TWITTER_ACCOUNTS
from db.models import get_client
from intelligence.source_discovery import (
    SKIP_DOMAINS, _existing_domains, _root_domain, _gemini_json,
    build_taste_vector, discover_feed,
)

log = logging.getLogger(__name__)

# How much each endorsement kind is worth
KIND_WEIGHTS = {
    "retweet": 1.0,
    "quote": 1.0,
    "article_link": 0.8,
    "link": 0.6,
    "mention": 0.3,
}

# Platforms, shorteners, and share-widget targets that carry no source signal
EXTRA_SKIP = {
    "pinterest.com", "bit.ly", "tinyurl.com", "buff.ly", "ow.ly", "goo.gl",
    "bsky.app", "t.me", "flipboard.com", "getpocket.com", "whatsapp.com",
    "substackcdn.com", "apple.com", "play.google.com",
}


def _is_skippable(domain: str) -> bool:
    all_skip = SKIP_DOMAINS | EXTRA_SKIP
    return (domain in all_skip
            or any(domain == s or domain.endswith("." + s) for s in all_skip))


def _is_self_endorsement(endorser: str, endorser_type: str,
                         target: str, target_type: str) -> bool:
    """A company tweeting links to its own site is not an endorsement."""
    if endorser_type == "twitter" and target_type == "domain":
        root_label = _root_domain(target).split(".")[0]
        return root_label == endorser.lower()
    return False


# ---------------------------------------------------------------------------
# Article outbound-link mining
# ---------------------------------------------------------------------------

def mine_article_links(days: int = 7, max_articles: int = 40) -> int:
    """
    Fetch recent collected articles and log their in-content external links
    as endorsement edges (article's domain → linked domain).
    Returns number of edges logged.
    """
    client = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    items = (
        client.table("raw_items")
        .select("url,fetched_at")
        .gte("fetched_at", cutoff)
        .order("fetched_at", desc=True)
        .limit(300)
        .execute()
        .data or []
    )
    # Articles only — tweets' links are already mined by the collector
    articles = [i["url"] for i in items
                if urllib.parse.urlparse(i["url"]).netloc.removeprefix("www.").lower()
                not in ("x.com", "twitter.com")][:max_articles]

    log.info(f"Mining outbound links from {len(articles)} recent articles...")
    events = []
    headers = {"User-Agent": "Mozilla/5.0 (SiliconRadar citation miner)"}

    with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as http:
        for url in articles:
            src_domain = urllib.parse.urlparse(url).netloc.removeprefix("www.").lower()
            try:
                resp = http.get(url)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
            except Exception:
                continue

            # Only links inside paragraphs/article body — skips nav, footers, blogrolls
            targets = set()
            for a in soup.select("p a[href], article a[href]"):
                href = a.get("href") or ""
                if not href.startswith("http"):
                    continue
                domain = urllib.parse.urlparse(href).netloc.removeprefix("www.").lower()
                if (not domain or domain == src_domain
                        or _root_domain(domain) == _root_domain(src_domain)):
                    continue
                if _is_skippable(domain):
                    continue
                targets.add(domain)

            for domain in list(targets)[:15]:  # cap per article — link farms
                events.append({
                    "endorser": src_domain, "endorser_type": "domain",
                    "target": domain, "target_type": "domain",
                    "kind": "article_link", "evidence": url,
                })

    if events:
        client.table("endorsements").upsert(
            events, on_conflict="endorser,target,kind,evidence", ignore_duplicates=True,
        ).execute()
    log.info(f"  logged {len(events)} article-link edges")
    return len(events)


# ---------------------------------------------------------------------------
# Trust-weighted candidate ranking
# ---------------------------------------------------------------------------

def _endorser_trust(endorser: str, endorser_type: str, source_cred: dict) -> float:
    """Trust of the endorser, 0..1."""
    if endorser_type == "twitter":
        from collectors.twitter_collector import tier_credibility
        return tier_credibility(endorser) / 10.0
    return source_cred.get(endorser, 7) / 10.0


def rank_candidates(min_endorsers: int = 2) -> list[dict]:
    """
    Aggregate the endorsement graph into ranked candidates not yet tracked.
    score = Σ (kind_weight × endorser_trust), requires ≥ min_endorsers
    distinct endorsers (one enthusiastic fan isn't a signal).
    """
    client = get_client()
    edges = client.table("endorsements").select(
        "endorser,endorser_type,target,target_type,kind"
    ).execute().data or []
    log.info(f"Ranking from {len(edges)} endorsement edges...")

    # Trust lookup for domain endorsers
    sources = client.table("sources").select("url,credibility").execute().data or []
    source_cred = {}
    for s in sources:
        try:
            d = urllib.parse.urlparse(s["url"]).netloc.removeprefix("www.").lower()
            source_cred[d] = s.get("credibility", 7)
        except Exception:
            pass

    tracked_accounts = {a.lower() for a in TWITTER_ACCOUNTS}
    tracked_domains = {_root_domain(d) for d in _existing_domains()}
    try:
        seen = client.table("discovered_sources").select("domain").execute().data or []
        already_discovered = {r["domain"].lstrip("@") for r in seen}
    except Exception:
        already_discovered = set()

    agg: dict[tuple, dict] = defaultdict(lambda: {"score": 0.0, "endorsers": set(), "kinds": defaultdict(int)})
    for e in edges:
        target, ttype = e["target"], e["target_type"]
        if ttype == "twitter" and target in tracked_accounts:
            continue
        if ttype == "domain" and (_root_domain(target) in tracked_domains or _is_skippable(target)):
            continue
        if target in already_discovered:
            continue
        if _is_self_endorsement(e["endorser"], e["endorser_type"], target, ttype):
            continue
        trust = _endorser_trust(e["endorser"], e["endorser_type"], source_cred)
        entry = agg[(target, ttype)]
        entry["score"] += KIND_WEIGHTS.get(e["kind"], 0.3) * trust
        entry["endorsers"].add(e["endorser"])
        entry["kinds"][e["kind"]] += 1

    ranked = [
        {
            "target": target, "target_type": ttype,
            "score": round(v["score"], 2),
            "endorsers": sorted(v["endorsers"]),
            "kinds": dict(v["kinds"]),
        }
        for (target, ttype), v in agg.items()
        if len(v["endorsers"]) >= min_endorsers
    ]
    ranked.sort(key=lambda c: -c["score"])
    return ranked


# ---------------------------------------------------------------------------
# Twitter account audition
# ---------------------------------------------------------------------------

async def _fetch_account_sample(handle: str, n: int = 20) -> tuple[str, list[str]]:
    """Return (display_name, recent original tweet texts) for an account."""
    from collectors.twitter_collector import _get_api
    api = await _get_api()
    user = await api.user_by_login(handle)
    if user is None:
        return "", []
    texts = []

    async def _pull():
        async for t in api.user_tweets(user.id, limit=n):
            if t.retweetedTweet is None and t.rawContent:
                texts.append(t.rawContent[:200])
        return texts

    try:
        await asyncio.wait_for(_pull(), timeout=45.0)
    except asyncio.TimeoutError:
        pass
    return user.displayname or handle, texts


def audition_twitter_account(handle: str, taste: dict, endorsement: dict) -> dict | None:
    """Audition a candidate account by its actual recent tweets."""
    name, tweets = asyncio.run(_fetch_account_sample(handle))
    if not tweets:
        return None

    topics_str = "\n".join(f"  {t}: {w}" for t, w in list(taste["topics"].items())[:10])
    tweets_str = "\n".join(f"  - {t[:150]}" for t in tweets[:15])
    endorsed_by = ", ".join("@" + e for e in endorsement["endorsers"])

    prompt = f"""You are auditioning a Twitter account as a source for a personalized semiconductor radar.

READER'S TOP INTERESTS (weight 0-1):
{topics_str}

CANDIDATE: @{handle} ({name})
Endorsed (retweeted/quoted/mentioned) by accounts the reader trusts: {endorsed_by}

Their ACTUAL recent tweets:
{tweets_str}

Score 0.0-1.0 based on what they actually post:
- relevance: overlap with the reader's interests
- depth: technical substance (engineering insight > hot takes > memes/promo)
- uniqueness: perspective the reader's current accounts don't provide

Return JSON: {{"relevance": 0.0, "depth": 0.0, "uniqueness": 0.0,
"verdict": "under 15 words: who this is and whether they fit"}}"""

    try:
        a = _gemini_json(prompt, temperature=0.2)
    except Exception as e:
        log.warning(f"  @{handle}: audition failed: {e}")
        return None

    score = round(0.45 * a.get("relevance", 0) + 0.35 * a.get("depth", 0) + 0.20 * a.get("uniqueness", 0), 3)
    return {"handle": handle, "name": name, "score": score, "audition": a}


# ---------------------------------------------------------------------------
# Full citation-graph discovery run
# ---------------------------------------------------------------------------

def run_citation_discovery(
    mine_articles: bool = True,
    max_twitter_auditions: int = 8,
    max_domain_candidates: int = 10,
    min_score: float = 0.55,
) -> dict:
    """
    Mine article links, rank all endorsement candidates, audition the top
    ones, and persist survivors to discovered_sources.
    """
    if mine_articles:
        log.info("=== Mining article outbound links ===")
        mine_article_links()

    log.info("=== Ranking endorsement candidates ===")
    ranked = rank_candidates()
    twitter_cands = [c for c in ranked if c["target_type"] == "twitter"][:max_twitter_auditions]
    domain_cands = [c for c in ranked if c["target_type"] == "domain"][:max_domain_candidates]
    log.info(f"  {len(ranked)} candidates ({len(twitter_cands)} twitter, {len(domain_cands)} domains to audition)")

    taste = build_taste_vector()
    client = get_client()
    verified_accounts, verified_domains = [], []

    log.info("=== Auditioning Twitter accounts ===")
    for cand in twitter_cands:
        result = audition_twitter_account(cand["target"], taste, cand)
        if result is None:
            log.info(f"  @{cand['target']}: no tweets fetchable — skipped")
            continue
        status = "verified" if result["score"] >= min_score else "rejected"
        log.info(f"  @{cand['target']}: {result['score']} → {status} — {result['audition'].get('verdict', '')[:60]}")
        client.table("discovered_sources").upsert({
            "domain": "@" + cand["target"],
            "name": result["name"][:120],
            "feed_url": None,
            "discovery_query": f"citation-graph: endorsed by {', '.join(cand['endorsers'][:5])}",
            "audition": {**result["audition"], "deep": True, "endorsement": cand["kinds"]},
            "audition_score": result["score"],
            "status": status,
        }, on_conflict="domain").execute()
        if status == "verified":
            verified_accounts.append(result)

    log.info("=== Feed discovery for cited domains ===")
    for cand in domain_cands:
        feed = discover_feed(cand["target"])
        log.info(f"  {cand['target']}: feed={'yes' if feed else 'no'} (score {cand['score']}, {len(cand['endorsers'])} endorsers)")
        client.table("discovered_sources").upsert({
            "domain": cand["target"],
            "name": cand["target"],
            "feed_url": feed,
            "discovery_query": f"citation-graph: cited by {', '.join(cand['endorsers'][:5])}",
            "audition": {"endorsement": cand["kinds"], "graph_score": cand["score"]},
            "audition_score": None,
            "status": "candidate",  # deep_audition() verifies these by feed content
        }, on_conflict="domain").execute()
        verified_domains.append({**cand, "feed_url": feed})

    return {
        "ranked": ranked,
        "twitter_verified": verified_accounts,
        "domains_queued": verified_domains,
    }
