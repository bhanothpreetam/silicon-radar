#!/usr/bin/env python3
"""Apply expert, source-bounded curation to the rejected pipeline case."""

from __future__ import annotations

import argparse
import copy
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
        default="case-0ebc0ceab815-r005",
    )
    parser.add_argument("--revision", type=int, default=6)
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
    source_bundle = json.loads(
        (source_dir / "bundle.json").read_text(encoding="utf-8")
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

    bundle = copy.deepcopy(source_bundle)
    opaque_key = (
        f"{bundle['corpus_version']}:{bundle['concept_id']}:{args.revision}"
    )
    import hashlib

    opaque = hashlib.sha256(opaque_key.encode("utf-8")).hexdigest()[:12]
    case_id = f"case-{opaque}-r{args.revision:03d}"
    bundle.update(
        {
            "case_id": case_id,
            "case_revision": args.revision,
            "compiler_version": "learning-case-v1+human-curation-r1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "curation": {
                "source_case_id": args.source_case,
                "source_model_review_verdict": source_review.get("verdict"),
                "method": (
                    "Expert correction constrained to executable truth and "
                    "the supplied claim ledger."
                ),
            },
        }
    )

    reveal = bundle["reveal"]
    reveal["why_it_exists"] = (
        "The design problem is to increase the rate at which instructions "
        "complete without pretending that one instruction's ordered work has "
        "vanished. The source describes pipelining as overlapping instruction "
        "execution and calls the available overlap instruction-level parallelism "
        "[c1]. It also gives the accounting identity CPI = base CPI + stall "
        "contributions [c2]. Together they frame the architect's real task: "
        "create legal overlap, then explain every event that prevents the ideal "
        "completion rate."
    )
    reveal["tradeoffs"] = [
        {
            "axis": "Per-operation latency vs. completion rate",
            "gain": (
                "For the synthetic five-stage machine, a long independent stream "
                "approaches one completed operation per cycle."
            ),
            "cost": (
                "One operation still traverses five stages; overlap changes the "
                "completion rate, not the amount of ordered work it must visit."
            ),
            "decision_condition": (
                "Use completion rate for sustained streams and latency for an "
                "isolated or short invocation; do not substitute one metric for the other."
            ),
        },
        {
            "axis": "Stage balance vs. boundary cost",
            "gain": (
                "In the supplied partition, splitting the 310 ps stage lowers "
                "the clock period from 345 ps to 275 ps and raises ideal throughput."
            ),
            "cost": (
                "The split adds a stage boundary. Its area and energy cost are "
                "not present in the timing evidence and must be measured separately."
            ),
            "decision_condition": (
                "Split only after identifying the clock-setting stage, then "
                "evaluate timing and implementation cost as separate evidence."
            ),
        },
        {
            "axis": "Available independence vs. stalls",
            "gain": (
                "Independent instructions can occupy otherwise idle stages; a "
                "compiler can schedule such instructions between a producer and consumer [c6]."
            ),
            "cost": (
                "If the available independent work cannot cover the producer's "
                "latency, the dependent instruction cannot preserve the ideal initiation rate [c6]."
            ),
            "decision_condition": (
                "Judge the mechanism against dependence distance and functional-unit "
                "latency, not against pipeline depth alone."
            ),
        },
    ]
    reveal["boundary_cases"] = [
        {
            "condition": "A consumer reaches execution before its producer is ready",
            "consequence": (
                "Without enough independent work between them, the consumer must "
                "wait and the ideal overlap develops an empty slot [c6]."
            ),
            "diagnostic": (
                "Compare producer latency with the scheduled distance to its "
                "consumer, then inspect the occupancy trace where readiness first fails."
            ),
        },
        {
            "condition": "Several speculative branches remain unresolved",
            "consequence": (
                "High branch frequency, clustered branches, and long resolution "
                "delays can leave multiple speculative branches pending and make "
                "branch speculation important for avoiding stalls [c7]."
            ),
            "diagnostic": (
                "Measure branch frequency, clustering, resolution delay, and "
                "misprediction behavior rather than attributing every lost cycle "
                "to pipeline depth."
            ),
        },
        {
            "condition": "Two operations require a resource that cannot accept both",
            "consequence": (
                "The resource's initiation capability, rather than the nominal "
                "stage schedule, limits how frequently new work can begin."
            ),
            "diagnostic": (
                "Find the first cycle with competing requests. The source's ideal "
                "model avoids this boundary by assuming fully pipelined or replicated "
                "functional units [c6]."
            ),
        },
    ]
    reveal["system_connections"] = [
        {
            "layer": "CPU",
            "connection": (
                "A supplied superscalar example is four instructions wide and "
                "fifteen stages deep, so it may overlap sixty instructions, yet "
                "the text explicitly says it still requires high ILP [c4]. Dynamic "
                "scheduling dispatches work when operands and a suitable functional "
                "unit are ready [c5]."
            ),
            "why_it_matters": (
                "Width and depth create capacity for overlap; operand readiness, "
                "resource availability, and workload ILP decide whether that capacity is used."
            ),
        },
        {
            "layer": "compiler",
            "connection": (
                "Compiler scheduling searches for independent instructions and "
                "separates a dependent consumer from its producer by the producer's "
                "pipeline latency when enough ILP exists [c6]."
            ),
            "why_it_matters": (
                "The compiler changes the occupancy schedule seen by the hardware; "
                "it cannot manufacture independence absent from the program."
            ),
        },
    ]
    reveal["common_misconceptions"] = [
        {
            "belief": "Overlap makes one instruction complete in fewer stages.",
            "why_it_fails": (
                "The executable trace keeps five-cycle latency for every operation "
                "while adjacent completions become one cycle apart."
            ),
            "replacement_model": (
                "Track two quantities independently: traversal latency for one "
                "operation and initiation/completion interval for the stream."
            ),
        },
        {
            "belief": "If one extra boundary improved throughput, every additional boundary will.",
            "why_it_fails": (
                "The supplied split helps because 310 ps was the clock-setting "
                "delay. After the split, 240 ps becomes the maximum; subdividing "
                "a nonmaximum stage would not lower that maximum, while boundary "
                "overhead remains."
            ),
            "replacement_model": (
                "Recompute the maximum stage delay plus boundary overhead after "
                "each proposed partition. Stage count by itself predicts neither "
                "clock period nor useful throughput."
            ),
        },
    ]

    bundle["transfer_lab"][1] = {
        "lab_id": "t2",
        "title": "When a CPI Residual Pretends to Be a Cause",
        "scenario": (
            "A simulator estimates memory-generated stalls per instruction from "
            "cache miss rates and penalties, subtracts that estimate from measured "
            "CPI, and labels the residual pipeline stalls. The supplied CPI "
            "composition uses this procedure and notes that the residual "
            "contains all three hazard classes [c2, c3]."
        ),
        "task": (
            "Design a counterfactual experiment that tests whether the residual "
            "uniquely measures the causal cost of pipeline hazards rather than "
            "whatever the memory estimate did not explain."
        ),
        "constraints": [
            "Change one stall-producing mechanism at a time.",
            "Keep the instruction stream and measurement method fixed.",
            "Use no invented CPI values.",
        ],
        "required_measurement": (
            "Measure total CPI, the estimated memory contribution, and the residual "
            "under baseline, ideal-memory, and ideal-hazard interventions."
        ),
        "falsifying_observation": (
            "If changing only memory behavior also changes the residual hazard "
            "term, the original decomposition is not a unique causal attribution."
        ),
        "truth_fact_ids": [],
        "solution": {
            "reasoning": (
                "The subtraction is an accounting decomposition, not by itself a "
                "causal proof. Run the same trace with memory stalls removed, then "
                "with one hazard class removed, and finally with both removed. "
                "Compare each individual CPI reduction with the joint reduction. "
                "A nonzero interaction means one stall source was masking or "
                "exposing another, so a single residual cannot uniquely assign cost."
            ),
            "tempting_wrong_path": (
                "Treat the largest reported component as independently removable "
                "without testing whether another component changes with it."
            ),
            "answer_changes_if": (
                "A simulator that records mutually exclusive critical-path causes "
                "per cycle supplies stronger attribution, but its classification "
                "still needs counterfactual validation."
            ),
        },
    }

    bundle["research_frontier"] = [
        {
            "question": (
                "Where should a designer place stage boundaries when logic "
                "partitioning changes clock period and branch behavior penalizes lost speculation?"
            ),
            "tension": (
                "The executable example proves that one bottleneck split can lower "
                "clock period [pipe-f6, pipe-f7, pipe-f8]. The source separately "
                "describes deeply pipelined processors with large branch-misprediction "
                "penalties [c8]. Neither observation alone chooses a partition."
            ),
            "why_existing_techniques_are_insufficient": (
                "Static timing identifies the slowest stage but contains no workload "
                "control behavior. Predictor measurements expose control behavior "
                "but do not say how the logic should be repartitioned."
            ),
            "experiment": (
                "Enumerate legal partitions of the same logic, obtain a clock period "
                "for each, and replay identical control-flow traces through each "
                "design. Record total execution time and its CPI components, then "
                "test whether the selected partition remains best on held-out traces."
            ),
            "success_metric": (
                "A selection rule that predicts the lowest-execution-time legal "
                "partition on traces not used to construct the rule."
            ),
            "hardest_confounder": (
                "Retiming may change both physical stage delays and the cycle at "
                "which a branch resolves, so the two effects cannot be varied "
                "independently without a careful experimental model."
            ),
        },
        {
            "question": (
                "Can a CPI decomposition uniquely attribute lost overlap when "
                "pipeline hazards and memory stalls interact?"
            ),
            "tension": (
                "The source computes memory-generated stalls and assigns the CPI "
                "residual to pipeline stalls [c3], but a residual is not necessarily "
                "the counterfactual speedup from removing its labeled cause."
            ),
            "why_existing_techniques_are_insufficient": (
                "An additive report does not reveal whether one stalled mechanism "
                "masked work that would otherwise have stalled on another mechanism."
            ),
            "experiment": (
                "Use matched simulator runs that remove memory stalls, individual "
                "hazard classes, and combinations of both. Compare individual CPI "
                "reductions with joint reductions to measure interaction terms."
            ),
            "success_metric": (
                "An attribution method whose predicted CPI change matches the "
                "measured change under held-out interventions."
            ),
            "hardest_confounder": (
                "Removing one delay changes the schedule itself, which can expose "
                "new dependences or memory requests and thereby change the workload "
                "observed by downstream structures."
            ),
        },
    ]
    bundle["retention"]["delayed_probe"] = {
        "delay_days": 4,
        "changed_context": (
            "A compiler must schedule a producer, its consumer, and several "
            "independent operations for a machine whose functional-unit latencies "
            "are known."
        ),
        "prompt": (
            "Closed book: construct the scheduling rule that keeps the machine "
            "occupied without letting the consumer read an unavailable result. "
            "Then explain what symptom appears when the basic block contains too "
            "little independent work and name the first measurement you would inspect."
        ),
        "success_criteria": [
            "Separates producer-consumer readiness from nominal issue order.",
            "Uses independent work to cover producer latency when possible.",
            "Predicts an empty slot or stall when available ILP is insufficient.",
            "Inspects dependence distance, operand readiness, or stage occupancy.",
        ],
    }
    bundle["evaluation"]["reasoning_atoms"][4] = {
        "atom_id": "r5",
        "description": (
            "Explains why stage partitioning must consider the clock-setting "
            "delay and boundary overhead rather than stage count alone."
        ),
        "critical": True,
    }

    keep_claims = {"c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"}
    bundle["claim_ledger"] = [
        claim for claim in bundle["claim_ledger"] if claim["claim_id"] in keep_claims
    ]

    readiness = validate_generated_case(
        bundle,
        concept=source_pack["concept"],
        valid_span_ids={
            span["span_id"] for span in source_pack.get("source_spans") or []
        },
        executable_truth=source_pack.get("executable_truth"),
    )
    readiness["curation_review"] = {
        "status": "awaiting_final_human_smoke",
        "source_case_id": args.source_case,
        "addressed_model_review_issues": len(
            source_review.get("blocking_issues") or []
        ),
    }

    pre, reveal_payload, evaluator = split_case_for_delivery(bundle)
    private_dir = args.private_output / case_id
    public_dir = args.public_output / case_id
    _write_json(private_dir / "bundle.json", bundle)
    _write_json(private_dir / "evaluator.json", evaluator)
    _write_json(private_dir / "readiness.json", readiness)
    _write_json(private_dir / "source-model-review.json", source_review)
    _write_json(private_dir / "source-pack.json", source_pack)
    _write_json(public_dir / "pre.json", pre)
    _write_json(public_dir / "reveal.json", reveal_payload)
    _update_public_index(args.public_output, pre)

    print(
        json.dumps(
            {
                "status": "curated",
                "source_case_id": args.source_case,
                "case_id": case_id,
                "readiness": readiness,
                "public_preview_status": "awaiting_human_review",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
