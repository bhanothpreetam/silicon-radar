"""Gemini-backed case generation and safe client-payload splitting."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from learning_engine.case_validation import CaseValidationError, validate_generated_case


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "learning_case_v1.txt"
CRITIC_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "learning_case_critic_v1.txt"
)
REPAIR_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "learning_case_repair_v1.txt"
)


def render_case_prompt(source_pack: dict[str, Any]) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    private_json = json.dumps(source_pack, indent=2, ensure_ascii=False)
    return template.replace("__SOURCE_PACK_JSON__", private_json)


def render_critic_prompt(
    source_pack: dict[str, Any],
    draft: dict[str, Any],
    validator_note: str,
) -> str:
    template = CRITIC_PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template.replace(
            "__SOURCE_PACK_JSON__",
            json.dumps(source_pack, indent=2, ensure_ascii=False),
        )
        .replace(
            "__DRAFT_CASE_JSON__",
            json.dumps(draft, indent=2, ensure_ascii=False),
        )
        .replace("__VALIDATOR_NOTE__", validator_note)
    )


def render_repair_prompt(
    source_pack: dict[str, Any],
    draft: dict[str, Any],
    review: dict[str, Any],
) -> str:
    case_contract = render_case_prompt(source_pack)
    template = REPAIR_PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template.replace("__AUTHORING_CONTRACT__", case_contract)
        .replace(
            "__REVIEW_JSON__",
            json.dumps(review, indent=2, ensure_ascii=False),
        )
        .replace(
            "__DRAFT_CASE_JSON__",
            json.dumps(draft, indent=2, ensure_ascii=False),
        )
    )


def _generate_json(
    prompt: str,
    *,
    api_keys: list[str],
    model: str,
    temperature: float,
    thinking_budget: int,
    max_output_tokens: int,
) -> dict[str, Any]:
    from google import genai
    from google.genai import types

    last_error: Exception | None = None
    for key in api_keys:
        client = genai.Client(
            api_key=key,
            http_options=types.HttpOptions(timeout=180_000),
        )
        for json_attempt in range(2):
            retry_instruction = ""
            if json_attempt:
                retry_instruction = (
                    "\n\nYour previous response was not valid JSON. Generate "
                    "the complete object again, check every comma and quote, "
                    "and return JSON only."
                )
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt + retry_instruction,
                    config=types.GenerateContentConfig(
                        temperature=max(0.05, temperature - 0.05 * json_attempt),
                        max_output_tokens=max_output_tokens,
                        response_mime_type="application/json",
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=thinking_budget
                        ),
                    ),
                )
                try:
                    return json.loads(response.text)
                except json.JSONDecodeError as error:
                    last_error = error
                    continue
            except Exception as error:
                last_error = error
                if "RESOURCE_EXHAUSTED" in str(error):
                    break
                raise
    raise RuntimeError(f"All configured Gemini keys failed: {last_error}")


def _private_bundle(
    generated: dict[str, Any],
    source_pack: dict[str, Any],
    revision: int,
) -> dict[str, Any]:
    concept = source_pack["concept"]
    opaque_case_key = (
        f"{source_pack['corpus_version']}:{concept['concept_id']}:{revision}"
    )
    opaque_case_id = hashlib.sha256(opaque_case_key.encode("utf-8")).hexdigest()[:12]
    case_id = f"case-{opaque_case_id}-r{revision:03d}"
    return {
        "case_id": case_id,
        "case_revision": revision,
        "concept_id": concept["concept_id"],
        "experience_type": generated.get("experience_type", "frontier"),
        "corpus_version": source_pack["corpus_version"],
        "compiler_version": "learning-case-v1",
        "executable_truth_id": (
            (source_pack.get("executable_truth") or {}).get("kernel_id")
        ),
        "executable_truth_sha256": (
            (source_pack.get("executable_truth") or {}).get("truth_sha256")
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "investigation_mode": generated.get("investigation_mode"),
        "pre_reveal": generated.get("pre_reveal"),
        "reveal": generated.get("reveal"),
        "transfer_lab": generated.get("transfer_lab"),
        "research_frontier": generated.get("research_frontier"),
        "retention": generated.get("retention"),
        "evaluation": generated.get("evaluation"),
        "claim_ledger": generated.get("claim_ledger"),
    }


def _normalize_truth_references(
    bundle: dict[str, Any],
    source_pack: dict[str, Any],
) -> None:
    truth = source_pack.get("executable_truth") or {}
    if not truth:
        return
    legal_ids = {fact["fact_id"] for fact in truth.get("facts") or []}
    source_entity_ids = {
        entity["entity_id"] for entity in source_pack.get("content_entities") or []
    }
    aliases = {
        "three_operation_schedule": "pipe-f9",
    }
    notes: list[str] = []
    records = list((bundle.get("pre_reveal") or {}).get("evidence_beats") or [])
    records.extend(bundle.get("transfer_lab") or [])
    for record in records:
        normalized: list[str] = []
        for reference in record.get("truth_fact_ids") or []:
            mapped = aliases.get(reference, reference)
            if mapped != reference:
                notes.append(f"mapped {reference} to {mapped}")
            if mapped in source_entity_ids:
                notes.append(
                    f"removed source entity {mapped} from executable fact references"
                )
                continue
            if mapped not in normalized:
                normalized.append(mapped)
        record["truth_fact_ids"] = normalized
    if notes:
        bundle["truth_reference_normalization"] = {
            "legal_fact_ids": sorted(legal_ids),
            "notes": notes,
        }


def _normalize_hint_ladders(bundle: dict[str, Any]) -> None:
    """Complete truncated hint arrays without adding technical claims.

    Hint scaffolding is interaction metadata, not architecture content. Models
    occasionally truncate a ladder to one or two items even after a repair
    pass. These generic prompts preserve whatever authored hints exist and
    complete only the missing metacognitive steps.
    """

    fallbacks = (
        "Write down the invariant that every admissible explanation must preserve.",
        "Use the newest observation to eliminate at least one competing hypothesis.",
        "Name a measurement or counterexample that would distinguish the remaining explanations.",
    )
    notes: list[str] = []
    beats = (bundle.get("pre_reveal") or {}).get("evidence_beats") or []
    for index, beat in enumerate(beats, 1):
        raw_hints = beat.get("hints")
        hints = (
            [str(hint).strip() for hint in raw_hints if str(hint).strip()]
            if isinstance(raw_hints, list)
            else []
        )
        original_count = len(hints)
        for fallback in fallbacks:
            if len(hints) >= 3:
                break
            if fallback not in hints:
                hints.append(fallback)
        beat["hints"] = hints
        if len(hints) != original_count:
            notes.append(
                f"completed evidence beat {index} hint ladder "
                f"from {original_count} to {len(hints)} items"
            )
    if notes:
        bundle["structural_normalization"] = {"notes": notes}


def _apply_truth_owned_renderings(
    bundle: dict[str, Any],
    source_pack: dict[str, Any],
) -> None:
    """Replace arithmetic-bearing prose with kernel-owned canonical output."""

    renderings = (
        (source_pack.get("executable_truth") or {}).get("canonical_renderings")
        or {}
    )
    worked_trace = renderings.get("worked_trace")
    fields: list[str] = []
    if worked_trace:
        formalization = (bundle.get("reveal") or {}).get("formalization")
        if isinstance(formalization, dict):
            formalization["worked_trace"] = copy.deepcopy(worked_trace)
            fields.append("reveal.formalization.worked_trace")

    overrides = renderings.get("transfer_lab_overrides") or {}
    for lab in bundle.get("transfer_lab") or []:
        lab_id = str(lab.get("lab_id") or "")
        if lab_id in overrides:
            lab.clear()
            lab.update(copy.deepcopy(overrides[lab_id]))
            lab["lab_id"] = lab_id
            fields.append(f"transfer_lab.{lab_id}")

    if fields:
        bundle.setdefault("truth_rendering_normalization", {})["fields"] = fields


def _review_passes(review: dict[str, Any]) -> bool:
    if review.get("verdict") != "pass":
        return False
    if any(
        issue.get("severity") in {"blocking", "major"}
        for issue in review.get("blocking_issues") or []
    ):
        return False
    scores = review.get("scores") or {}
    required = {
        "target_alignment",
        "solvability",
        "technical_correctness",
        "grounding",
        "learning_quality",
        "authored_voice",
    }
    if not required.issubset(scores):
        return False
    if int(scores["target_alignment"]) != 5:
        return False
    if int(scores["technical_correctness"]) != 5:
        return False
    return all(int(scores[name]) >= 4 for name in required)


def generate_case(
    source_pack: dict[str, Any],
    *,
    api_keys: Iterable[str],
    model: str,
    revision: int = 2,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Generate, critique, repair, and re-review one private CaseBundle."""

    keys = [key for key in api_keys if key]
    if not keys:
        raise ValueError("No Gemini API keys are configured")

    generated = _generate_json(
        render_case_prompt(source_pack),
        api_keys=keys,
        model=model,
        temperature=0.3,
        thinking_budget=4096,
        max_output_tokens=32768,
    )
    concept = source_pack["concept"]
    bundle = _private_bundle(generated, source_pack, revision)
    _normalize_truth_references(bundle, source_pack)
    _normalize_hint_ladders(bundle)
    _apply_truth_owned_renderings(bundle, source_pack)
    valid_span_ids = {
        span["span_id"] for span in source_pack.get("source_spans") or []
    }
    validator_note = "Automatic structural validation passed."
    try:
        validate_generated_case(
            bundle,
            concept=concept,
            valid_span_ids=valid_span_ids,
            executable_truth=source_pack.get("executable_truth"),
        )
    except CaseValidationError as error:
        validator_note = f"Automatic structural validation failed: {error}"

    review = _generate_json(
        render_critic_prompt(source_pack, bundle, validator_note),
        api_keys=keys,
        model=model,
        temperature=0.1,
        thinking_budget=4096,
        max_output_tokens=12288,
    )
    if not _review_passes(review) or "failed" in validator_note.lower():
        repaired = _generate_json(
            render_repair_prompt(source_pack, bundle, review),
            api_keys=keys,
            model=model,
            temperature=0.2,
            thinking_budget=4096,
            max_output_tokens=32768,
        )
        bundle = _private_bundle(repaired, source_pack, revision)
        _normalize_truth_references(bundle, source_pack)
        _normalize_hint_ladders(bundle)
        _apply_truth_owned_renderings(bundle, source_pack)

    try:
        readiness = validate_generated_case(
            bundle,
            concept=concept,
            valid_span_ids=valid_span_ids,
            executable_truth=source_pack.get("executable_truth"),
        )
    except CaseValidationError as error:
        legal_truth_ids = [
            fact["fact_id"]
            for fact in (source_pack.get("executable_truth") or {}).get("facts")
            or []
        ]
        structural_review = {
            "verdict": "revise",
            "blocking_issues": [
                {
                    "category": "learning",
                    "severity": "blocking",
                    "location": "automatic structural readiness gate",
                    "problem": str(error),
                    "analysis": (
                        "The repaired case cannot enter review because a "
                        "load-bearing runtime or learning field is invalid."
                    ),
                    "required_fix": (
                        "Return a complete case satisfying the exact authoring "
                        "contract without weakening or deleting the interaction. "
                        f"The only legal executable fact IDs are {legal_truth_ids}."
                    ),
                    "source_span_ids": [],
                }
            ],
            "strengths_to_preserve": review.get("strengths_to_preserve") or [],
            "revision_brief": [
                f"Repair the blocking structural failure: {error}",
                "Recheck every required array and learner commitment field.",
                f"Use only these executable fact IDs: {legal_truth_ids}.",
            ],
            "scores": {},
        }
        repaired = _generate_json(
            render_repair_prompt(source_pack, bundle, structural_review),
            api_keys=keys,
            model=model,
            temperature=0.1,
            thinking_budget=2048,
            max_output_tokens=32768,
        )
        bundle = _private_bundle(repaired, source_pack, revision)
        _normalize_truth_references(bundle, source_pack)
        _normalize_hint_ladders(bundle)
        _apply_truth_owned_renderings(bundle, source_pack)
        readiness = validate_generated_case(
            bundle,
            concept=concept,
            valid_span_ids=valid_span_ids,
            executable_truth=source_pack.get("executable_truth"),
        )
    final_review = _generate_json(
        render_critic_prompt(
            source_pack,
            bundle,
            "Automatic structural validation passed.",
        ),
        api_keys=keys,
        model=model,
        temperature=0.1,
        thinking_budget=4096,
        max_output_tokens=12288,
    )
    readiness["model_review"] = {
        "verdict": final_review.get("verdict"),
        "passes_strict_threshold": _review_passes(final_review),
        "scores": final_review.get("scores"),
        "blocking_issue_count": len(final_review.get("blocking_issues") or []),
    }
    return bundle, readiness, final_review


def repair_case(
    source_pack: dict[str, Any],
    draft: dict[str, Any],
    human_review: dict[str, Any],
    *,
    api_keys: Iterable[str],
    model: str,
    revision: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Create one new revision from explicit human findings.

    Unlike the automatic generation path, this performs exactly one authoring
    call and one independent critic call. A structural failure is returned to
    the operator rather than triggering an unbounded repair loop.
    """

    keys = [key for key in api_keys if key]
    if not keys:
        raise ValueError("No Gemini API keys are configured")

    repaired = _generate_json(
        render_repair_prompt(source_pack, draft, human_review),
        api_keys=keys,
        model=model,
        temperature=0.1,
        thinking_budget=4096,
        max_output_tokens=32768,
    )
    bundle = _private_bundle(repaired, source_pack, revision)
    _normalize_truth_references(bundle, source_pack)
    _normalize_hint_ladders(bundle)
    _apply_truth_owned_renderings(bundle, source_pack)

    concept = source_pack["concept"]
    try:
        readiness = validate_generated_case(
            bundle,
            concept=concept,
            valid_span_ids={
                span["span_id"] for span in source_pack.get("source_spans") or []
            },
            executable_truth=source_pack.get("executable_truth"),
        )
    except CaseValidationError as error:
        readiness = {
            "status": "structurally_rejected",
            "blocking_failures": [str(error)],
            "model_review": {
                "verdict": "not_run",
                "passes_strict_threshold": False,
                "scores": {},
                "blocking_issue_count": 1,
            },
        }
        return (
            bundle,
            readiness,
            {
                "verdict": "not_run",
                "blocking_issues": [
                    {
                        "category": "structure",
                        "severity": "blocking",
                        "location": "automatic structural readiness gate",
                        "problem": str(error),
                        "analysis": (
                            "The human-directed repair was preserved privately, "
                            "but critique was skipped because it was not structurally safe."
                        ),
                        "required_fix": "Correct the compiler contract violation.",
                        "source_span_ids": [],
                    }
                ],
                "strengths_to_preserve": [],
                "revision_brief": [],
                "scores": {},
            },
        )
    final_review = _generate_json(
        render_critic_prompt(
            source_pack,
            bundle,
            "Automatic structural validation passed after human-directed repair.",
        ),
        api_keys=keys,
        model=model,
        temperature=0.1,
        thinking_budget=4096,
        max_output_tokens=12288,
    )
    readiness["model_review"] = {
        "verdict": final_review.get("verdict"),
        "passes_strict_threshold": _review_passes(final_review),
        "scores": final_review.get("scores"),
        "blocking_issue_count": len(final_review.get("blocking_issues") or []),
    }
    return bundle, readiness, final_review


_INTERNAL_CITATION = re.compile(
    r"\s*\[(?:(?:c\d+|pipe-f\d+)(?:\s*,\s*)?)+\]"
)


def _reader_copy(value: Any) -> Any:
    """Deep-copy a reader payload while removing private provenance markers."""

    if isinstance(value, str):
        return _INTERNAL_CITATION.sub("", value)
    if isinstance(value, list):
        return [_reader_copy(item) for item in value]
    if isinstance(value, dict):
        return {key: _reader_copy(item) for key, item in value.items()}
    return copy.deepcopy(value)


def split_case_for_delivery(
    bundle: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Split a private bundle into pre-reveal, reveal, and evaluator payloads."""

    common = {
        "case_id": bundle["case_id"],
        "case_revision": bundle["case_revision"],
        "experience_type": bundle["experience_type"],
        "corpus_version": bundle["corpus_version"],
    }
    pre_reveal = {
        **common,
        "investigation_mode": bundle.get("investigation_mode"),
        "pre_reveal": _reader_copy(bundle["pre_reveal"]),
    }
    reveal = {
        **common,
        "concept_id": bundle["concept_id"],
        "reveal": _reader_copy(bundle["reveal"]),
        "transfer_lab": _reader_copy(bundle["transfer_lab"]),
        "research_frontier": _reader_copy(bundle["research_frontier"]),
        "retention": _reader_copy(bundle["retention"]),
    }
    evaluator = {
        **common,
        "concept_id": bundle["concept_id"],
        "evaluation": bundle["evaluation"],
        "claim_ledger": bundle["claim_ledger"],
    }
    return pre_reveal, reveal, evaluator
