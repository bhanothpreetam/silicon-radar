#!/usr/bin/env python3

import json
import random
import tempfile
import unittest
from pathlib import Path

from learning_engine.case_validation import (
    CaseValidationError,
    _validate_experience_blueprint,
    validate_generated_case,
)
from learning_engine.generation import (
    _apply_truth_owned_renderings,
    _normalize_hint_ladders,
    _normalize_truth_references,
    render_case_prompt,
    split_case_for_delivery,
)
from learning_engine.executable_truth import pipeline_overlap_truth
from learning_engine.selection import (
    PersistentShuffleBag,
    eligible_frontier,
)


class FakeRepository:
    corpus_version = "test-v1"

    def __init__(self):
        self.concepts = [
            {"concept_id": "foundation"},
            {"concept_id": "advanced"},
            {"concept_id": "independent"},
        ]
        self._prerequisites = {
            "foundation": [],
            "advanced": ["foundation"],
            "independent": [],
        }

    def hard_prerequisites(self, concept_id):
        return self._prerequisites[concept_id]


def valid_case() -> dict:
    return {
        "case_id": "case-1",
        "case_revision": 1,
        "concept_id": "concept-1",
        "experience_type": "frontier",
        "corpus_version": "test-v1",
        "pre_reveal": {
            "mystery_title": "The register that changed without changing",
            "opening": {
                "scene": "Three instructions share two architectural names.",
                "observations": ["One read is delayed.", "A later write is ready."],
                "constraints": ["Program results must remain unchanged."],
                "central_question": "Which ordering is real and which is accidental?",
                "commitment_prompt": "State an ordering rule and falsify it.",
                "confidence_prompt": "How certain are you?",
            },
            "evidence_beats": [
                {
                    "beat_id": f"e{index}",
                    "evidence": f"Trace fragment {index}",
                    "question": f"What changes after fragment {index}?",
                    "hints": ["constraint", "prior mechanism", "measurement"],
                }
                for index in range(1, 4)
            ],
            "design_gate": {
                "prompt": "Construct storage that removes false ordering.",
                "required_elements": ["preserve values", "recover state"],
            },
        },
        "reveal": {
            "canonical_name": "Register renaming",
            "mechanism": [
                {"step": 1, "explanation": "Allocate storage."},
                {"step": 2, "explanation": "Update the mapping."},
            ],
            "formalization": {
                "definition": "Map architectural names to physical storage.",
                "equations": [],
                "worked_trace": {"setup": "A trace", "steps": [], "result": "Safe"},
            },
            "tradeoffs": [
                {"axis": "area", "gain": "parallelism", "cost": "storage"},
                {"axis": "power", "gain": "throughput", "cost": "lookup energy"},
            ],
            "boundary_cases": [{"condition": "No free storage"}],
            "common_misconceptions": [{"belief": "It removes true dependence"}],
        },
        "transfer_lab": [
            {
                "scenario": "Changed system",
                "task": "Diagnose it",
                "required_measurement": "Observe the mapping",
                "falsifying_observation": "A value changes",
                "solution": {"reasoning": "Trace mappings"},
            },
            {
                "scenario": "Another layer",
                "task": "Design it",
                "required_measurement": "Observe reuse",
                "falsifying_observation": "Names remain unique",
                "solution": {"reasoning": "Separate identities"},
            },
        ],
        "research_frontier": [
            {
                "question": f"Question {index}",
                "tension": "Scale versus energy",
                "why_existing_techniques_are_insufficient": "Lookup grows",
                "experiment": "Sweep the structure",
                "success_metric": "Energy-delay product",
                "hardest_confounder": "Workload dependence",
            }
            for index in range(1, 3)
        ],
        "retention": {
            "retrieval_trigger": "A false ordering appears",
            "one_sentence_compression": "Separate value flow from reused names.",
            "delayed_probe": {"success_criteria": ["identify false dependence"]},
        },
        "evaluation": {
            "reasoning_atoms": [
                {"atom_id": f"r{index}"} for index in range(1, 6)
            ],
            "rubric": [{"criterion": f"c{index}"} for index in range(1, 6)],
        },
        "claim_ledger": [
            {
                "claim_id": f"c{index}",
                "claim": "Grounded statement",
                "source_span_ids": [f"span-{index}"],
            }
            for index in range(1, 6)
        ],
    }


class SelectionTests(unittest.TestCase):
    def test_frontier_gate_requires_delayed_mastery(self):
        repository = FakeRepository()
        available = {"foundation", "advanced", "independent"}
        fresh = eligible_frontier(
            repository,
            {},
            available_case_concepts=available,
        )
        self.assertCountEqual(fresh, ["foundation", "independent"])

        learner = {
            "foundation": {
                "lifecycle_state": "delayed_retrieval_passed",
                "successful_delayed_retrievals": 1,
            }
        }
        unlocked = eligible_frontier(
            repository,
            learner,
            available_case_concepts=available,
        )
        self.assertIn("advanced", unlocked)
        self.assertNotIn("foundation", unlocked)

    def test_shuffle_bag_draws_without_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            bag = PersistentShuffleBag(
                Path(temporary) / "deck.json",
                corpus_version="test-v1",
                deck_name="frontier",
                randomizer=random.Random(7),
            )
            draws = [bag.draw(["a", "b", "c"]) for _ in range(3)]
            self.assertEqual(len(set(draws)), 3)
            self.assertIn(bag.draw(["a", "b", "c"]), {"a", "b", "c"})


class CaseContractTests(unittest.TestCase):
    def test_pipeline_blueprint_enforces_reveal_order_and_transfer_shape(self):
        truth = pipeline_overlap_truth()
        blueprint = truth["experience_blueprint"]
        beats = [
            {
                "beat_id": expected["beat_id"],
                "evidence": "Inputs only.",
                "question": "Calculate and justify.",
                "truth_fact_ids": expected["required_truth_fact_ids"],
            }
            for expected in blueprint["evidence_beats"]
        ]
        bundle = {
            "pre_reveal": {
                "opening": {"scene": "Five ordered transformations."},
                "evidence_beats": beats,
            },
            "reveal": {
                "system_connections": [
                    {"layer": "CPU"},
                    {"layer": "compiler"},
                ]
            },
            "transfer_lab": [
                {
                    "lab_id": "t1",
                    "truth_fact_ids": ["pipe-f6", "pipe-f7", "pipe-f8"],
                    "task": "Choose for a short burst and a long stream.",
                },
                {
                    "lab_id": "t2",
                    "truth_fact_ids": [],
                    "task": "Diagnose interacting stall sources.",
                },
            ],
            "research_frontier": [],
            "retention": {"delayed_probe": {"prompt": "Reconstruct the mechanism."}},
        }

        _validate_experience_blueprint(bundle, truth)
        bundle["pre_reveal"]["evidence_beats"][0]["evidence"] = (
            "The result is 7 cycles."
        )
        with self.assertRaisesRegex(CaseValidationError, "too early"):
            _validate_experience_blueprint(bundle, truth)

    def test_pipeline_blueprint_rejects_analogy_and_unowned_numbers(self):
        truth = pipeline_overlap_truth()
        blueprint = truth["experience_blueprint"]
        bundle = {
            "pre_reveal": {
                "opening": {"scene": "Five ordered transformations."},
                "evidence_beats": [
                    {
                        "beat_id": expected["beat_id"],
                        "evidence": "Inputs only.",
                        "question": "Calculate and justify.",
                        "truth_fact_ids": expected["required_truth_fact_ids"],
                    }
                    for expected in blueprint["evidence_beats"]
                ],
            },
            "reveal": {
                "system_connections": [{"layer": "CPU"}],
                "common_misconceptions": [],
            },
            "transfer_lab": [
                {
                    "lab_id": "t1",
                    "truth_fact_ids": ["pipe-f6", "pipe-f7", "pipe-f8"],
                    "task": "Choose for a short burst and a long stream.",
                },
                {
                    "lab_id": "t2",
                    "truth_fact_ids": [],
                    "task": "Diagnose interacting stall sources.",
                    "scenario": "The measured CPI is 2.5.",
                },
            ],
            "research_frontier": [],
            "retention": {"delayed_probe": {"prompt": "Reconstruct the mechanism."}},
        }

        with self.assertRaisesRegex(CaseValidationError, "qualitative"):
            _validate_experience_blueprint(bundle, truth)
        bundle["transfer_lab"][1]["scenario"] = "Two stall sources overlap."
        bundle["reveal"]["common_misconceptions"] = [
            {"replacement_model": "Use an assembly line."}
        ]
        with self.assertRaisesRegex(CaseValidationError, "forbidden"):
            _validate_experience_blueprint(bundle, truth)

    def test_truth_owned_worked_trace_replaces_model_timing_prose(self):
        truth = pipeline_overlap_truth()
        bundle = {
            "reveal": {
                "formalization": {
                    "worked_trace": {"result": "Contradictory model text."}
                }
            },
            "transfer_lab": [
                {
                    "lab_id": "t1",
                    "scenario": "Invented 1400 ps case.",
                    "truth_fact_ids": ["pipe-f6"],
                }
            ],
        }
        _apply_truth_owned_renderings(
            bundle,
            {"executable_truth": truth},
        )
        trace = bundle["reveal"]["formalization"]["worked_trace"]
        self.assertIn("I1 completes at the end", trace["steps"][4])
        self.assertNotIn("I1", trace["steps"][5].split(";")[0])
        self.assertIn("cycles 5, 6, and 7", trace["result"])
        lab = bundle["transfer_lab"][0]
        self.assertNotIn("1400", json.dumps(lab))
        self.assertEqual(
            lab["truth_fact_ids"],
            ["pipe-f6", "pipe-f7", "pipe-f8"],
        )
        self.assertIn("short", lab["task"])
        self.assertIn("long", lab["task"])

    def test_hint_normalization_completes_only_missing_scaffolding(self):
        bundle = {
            "pre_reveal": {
                "evidence_beats": [
                    {"hints": ["Keep this authored hint."]},
                    {"hints": ["One", "Two", "Three", "Four"]},
                ]
            }
        }

        _normalize_hint_ladders(bundle)

        first = bundle["pre_reveal"]["evidence_beats"][0]["hints"]
        second = bundle["pre_reveal"]["evidence_beats"][1]["hints"]
        self.assertEqual(first[0], "Keep this authored hint.")
        self.assertEqual(len(first), 3)
        self.assertEqual(second, ["One", "Two", "Three", "Four"])

    def test_truth_reference_normalization_keeps_unknown_ids_visible(self):
        bundle = {
            "pre_reveal": {
                "evidence_beats": [
                    {
                        "truth_fact_ids": [
                            "three_operation_schedule",
                            "hp7-entity-1",
                            "invented-fact",
                        ]
                    }
                ]
            },
            "transfer_lab": [],
        }
        source_pack = {
            "executable_truth": {
                "facts": [{"fact_id": "pipe-f9"}],
            },
            "content_entities": [{"entity_id": "hp7-entity-1"}],
        }

        _normalize_truth_references(bundle, source_pack)

        references = bundle["pre_reveal"]["evidence_beats"][0]["truth_fact_ids"]
        self.assertEqual(references, ["pipe-f9", "invented-fact"])
        notes = bundle["truth_reference_normalization"]["notes"]
        self.assertTrue(any("mapped three_operation_schedule" in note for note in notes))
        self.assertTrue(any("removed source entity" in note for note in notes))

    def test_pipeline_truth_kernel_computes_schedule_and_stage_balance(self):
        truth = pipeline_overlap_truth()
        facts = {fact["fact_id"]: fact for fact in truth["facts"]}
        self.assertIn("1,004 cycles", facts["pipe-f4"]["statement"])
        self.assertEqual(
            truth["stage_balance_transfer"]["original_clock_period_ps"],
            345,
        )
        self.assertEqual(
            truth["stage_balance_transfer"]["split_clock_period_ps"],
            275,
        )
        schedule = truth["three_operation_schedule"]
        self.assertEqual(len(schedule), 7)
        for cycle in schedule:
            occupants = [
                instruction
                for key, instruction in cycle.items()
                if key != "cycle"
            ]
            self.assertEqual(len(occupants), len(set(occupants)))

    def test_valid_case_passes_and_delivery_is_split(self):
        bundle = valid_case()
        report = validate_generated_case(
            bundle,
            concept={
                "canonical_name": "Register renaming",
                "aliases": ["physical register renaming"],
            },
            valid_span_ids={f"span-{index}" for index in range(1, 6)},
        )
        self.assertEqual(report["status"], "structurally_ready")
        pre, reveal, evaluator = split_case_for_delivery(bundle)
        self.assertNotIn("concept_id", pre)
        self.assertNotIn("reveal", pre)
        self.assertIn("concept_id", reveal)
        self.assertNotIn("evaluation", reveal)
        self.assertIn("evaluation", evaluator)

    def test_reader_payload_removes_private_claim_markers(self):
        bundle = valid_case()
        bundle["reveal"]["why_it_exists"] = (
            "Grounded statement [c1] and computed result [pipe-f2, pipe-f9]."
        )

        _, reveal, evaluator = split_case_for_delivery(bundle)

        self.assertEqual(
            reveal["reveal"]["why_it_exists"],
            "Grounded statement and computed result.",
        )
        self.assertEqual(evaluator["claim_ledger"], bundle["claim_ledger"])

    def test_hidden_name_leak_is_rejected(self):
        bundle = valid_case()
        bundle["pre_reveal"]["mystery_title"] = "Register renaming puzzle"
        with self.assertRaisesRegex(CaseValidationError, "leaks"):
            validate_generated_case(
                bundle,
                concept={
                    "canonical_name": "Register renaming",
                    "aliases": [],
                },
                valid_span_ids={f"span-{index}" for index in range(1, 6)},
            )

    def test_prompt_uses_source_pack_without_article_template(self):
        prompt = render_case_prompt(
            {
                "concept": {"canonical_name": "Some mechanism"},
                "source_spans": [{"span_id": "s1", "text": "Grounding"}],
            }
        )
        self.assertIn('"span_id": "s1"', prompt)
        self.assertNotIn("__SOURCE_PACK_JSON__", prompt)
        self.assertIn("It is NOT a structural template", prompt)


if __name__ == "__main__":
    unittest.main()
