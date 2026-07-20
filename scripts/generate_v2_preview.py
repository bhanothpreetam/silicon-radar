#!/usr/bin/env python3
"""Generate a quota-bounded v2 preview from real collected items.

This script intentionally performs no Supabase writes and sends no Telegram
messages. It reads candidate raw_items, generates only explicitly selected IDs,
and writes a static JSON fixture for a Vercel branch preview.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "miniapp" / "actual-preview-cards.json"
MAX_PREVIEW_CARDS = 3
MIN_SOURCE_CHARS = 2_000
SUMMARY_CHAR_LIMIT = 110


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT / ".env",
        help="Environment file containing Supabase and Gemini credentials",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true", help="List recent eligible items without Gemini calls")
    action.add_argument("--show", help="Show source metadata and excerpts for comma-separated raw_item IDs")
    action.add_argument("--ids", help="Comma-separated raw_item IDs to generate (maximum 3)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def configure(env_file: Path):
    if not env_file.exists():
        raise SystemExit(f"Environment file not found: {env_file}")
    load_dotenv(env_file)
    # This script never imports the production generator and never writes cards;
    # the variable documents the intended prompt contract for imported config.
    os.environ["INTELLIGENCE_PROMPT_VERSION"] = "v2"
    sys.path.insert(0, str(ROOT))


def fetch_candidates(limit=500):
    from db.models import get_client

    client = get_client()
    items = (
        client.table("raw_items")
        .select("id,title,url,raw_text,source_id,published_at,fetched_at")
        .order("fetched_at", desc=True)
        .limit(limit)
        .execute().data or []
    )
    source_ids = list({item["source_id"] for item in items if item.get("source_id")})
    sources = {}
    if source_ids:
        rows = (
            client.table("sources")
            .select("id,name,type,credibility,status")
            .in_("id", source_ids)
            .execute().data or []
        )
        sources = {row["id"]: row for row in rows}

    candidates = []
    for item in items:
        source = sources.get(item.get("source_id"), {})
        raw_text = item.get("raw_text") or ""
        if len(raw_text) < MIN_SOURCE_CHARS:
            continue
        if source.get("type") not in {"rss", "youtube", "arxiv"}:
            continue
        candidates.append({**item, "source": source, "source_chars": len(raw_text)})
    return candidates


def list_candidates(candidates):
    print("ID       chars  type      source                    title")
    print("-" * 108)
    for item in candidates[:30]:
        source = item["source"]
        print(
            f"{item['id']:<8} {item['source_chars']:<6} "
            f"{source.get('type', '?'):<9} {source.get('name', '?')[:24]:<25} "
            f"{(item.get('title') or '')[:58]}"
        )


def validate_card(card):
    required = [
        "one_line_summary", "what_happened", "why_technical", "why_strategic",
        "tech_layer", "importance_score", "notification_level", "deep_dive",
    ]
    missing = [key for key in required if not card.get(key)]
    if missing:
        raise ValueError(f"v2 response missing required fields: {', '.join(missing)}")
    if len(card["one_line_summary"]) > SUMMARY_CHAR_LIMIT:
        raise ValueError("one_line_summary exceeds the compact-card limit after normalization")
    deep = card["deep_dive"]
    for key in ("thesis", "sections", "prerequisites", "tradeoffs", "key_takeaways"):
        if not deep.get(key):
            raise ValueError(f"v2 deep_dive missing {key}")


def clamp_summary(text, limit=SUMMARY_CHAR_LIMIT):
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    shortened = text[: limit - 3].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return shortened + "..."


def generate_card(item, template, keys):
    from google import genai
    from google.genai import types
    from app.config import config

    prompt = template.format(
        raw_text=(item.get("raw_text") or "")[:40_000],
        url=item.get("url") or "",
        source_type=item["source"].get("type", "rss"),
    )

    last_error = None
    for key_index, key in enumerate(keys, 1):
        try:
            print(f"Generating raw_item {item['id']} with key {key_index}/{len(keys)}...")
            client = genai.Client(api_key=key)
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
            card["one_line_summary"] = clamp_summary(card.get("one_line_summary"))
            validate_card(card)

            credibility = item["source"].get("credibility", 5) or 5
            score = min(1.0, max(0.0, float(card.get("importance_score", 0.5)) + (credibility - 5) * 0.02))
            card["importance_score"] = score
            if score >= 0.90:
                level = "wake_up"
            elif score >= 0.75:
                level = "brief"
            elif score >= 0.65:
                level = "ping"
            else:
                level = "none"
            card["notify"] = level != "none"
            card["notification_level"] = level
            card.update({
                "id": 800_000 + int(item["id"]),
                "raw_item_id": item["id"],
                "prompt_version": "v2-preview",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "url": item.get("url") or "",
                "sourceName": item["source"].get("name") or "Unknown source",
                "sourceStatus": item["source"].get("status") or "trusted",
                "isLearning": False,
                "isDemo": True,
                "userReaction": None,
            })
            return card
        except Exception as exc:
            last_error = exc
            message = str(exc)
            if "RESOURCE_EXHAUSTED" in message and "PerDay" in message:
                print(f"Key {key_index} exhausted; trying the next configured key.")
                continue
            raise
    raise RuntimeError(f"All configured Gemini keys exhausted: {last_error}")


def main():
    args = parse_args()
    configure(args.env_file)
    candidates = fetch_candidates()

    if args.list:
        list_candidates(candidates)
        return

    if args.show:
        try:
            show_ids = [int(value.strip()) for value in args.show.split(",") if value.strip()]
        except ValueError as exc:
            raise SystemExit("--show must contain only integer raw_item IDs") from exc
        by_id = {item["id"]: item for item in candidates}
        for item_id in show_ids:
            item = by_id.get(item_id)
            if not item:
                print(f"{item_id}: not an eligible recent long-form item")
                continue
            print(f"\n{'=' * 88}\n{item_id} | {item['source'].get('name')} | {item.get('title')}\n{item.get('url')}\n")
            print((item.get("raw_text") or "")[:1_500])
        return

    try:
        selected_ids = [int(value.strip()) for value in args.ids.split(",") if value.strip()]
    except ValueError as exc:
        raise SystemExit("--ids must contain only integer raw_item IDs") from exc
    if not selected_ids or len(selected_ids) > MAX_PREVIEW_CARDS:
        raise SystemExit(f"Select between 1 and {MAX_PREVIEW_CARDS} raw_item IDs")
    if len(set(selected_ids)) != len(selected_ids):
        raise SystemExit("Duplicate raw_item IDs are not allowed")

    by_id = {item["id"]: item for item in candidates}
    missing = [item_id for item_id in selected_ids if item_id not in by_id]
    if missing:
        raise SystemExit(f"IDs are not eligible recent long-form items: {missing}")

    from app.config import config
    if not config.GEMINI_API_KEYS:
        raise SystemExit("No Gemini keys configured")
    template = (ROOT / "prompts" / "intelligence_card_v2.txt").read_text()
    cards = [generate_card(by_id[item_id], template, config.GEMINI_API_KEYS) for item_id in selected_ids]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cards, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(cards)} preview cards to {args.output}")
    print("No Supabase rows or Telegram messages were written.")


if __name__ == "__main__":
    main()
