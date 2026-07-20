"""
Silicon Radar — Database models
Uses supabase-py (REST over HTTPS) instead of psycopg2.
Bypasses IPv6-only direct Postgres and broken pooler registration.
"""

import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional

from supabase import create_client, Client
from app.config import config


def get_client() -> Client:
    return create_client(config.SUPABASE_URL, config.SUPABASE_KEY)


def compute_hash(text: str) -> str:
    """SHA-256 hash of text for exact deduplication."""
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# raw_items
# ---------------------------------------------------------------------------

def item_exists(url: str, content_hash: str) -> bool:
    """Check if we already have this item (by URL or content hash)."""
    client = get_client()
    r1 = client.table('raw_items').select('id').eq('url', url).limit(1).execute()
    if r1.data:
        return True
    r2 = client.table('raw_items').select('id').eq('content_hash', content_hash).limit(1).execute()
    return len(r2.data) > 0


def insert_raw_item(
    source_id: int,
    title: str,
    url: str,
    raw_text: str,
    published_at: Optional[datetime] = None,
) -> Optional[int]:
    """
    Insert a new raw item. Returns the new row ID, or None if duplicate.
    Does NOT insert if URL or hash already exists.
    """
    content_hash = compute_hash(url + (raw_text or "")[:500])

    if item_exists(url, content_hash):
        return None

    client = get_client()
    try:
        resp = client.table('raw_items').insert({
            'source_id': source_id,
            'title': title,
            'url': url,
            'raw_text': raw_text,
            'published_at': (published_at or datetime.now(timezone.utc)).isoformat(),
            'content_hash': content_hash,
        }).execute()
        return resp.data[0]['id'] if resp.data else None
    except Exception:
        return None


def get_unprocessed_items(limit: int = 50):
    """Get raw items that don't yet have an intelligence card."""
    import random
    client = get_client()

    # Find IDs already processed
    processed_resp = client.table('intelligence_cards').select('raw_item_id').execute()
    processed_ids = [r['raw_item_id'] for r in processed_resp.data]

    # Fetch a larger pool then shuffle so we don't drain one source before seeing others
    fetch_limit = min(limit * 6, 300)
    query = (
        client.table('raw_items')
        .select('id,title,url,raw_text,source_id')
        .order('fetched_at', desc=True)
        .limit(fetch_limit)
    )
    if processed_ids:
        query = query.not_.in_('id', processed_ids)
    items_resp = query.execute()

    if not items_resp.data:
        return []

    # Build source lookup first so we can use it for partitioning
    sources_resp = client.table('sources').select('id,type,credibility').execute()
    sources = {s['id']: s for s in sources_resp.data}

    # Twitter items go first (fresher, higher signal); shuffle within each partition
    twitter_pool = [i for i in items_resp.data if sources.get(i['source_id'], {}).get('type') == 'twitter']
    other_pool   = [i for i in items_resp.data if sources.get(i['source_id'], {}).get('type') != 'twitter']
    random.shuffle(twitter_pool)
    random.shuffle(other_pool)
    items_pool = (twitter_pool + other_pool)[:limit]

    result = []
    for item in items_pool:
        source = sources.get(item['source_id'], {})
        result.append({
            'id': item['id'],
            'title': item['title'],
            'url': item['url'],
            'raw_text': item['raw_text'],
            'source_type': source.get('type', 'rss'),
            'credibility': source.get('credibility', 5),
        })
    return result


# ---------------------------------------------------------------------------
# intelligence_cards
# ---------------------------------------------------------------------------

def insert_intelligence_card(raw_item_id: int, card: dict) -> int:
    """Insert a generated intelligence card. Returns new card ID."""
    client = get_client()
    resp = client.table('intelligence_cards').insert({
        'raw_item_id': raw_item_id,
        'one_line_summary': card.get('one_line_summary'),
        'what_happened': card.get('what_happened'),
        'who_is_involved': card.get('who_is_involved'),
        'tech_layer': card.get('tech_layer', []),
        'why_technical': card.get('why_technical'),
        'why_strategic': card.get('why_strategic'),
        'eli5_explanation': card.get('eli5_explanation'),
        'textbook_concepts': card.get('textbook_concepts', []),
        'textbook_bridge': card.get('textbook_bridge'),
        'industry_bridge': card.get('industry_bridge'),
        'flashcard_q1': card.get('flashcard_q1'),
        'flashcard_a1': card.get('flashcard_a1'),
        'flashcard_q2': card.get('flashcard_q2'),
        'flashcard_a2': card.get('flashcard_a2'),
        'flashcard_q3': card.get('flashcard_q3'),
        'flashcard_a3': card.get('flashcard_a3'),
        'quiz_question': card.get('quiz_question'),
        'quiz_answer': card.get('quiz_answer'),
        'rabbit_hole': card.get('rabbit_hole'),
        'research_angle': card.get('research_angle'),
        'startup_gap': card.get('startup_gap'),
        'watch_next': card.get('watch_next', []),
        'importance_score': card.get('importance_score', 0.5),
        'novelty_score': card.get('novelty_score', 0.5),
        'notify': card.get('notify', False),
        'notification_level': card.get('notification_level', 'none'),
    }).execute()
    return resp.data[0]['id']


def get_pending_notifications():
    """Get cards that should be notified but haven't been yet."""
    client = get_client()

    notified_resp = client.table('notifications').select('card_id').execute()
    notified_ids = [r['card_id'] for r in notified_resp.data]

    query = (
        client.table('intelligence_cards')
        .select('*')
        .eq('notify', True)
        .order('importance_score', desc=True)
        .limit(20)
    )
    if notified_ids:
        query = query.not_.in_('id', notified_ids)
    cards_resp = query.execute()

    if not cards_resp.data:
        return []

    item_ids = [c['raw_item_id'] for c in cards_resp.data]
    items_resp = client.table('raw_items').select('id,title,url,source_id').in_('id', item_ids).execute()
    items = {r['id']: r for r in items_resp.data}

    # Attach source status so probation cards can be visually flagged
    source_ids = list({r['source_id'] for r in items_resp.data if r.get('source_id')})
    statuses = {}
    if source_ids:
        try:
            src_resp = client.table('sources').select('id,status').in_('id', source_ids).execute()
            statuses = {r['id']: r.get('status') or 'trusted' for r in src_resp.data}
        except Exception:
            pass  # status column may not exist yet

    return [
        {**c, 'title': items.get(c['raw_item_id'], {}).get('title'),
               'url': items.get(c['raw_item_id'], {}).get('url'),
               'source_status': statuses.get(items.get(c['raw_item_id'], {}).get('source_id'), 'trusted')}
        for c in cards_resp.data
    ]


def get_daily_digest_cards(limit: int = 10):
    """Get today's top cards for the morning digest."""
    client = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    cards_resp = (
        client.table('intelligence_cards')
        .select('*')
        .gte('generated_at', cutoff)
        .gte('importance_score', config.MIN_IMPORTANCE_FOR_DIGEST)
        .order('importance_score', desc=True)
        .limit(limit)
        .execute()
    )

    if not cards_resp.data:
        return []

    item_ids = [c['raw_item_id'] for c in cards_resp.data]
    items_resp = client.table('raw_items').select('id,title,url').in_('id', item_ids).execute()
    items = {r['id']: r for r in items_resp.data}

    return [
        {**c, 'title': items.get(c['raw_item_id'], {}).get('title'),
               'url': items.get(c['raw_item_id'], {}).get('url')}
        for c in cards_resp.data
    ]


def log_notification(card_id: int, level: str, message: str, telegram_msg_id: int = None):
    """Record that we sent a notification."""
    client = get_client()
    client.table('notifications').insert({
        'card_id': card_id,
        'level': level,
        'message_text': message,
        'telegram_msg_id': telegram_msg_id,
    }).execute()


def save_feedback(card_id: int, reaction: str):
    """Save user feedback from Telegram inline buttons."""
    client = get_client()
    client.table('feedback').insert({
        'card_id': card_id,
        'reaction': reaction,
    }).execute()


def get_sources():
    """Get all active sources (trusted + probation; excludes blacklisted/shelved)."""
    client = get_client()
    resp = client.table('sources').select('*').order('credibility', desc=True).execute()
    return [s for s in resp.data
            if (s.get('status') or 'trusted') in ('trusted', 'probation')]
