#!/usr/bin/env python3
"""Record a human accept/reject decision for a generated Learning Lab case."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id")
    parser.add_argument(
        "decision",
        choices=("ready_for_reader", "rejected"),
    )
    parser.add_argument("--reason", required=True)
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
    return parser.parse_args()


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    index_path = args.public_output / "index.json"
    if not index_path.exists():
        raise SystemExit(f"Public case index does not exist: {index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    record = next(
        (
            case
            for case in index.get("cases") or []
            if case["case_id"] == args.case_id
        ),
        None,
    )
    if not record:
        raise SystemExit(f"Case is not in the public index: {args.case_id}")

    record["preview_status"] = args.decision
    record["human_review"] = {
        "decision": args.decision,
        "reason": args.reason,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    if args.decision == "rejected":
        index["cases"] = [
            case
            for case in index.get("cases") or []
            if case["case_id"] != args.case_id
        ]
    write_json(index_path, index)

    readiness_path = args.private_output / args.case_id / "readiness.json"
    if readiness_path.exists():
        readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
        readiness["human_review"] = record["human_review"]
        write_json(readiness_path, readiness)

    print(
        json.dumps(
            {
                "case_id": args.case_id,
                "decision": args.decision,
                "reason": args.reason,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
