#!/usr/bin/env python3
"""Prepare grounded mystery cases without touching Supabase or the Mini App."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
        "--deck-state",
        type=Path,
        default=ROOT / "learning_lab" / "state" / "authoring-deck.json",
    )
    parser.add_argument(
        "--learner-state",
        type=Path,
        help="Optional learner-state JSON; absent means a fresh learner",
    )
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument(
        "--concept",
        help="Developer override for one concept; ordinary selection is random",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Deterministic test seed; omit for system randomness",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Select concepts and write source packs without Gemini calls",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT / ".env",
    )
    return parser.parse_args()


def _load_learner_states(path: Path | None) -> dict:
    if not path:
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value.get("concepts") or {}


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _update_public_index(output: Path, pre_payload: dict) -> None:
    index_path = output / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = {"schema_version": "1.0.0", "cases": []}
    case_id = pre_payload["case_id"]
    record = {
        "case_id": case_id,
        "case_revision": pre_payload["case_revision"],
        "experience_type": pre_payload["experience_type"],
        "pre_url": f"cases/{case_id}/pre.json",
        "reveal_url": f"cases/{case_id}/reveal.json",
        "preview_status": "awaiting_human_review",
    }
    index["cases"] = [
        existing
        for existing in index.get("cases") or []
        if existing["case_id"] != case_id
    ]
    index["cases"].append(record)
    _write_json(index_path, index)


def _next_case_revision(private_output: Path, concept_id: str) -> int:
    revisions = []
    for bundle_path in private_output.glob("case-*/bundle.json"):
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if bundle.get("concept_id") == concept_id:
            revisions.append(int(bundle.get("case_revision") or 0))
    return max(revisions, default=0) + 1


def main() -> int:
    args = parse_args()
    if args.count < 1 or args.count > 5:
        raise SystemExit("--count must be between 1 and 5")
    if args.concept and args.count != 1:
        raise SystemExit("--concept can prepare only one case at a time")

    load_dotenv(args.env_file)
    from app.config import config
    from learning_engine.generation import generate_case, split_case_for_delivery
    from learning_engine.repository import CorpusRepository
    from learning_engine.selection import (
        PersistentShuffleBag,
        eligible_authoring_candidates,
        eligible_frontier,
    )
    from learning_engine.source_pack import build_source_pack

    repository = CorpusRepository(args.corpus)
    learner_states = _load_learner_states(args.learner_state)
    authorable = eligible_authoring_candidates(repository)
    eligible = eligible_frontier(
        repository,
        learner_states,
        available_case_concepts=authorable,
    )
    if args.concept:
        if args.concept not in repository.concept_by_id:
            raise SystemExit(f"Unknown concept: {args.concept}")
        selected = [args.concept]
    else:
        randomizer = random.Random(args.seed) if args.seed is not None else None
        bag = PersistentShuffleBag(
            args.deck_state,
            corpus_version=repository.corpus_version,
            deck_name="frontier_authoring",
            randomizer=randomizer,
        )
        selected = []
        for _ in range(min(args.count, len(eligible))):
            concept_id = bag.draw(
                concept for concept in eligible if concept not in selected
            )
            if concept_id:
                selected.append(concept_id)
    if not selected:
        raise SystemExit(
            "No prerequisite-eligible concepts have source packs. "
            "Inspect the learner state and graph."
        )

    results = []
    for concept_id in selected:
        source_pack = build_source_pack(repository, concept_id)
        private_case_dir = args.private_output / concept_id
        _write_json(private_case_dir / "source-pack.json", source_pack)

        if args.dry_run:
            results.append(
                {
                    "concept_id": concept_id,
                    "mode": "source_pack_only",
                    "source_spans": len(source_pack["source_spans"]),
                    "source_chars": source_pack["assembly"]["source_chars"],
                }
            )
            continue

        bundle, readiness, model_review = generate_case(
            source_pack,
            api_keys=config.GEMINI_API_KEYS,
            model=config.GEMINI_MODEL,
            revision=_next_case_revision(args.private_output, concept_id),
        )
        pre_payload, reveal_payload, evaluator_payload = split_case_for_delivery(
            bundle
        )
        case_id = bundle["case_id"]
        private_case_dir = args.private_output / case_id
        public_case_dir = args.public_output / case_id
        _write_json(private_case_dir / "bundle.json", bundle)
        _write_json(private_case_dir / "evaluator.json", evaluator_payload)
        _write_json(private_case_dir / "model-review.json", model_review)
        _write_json(private_case_dir / "readiness.json", readiness)
        _write_json(private_case_dir / "source-pack.json", source_pack)
        model_review_passed = bool(
            readiness.get("model_review", {}).get("passes_strict_threshold")
        )
        if model_review_passed:
            _write_json(public_case_dir / "pre.json", pre_payload)
            _write_json(public_case_dir / "reveal.json", reveal_payload)
            _update_public_index(args.public_output, pre_payload)
        results.append(
            {
                "case_id": case_id,
                "mode": "generated_preview",
                "readiness": readiness,
                "public_preview_written": model_review_passed,
            }
        )

    print(
        json.dumps(
            {
                "status": "prepared",
                "corpus_version": repository.corpus_version,
                "eligible_frontier_count": len(eligible),
                "results": results,
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
