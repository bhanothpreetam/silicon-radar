"""
Silicon Radar — Intelligence Card Generator
Uses Gemini 2.0 Flash (free tier) to convert raw articles
into structured "why it matters" intelligence cards.

Free tier limits: 1,500 req/day, 15 RPM, 1M token context
We stay well within this with careful rate limiting.
"""

import json
import time
import logging
from pathlib import Path

from google import genai
from google.genai import types

from app.config import config
from db.models import get_unprocessed_items, insert_intelligence_card

log = logging.getLogger(__name__)


class GeminiKeyRotator:
    def __init__(self, api_keys: list):
        self.keys = api_keys
        self.current_index = 0
        self.exhausted: set = set()

    def get_current_key(self) -> str | None:
        for i in range(len(self.keys)):
            idx = (self.current_index + i) % len(self.keys)
            if idx not in self.exhausted:
                self.current_index = idx
                return self.keys[idx]
        return None

    def mark_exhausted(self, key: str) -> None:
        try:
            idx = self.keys.index(key)
        except ValueError:
            return
        self.exhausted.add(idx)
        remaining = len(self.keys) - len(self.exhausted)
        log.warning(f"Key {idx+1}/{len(self.keys)} exhausted. {remaining} key(s) remaining today.")
        self.current_index = (idx + 1) % len(self.keys)

    @property
    def all_exhausted(self) -> bool:
        return len(self.exhausted) >= len(self.keys)

# Load the prompt template once at startup
PROMPT_TEMPLATE = (Path(__file__).parent.parent / "prompts" / "intelligence_card_v1.txt").read_text()

# Relevance pre-filter — skip items with no semiconductor/AI-hardware keywords
KEYWORDS = [
    "chip", "semiconductor", "TSMC", "NVIDIA", "AMD", "Intel",
    "ARM", "RISC-V", "HBM", "memory", "GPU", "CPU", "NPU", "ASIC",
    "foundry", "silicon", "wafer", "node", "process", "EDA", "VLSI",
    "packaging", "chiplet", "UCIe", "interconnect", "inference",
    "accelerator", "fabrication", "photonic", "quantum", "architecture",
    "EUV", "Qualcomm", "Snapdragon", "Cerebras", "Graviton",
    "3D-IC", "CoWoS", "photonics", "Tenstorrent", "Groq",
    "TPU", "MLPerf", "CXL", "Etched", "DRAM", "NAND",
    "fab", "tape-out", "reticle",
]
_KEYWORDS_LOWER = [k.lower() for k in KEYWORDS]


def _is_relevant(title: str) -> bool:
    """Return True if the title contains at least one domain keyword."""
    t = title.lower()
    return any(kw in t for kw in _KEYWORDS_LOWER)


# Key rotator — instantiated once at module load with all configured keys
_rotator = GeminiKeyRotator(config.GEMINI_API_KEYS)

# Rate limiting state
_requests_this_minute = 0
_minute_start = time.time()
_requests_today = 0
_day_start = time.time()


def _get_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def _rate_limit() -> bool:
    """Enforce Gemini free tier rate limits: 15 RPM, 1500 RPD."""
    global _requests_this_minute, _minute_start, _requests_today, _day_start

    now = time.time()

    if now - _day_start > 86400:
        _requests_today = 0
        _day_start = now

    if _requests_today >= config.GEMINI_REQUESTS_PER_DAY:
        log.warning("Daily Gemini quota reached. Stopping for today.")
        return False

    if now - _minute_start > 60:
        _requests_this_minute = 0
        _minute_start = now

    if _requests_this_minute >= config.GEMINI_REQUESTS_PER_MINUTE:
        sleep_time = 60 - (now - _minute_start) + 2
        log.info(f"Rate limit: sleeping {sleep_time:.1f}s")
        time.sleep(sleep_time)
        _requests_this_minute = 0
        _minute_start = time.time()

    _requests_this_minute += 1
    _requests_today += 1
    return True


def generate_intelligence_card(
    raw_item_id: int,
    title: str,
    url: str,
    raw_text: str,
    source_type: str,
    credibility: int,
) -> dict | None:
    """
    Send one raw item to Gemini and get back a structured intelligence card.
    Rotates through API keys on daily quota exhaustion.
    Returns the parsed card dict, or None on failure.
    """
    if not _rate_limit():
        return None

    prompt = PROMPT_TEMPLATE.format(
        raw_text=raw_text[:6000],
        url=url,
        source_type=source_type,
    )

    # Try each key at most once per item
    for attempt in range(len(_rotator.keys) + 1):
        current_key = _rotator.get_current_key()
        if current_key is None:
            log.error("All API keys exhausted for today. Stopping.")
            return None

        key_idx = _rotator.keys.index(current_key) + 1
        try:
            client = _get_client(current_key)
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=8192,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )

            card = json.loads(response.text)

            # Adjust importance based on source credibility
            credibility_boost = (credibility - 5) * 0.02
            card["importance_score"] = min(
                1.0,
                max(0.0, card.get("importance_score", 0.5) + credibility_boost)
            )

            # Re-evaluate notify/level after adjustment
            score = card["importance_score"]
            if score >= 0.90:
                card["notify"] = True
                card["notification_level"] = "wake_up"
            elif score >= 0.75:
                card["notify"] = True
                card["notification_level"] = "brief"
            elif score >= 0.65:
                card["notify"] = True
                card["notification_level"] = "ping"
            else:
                card["notify"] = False
                card["notification_level"] = "none"

            log.info(
                f"  [key {key_idx}] Card generated: score={score:.2f}, "
                f"level={card['notification_level']}, "
                f"title={title[:50]}"
            )

            time.sleep(config.DELAY_BETWEEN_REQUESTS)
            return card

        except json.JSONDecodeError as e:
            log.error(f"JSON parse error for {url}: {e}")
            return None

        except Exception as e:
            err_str = str(e)
            is_daily_exhausted = (
                "RESOURCE_EXHAUSTED" in err_str
                and "PerDay" in err_str
            )
            is_minute_limit = (
                "RESOURCE_EXHAUSTED" in err_str
                and "PerDay" not in err_str
            )

            if is_daily_exhausted:
                log.warning(f"  [key {key_idx}] Daily quota exhausted — rotating to next key")
                _rotator.mark_exhausted(current_key)
                # Immediately retry with next key (no sleep needed)
                continue

            elif is_minute_limit:
                # Per-minute cap — wait and retry with same key
                log.info(f"  [key {key_idx}] Per-minute rate limit — sleeping 62s")
                time.sleep(62)
                continue

            else:
                log.error(f"  [key {key_idx}] Gemini error for {url}: {err_str[:200]}")
                return None

    return None


def process_unprocessed_items(max_items: int = 50) -> int:
    """
    Main loop: pull unprocessed items, generate cards, store them.
    Keyword pre-filter runs before any Gemini call.
    Returns count of cards generated.
    """
    items = get_unprocessed_items(limit=max_items)
    log.info(f"Processing {len(items)} unprocessed items...")

    generated = 0
    filtered = 0
    for item in items:
        if not _is_relevant(item["title"]):
            log.info(f"  filtered: off-topic | {item['title'][:70]}")
            filtered += 1
            continue

        log.info(f"Generating card for: {item['title'][:60]}")

        card = generate_intelligence_card(
            raw_item_id=item["id"],
            title=item["title"],
            url=item["url"],
            raw_text=item["raw_text"] or "",
            source_type=item["source_type"],
            credibility=item["credibility"],
        )

        if card:
            insert_intelligence_card(item["id"], card)
            generated += 1
            print(f"\n{'='*60}")
            print(f"CARD {generated}: {item['title'][:70]}")
            print('='*60)
            print(json.dumps(card, indent=2, ensure_ascii=False))
        else:
            if _rotator.all_exhausted:
                log.error("All API keys exhausted — stopping processing early.")
                break
            log.warning(f"  Skipped (no card): {item['title'][:60]}")

    log.info(f"=== Filtered {filtered} off-topic, generated {generated} intelligence cards ===")
    return generated
