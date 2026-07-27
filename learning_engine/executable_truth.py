"""Deterministic truth kernels for numerical and trace-based mysteries."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _pipeline_table(
    instruction_count: int,
    stages: list[str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    total_cycles = instruction_count + len(stages) - 1
    for cycle in range(1, total_cycles + 1):
        occupancy: dict[str, str] = {}
        for instruction_index in range(1, instruction_count + 1):
            stage_index = cycle - instruction_index
            if 0 <= stage_index < len(stages):
                occupancy[stages[stage_index]] = f"I{instruction_index}"
        rows.append({"cycle": str(cycle), **occupancy})
    return rows


def pipeline_overlap_truth() -> dict[str, Any]:
    stages = ["S1", "S2", "S3", "S4", "S5"]
    three_operation_schedule = _pipeline_table(3, stages)
    long_stream_instructions = 1000
    long_stream_cycles = long_stream_instructions + len(stages) - 1
    delays_ps = [240, 170, 310, 180]
    latch_overhead_ps = 35
    original_period_ps = max(delays_ps) + latch_overhead_ps
    original_latency_ps = len(delays_ps) * original_period_ps
    split_delays_ps = [240, 170, 155, 155, 180]
    split_period_ps = max(split_delays_ps) + latch_overhead_ps
    split_latency_ps = len(split_delays_ps) * split_period_ps

    facts = [
        {
            "fact_id": "pipe-f1",
            "statement": (
                "One operation must visit five ordered stages S1-S5; each "
                "stage occupies a distinct resource for exactly one cycle."
            ),
            "derivation": "Definition of the synthetic machine.",
        },
        {
            "fact_id": "pipe-f2",
            "statement": (
                "One isolated operation has a latency of 5 cycles from entry "
                "into S1 through completion of S5."
            ),
            "derivation": "5 stages × 1 cycle/stage = 5 cycles.",
        },
        {
            "fact_id": "pipe-f3",
            "statement": (
                "If 1,000 independent operations run without overlap, they "
                "require 5,000 cycles."
            ),
            "derivation": "1,000 operations × 5 cycles/operation = 5,000 cycles.",
        },
        {
            "fact_id": "pipe-f4",
            "statement": (
                "If independent operations enter S1 one per cycle and no "
                "resource handles two operations in the same cycle, 1,000 "
                "operations complete in 1,004 cycles."
            ),
            "derivation": "N + depth - 1 = 1,000 + 5 - 1 = 1,004 cycles.",
        },
        {
            "fact_id": "pipe-f5",
            "statement": (
                "The finite-stream CPI is 1.004, while steady-state CPI tends "
                "to 1 as the stream length grows; the latency remains 5 cycles."
            ),
            "derivation": "1,004 / 1,000 = 1.004; limit of (N+4)/N is 1.",
        },
        {
            "fact_id": "pipe-f6",
            "statement": (
                "For four combinational stages with delays 240, 170, 310, and "
                "180 ps plus 35 ps of latch overhead, the clock period is "
                "345 ps and four-stage latency is 1,380 ps."
            ),
            "derivation": (
                "period = max(240,170,310,180)+35 = 345 ps; "
                "latency = 4×345 = 1,380 ps."
            ),
        },
        {
            "fact_id": "pipe-f7",
            "statement": (
                "Splitting the 310 ps stage into two 155 ps stages changes the "
                "clock period to 275 ps and five-stage latency to 1,375 ps."
            ),
            "derivation": (
                "period = max(240,170,155,155,180)+35 = 275 ps; "
                "latency = 5×275 = 1,375 ps."
            ),
        },
        {
            "fact_id": "pipe-f8",
            "statement": (
                "The stage split raises ideal steady-state throughput from "
                "about 2.90 to 3.64 billion operations/s, assuming the stream "
                "has no hazards and every stage can accept new work each cycle."
            ),
            "derivation": "10^12/345 ≈ 2.90G/s; 10^12/275 ≈ 3.64G/s.",
        },
        {
            "fact_id": "pipe-f9",
            "statement": (
                "Three independent operations traversing five stages one "
                "stage per cycle complete in 7 cycles; after filling, adjacent "
                "operations complete one cycle apart."
            ),
            "derivation": "N + depth - 1 = 3 + 5 - 1 = 7 cycles.",
        },
    ]
    value = {
        "kernel_id": "pipeline-overlap-v1",
        "concept_id": "hp7-pipeline-overlap",
        "purpose": (
            "All numerical pre-reveal evidence and quantitative transfer work "
            "for this concept must come from these facts."
        ),
        "authoring_constraints": [
            "Do not invent a named processor, cache, branch predictor, or load latency.",
            "The pre-reveal mystery must stay on latency versus throughput and stage overlap.",
            "Hazards may appear after reveal as boundaries, not as a competing mystery.",
            "Do not say finite-stream CPI is exactly 1.0; distinguish 1.004 from its limit.",
            "Every quantitative evidence beat and transfer lab must cite truth_fact_ids.",
            "The only legal truth fact IDs are pipe-f1 through pipe-f9.",
            "Do not use factories, assembly lines, roads, pipes, or other physical analogies.",
            "Do not state the 7-cycle or 1,004-cycle result in the opening.",
        ],
        "forbidden_learner_terms": [
            "assembly line",
            "factory",
            "highway",
            "water pipe",
            "WAR",
            "WAW",
        ],
        "experience_blueprint": {
            "purpose": (
                "This is a mandatory reveal-order contract, not optional inspiration. "
                "The learner must calculate before the prose supplies each result."
            ),
            "opening": {
                "learner_sees": [
                    "Five ordered transformations S1-S5.",
                    "Each transformation uses its own resource for one cycle.",
                    "One isolated operation therefore has five-cycle latency.",
                    "Three independent operations are waiting.",
                ],
                "learner_must_commit_to": (
                    "A minimum-cycle schedule for the three operations and the "
                    "resource invariant that makes the schedule legal."
                ),
                "forbidden_results": ["7 cycles", "1,004 cycles", "1004 cycles"],
            },
            "evidence_beats": [
                {
                    "beat_id": "e1",
                    "intellectual_move": (
                        "Complete a partial occupancy table. The evidence may show "
                        "only cycles 1-3 of three_operation_schedule; it must not "
                        "state the final completion cycle."
                    ),
                    "required_truth_fact_ids": ["pipe-f1", "pipe-f2", "pipe-f9"],
                    "question_requirement": (
                        "Ask for cycles 4 onward, the last completion cycle, and "
                        "one explicit same-resource conflict check."
                    ),
                    "forbidden_in_evidence_and_question": ["7 cycles"],
                },
                {
                    "beat_id": "e2",
                    "intellectual_move": (
                        "Now reveal that the legal schedule completes in 7 cycles. "
                        "Make the learner reconcile this with five-cycle latency "
                        "without saying that one operation became faster."
                    ),
                    "required_truth_fact_ids": ["pipe-f2", "pipe-f9"],
                    "question_requirement": (
                        "Force a latency-versus-completion-rate distinction and "
                        "ask which earlier hypothesis the trace falsifies."
                    ),
                },
                {
                    "beat_id": "e3",
                    "intellectual_move": (
                        "Give the 5,000-cycle non-overlap baseline and the rule that "
                        "one independent operation may enter S1 per cycle. Ask the "
                        "learner to derive T(N), calculate T(1000), finite CPI, and "
                        "the large-N limit before any prose supplies those results."
                    ),
                    "required_truth_fact_ids": [
                        "pipe-f3",
                        "pipe-f4",
                        "pipe-f5",
                    ],
                    "question_requirement": (
                        "Require a formula, the 1,004-cycle result, CPI 1.004, and "
                        "the limiting CPI; do not turn it into definition recall."
                    ),
                    "forbidden_in_evidence_and_question": [
                        "1,004",
                        "1004",
                        "1.004",
                    ],
                },
                {
                    "beat_id": "e4",
                    "intellectual_move": (
                        "Present the four combinational delays and 35 ps latch "
                        "overhead. Ask the learner to identify the clock-setting "
                        "stage, then predict the consequence of splitting 310 ps "
                        "into two 155 ps stages."
                    ),
                    "required_truth_fact_ids": [
                        "pipe-f6",
                        "pipe-f7",
                        "pipe-f8",
                    ],
                    "question_requirement": (
                        "Require both configurations' period, latency, throughput, "
                        "and the reason throughput changes."
                    ),
                    "forbidden_in_evidence_and_question": [
                        "345 ps",
                        "275 ps",
                        "1,380 ps",
                        "1380 ps",
                        "1,375 ps",
                        "1375 ps",
                        "2.90",
                        "3.64",
                    ],
                },
            ],
            "design_gate": {
                "learner_must_construct": [
                    "Distinct stages hold different operations concurrently.",
                    "A stage accepts new work when that stage, not the whole operation, is free.",
                    "The design improves completion rate rather than shortening one operation.",
                    "The slowest stage and boundary overhead constrain the clock.",
                ],
                "must_predict_boundary": (
                    "Ask what kind of dependence or resource conflict would insert "
                    "an empty slot and break ideal completion rate."
                ),
            },
            "post_reveal": {
                "allowed_system_connections": ["CPU", "compiler"],
                "forbidden_claims": [
                    "An OS saves or restores in-flight instructions on a context switch.",
                    "Every modern CPU has a particular unnamed or invented pipeline depth.",
                ],
                "transfer_labs": [
                    {
                        "lab_id": "t1",
                        "form": (
                            "quantitative stage-partition decision review: reuse "
                            "the computed configurations, but ask the learner to "
                            "choose for a latency-sensitive short burst versus a "
                            "throughput-oriented long stream; do not repeat e4"
                        ),
                        "required_truth_fact_ids": ["pipe-f6", "pipe-f7", "pipe-f8"],
                        "required_task_terms": [
                            "short",
                            "long",
                            "choose",
                        ],
                        "forbidden_task_terms": [
                            "calculate the clock period",
                            "calculate the total latency",
                            "calculate the ideal",
                        ],
                        "allowed_numeric_tokens": [
                            "1",
                            "2.90",
                            "3.64",
                            "4",
                            "5",
                            "10",
                            "12",
                            "35",
                            "155",
                            "170",
                            "180",
                            "240",
                            "275",
                            "310",
                            "345",
                            "1375",
                            "1380",
                        ],
                    },
                    {
                        "lab_id": "t2",
                        "form": (
                            "qualitative CPI-attribution diagnosis grounded in "
                            "hp7-ch03-p003-span-008 and hp7-ch03-p087-span-004"
                        ),
                        "required_truth_fact_ids": [],
                        "forbid_numeric_scenario": True,
                    },
                ],
                "research_frontier_anchors": [
                    {
                        "question_core": (
                            "How should stage depth be chosen when shorter logic "
                            "stages improve clock period but deeper speculation "
                            "raises branch-misprediction cost?"
                        ),
                        "grounding": [
                            "pipe-f6",
                            "pipe-f7",
                            "pipe-f8",
                            "hp7-ch03-p033-span-004",
                            "hp7-ch03-p064-span-004",
                        ],
                    },
                    {
                        "question_core": (
                            "Can a CPI decomposition uniquely attribute lost overlap "
                            "when pipeline hazards and memory stalls interact?"
                        ),
                        "grounding": [
                            "hp7-ch03-p003-span-008",
                            "hp7-ch03-p087-span-004",
                        ],
                    },
                ],
                "forbid_numeric_research_proposals": True,
                "forbid_numeric_delayed_probe": True,
            },
        },
        "facts": facts,
        "three_operation_schedule": three_operation_schedule,
        "canonical_renderings": {
            "worked_trace": {
                "setup": (
                    "Three independent operations I1-I3 traverse five ordered "
                    "stages S1-S5, one stage per cycle."
                ),
                "steps": [
                    (
                        f"Cycle {row['cycle']}: "
                        + ", ".join(
                            f"{stage}={row[stage]}"
                            for stage in stages
                            if stage in row
                        )
                        + (
                            f"; {row['S5']} completes at the end of the cycle."
                            if "S5" in row
                            else "."
                        )
                    )
                    for row in three_operation_schedule
                ],
                "result": (
                    "I1, I2, and I3 complete at the ends of cycles 5, 6, and "
                    "7 respectively; all three therefore complete in 7 cycles."
                ),
                "architectural_meaning": (
                    "Each operation still has five-cycle latency, while the "
                    "filled machine completes adjacent operations one cycle apart."
                ),
            },
            "transfer_lab_overrides": {
                "t1": {
                    "title": "The Design That Appears to Dominate",
                    "scenario": (
                        "Two stage partitions have already been validated. The "
                        "original four-stage design has a 345 ps clock period and "
                        "1,380 ps single-operation latency. Splitting its 310 ps "
                        "stage produces a five-stage design with a 275 ps clock "
                        "period and 1,375 ps single-operation latency. Their ideal "
                        "steady-state throughputs are about 2.90 and 3.64 billion "
                        "operations per second respectively."
                    ),
                    "task": (
                        "Choose between the original and split designs first for "
                        "a latency-sensitive short invocation and then for a "
                        "throughput-oriented long stream. Does the supplied "
                        "performance evidence give either workload a reason to "
                        "choose the original design? Identify the additional "
                        "measurement needed before claiming that the split design "
                        "is globally better."
                    ),
                    "constraints": [
                        "Do not recompute the periods, latencies, or throughputs.",
                        "Separate conclusions supported by timing from conclusions about implementation cost.",
                    ],
                    "required_measurement": (
                        "Measure a non-timing implementation cost such as energy "
                        "per operation or added sequential-state area for both designs."
                    ),
                    "falsifying_observation": (
                        "A measured implementation cost large enough to outweigh "
                        "the split design's timing benefit would falsify the claim "
                        "that it is globally better."
                    ),
                    "truth_fact_ids": ["pipe-f6", "pipe-f7", "pipe-f8"],
                    "solution": {
                        "reasoning": (
                            "On the supplied timing evidence, the split design "
                            "wins both comparisons: 1,375 ps is slightly below "
                            "1,380 ps for one operation, and 3.64 billion operations "
                            "per second exceeds 2.90 for a long stream. Therefore "
                            "the original design has no timing-based advantage in "
                            "this specific comparison. That does not establish "
                            "global dominance: the extra stage boundary adds "
                            "sequential state and clocked work whose area and energy "
                            "were not measured."
                        ),
                        "tempting_wrong_path": (
                            "Assume that adding a stage must increase latency, or "
                            "declare the split design universally superior from "
                            "timing measurements alone."
                        ),
                        "answer_changes_if": (
                            "The decision can change when a measured implementation "
                            "cost, rather than an invented timing value, dominates "
                            "the design objective."
                        ),
                    },
                }
            },
        },
        "stage_balance_transfer": {
            "original_stage_delays_ps": delays_ps,
            "split_stage_delays_ps": split_delays_ps,
            "latch_overhead_ps": latch_overhead_ps,
            "original_clock_period_ps": original_period_ps,
            "original_latency_ps": original_latency_ps,
            "split_clock_period_ps": split_period_ps,
            "split_latency_ps": split_latency_ps,
        },
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    value["truth_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return value


def truth_for_concept(concept_id: str) -> dict[str, Any] | None:
    if concept_id == "hp7-pipeline-overlap":
        return pipeline_overlap_truth()
    return None
