"""Structural, grounding, and name-leakage gates for generated cases."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from learning_engine.contracts import ContractError, validate_case_bundle


class CaseValidationError(ValueError):
    """Raised when a generated case is unsafe or below the readiness floor."""


def _require_text(value: Any, path: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CaseValidationError(f"{path} must not be empty")
    return text


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _visible_numeric_tokens(value: Any) -> set[str]:
    text = json.dumps(value, ensure_ascii=False)
    text = re.sub(r"\[[^\]]+\]", "", text)
    tokens = re.findall(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?", text)
    return {token.replace(",", "") for token in tokens}


def _validate_experience_blueprint(
    bundle: Mapping[str, Any],
    executable_truth: Mapping[str, Any],
) -> None:
    blueprint = executable_truth.get("experience_blueprint") or {}
    if not blueprint:
        return

    learner_payload = {
        "pre_reveal": bundle.get("pre_reveal"),
        "reveal": bundle.get("reveal"),
        "transfer_lab": bundle.get("transfer_lab"),
        "research_frontier": bundle.get("research_frontier"),
        "retention": bundle.get("retention"),
    }
    learner_text = json.dumps(learner_payload, ensure_ascii=False).lower()
    for term in executable_truth.get("forbidden_learner_terms") or []:
        pattern = rf"(?<![a-z0-9]){re.escape(str(term).lower())}(?![a-z0-9])"
        if re.search(pattern, learner_text):
            raise CaseValidationError(
                f"learner payload uses forbidden analogy or adjacent term: {term}"
            )

    opening_text = json.dumps(
        (bundle["pre_reveal"].get("opening") or {}),
        ensure_ascii=False,
    ).lower()
    for forbidden in (blueprint.get("opening") or {}).get("forbidden_results") or []:
        if str(forbidden).lower() in opening_text:
            raise CaseValidationError(
                f"opening reveals blueprint-reserved result: {forbidden}"
            )

    actual_beats = bundle["pre_reveal"].get("evidence_beats") or []
    expected_beats = blueprint.get("evidence_beats") or []
    actual_ids = [str(beat.get("beat_id") or "") for beat in actual_beats]
    expected_ids = [str(beat.get("beat_id") or "") for beat in expected_beats]
    if actual_ids != expected_ids:
        raise CaseValidationError(
            "evidence beat order must match executable experience blueprint: "
            f"{expected_ids}"
        )

    for actual, expected in zip(actual_beats, expected_beats):
        expected_truth = set(expected.get("required_truth_fact_ids") or [])
        actual_truth = set(actual.get("truth_fact_ids") or [])
        if actual_truth != expected_truth:
            raise CaseValidationError(
                f"{actual.get('beat_id')} must cite exactly blueprint facts "
                f"{sorted(expected_truth)}"
            )
        learner_visible = (
            f"{actual.get('evidence') or ''} {actual.get('question') or ''}".lower()
        )
        for forbidden in expected.get("forbidden_in_evidence_and_question") or []:
            if str(forbidden).lower() in learner_visible:
                raise CaseValidationError(
                    f"{actual.get('beat_id')} reveals reserved result too early: "
                    f"{forbidden}"
                )

    post_reveal = blueprint.get("post_reveal") or {}
    allowed_layers = {
        str(layer).lower()
        for layer in post_reveal.get("allowed_system_connections") or []
    }
    for connection in bundle["reveal"].get("system_connections") or []:
        layer = str(connection.get("layer") or "").lower()
        if layer not in allowed_layers:
            raise CaseValidationError(
                f"system connection layer {layer!r} is outside the blueprint"
            )

    expected_labs = post_reveal.get("transfer_labs") or []
    actual_labs = bundle.get("transfer_lab") or []
    actual_lab_ids = [str(lab.get("lab_id") or "") for lab in actual_labs]
    expected_lab_ids = [str(lab.get("lab_id") or "") for lab in expected_labs]
    if actual_lab_ids != expected_lab_ids:
        raise CaseValidationError(
            "transfer lab order must match executable experience blueprint: "
            f"{expected_lab_ids}"
        )
    for actual, expected in zip(actual_labs, expected_labs):
        expected_truth = set(expected.get("required_truth_fact_ids") or [])
        actual_truth = set(actual.get("truth_fact_ids") or [])
        if actual_truth != expected_truth:
            raise CaseValidationError(
                f"{actual.get('lab_id')} must cite exactly blueprint facts "
                f"{sorted(expected_truth)}"
            )
        task = str(actual.get("task") or "").lower()
        missing_terms = [
            term
            for term in expected.get("required_task_terms") or []
            if str(term).lower() not in task
        ]
        if missing_terms:
            raise CaseValidationError(
                f"{actual.get('lab_id')} is missing blueprint task terms: "
                f"{missing_terms}"
            )
        for forbidden in expected.get("forbidden_task_terms") or []:
            if str(forbidden).lower() in task:
                raise CaseValidationError(
                    f"{actual.get('lab_id')} repeats an earlier calculation: "
                    f"{forbidden}"
                )

        visible_lab = {
            key: value
            for key, value in actual.items()
            if key not in {"lab_id", "truth_fact_ids"}
        }
        if expected.get("forbid_numeric_scenario"):
            numeric_tokens = _visible_numeric_tokens(visible_lab)
            if numeric_tokens:
                raise CaseValidationError(
                    f"{actual.get('lab_id')} must remain qualitative; found "
                    f"numeric tokens {sorted(numeric_tokens)}"
                )
        allowed_tokens = {
            str(token).replace(",", "")
            for token in expected.get("allowed_numeric_tokens") or []
        }
        if allowed_tokens:
            unknown_tokens = _visible_numeric_tokens(visible_lab) - allowed_tokens
            if unknown_tokens:
                raise CaseValidationError(
                    f"{actual.get('lab_id')} invents numbers outside executable "
                    f"truth: {sorted(unknown_tokens)}"
                )

    if post_reveal.get("forbid_numeric_research_proposals"):
        numeric_tokens = _visible_numeric_tokens(bundle.get("research_frontier") or [])
        if numeric_tokens:
            raise CaseValidationError(
                "research frontier invents quantitative parameters outside "
                f"executable truth: {sorted(numeric_tokens)}"
            )
    if post_reveal.get("forbid_numeric_delayed_probe"):
        delayed_probe = (bundle.get("retention") or {}).get("delayed_probe") or {}
        learner_probe = {
            key: value for key, value in delayed_probe.items() if key != "delay_days"
        }
        numeric_tokens = _visible_numeric_tokens(learner_probe)
        if numeric_tokens:
            raise CaseValidationError(
                "delayed probe invents quantitative parameters outside "
                f"executable truth: {sorted(numeric_tokens)}"
            )


def validate_generated_case(
    bundle: Mapping[str, Any],
    *,
    concept: Mapping[str, Any],
    valid_span_ids: set[str],
    executable_truth: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a readiness report or raise on a blocking failure."""

    try:
        validate_case_bundle(bundle)
    except ContractError as error:
        raise CaseValidationError(str(error)) from error

    canonical_name = _require_text(
        concept.get("canonical_name"), "concept.canonical_name"
    )
    if bundle["reveal"].get("canonical_name") != canonical_name:
        raise CaseValidationError(
            "reveal.canonical_name must exactly match the canonical concept name"
        )

    pre_reveal_text = _normalized(
        json.dumps(bundle["pre_reveal"], ensure_ascii=False)
    )
    leak_terms = [canonical_name, *(concept.get("aliases") or [])]
    leaked = []
    for term in leak_terms:
        normalized_term = _normalized(str(term))
        if len(normalized_term) >= 4 and normalized_term in pre_reveal_text:
            leaked.append(str(term))
    if leaked:
        raise CaseValidationError(
            "pre_reveal leaks the hidden concept through: " + ", ".join(leaked)
        )

    if executable_truth:
        _validate_experience_blueprint(bundle, executable_truth)

    opening = bundle["pre_reveal"].get("opening") or {}
    for field in (
        "scene",
        "central_question",
        "commitment_prompt",
        "confidence_prompt",
    ):
        _require_text(opening.get(field), f"pre_reveal.opening.{field}")
    if len(opening.get("observations") or []) < 2:
        raise CaseValidationError("opening needs at least two concrete observations")
    if not opening.get("constraints"):
        raise CaseValidationError("opening needs explicit constraints")

    beats = bundle["pre_reveal"].get("evidence_beats") or []
    if not 3 <= len(beats) <= 5:
        raise CaseValidationError("pre_reveal needs 3-5 evidence beats")
    beat_ids: set[str] = set()
    valid_truth_ids = {
        fact["fact_id"] for fact in (executable_truth or {}).get("facts") or []
    }
    used_truth_ids: set[str] = set()
    for index, beat in enumerate(beats, 1):
        beat_id = _require_text(beat.get("beat_id"), f"evidence_beats[{index}].beat_id")
        if beat_id in beat_ids:
            raise CaseValidationError(f"duplicate evidence beat ID: {beat_id}")
        beat_ids.add(beat_id)
        _require_text(beat.get("evidence"), f"evidence_beats[{index}].evidence")
        _require_text(beat.get("question"), f"evidence_beats[{index}].question")
        if len(beat.get("hints") or []) < 3:
            raise CaseValidationError(
                f"evidence_beats[{index}] needs a progressive hint ladder"
            )
        beat_truth_ids = set(beat.get("truth_fact_ids") or [])
        unknown_truth_ids = beat_truth_ids - valid_truth_ids
        if unknown_truth_ids:
            raise CaseValidationError(
                f"evidence_beats[{index}] cites unknown executable facts: "
                f"{sorted(unknown_truth_ids)}"
            )
        used_truth_ids.update(beat_truth_ids)

    design_gate = bundle["pre_reveal"].get("design_gate") or {}
    _require_text(design_gate.get("prompt"), "pre_reveal.design_gate.prompt")
    if len(design_gate.get("required_elements") or []) < 2:
        raise CaseValidationError("design gate needs at least two constraints")

    reveal = bundle["reveal"]
    if len(reveal.get("mechanism") or []) < 2:
        raise CaseValidationError("reveal needs a multi-step mechanism")
    formalization = reveal.get("formalization") or {}
    _require_text(formalization.get("definition"), "reveal.formalization.definition")
    if not formalization.get("worked_trace"):
        raise CaseValidationError("reveal needs a worked trace")
    if len(reveal.get("tradeoffs") or []) < 2:
        raise CaseValidationError("reveal needs at least two real tradeoffs")
    if not reveal.get("boundary_cases"):
        raise CaseValidationError("reveal needs at least one boundary case")
    if not reveal.get("common_misconceptions"):
        raise CaseValidationError("reveal needs at least one misconception correction")

    transfer_labs = bundle.get("transfer_lab") or []
    if len(transfer_labs) != 2:
        raise CaseValidationError("case needs exactly two transfer labs")
    for index, lab in enumerate(transfer_labs, 1):
        for field in (
            "scenario",
            "task",
            "required_measurement",
            "falsifying_observation",
            "solution",
        ):
            if not lab.get(field):
                raise CaseValidationError(
                    f"transfer_lab[{index}].{field} must not be empty"
                )
        lab_truth_ids = set(lab.get("truth_fact_ids") or [])
        unknown_truth_ids = lab_truth_ids - valid_truth_ids
        if unknown_truth_ids:
            raise CaseValidationError(
                f"transfer_lab[{index}] cites unknown executable facts: "
                f"{sorted(unknown_truth_ids)}"
            )
        used_truth_ids.update(lab_truth_ids)

    if executable_truth and len(used_truth_ids) < 4:
        raise CaseValidationError(
            "case does not use enough facts from its executable truth kernel"
        )

    frontier = bundle.get("research_frontier") or []
    if len(frontier) < 2:
        raise CaseValidationError("case needs at least two research-frontier questions")
    for index, question in enumerate(frontier, 1):
        for field in (
            "question",
            "tension",
            "why_existing_techniques_are_insufficient",
            "experiment",
            "success_metric",
            "hardest_confounder",
        ):
            _require_text(
                question.get(field), f"research_frontier[{index}].{field}"
            )

    atoms = bundle["evaluation"].get("reasoning_atoms") or []
    rubric = bundle["evaluation"].get("rubric") or []
    if len(atoms) < 5 or len(rubric) < 5:
        raise CaseValidationError(
            "evaluation needs at least five reasoning atoms and rubric criteria"
        )

    claims = bundle["claim_ledger"]
    if len(claims) < 5:
        raise CaseValidationError("claim ledger needs at least five grounded claims")
    used_spans: set[str] = set()
    for claim in claims:
        for span_id in claim.get("source_span_ids") or []:
            if span_id not in valid_span_ids:
                raise CaseValidationError(
                    f"claim {claim.get('claim_id')} cites unknown span {span_id}"
                )
            used_spans.add(span_id)

    retention = bundle.get("retention") or {}
    _require_text(retention.get("retrieval_trigger"), "retention.retrieval_trigger")
    _require_text(
        retention.get("one_sentence_compression"),
        "retention.one_sentence_compression",
    )
    if not (retention.get("delayed_probe") or {}).get("success_criteria"):
        raise CaseValidationError("retention needs delayed-probe success criteria")

    return {
        "status": "structurally_ready",
        "blocking_failures": [],
        "human_review_required": [
            "technical_claim_accuracy",
            "mystery_solvability",
            "authored_voice",
            "question_timing",
            "research_frontier_quality",
            "visual_leakage_if_assets_are_added",
        ],
        "metrics": {
            "evidence_beats": len(beats),
            "transfer_labs": len(transfer_labs),
            "research_frontier_questions": len(frontier),
            "reasoning_atoms": len(atoms),
            "grounded_claims": len(claims),
            "distinct_source_spans_cited": len(used_spans),
            "executable_truth_facts_used": len(used_truth_ids),
        },
    }
