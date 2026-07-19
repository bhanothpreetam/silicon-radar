"""
Silicon Radar — Source Discovery Runner

  python scripts/run_discovery.py            # full loop, persist to DB
  python scripts/run_discovery.py --dry-run  # full loop, print only
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from intelligence.source_discovery import run_discovery


def main():
    persist = "--dry-run" not in sys.argv
    result = run_discovery(persist=persist)

    taste = result["taste"]
    queries = result["queries"]
    ranked = result["candidates"]

    print("\n" + "=" * 70)
    print("TASTE VECTOR — top topics")
    print("=" * 70)
    for topic, weight in list(taste["topics"].items())[:12]:
        bar = "█" * int(weight * 30)
        print(f"  {topic:<28} {weight:.3f} {bar}")

    print("\n" + "=" * 70)
    print("PERSONA")
    print("=" * 70)
    print(f"  {queries.get('persona', '(none)')}")

    print("\n" + "=" * 70)
    print("SEARCH QUERIES")
    print("=" * 70)
    for q in queries.get("core", []):
        print(f"  [core]     {q}")
    for q in queries.get("frontier", []):
        print(f"  [frontier] {q}")
    print(f"\n  Frontier rationale: {queries.get('frontier_rationale', '')}")

    print("\n" + "=" * 70)
    print(f"AUDITIONED CANDIDATES — {len(ranked)} total, ranked")
    print("=" * 70)
    for c in ranked[:20]:
        score = c.get("audition_score")
        feed = "📡" if c.get("feed_url") else "  "
        verdict = (c.get("audition") or {}).get("verdict", "")
        print(f"  {score if score is not None else '?':<6} {feed} {c['domain']}")
        print(f"         {verdict[:100]}")

    if not persist:
        print("\n(dry run — nothing saved)")


if __name__ == "__main__":
    main()
