#!/usr/bin/env python3
"""Build Radar's private learning corpus without unpacking the source ZIP."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_engine.corpus import CorpusBuildError, build_corpus  # noqa: E402


DEFAULT_SEED = ROOT / "learning_engine" / "seeds" / "hp7_ch2_ch3_concepts.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize a private textbook extraction ZIP into stable, "
            "reviewable learning-engine artifacts."
        )
    )
    parser.add_argument("archive", type=Path, help="Path to the extraction ZIP")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "corpus" / "build" / "hp7-v0.1",
        help="Private derived output directory",
    )
    parser.add_argument(
        "--corpus-version",
        default="hp7-ch2-ch3-v0.1",
        help="Immutable logical version for this corpus release",
    )
    parser.add_argument(
        "--knowledge-seed",
        type=Path,
        default=DEFAULT_SEED,
        help="Reviewable seed concepts and proposed graph edges",
    )
    parser.add_argument(
        "--no-knowledge-seed",
        action="store_true",
        help="Build source artifacts without concept candidates",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed = None if args.no_knowledge_seed else args.knowledge_seed
    try:
        manifest = build_corpus(
            args.archive,
            args.output,
            corpus_version=args.corpus_version,
            knowledge_seed_path=seed,
        )
    except (CorpusBuildError, OSError) as error:
        print(f"Corpus build failed: {error}", file=sys.stderr)
        return 1

    summary = {
        "status": "built",
        "output": str(args.output.resolve()),
        "corpus_version": manifest["corpus_version"],
        "source_archive_sha256": manifest["source"]["archive_sha256"],
        "counts": manifest["counts"],
        "warnings": len(manifest["warnings"]),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
