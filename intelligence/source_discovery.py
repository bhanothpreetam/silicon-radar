"""
Silicon Radar — Intelligent Source Discovery (the Radar Intelligence Loop)

Learns the user's taste from feedback + card history, generates search
queries (core = deepen known interests, frontier = adjacent exploration),
hunts the web for candidate sources, and auditions them with Gemini
before they can enter the collection rotation.

Stages:
  1. build_taste_vector()   — weighted topic profile from DB signals
  2. generate_queries()     — Gemini: 8 core + 2 frontier search queries
  3. hunt_sources()         — web search → new domains → RSS autodiscovery
  4. audition_sources()     — Gemini scores candidates → stored ranked
"""

import json
import logging
import re
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone

import httpx
import feedparser
from bs4 import BeautifulSoup
from ddgs import DDGS
from google import genai
from google.genai import types

from app.config import config
from db.models import get_client

log = logging.getLogger(__name__)

REACTION_WEIGHTS = {"fire": 3.0, "brain": 2.0, "rabbit_hole": 2.0, "trash": -3.0}
RECENCY_HALF_LIFE_DAYS = 14
FEED_PATHS = ["/feed", "/rss", "/feed/", "/rss.xml", "/atom.xml", "/index.xml", "/feeds/posts/default"]

# Domains that are platforms/aggregators, not sources worth auditioning
SKIP_DOMAINS = {
    "youtube.com", "reddit.com", "x.com", "twitter.com", "linkedin.com",
    "facebook.com", "wikipedia.org", "github.com", "medium.com",
    "news.ycombinator.com", "google.com", "bing.com", "amazon.com",
    "quora.com", "stackexchange.com", "stackoverflow.com",
}


def _parse_iso(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    s = re.sub(r"(\.\d+)(?=[+-])", lambda m: m.group(1).ljust(7, "0")[:7], s)
    return datetime.fromisoformat(s)


_gemini_client: genai.Client | None = None

def _gemini() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEYS[0])
    return _gemini_client


def _gemini_json(prompt: str, temperature: float = 0.4) -> dict:
    response = _gemini().models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=4096,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return json.loads(response.text)


# ---------------------------------------------------------------------------
# Stage 1 — Taste Vector
# ---------------------------------------------------------------------------

def build_taste_vector() -> dict:
    """
    Blend explicit feedback (dominant when present) and implicit card history
    (importance-weighted with recency decay) into a topic profile.

    Returns {"topics": {layer: weight}, "exemplars": [summary, ...],
             "loved": [summary, ...], "hated": [summary, ...]}
    """
    client = get_client()
    now = datetime.now(timezone.utc)

    cards = client.table("intelligence_cards") \
        .select("id,one_line_summary,tech_layer,importance_score,generated_at") \
        .execute().data or []
    feedback = client.table("feedback").select("card_id,reaction").execute().data or []

    fb_by_card = defaultdict(list)
    for row in feedback:
        fb_by_card[row["card_id"]].append(row["reaction"])

    topics: dict[str, float] = defaultdict(float)
    scored_cards = []
    loved, hated = [], []

    for card in cards:
        age_days = (now - _parse_iso(card["generated_at"])).total_seconds() / 86400
        decay = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
        weight = (card.get("importance_score") or 0.5) * decay

        # Explicit feedback overrides implicit signal, heavily
        for reaction in fb_by_card.get(card["id"], []):
            weight += REACTION_WEIGHTS.get(reaction, 0) * max(decay, 0.3)
            summary = card.get("one_line_summary") or ""
            if reaction in ("fire", "brain", "rabbit_hole") and summary:
                loved.append(summary)
            elif reaction == "trash" and summary:
                hated.append(summary)

        for layer in card.get("tech_layer") or []:
            topics[layer] += weight
        scored_cards.append((weight, card.get("one_line_summary") or ""))

    # Normalize topic weights to 0..1
    if topics:
        top = max(topics.values())
        topics = {k: round(v / top, 3) for k, v in sorted(topics.items(), key=lambda x: -x[1])}

    scored_cards.sort(key=lambda x: -x[0])
    exemplars = [s for _, s in scored_cards[:20] if s]

    return {"topics": dict(topics), "exemplars": exemplars, "loved": loved, "hated": hated}


# ---------------------------------------------------------------------------
# Stage 2 — Curiosity Frontier (query generation)
# ---------------------------------------------------------------------------

def generate_queries(taste: dict, n_core: int = 8, n_frontier: int = 2) -> dict:
    """
    Turn the taste vector into web search queries.
    Core queries deepen the strongest interests; frontier queries explore
    topics one conceptual hop away that the profile has never seen.
    """
    client = get_client()
    existing = client.table("sources").select("name,url").execute().data or []
    existing_names = ", ".join(s["name"] for s in existing)

    top_topics = list(taste["topics"].items())[:12]
    topics_str = "\n".join(f"  {t}: {w}" for t, w in top_topics)
    exemplars_str = "\n".join(f"  - {e}" for e in taste["exemplars"][:15])
    loved_str = "\n".join(f"  - {e}" for e in taste["loved"]) or "  (none yet)"

    prompt = f"""You are the discovery engine of a personalized semiconductor-industry radar.

READER PROFILE — topic weights (0-1, from their reading + reactions):
{topics_str}

Highest-signal stories they've received:
{exemplars_str}

Stories they explicitly reacted positively to:
{loved_str}

Sources ALREADY in rotation (do not target these):
{existing_names}

Generate web search queries to find NEW publications, blogs, newsletters, and
research feeds this reader would love.

Rules:
- {n_core} "core" queries: deepen their strongest interests. Target technical
  depth (analyst blogs, engineering blogs, niche trade press) — not generic news.
- {n_frontier} "frontier" queries: topics ONE conceptual hop away that a person
  with this profile would love but the profile shows no exposure to yet.
  Be creative — think adjacent layers of the stack, upstream/downstream of
  their interests.
- Queries should be phrased to surface publications/feeds, not individual
  articles (e.g. "chip packaging analysis blog" not "TSMC CoWoS news today").

Return JSON:
{{"core": ["query1", ...], "frontier": ["query1", ...],
  "persona": "2-sentence description of this reader",
  "frontier_rationale": "1 sentence on why you chose these frontier topics"}}"""

    result = _gemini_json(prompt)
    log.info(f"Persona: {result.get('persona', '')}")
    return result


# ---------------------------------------------------------------------------
# Stage 3 — Source Hunt
# ---------------------------------------------------------------------------

def _domain_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.removeprefix("www.").lower()


def _existing_domains() -> set:
    client = get_client()
    sources = client.table("sources").select("url").execute().data or []
    domains = set()
    for s in sources:
        try:
            domains.add(_domain_of(s["url"]))
        except Exception:
            pass
    return domains


def discover_feed(domain: str, timeout: float = 8.0) -> str | None:
    """Find a working RSS/Atom feed for a domain: <link> tags first, then common paths."""
    base = f"https://{domain}"
    headers = {"User-Agent": "Mozilla/5.0 (SiliconRadar feed discovery)"}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as http:
            resp = http.get(base)
            soup = BeautifulSoup(resp.text, "html.parser")
            candidates = [
                urllib.parse.urljoin(str(resp.url), link["href"])
                for link in soup.find_all("link", rel="alternate")
                if link.get("type") in ("application/rss+xml", "application/atom+xml") and link.get("href")
            ]
            candidates += [base + p for p in FEED_PATHS]
            for feed_url in candidates:
                try:
                    r = http.get(feed_url)
                    if r.status_code != 200:
                        continue
                    parsed = feedparser.parse(r.text)
                    if parsed.entries:
                        return feed_url
                except Exception:
                    continue
    except Exception as e:
        log.debug(f"  feed discovery failed for {domain}: {e}")
    return None


def hunt_sources(queries: list[str], results_per_query: int = 8) -> list[dict]:
    """
    Search the web for each query, collect unseen domains, and try to
    autodiscover an RSS feed for each. Returns candidate dicts.
    """
    seen = _existing_domains()
    client = get_client()
    try:
        already = client.table("discovered_sources").select("domain").execute().data or []
        seen |= {r["domain"] for r in already}
    except Exception:
        pass  # table may not exist yet — dry run

    candidates: dict[str, dict] = {}
    for query in queries:
        try:
            results = list(DDGS().text(query, max_results=results_per_query))
        except Exception as e:
            log.warning(f"  search failed for '{query}': {e}")
            continue
        for r in results:
            domain = _domain_of(r["href"])
            if not domain or domain in seen or domain in SKIP_DOMAINS:
                continue
            if any(domain.endswith("." + skip) or domain == skip for skip in SKIP_DOMAINS):
                continue
            if domain in candidates:
                candidates[domain]["hits"] += 1
                continue
            candidates[domain] = {
                "domain": domain,
                "title": r.get("title", ""),
                "snippet": r.get("body", "")[:300],
                "discovery_query": query,
                "hits": 1,
            }
        log.info(f"  '{query[:60]}' → {len(results)} results")

    log.info(f"Hunting feeds for {len(candidates)} new domains...")
    for domain, cand in candidates.items():
        cand["feed_url"] = discover_feed(domain)

    return list(candidates.values())


# ---------------------------------------------------------------------------
# Stage 4 — Source Audition
# ---------------------------------------------------------------------------

def _audition_batch(batch: list[dict], topics_str: str) -> None:
    """Audition one batch of candidates in a single Gemini call (mutates batch)."""
    cands_str = "\n".join(
        f'{i}. {c["domain"]} — "{c["title"][:80]}" — {c["snippet"][:120]} '
        f'(feed: {"yes" if c.get("feed_url") else "no"}, found {c["hits"]}x)'
        for i, c in enumerate(batch)
    )

    prompt = f"""You are auditioning candidate sources for a personalized semiconductor radar.

READER'S TOP INTERESTS (weight 0-1):
{topics_str}

CANDIDATE SOURCES:
{cands_str}

Score each candidate 0.0-1.0 on:
- relevance: how well its content matches the reader's interests
- depth: technical depth (analyst/engineering content > consumer news > marketing)
- uniqueness: does it add coverage the big mainstream outlets don't?

Judge from the domain and description. Well-known low-quality content farms,
SEO spam, market-research report mills, and press-release wires score low.

Keep each verdict under 15 words.

Return JSON: {{"auditions": [{{"index": 0, "relevance": 0.8, "depth": 0.7,
"uniqueness": 0.6, "verdict": "what this source is, why it fits or doesn't"}}, ...]}}"""

    result = _gemini_json(prompt, temperature=0.2)
    for a in result.get("auditions", []):
        i = a.get("index")
        if i is None or i >= len(batch):
            continue
        score = round(
            0.45 * a.get("relevance", 0) + 0.35 * a.get("depth", 0) + 0.20 * a.get("uniqueness", 0),
            3,
        )
        batch[i]["audition"] = a
        batch[i]["audition_score"] = score


def audition_sources(candidates: list[dict], taste: dict, batch_size: int = 15) -> list[dict]:
    """
    Gemini scores every candidate against the reader profile, in batches
    to stay within output token limits. Returns candidates ranked by score.
    """
    if not candidates:
        return []

    top_topics = list(taste["topics"].items())[:10]
    topics_str = "\n".join(f"  {t}: {w}" for t, w in top_topics)

    for start in range(0, len(candidates), batch_size):
        batch = candidates[start:start + batch_size]
        try:
            _audition_batch(batch, topics_str)
            log.info(f"  auditioned {start + len(batch)}/{len(candidates)}")
        except Exception as e:
            log.warning(f"  audition batch failed ({start}-{start + len(batch)}): {e}")

    ranked = sorted(candidates, key=lambda c: -(c.get("audition_score") or 0))
    return ranked


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_profile(taste: dict, queries: dict) -> None:
    client = get_client()
    client.table("interest_profile").insert({
        "profile": {
            "topics": taste["topics"],
            "persona": queries.get("persona", ""),
            "queries_core": queries.get("core", []),
            "queries_frontier": queries.get("frontier", []),
            "frontier_rationale": queries.get("frontier_rationale", ""),
        },
    }).execute()


def save_candidates(ranked: list[dict]) -> int:
    client = get_client()
    saved = 0
    for c in ranked:
        try:
            client.table("discovered_sources").upsert({
                "domain": c["domain"],
                "name": c["title"][:120],
                "feed_url": c.get("feed_url"),
                "discovery_query": c["discovery_query"],
                "audition": c.get("audition"),
                "audition_score": c.get("audition_score"),
                "status": "candidate",
            }, on_conflict="domain").execute()
            saved += 1
        except Exception as e:
            log.warning(f"  failed to save {c['domain']}: {e}")
    return saved


# ---------------------------------------------------------------------------
# Full loop
# ---------------------------------------------------------------------------

def run_discovery(persist: bool = True) -> dict:
    """Run the full intelligence loop. Returns everything for inspection."""
    log.info("=== Stage 1: Taste Vector ===")
    taste = build_taste_vector()
    log.info(f"  {len(taste['topics'])} topics, {len(taste['loved'])} loved, {len(taste['hated'])} hated")

    log.info("=== Stage 2: Curiosity Frontier ===")
    queries = generate_queries(taste)
    all_queries = queries.get("core", []) + queries.get("frontier", [])
    log.info(f"  {len(queries.get('core', []))} core + {len(queries.get('frontier', []))} frontier queries")

    log.info("=== Stage 3: Source Hunt ===")
    candidates = hunt_sources(all_queries)
    with_feeds = sum(1 for c in candidates if c.get("feed_url"))
    log.info(f"  {len(candidates)} new domains found, {with_feeds} with working feeds")

    log.info("=== Stage 4: Source Audition ===")
    ranked = audition_sources(candidates, taste)

    if persist:
        try:
            save_profile(taste, queries)
            n = save_candidates(ranked)
            log.info(f"  Saved profile + {n} candidates to DB")
        except Exception as e:
            log.warning(f"  Persistence skipped (tables missing?): {e}")

    return {"taste": taste, "queries": queries, "candidates": ranked}
