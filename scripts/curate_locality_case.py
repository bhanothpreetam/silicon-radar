#!/usr/bin/env python3
"""Apply source-bounded expert corrections to the locality reader case."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-case",
        default="case-9d8959ce627f-r002",
    )
    parser.add_argument("--revision", type=int, default=3)
    parser.add_argument(
        "--private-output",
        type=Path,
        default=ROOT / "learning_lab" / "private",
    )
    parser.add_argument(
        "--public-output",
        type=Path,
        default=ROOT / "miniapp" / "learning" / "cases",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_dir = args.private_output / args.source_case
    bundle = copy.deepcopy(
        json.loads((source_dir / "bundle.json").read_text(encoding="utf-8"))
    )
    source_pack = json.loads(
        (source_dir / "source-pack.json").read_text(encoding="utf-8")
    )
    source_review = json.loads(
        (source_dir / "model-review.json").read_text(encoding="utf-8")
    )

    from learning_engine.case_validation import validate_generated_case
    from learning_engine.generation import split_case_for_delivery
    from scripts.prepare_learning_cases import _update_public_index, _write_json

    opaque_key = (
        f"{bundle['corpus_version']}:{bundle['concept_id']}:{args.revision}"
    )
    opaque = hashlib.sha256(opaque_key.encode("utf-8")).hexdigest()[:12]
    case_id = f"case-{opaque}-r{args.revision:03d}"
    bundle.update(
        {
            "case_id": case_id,
            "case_revision": args.revision,
            "compiler_version": "learning-case-v1+human-curation-locality-r1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "curation": {
                "source_case_id": args.source_case,
                "source_model_review_verdict": source_review.get("verdict"),
                "method": (
                    "Expert correction constrained to high-confidence source "
                    "spans and the worked access trace."
                ),
            },
        }
    )

    opening = bundle["pre_reveal"]["opening"]
    opening["constraints"] = [
        "This bounded exercise uses 8-byte cache blocks and 4-byte integers.",
        "Array a has dimensions [3][100]; array b has dimensions [101][100].",
        "Both arrays use row-major layout.",
        (
            "Count only the blocks touched by the shown references; assume those "
            "101 b blocks remain resident between the three passes."
        ),
        "Ignore conflict misses, matching the source exercise.",
    ]
    opening["central_question"] = (
        "What property of the reference sequence—not the array's declared "
        "size—explains why one trace misses 150 times and the other only 101?"
    )

    beat = bundle["pre_reveal"]["evidence_beats"][2]
    beat["title"] = "Two predictors, one cache"
    beat["evidence"] = (
        "For a, the first reference to each 8-byte block misses; the immediately "
        "following integer is already present. For b, references jump 400 bytes "
        "between rows during one pass, yet the next two passes over the same 101 "
        "elements hit. A mechanism that predicts only the next address explains "
        "the first trace but not the second. A mechanism that remembers only the "
        "last address explains the second but not the first."
    )
    beat["question"] = (
        "State the two independent predictions the cache is exploiting. Then "
        "construct one short reference sequence that satisfies the first "
        "prediction but defeats the second, and another that does the reverse."
    )
    beat["hints"] = [
        (
            "Write the byte-address deltas for four consecutive references in "
            "each trace; do not name a cache policy."
        ),
        (
            "Ask whether the useful word is one already referenced or one merely "
            "carried in by the same block."
        ),
        (
            "Your two counterexamples should change only recurrence in one case "
            "and adjacency in the other."
        ),
    ]

    bundle["pre_reveal"]["design_gate"] = {
        "prompt": (
            "Design the two predictions a memory hierarchy may safely gamble on. "
            "For each, identify what state or transfer granularity lets a cache "
            "exploit it, and give a falsifying access trace. Your design must "
            "explain both 150 and 101 misses without referring to total array size."
        ),
        "required_elements": [
            "A prediction about reuse of an already referenced word",
            "A separate prediction about untouched words carried in the same block",
            "The cache action that exploits each prediction",
            "One adversarial reference trace for each prediction",
        ],
        "confidence_prompt": "Confidence that both predictions are independent",
    }

    bundle["reveal"]["system_connections"] = [
        {
            "layer": "compiler",
            "connection": (
                "Loop interchange consumes more of each resident block before "
                "discarding it, while blocking keeps matrix tiles available long "
                "enough for repeated use [c11, c12]."
            ),
            "why_it_matters": (
                "The compiler changes the address sequence presented to identical "
                "hardware; it can expose locality but cannot enlarge the cache."
            ),
        },
        {
            "layer": "CPU",
            "connection": (
                "The supplied source grounds instruction-cache lookahead and "
                "prefetching in spatial locality and branch prediction [c14], and "
                "notes that critical-word-first benefits depend on the degree of "
                "spatial locality [c15]."
            ),
            "why_it_matters": (
                "A block transfer is valuable only when its other words arrive "
                "soon enough to be used; demand order and return order interact."
            ),
        },
    ]

    transfer = bundle["transfer_lab"][1]
    transfer["task"] = (
        "Decide whether the supplied information uniquely selects 16, 32, 64, "
        "or 128 bytes. If it does not, identify the smallest additional "
        "measurements needed, write the weighted objective, and predict which "
        "workload pushes the optimum in each direction."
    )
    transfer["required_measurement"] = (
        "For every candidate size and workload: access count, miss count, useful "
        "bytes per fetched block, miss latency, and execution weight. Compare "
        "weighted total stall cycles or weighted AMAT, not miss rate alone."
    )
    transfer["falsifying_observation"] = (
        "A claimed optimum is falsified by any measured candidate with lower "
        "weighted stall time after both transfer latency and pollution are included."
    )
    transfer["solution"] = {
        "reasoning": (
            "The prompt does not supply workload weights or per-size miss counts, "
            "so no unique block size follows. Larger blocks can amortize compulsory "
            "misses in the streaming trace [c9], but they increase transfer time and "
            "may reduce the number of resident blocks or introduce conflicts [c10]. "
            "Measure each candidate, compute the weighted objective, and choose its "
            "minimum. Streaming weight tends to move the optimum upward; random "
            "access weight tends to move it downward, but measurement—not a "
            "conventional 64-byte default—decides."
        ),
        "tempting_wrong_path": (
            "Naming 64 bytes because current processors commonly use it, or choosing "
            "the lowest miss rate without charging for unused transferred bytes."
        ),
        "answer_changes_if": (
            "A fixed external bus burst, adjacent-line prefetcher, coherence traffic, "
            "or page-boundary rule changes the per-size cost curve and must enter the "
            "same experiment."
        ),
    }

    valid_span_ids = {
        span["span_id"] for span in source_pack.get("source_spans") or []
    }
    readiness = validate_generated_case(
        bundle,
        concept=source_pack["concept"],
        valid_span_ids=valid_span_ids,
        executable_truth=source_pack.get("executable_truth"),
    )
    readiness["human_review"] = {
        "decision": "ready_for_reader",
        "reason": (
            "Source-bounded expert curation resolved critic errors, removed the "
            "leading reveal, and made the cache-line decision experimentally decidable."
        ),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }

    pre_payload, reveal_payload, evaluator_payload = split_case_for_delivery(bundle)
    private_case_dir = args.private_output / case_id
    public_case_dir = args.public_output / case_id
    _write_json(private_case_dir / "bundle.json", bundle)
    _write_json(private_case_dir / "evaluator.json", evaluator_payload)
    _write_json(private_case_dir / "readiness.json", readiness)
    _write_json(private_case_dir / "source-model-review.json", source_review)
    _write_json(private_case_dir / "source-pack.json", source_pack)
    _write_json(public_case_dir / "pre.json", pre_payload)
    _write_json(public_case_dir / "reveal.json", reveal_payload)
    _update_public_index(args.public_output, pre_payload)

    print(
        json.dumps(
            {
                "status": "curated",
                "source_case_id": args.source_case,
                "case_id": case_id,
                "readiness": readiness,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
