"""Assemble bounded, role-aware evidence packs for the mystery compiler."""

from __future__ import annotations

from collections import Counter
from typing import Any

from learning_engine.executable_truth import truth_for_concept
from learning_engine.repository import CorpusRepository


ROLE_PRIORITY = {
    "canonical": 0,
    "formalization": 1,
    "worked_example": 2,
    "boundary_case": 3,
    "adversarial": 4,
    "historical": 5,
    "problem_family": 6,
}


def build_source_pack(
    repository: CorpusRepository,
    concept_id: str,
    *,
    max_source_chars: int = 42_000,
    max_spans: int = 12,
) -> dict[str, Any]:
    """Build a private compiler packet, never a client payload."""

    concept = repository.concept(concept_id)
    links = sorted(
        repository.concept_links(concept_id),
        key=lambda link: (
            ROLE_PRIORITY.get(link.get("pedagogical_role"), 99),
            -int(link.get("lexical_score") or 0),
            link["span_id"],
        ),
    )
    if not links:
        raise ValueError(f"{concept_id} has no source links")

    selected: list[dict[str, Any]] = []
    role_counts: Counter[str] = Counter()
    page_counts: Counter[str] = Counter()
    source_chars = 0

    # First preserve role diversity; then spend the remaining budget on the
    # strongest unused links.
    ordered = []
    for role in ROLE_PRIORITY:
        ordered.extend(
            link for link in links if link.get("pedagogical_role") == role
        )
    ordered.extend(link for link in links if link not in ordered)

    for link in ordered:
        span = repository.span_by_id[link["span_id"]]
        role = str(link.get("pedagogical_role") or "canonical")
        if page_counts[span["page_id"]] >= 2:
            continue
        if source_chars + len(span["text"]) > max_source_chars and selected:
            continue
        selected.append(
            {
                "span_id": span["span_id"],
                "pedagogical_role": role,
                "chapter_id": span["chapter_id"],
                "section_id": span.get("section_id"),
                "book_page": span.get("book_page"),
                "kind": span["kind"],
                "confidence": span["confidence"],
                "needs_review": span["needs_review"],
                "text": span["text"],
            }
        )
        source_chars += len(span["text"])
        role_counts[role] += 1
        page_counts[span["page_id"]] += 1
        if len(selected) >= max_spans:
            break

    selected_page_ids = {span["span_id"].rsplit("-span-", 1)[0] for span in selected}
    assets = [
        {
            key: asset.get(key)
            for key in (
                "asset_id",
                "page_id",
                "asset_type",
                "source_label",
                "content_type",
                "caption",
                "description",
                "bbox_pct",
                "archive_member",
            )
        }
        for asset in repository.assets
        if asset.get("page_id") in selected_page_ids
        and asset.get("asset_type") == "figure"
    ]
    entities = [
        {
            "entity_id": entity["entity_id"],
            "entity_type": entity["entity_type"],
            "page_id": entity.get("page_id"),
            "source_label": entity.get("source_label"),
            "content": entity["content"],
        }
        for entity in repository.entities
        if entity.get("page_id") in selected_page_ids
        and entity["entity_type"] in {"equation", "table", "example", "problem"}
    ]

    prerequisites = [
        {
            "concept_id": prerequisite_id,
            "canonical_name": repository.concept(prerequisite_id)[
                "canonical_name"
            ],
            "problem_solved": repository.concept(prerequisite_id)[
                "problem_solved"
            ],
        }
        for prerequisite_id in repository.hard_prerequisites(concept_id)
    ]
    neighboring_edges = [
        {
            key: edge.get(key)
            for key in (
                "edge_id",
                "from_concept_id",
                "to_concept_id",
                "edge_type",
                "rationale",
            )
        }
        for edge in repository.neighboring_edges(concept_id)
    ]

    source_pack = {
        "packet_type": "private_mystery_compiler_source_pack",
        "packet_version": "1.0.0",
        "corpus_version": repository.corpus_version,
        "concept": {
            key: concept.get(key)
            for key in (
                "concept_id",
                "canonical_name",
                "aliases",
                "problem_solved",
                "revision",
            )
        },
        "hard_prerequisites": prerequisites,
        "neighboring_edges": neighboring_edges,
        "source_spans": selected,
        "visual_assets": assets,
        "content_entities": entities,
        "assembly": {
            "source_chars": source_chars,
            "span_count": len(selected),
            "role_counts": dict(role_counts),
            "all_links_review_status": sorted(
                {link.get("review_status", "unknown") for link in links}
            ),
            "warning": (
                "This packet is private and contains the hidden concept name "
                "and copyrighted source passages. Never send it to the client."
            ),
        },
    }
    executable_truth = truth_for_concept(concept_id)
    if executable_truth:
        source_pack["executable_truth"] = executable_truth
    return source_pack
