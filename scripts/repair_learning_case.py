#!/usr/bin/env python3
"""Create one bounded case revision from an explicit human review brief."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id", help="Rejected or review-pending source case")
    parser.add_argument("review_file", type=Path)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "corpus" / "build" / "hp7-v0.1",
    )
    parser.add_argument(
        "--public-output",
        type=Path,
        default=ROOT / "learning_lab" / "cases",
    )
    parser.add_argument(
        "--private-output",
        type=Path,
        default=ROOT / "learning_lab" / "private",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT / ".env",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    draft_dir = args.private_output / args.case_id
    draft_path = draft_dir / "bundle.json"
    if not draft_path.exists():
        raise SystemExit(f"Private bundle does not exist: {draft_path}")
    if not args.review_file.exists():
        raise SystemExit(f"Human review file does not exist: {args.review_file}")

    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    human_review = json.loads(args.review_file.read_text(encoding="utf-8"))

    load_dotenv(args.env_file)
    from app.config import config
    from learning_engine.generation import repair_case, split_case_for_delivery
    from learning_engine.repository import CorpusRepository
    from learning_engine.source_pack import build_source_pack
    from scripts.prepare_learning_cases import (
        _next_case_revision,
        _update_public_index,
        _write_json,
    )

    repository = CorpusRepository(args.corpus)
    source_pack = build_source_pack(repository, draft["concept_id"])
    revision = _next_case_revision(args.private_output, draft["concept_id"])
    bundle, readiness, model_review = repair_case(
        source_pack,
        draft,
        human_review,
        api_keys=config.GEMINI_API_KEYS,
        model=config.GEMINI_MODEL,
        revision=revision,
    )

    pre_payload, reveal_payload, evaluator_payload = split_case_for_delivery(bundle)
    case_id = bundle["case_id"]
    private_case_dir = args.private_output / case_id
    _write_json(private_case_dir / "bundle.json", bundle)
    _write_json(private_case_dir / "evaluator.json", evaluator_payload)
    _write_json(private_case_dir / "human-repair-brief.json", human_review)
    _write_json(private_case_dir / "model-review.json", model_review)
    _write_json(private_case_dir / "readiness.json", readiness)
    _write_json(private_case_dir / "source-pack.json", source_pack)

    model_passed = bool(
        readiness.get("model_review", {}).get("passes_strict_threshold")
    )
    if model_passed:
        public_case_dir = args.public_output / case_id
        _write_json(public_case_dir / "pre.json", pre_payload)
        _write_json(public_case_dir / "reveal.json", reveal_payload)
        _update_public_index(args.public_output, pre_payload)

    print(
        json.dumps(
            {
                "status": "repaired",
                "source_case_id": args.case_id,
                "case_id": case_id,
                "readiness": readiness,
                "public_preview_written": model_passed,
                "writes": {
                    "supabase": False,
                    "telegram": False,
                    "production_miniapp": False,
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
