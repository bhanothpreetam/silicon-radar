"""
Silicon Radar — Citation-Graph Discovery Runner

  python scripts/run_citations.py             # full run
  python scripts/run_citations.py --no-mine   # skip article mining (rank+audition only)
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)

from intelligence.citation_graph import run_citation_discovery


def main():
    mine = "--no-mine" not in sys.argv
    result = run_citation_discovery(mine_articles=mine)

    print("\n" + "=" * 70)
    print("ENDORSEMENT CANDIDATES — ranked by trust-weighted citations")
    print("=" * 70)
    for c in result["ranked"][:25]:
        tag = "@" + c["target"] if c["target_type"] == "twitter" else c["target"]
        kinds = ", ".join(f"{k}×{n}" for k, n in c["kinds"].items())
        print(f"  {c['score']:<7} {tag:<35} ← {len(c['endorsers'])} endorsers ({kinds})")

    print("\n" + "=" * 70)
    print(f"VERIFIED TWITTER ACCOUNTS — {len(result['twitter_verified'])}")
    print("=" * 70)
    for a in result["twitter_verified"]:
        print(f"  {a['score']:<6} @{a['handle']} ({a['name']})")
        print(f"         {a['audition'].get('verdict', '')[:90]}")

    print("\n" + "=" * 70)
    print(f"CITED DOMAINS QUEUED FOR DEEP AUDITION — {len(result['domains_queued'])}")
    print("=" * 70)
    for d in result["domains_queued"]:
        feed = "📡" if d.get("feed_url") else "  "
        print(f"  {d['score']:<7} {feed} {d['target']} ← {', '.join(d['endorsers'][:4])}")


if __name__ == "__main__":
    main()
