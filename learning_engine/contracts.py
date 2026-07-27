"""Runtime contracts and invariant checks for the learning engine.

The first corpus build does not need a database or a web client.  It does need
stable boundaries that prevent later implementations from quietly collapsing
the concept graph, generated case, and learner state into one mutable object.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping


EDGE_TYPES = frozenset(
    {
        "hard_requires",
        "supporting_requires",
        "explains",
        "contrasts_with",
        "trades_off_with",
        "breaks_under",
        "same_mechanism_different_layer",
        "historically_led_to",
        "appears_in_product",
        "measured_by",
        "implemented_by",
    }
)

EXPERIENCE_TYPES = frozenset({"frontier", "cold_probe", "bridge"})

CONTENT_LIFECYCLE = (
    "extracted",
    "graph_reviewed",
    "case_authored",
    "leakage_checked",
    "content_ready",
    "active",
    "revised",
    "retired",
)

LEARNER_LIFECYCLE = (
    "unseen",
    "mechanism_discovered",
    "formally_understood",
    "applied",
    "delayed_retrieval_passed",
    "transferred",
    "operationally_mastered",
)


class ContractError(ValueError):
    """Raised when an artifact violates a load-bearing engine invariant."""


def validate_concept_graph(
    concepts: Iterable[Mapping],
    edges: Iterable[Mapping],
) -> None:
    """Validate endpoints, edge types, rationales, and hard-edge acyclicity."""

    concept_list = list(concepts)
    edge_list = list(edges)
    concept_ids = [str(concept.get("concept_id", "")) for concept in concept_list]

    if any(not concept_id for concept_id in concept_ids):
        raise ContractError("Every concept must have a non-empty concept_id")
    if len(set(concept_ids)) != len(concept_ids):
        raise ContractError("Concept IDs must be unique")

    known = set(concept_ids)
    hard_adjacency: dict[str, list[str]] = defaultdict(list)

    for edge in edge_list:
        edge_type = edge.get("edge_type")
        source = edge.get("from_concept_id")
        target = edge.get("to_concept_id")
        if edge_type not in EDGE_TYPES:
            raise ContractError(f"Unknown edge type: {edge_type!r}")
        if source not in known or target not in known:
            raise ContractError(
                f"Edge endpoint is not in the concept graph: {source!r} -> {target!r}"
            )
        if source == target:
            raise ContractError(f"Self-edge is not allowed: {source!r}")
        if edge_type == "hard_requires":
            if not str(edge.get("rationale", "")).strip():
                raise ContractError(
                    f"Hard prerequisite {source!r} -> {target!r} needs a rationale"
                )
            # "A hard_requires B" means A depends on B.
            hard_adjacency[source].append(target)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(concept_id: str, path: list[str]) -> None:
        if concept_id in visiting:
            cycle_start = path.index(concept_id)
            cycle = path[cycle_start:] + [concept_id]
            raise ContractError(
                "Cycle in hard prerequisites: " + " -> ".join(cycle)
            )
        if concept_id in visited:
            return
        visiting.add(concept_id)
        path.append(concept_id)
        for prerequisite in hard_adjacency.get(concept_id, []):
            visit(prerequisite, path)
        path.pop()
        visiting.remove(concept_id)
        visited.add(concept_id)

    for concept_id in concept_ids:
        visit(concept_id, [])


def validate_case_bundle(bundle: Mapping) -> None:
    """Validate the privacy and state boundaries of a compiled case.

    The browser must receive ``pre_reveal`` before it earns ``reveal``.  Keeping
    those payloads as explicit siblings prevents an implementation from hiding
    the answer with CSS while still shipping it to the client.
    """

    required = {
        "case_id",
        "case_revision",
        "concept_id",
        "experience_type",
        "corpus_version",
        "pre_reveal",
        "reveal",
        "evaluation",
        "claim_ledger",
    }
    missing = sorted(required - set(bundle))
    if missing:
        raise ContractError(f"Case bundle is missing fields: {', '.join(missing)}")
    if bundle["experience_type"] not in EXPERIENCE_TYPES:
        raise ContractError(
            f"Unknown experience_type: {bundle['experience_type']!r}"
        )
    if not isinstance(bundle["pre_reveal"], Mapping):
        raise ContractError("pre_reveal must be an object")
    if not isinstance(bundle["reveal"], Mapping):
        raise ContractError("reveal must be an object")
    if "canonical_name" in bundle["pre_reveal"]:
        raise ContractError("pre_reveal must not contain canonical_name")

    reveal_name = str(bundle["reveal"].get("canonical_name", "")).strip()
    if not reveal_name:
        raise ContractError("reveal must contain canonical_name")

    claims = bundle["claim_ledger"]
    if not isinstance(claims, list) or not claims:
        raise ContractError("claim_ledger must contain at least one grounded claim")
    for claim in claims:
        if not claim.get("claim_id") or not claim.get("source_span_ids"):
            raise ContractError(
                "Every claim needs claim_id and at least one source_span_id"
            )
