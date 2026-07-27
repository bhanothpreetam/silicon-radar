"""Build normalized Radar learning artifacts from an H&P extraction archive.

The source ZIP is never unpacked.  Generated records use stable logical IDs and
point back to archive members, while the archive's SHA-256 identifies the exact
immutable source release.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from learning_engine.contracts import ContractError, validate_concept_graph


CORPUS_SCHEMA_VERSION = "1.0.0"
BUILDER_VERSION = "hp-zip-normalizer-v1"

_CHAPTER_RE = re.compile(r"^chapter_(\d+)/chapter\.json$")
_REFERENCE_RE = re.compile(
    r"\b(?P<kind>Figure|Table|Section)\s+(?P<label>\d+\.\d+)\b",
    re.IGNORECASE,
)


class CorpusBuildError(ValueError):
    """Raised when the archive or extracted content is unsafe or inconsistent."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "unnamed"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as destination:
        for row in rows:
            destination.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)


def _load_json_member(archive: zipfile.ZipFile, member: str) -> Any:
    try:
        return json.loads(archive.read(member))
    except KeyError as error:
        raise CorpusBuildError(f"Archive member is missing: {member}") from error
    except json.JSONDecodeError as error:
        raise CorpusBuildError(f"Invalid JSON in {member}: {error}") from error


def _validate_archive_members(archive: zipfile.ZipFile) -> set[str]:
    names: set[str] = set()
    for info in archive.infolist():
        member = PurePosixPath(info.filename)
        if member.is_absolute() or ".." in member.parts:
            raise CorpusBuildError(f"Unsafe archive path: {info.filename!r}")
        if info.filename in names:
            raise CorpusBuildError(f"Duplicate archive member: {info.filename!r}")
        names.add(info.filename)
    return names


def _discover_chapters(member_names: Iterable[str]) -> list[int]:
    chapters = sorted(
        int(match.group(1))
        for name in member_names
        if (match := _CHAPTER_RE.fullmatch(name))
    )
    if not chapters:
        raise CorpusBuildError("No chapter_N/chapter.json members were found")
    return chapters


def _section_id(chapter_id: str, section: Mapping[str, Any], ordinal: int) -> str:
    number = str(section.get("number") or "").strip()
    if number:
        suffix = _slug(number)
    else:
        suffix = f"front-{ordinal:02d}-{_slug(section.get('title'))}"
    return f"{chapter_id}-sec-{suffix}"


def _classify_span(text: str, page_kind: str) -> str:
    stripped = text.strip()
    lower = stripped.lower()
    if stripped.startswith("#"):
        return "heading"
    if stripped.startswith("[[") and stripped.endswith("]]"):
        return "asset_reference"
    if stripped.startswith("|") and "\n|" in stripped:
        return "table"
    if stripped.startswith("$$") or "\\begin{" in stripped:
        return "equation"
    if lower.startswith("**figure ") or lower.startswith("**table "):
        return "caption"
    if lower.startswith("example ") or lower.startswith("**example"):
        return "example"
    if page_kind in {"problems", "exercises"}:
        return "problem"
    return "prose"


def _split_source_blocks(text: str) -> list[tuple[int, int, str]]:
    """Return exact non-empty blocks and offsets into the raw page text."""

    blocks: list[tuple[int, int, str]] = []
    for match in re.finditer(
        r"\S(?:.*?\S)?(?=(?:\n[ \t]*){2,}|\Z)",
        text,
        flags=re.DOTALL,
    ):
        blocks.append((match.start(), match.end(), match.group(0)))
    if not blocks and text.strip():
        start = len(text) - len(text.lstrip())
        end = len(text.rstrip())
        blocks.append((start, end, text[start:end]))
    return blocks


def _section_for_page(
    sections: list[dict[str, Any]], page_index: int
) -> dict[str, Any] | None:
    matches = [
        section
        for section in sections
        if int(section["page_index_start"]) <= page_index
        <= int(section["page_index_end"])
    ]
    if not matches:
        return None
    return min(
        matches,
        key=lambda section: (
            int(section["page_index_end"]) - int(section["page_index_start"]),
            -int(section["ordinal"]),
        ),
    )


def _archive_member_uri(archive_sha256: str, member: str) -> str:
    return f"zip://sha256/{archive_sha256}!/{member}"


def _normalize_confidence(value: Any) -> str:
    normalized = str(value or "unknown").strip().lower()
    if normalized not in {"high", "medium", "low", "unknown"}:
        return "unknown"
    return normalized


def _normalize_chapter(
    archive: zipfile.ZipFile,
    member_names: set[str],
    archive_sha256: str,
    chapter_number: int,
    corpus_version: str,
) -> dict[str, Any]:
    prefix = f"chapter_{chapter_number}"
    chapter_member = f"{prefix}/chapter.json"
    chapter_bytes = archive.read(chapter_member)
    chapter = json.loads(chapter_bytes)

    book_id = _slug(chapter.get("book") or "hp7")
    declared_chapter = int(chapter.get("chapter", chapter_number))
    if declared_chapter != chapter_number:
        raise CorpusBuildError(
            f"{chapter_member} declares chapter {declared_chapter}, "
            f"expected {chapter_number}"
        )
    chapter_id = f"{book_id}-ch{chapter_number:02d}"
    pages = chapter.get("pages")
    if not isinstance(pages, list) or not pages:
        raise CorpusBuildError(f"{chapter_member} has no pages")

    raw_manifest_member = f"{prefix}/work/manifest.json"
    raw_manifest = _load_json_member(archive, raw_manifest_member)
    if not isinstance(raw_manifest, list):
        raise CorpusBuildError(f"{raw_manifest_member} must be a list")
    dimensions_by_page = {
        int(row["n"]): {
            "width": row.get("width"),
            "height": row.get("height"),
            "complete_image": bool(row.get("complete_image", False)),
        }
        for row in raw_manifest
    }

    page_numbers = [int(page["n"]) for page in pages]
    expected_pages = list(range(1, len(pages) + 1))
    if page_numbers != expected_pages:
        raise CorpusBuildError(
            f"{chapter_id} page indices are not contiguous from 1"
        )
    if sorted(dimensions_by_page) != expected_pages:
        raise CorpusBuildError(
            f"{chapter_id} raw manifest does not cover every assembled page"
        )

    sections: list[dict[str, Any]] = []
    section_number_to_id: dict[str, str] = {}
    for ordinal, section in enumerate(chapter.get("sections") or [], 1):
        normalized = {
            "section_id": _section_id(chapter_id, section, ordinal),
            "chapter_id": chapter_id,
            "ordinal": ordinal,
            "number": str(section.get("number") or ""),
            "title": str(section.get("title") or ""),
            "page_start": section.get("page_start"),
            "page_end": section.get("page_end"),
            "page_index_start": int(section["page_index_start"]),
            "page_index_end": int(section["page_index_end"]),
            "text_sha256": _sha256_bytes(
                str(section.get("text") or "").encode("utf-8")
            ),
        }
        sections.append(normalized)
        if normalized["number"] and normalized["number"] not in {"TOC"}:
            section_number_to_id[normalized["number"]] = normalized["section_id"]

    spans: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    warnings: list[str] = []
    page_records: list[dict[str, Any]] = []

    for page in pages:
        page_index = int(page["n"])
        page_id = f"{chapter_id}-p{page_index:03d}"
        image_relative = str(page.get("image") or f"pages/page-{page_index:03d}.jpg")
        image_member = f"{prefix}/{image_relative}"
        if image_member not in member_names:
            raise CorpusBuildError(
                f"{page_id} references missing page image {image_member}"
            )
        raw_page_member = f"{prefix}/work/page-{page_index:03d}.json"
        raw_page = _load_json_member(archive, raw_page_member)
        raw_index = int(raw_page.get("_page_index", page_index))
        if raw_index != page_index:
            raise CorpusBuildError(
                f"{raw_page_member} declares page index {raw_index}"
            )
        if raw_page.get("book_page") != page.get("book_page"):
            warnings.append(
                f"{page_id}: raw and assembled book_page differ "
                f"({raw_page.get('book_page')!r} != {page.get('book_page')!r})"
            )

        section = _section_for_page(sections, page_index)
        confidence = _normalize_confidence(page.get("confidence"))
        needs_review = bool(page.get("needs_review", False))
        notes = str(page.get("notes") or "")
        full_text = str(raw_page.get("full_text") or "")
        source_hash = _sha256_bytes(full_text.encode("utf-8"))
        dims = dimensions_by_page[page_index]

        running_header = str(raw_page.get("running_header") or "")
        extracted_page_kind = str(raw_page.get("page_kind") or "unknown")
        effective_page_kind = extracted_page_kind
        if (
            raw_page.get("problems")
            or "case studies and exercises" in running_header.lower()
        ):
            effective_page_kind = "problems"

        page_record = {
            "page_id": page_id,
            "chapter_id": chapter_id,
            "section_id": section["section_id"] if section else None,
            "page_index": page_index,
            "book_page": page.get("book_page"),
            "book_page_inferred": bool(page.get("book_page_inferred", False)),
            "page_kind": effective_page_kind,
            "extracted_page_kind": extracted_page_kind,
            "confidence": confidence,
            "needs_review": needs_review,
            "notes": notes,
            "text_sha256": source_hash,
            "asset_id": f"{page_id}-image",
        }
        page_records.append(page_record)

        image_info = archive.getinfo(image_member)
        assets.append(
            {
                "schema_version": CORPUS_SCHEMA_VERSION,
                "asset_id": f"{page_id}-image",
                "corpus_version": corpus_version,
                "book_id": book_id,
                "chapter_id": chapter_id,
                "page_id": page_id,
                "asset_type": "source_page",
                "source_label": None,
                "content_type": "page_scan",
                "logical_uri": f"corpus://{book_id}/ch{chapter_number:02d}/pages/{page_index:03d}",
                "archive_member": image_member,
                "archive_uri": _archive_member_uri(archive_sha256, image_member),
                "crc32": f"{image_info.CRC:08x}",
                "size_bytes": image_info.file_size,
                "width": dims["width"],
                "height": dims["height"],
                "complete_image": dims["complete_image"],
                "book_page": page.get("book_page"),
                "confidence": confidence,
                "needs_review": needs_review,
                "contains_name_leak": None,
                "reveal_stage": "private_source_only",
            }
        )

        for block_index, (start, end, block) in enumerate(
            _split_source_blocks(full_text), 1
        ):
            span_id = f"{page_id}-span-{block_index:03d}"
            spans.append(
                {
                    "schema_version": CORPUS_SCHEMA_VERSION,
                    "span_id": span_id,
                    "corpus_version": corpus_version,
                    "book_id": book_id,
                    "chapter_id": chapter_id,
                    "section_id": section["section_id"] if section else None,
                    "page_id": page_id,
                    "page_index": page_index,
                    "book_page": page.get("book_page"),
                    "block_index": block_index,
                    "char_start": start,
                    "char_end": end,
                    "kind": _classify_span(
                        block, effective_page_kind
                    ),
                    "text": block,
                    "content_sha256": _sha256_bytes(block.encode("utf-8")),
                    "source_asset_id": f"{page_id}-image",
                    "confidence": confidence,
                    "needs_review": needs_review,
                    "review_notes": notes,
                    "provenance": {
                        "archive_sha256": archive_sha256,
                        "raw_page_member": raw_page_member,
                        "assembled_chapter_member": chapter_member,
                    },
                }
            )

        for equation_index, equation in enumerate(raw_page.get("equations") or [], 1):
            entities.append(
                {
                    "schema_version": CORPUS_SCHEMA_VERSION,
                    "entity_id": f"{page_id}-eq-{equation_index:02d}",
                    "entity_type": "equation",
                    "corpus_version": corpus_version,
                    "chapter_id": chapter_id,
                    "section_id": section["section_id"] if section else None,
                    "page_id": page_id,
                    "book_page": page.get("book_page"),
                    "source_label": None,
                    "content": {
                        "latex": equation.get("latex"),
                        "context": equation.get("context"),
                    },
                    "review_status": "extracted",
                }
            )

    label_counts: Counter[tuple[str, str]] = Counter()

    for figure in chapter.get("figures") or []:
        label = str(figure.get("label") or "")
        label_counts[("figure", label)] += 1
        suffix = (
            ""
            if label_counts[("figure", label)] == 1
            else f"-{label_counts[('figure', label)]:02d}"
        )
        figure_id = f"{chapter_id}-fig-{_slug(label.removeprefix('Figure'))}{suffix}"
        image_relative = str(figure.get("image") or "")
        image_member = f"{prefix}/{image_relative}"
        if not image_relative or image_member not in member_names:
            raise CorpusBuildError(
                f"{figure_id} references missing crop {image_member!r}"
            )
        page_index = int(figure["page_index"])
        page_id = f"{chapter_id}-p{page_index:03d}"
        image_info = archive.getinfo(image_member)
        assets.append(
            {
                "schema_version": CORPUS_SCHEMA_VERSION,
                "asset_id": figure_id,
                "corpus_version": corpus_version,
                "book_id": book_id,
                "chapter_id": chapter_id,
                "page_id": page_id,
                "asset_type": "figure",
                "source_label": label,
                "content_type": "unclassified_figure",
                "logical_uri": (
                    f"corpus://{book_id}/ch{chapter_number:02d}/figures/"
                    f"{_slug(label)}"
                ),
                "archive_member": image_member,
                "archive_uri": _archive_member_uri(archive_sha256, image_member),
                "crc32": f"{image_info.CRC:08x}",
                "size_bytes": image_info.file_size,
                "book_page": figure.get("page"),
                "caption": figure.get("caption"),
                "description": figure.get("description"),
                "bbox_pct": figure.get("bbox_pct"),
                "contains_name_leak": None,
                "reveal_stage": "unreviewed",
            }
        )

    entity_suffix_counts: Counter[tuple[str, str]] = Counter()

    def add_assembled_entities(
        entity_type: str,
        values: list[Mapping[str, Any]],
        label_field: str | None,
    ) -> None:
        per_page: Counter[int] = Counter()
        for value in values:
            page_index = int(value.get("page_index") or 0)
            per_page[page_index] += 1
            page_id = f"{chapter_id}-p{page_index:03d}"
            if label_field and value.get(label_field):
                stable_suffix = _slug(value[label_field])
            else:
                stable_suffix = f"{page_index:03d}-{per_page[page_index]:02d}"
            entity_suffix_counts[(entity_type, stable_suffix)] += 1
            duplicate_ordinal = entity_suffix_counts[(entity_type, stable_suffix)]
            if duplicate_ordinal > 1:
                stable_suffix = f"{stable_suffix}-{duplicate_ordinal:02d}"
            entity_id = f"{chapter_id}-{entity_type}-{stable_suffix}"
            entities.append(
                {
                    "schema_version": CORPUS_SCHEMA_VERSION,
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "corpus_version": corpus_version,
                    "chapter_id": chapter_id,
                    "section_id": (
                        (_section_for_page(sections, page_index) or {}).get(
                            "section_id"
                        )
                    ),
                    "page_id": page_id if page_index else None,
                    "book_page": value.get("page"),
                    "source_label": (
                        value.get(label_field) if label_field else None
                    ),
                    "content": dict(value),
                    "review_status": "extracted",
                }
            )

    add_assembled_entities("table", chapter.get("tables") or [], "label")
    add_assembled_entities("example", chapter.get("examples") or [], "id")
    add_assembled_entities("problem", chapter.get("problems") or [], "source_ref")
    add_assembled_entities("reference", chapter.get("references") or [], None)

    return {
        "summary": {
            "book_id": book_id,
            "chapter_id": chapter_id,
            "chapter_number": chapter_number,
            "title": str(chapter.get("title") or ""),
            "source_note": str(chapter.get("source_note") or ""),
            "chapter_member": chapter_member,
            "chapter_json_sha256": _sha256_bytes(chapter_bytes),
            "counts": {
                "pages": len(page_records),
                "sections": len(sections),
                "source_spans": len(spans),
                "assets": len(assets),
                "figures": len(chapter.get("figures") or []),
                "tables": len(chapter.get("tables") or []),
                "equations": sum(
                    1 for entity in entities if entity["entity_type"] == "equation"
                ),
                "examples": len(chapter.get("examples") or []),
                "problems": len(chapter.get("problems") or []),
                "references": len(chapter.get("references") or []),
                "needs_review_pages": sum(
                    bool(page["needs_review"]) for page in page_records
                ),
            },
            "sections": sections,
            "pages": page_records,
        },
        "spans": spans,
        "assets": assets,
        "entities": entities,
        "section_number_to_id": section_number_to_id,
        "warnings": warnings,
    }


def _build_cross_references(
    spans: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    chapter_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    targets: dict[tuple[str, str, str], str] = {}

    for chapter in chapter_summaries:
        chapter_id = chapter["chapter_id"]
        for section in chapter["sections"]:
            number = str(section.get("number") or "")
            if re.fullmatch(r"\d+\.\d+", number):
                targets[(chapter_id, "section", number)] = section["section_id"]

    for asset in assets:
        if asset["asset_type"] != "figure":
            continue
        label = str(asset.get("source_label") or "")
        match = re.search(r"(\d+\.\d+)", label)
        if match:
            targets[(asset["chapter_id"], "figure", match.group(1))] = asset[
                "asset_id"
            ]

    # H&P intentionally labels many tabular objects as figures. Prefer an
    # actual crop when it exists, but let the normalized markdown table resolve
    # a Figure N.N reference when no crop was extracted.
    for entity in entities:
        if entity["entity_type"] != "table":
            continue
        label = str(entity.get("source_label") or "")
        match = re.search(r"(\d+\.\d+)", label)
        if not match:
            continue
        label_number = match.group(1)
        label_kind = "table" if label.lower().startswith("table") else "figure"
        targets.setdefault(
            (entity["chapter_id"], label_kind, label_number),
            entity["entity_id"],
        )

    references: list[dict[str, Any]] = []
    for span in spans:
        seen: set[tuple[str, str]] = set()
        for match in _REFERENCE_RE.finditer(span["text"]):
            kind = match.group("kind").lower()
            label = match.group("label")
            dedupe_key = (kind, label)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            target = targets.get((span["chapter_id"], kind, label))
            references.append(
                {
                    "schema_version": CORPUS_SCHEMA_VERSION,
                    "reference_id": (
                        f"{span['span_id']}-ref-{len(seen):02d}"
                    ),
                    "from_span_id": span["span_id"],
                    "surface_text": match.group(0),
                    "reference_type": kind,
                    "target_label": label,
                    "to_id": target,
                    "resolution": "resolved" if target else "unresolved",
                }
            )
    return references


def _role_for_link(span: Mapping[str, Any], section_title: str) -> str:
    lower = str(span["text"]).lower()
    section_lower = section_title.lower()
    if span["kind"] == "problem":
        return "problem_family"
    if span["kind"] == "equation" or "$$" in lower:
        return "formalization"
    if "example" in lower:
        return "worked_example"
    if (
        "fallac" in lower
        or "pitfall" in lower
        or "counterexample" in lower
        or "limitation" in lower
    ):
        return "adversarial"
    if "trade-off" in lower or "tradeoff" in lower or "trade off" in lower:
        return "boundary_case"
    if "historical" in section_lower:
        return "historical"
    return "canonical"


def _link_seed_knowledge(
    seed_path: Path | None,
    spans: list[dict[str, Any]],
    chapter_summaries: list[dict[str, Any]],
    corpus_version: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if seed_path is None:
        return [], [], []
    if not seed_path.exists():
        raise CorpusBuildError(f"Knowledge seed does not exist: {seed_path}")

    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    concepts = [dict(concept) for concept in seed.get("concepts") or []]
    edges = [dict(edge) for edge in seed.get("edges") or []]
    try:
        validate_concept_graph(concepts, edges)
    except ContractError as error:
        raise CorpusBuildError(f"Invalid seed concept graph: {error}") from error

    section_titles = {
        section["section_id"]: section["title"]
        for chapter in chapter_summaries
        for section in chapter["sections"]
    }
    section_numbers = {
        section["section_id"]: section["number"]
        for chapter in chapter_summaries
        for section in chapter["sections"]
    }
    spans_by_chapter: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for span in spans:
        spans_by_chapter[span["chapter_id"]].append(span)

    links: list[dict[str, Any]] = []
    for concept in concepts:
        terms = [
            str(term).strip().lower()
            for term in concept.pop("match_terms", [])
            if str(term).strip()
        ]
        source_chapters = concept.pop("source_chapters", [])
        preferred_sections = {
            str(number) for number in concept.pop("preferred_sections", [])
        }
        candidates: list[tuple[int, dict[str, Any], list[str]]] = []
        for chapter_id in source_chapters:
            for span in spans_by_chapter.get(chapter_id, []):
                lower = span["text"].lower()
                matched = [term for term in terms if term in lower]
                if not matched:
                    continue
                score = sum(lower.count(term) * max(1, len(term.split())) for term in matched)
                if section_numbers.get(span.get("section_id")) in preferred_sections:
                    score += 12
                if span["kind"] == "heading":
                    score += 2
                candidates.append((score, span, matched))

        candidates.sort(
            key=lambda item: (
                -item[0],
                item[1]["page_index"],
                item[1]["block_index"],
            )
        )
        selected: list[tuple[int, dict[str, Any], list[str]]] = []
        per_page: Counter[str] = Counter()
        for candidate in candidates:
            page_id = candidate[1]["page_id"]
            if per_page[page_id] >= 2:
                continue
            selected.append(candidate)
            per_page[page_id] += 1
            if len(selected) >= 12:
                break

        span_ids: list[str] = []
        for ordinal, (score, span, matched) in enumerate(selected, 1):
            link_id = f"{concept['concept_id']}-source-{ordinal:02d}"
            span_ids.append(span["span_id"])
            links.append(
                {
                    "schema_version": CORPUS_SCHEMA_VERSION,
                    "link_id": link_id,
                    "concept_id": concept["concept_id"],
                    "span_id": span["span_id"],
                    "pedagogical_role": _role_for_link(
                        span, section_titles.get(span.get("section_id"), "")
                    ),
                    "match_terms": matched,
                    "lexical_score": score,
                    "link_method": "reviewable_lexical_seed_v1",
                    "review_status": "proposed",
                }
            )

        concept["schema_version"] = CORPUS_SCHEMA_VERSION
        concept["source_span_ids"] = span_ids
        concept["content_status"] = "extracted"
        concept["graph_status"] = "proposed"
        concept["corpus_version"] = corpus_version
        concept["revision"] = int(concept.get("revision", 1))

    normalized_edges: list[dict[str, Any]] = []
    for ordinal, edge in enumerate(edges, 1):
        normalized_edges.append(
            {
                "schema_version": CORPUS_SCHEMA_VERSION,
                "edge_id": edge.get("edge_id") or f"edge-{ordinal:03d}",
                **edge,
                "review_status": edge.get("review_status", "proposed"),
            }
        )
    return concepts, normalized_edges, links


def _validate_derived_records(
    chapter_summaries: list[dict[str, Any]],
    spans: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    cross_references: list[dict[str, Any]],
    concepts: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    concept_span_links: list[dict[str, Any]],
) -> None:
    def unique_ids(
        rows: Iterable[Mapping[str, Any]], field: str, label: str
    ) -> set[str]:
        values = [str(row.get(field) or "") for row in rows]
        if any(not value for value in values):
            raise CorpusBuildError(f"{label} contains an empty {field}")
        if len(values) != len(set(values)):
            duplicates = [
                value
                for value, count in Counter(values).items()
                if count > 1
            ]
            raise CorpusBuildError(
                f"{label} contains duplicate {field} values: {duplicates[:5]}"
            )
        return set(values)

    page_ids = unique_ids(
        (
            page
            for chapter in chapter_summaries
            for page in chapter["pages"]
        ),
        "page_id",
        "pages",
    )
    section_ids = unique_ids(
        (
            section
            for chapter in chapter_summaries
            for section in chapter["sections"]
        ),
        "section_id",
        "sections",
    )
    span_ids = unique_ids(spans, "span_id", "source spans")
    asset_ids = unique_ids(assets, "asset_id", "assets")
    entity_ids = unique_ids(entities, "entity_id", "entities")
    reference_ids = unique_ids(
        cross_references, "reference_id", "cross references"
    )
    concept_ids = unique_ids(concepts, "concept_id", "concepts") if concepts else set()
    if edges:
        unique_ids(edges, "edge_id", "concept edges")
    if concept_span_links:
        unique_ids(concept_span_links, "link_id", "concept-span links")

    for span in spans:
        if span["page_id"] not in page_ids:
            raise CorpusBuildError(
                f"{span['span_id']} references unknown page {span['page_id']}"
            )
        if span.get("section_id") and span["section_id"] not in section_ids:
            raise CorpusBuildError(
                f"{span['span_id']} references unknown section "
                f"{span['section_id']}"
            )
        if span["source_asset_id"] not in asset_ids:
            raise CorpusBuildError(
                f"{span['span_id']} references unknown source asset "
                f"{span['source_asset_id']}"
            )
        if int(span["char_start"]) >= int(span["char_end"]):
            raise CorpusBuildError(
                f"{span['span_id']} has an invalid character range"
            )
        if _sha256_bytes(span["text"].encode("utf-8")) != span["content_sha256"]:
            raise CorpusBuildError(f"{span['span_id']} has an invalid content hash")

    resolvable_ids = asset_ids | entity_ids | section_ids
    for reference in cross_references:
        if reference["from_span_id"] not in span_ids:
            raise CorpusBuildError(
                f"{reference['reference_id']} starts at an unknown span"
            )
        if reference["resolution"] == "resolved":
            if reference.get("to_id") not in resolvable_ids:
                raise CorpusBuildError(
                    f"{reference['reference_id']} resolves to an unknown target"
                )
        elif reference.get("to_id") is not None:
            raise CorpusBuildError(
                f"{reference['reference_id']} is unresolved but has a target"
            )

    for link in concept_span_links:
        if link["concept_id"] not in concept_ids:
            raise CorpusBuildError(
                f"{link['link_id']} references unknown concept "
                f"{link['concept_id']}"
            )
        if link["span_id"] not in span_ids:
            raise CorpusBuildError(
                f"{link['link_id']} references unknown span {link['span_id']}"
            )

    # The graph has already been validated before enrichment, but re-run it on
    # the normalized records to guard against transformation mistakes.
    try:
        validate_concept_graph(concepts, edges)
    except ContractError as error:
        raise CorpusBuildError(f"Normalized concept graph is invalid: {error}") from error


def build_corpus(
    archive_path: str | Path,
    output_dir: str | Path,
    *,
    corpus_version: str,
    knowledge_seed_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build and validate normalized corpus artifacts.

    Existing individual output files are atomically replaced, but source files
    and unrelated files in the destination are never deleted.
    """

    archive_path = Path(archive_path).resolve()
    output_dir = Path(output_dir).resolve()
    seed_path = (
        Path(knowledge_seed_path).resolve() if knowledge_seed_path else None
    )
    if not archive_path.is_file():
        raise CorpusBuildError(f"Archive does not exist: {archive_path}")
    if not corpus_version.strip():
        raise CorpusBuildError("corpus_version must not be empty")

    archive_sha256 = _sha256_file(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise CorpusBuildError(f"CRC failure in archive member: {bad_member}")
        member_names = _validate_archive_members(archive)
        chapter_numbers = _discover_chapters(member_names)

        normalized = [
            _normalize_chapter(
                archive,
                member_names,
                archive_sha256,
                chapter_number,
                corpus_version,
            )
            for chapter_number in chapter_numbers
        ]

    chapter_summaries = [chapter["summary"] for chapter in normalized]
    spans = [
        span for chapter in normalized for span in chapter["spans"]
    ]
    assets = [
        asset for chapter in normalized for asset in chapter["assets"]
    ]
    entities = [
        entity for chapter in normalized for entity in chapter["entities"]
    ]
    warnings = [
        warning for chapter in normalized for warning in chapter["warnings"]
    ]
    cross_references = _build_cross_references(
        spans, assets, entities, chapter_summaries
    )
    concepts, edges, concept_span_links = _link_seed_knowledge(
        seed_path, spans, chapter_summaries, corpus_version
    )
    _validate_derived_records(
        chapter_summaries,
        spans,
        assets,
        entities,
        cross_references,
        concepts,
        edges,
        concept_span_links,
    )

    unresolved = sum(
        reference["resolution"] == "unresolved"
        for reference in cross_references
    )
    manifest = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "corpus_version": corpus_version,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "archive_filename": archive_path.name,
            "archive_sha256": archive_sha256,
            "archive_size_bytes": archive_path.stat().st_size,
            "storage_policy": "private_source_not_for_client_delivery",
        },
        "chapters": chapter_summaries,
        "counts": {
            "chapters": len(chapter_summaries),
            "pages": sum(chapter["counts"]["pages"] for chapter in chapter_summaries),
            "sections": sum(
                chapter["counts"]["sections"] for chapter in chapter_summaries
            ),
            "source_spans": len(spans),
            "assets": len(assets),
            "entities": len(entities),
            "cross_references": len(cross_references),
            "unresolved_cross_references": unresolved,
            "concepts": len(concepts),
            "concept_edges": len(edges),
            "concept_span_links": len(concept_span_links),
        },
        "warnings": warnings,
        "artifacts": {
            "source_spans": "source_spans.jsonl",
            "assets": "assets.jsonl",
            "entities": "entities.jsonl",
            "cross_references": "cross_references.jsonl",
            "concepts": "concepts.jsonl",
            "concept_edges": "concept_edges.jsonl",
            "concept_span_links": "concept_span_links.jsonl",
            "validation_report": "validation_report.json",
        },
    }

    validation_report = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "corpus_version": corpus_version,
        "status": "pass" if not warnings else "pass_with_warnings",
        "checks": {
            "archive_crc": "pass",
            "archive_paths_safe": "pass",
            "chapter_json_valid": "pass",
            "page_indices_contiguous": "pass",
            "page_images_present": "pass",
            "figure_crops_present": "pass",
            "raw_page_checkpoints_present": "pass",
            "stable_ids_unique": "pass",
            "derived_referential_integrity": "pass",
            "source_span_hashes": "pass",
            "hard_prerequisite_graph_acyclic": "pass",
        },
        "review_boundaries": {
            "concept_links": "proposed_links_require_human_review",
            "concept_graph": "proposed_edges_require_human_review",
            "figure_content_types": "unclassified",
            "visual_name_leakage": "unchecked",
            "content_readiness": "no_concept_is_automatically_content_ready",
        },
        "metrics": {
            "warnings": len(warnings),
            "resolved_cross_references": len(cross_references) - unresolved,
            "unresolved_cross_references": unresolved,
            "pages_needing_review": sum(
                chapter["counts"]["needs_review_pages"]
                for chapter in chapter_summaries
            ),
            "concepts_without_source_links": sum(
                not concept["source_span_ids"] for concept in concepts
            ),
        },
        "warnings": warnings,
    }

    _write_jsonl(output_dir / "source_spans.jsonl", spans)
    _write_jsonl(output_dir / "assets.jsonl", assets)
    _write_jsonl(output_dir / "entities.jsonl", entities)
    _write_jsonl(output_dir / "cross_references.jsonl", cross_references)
    _write_jsonl(output_dir / "concepts.jsonl", concepts)
    _write_jsonl(output_dir / "concept_edges.jsonl", edges)
    _write_jsonl(output_dir / "concept_span_links.jsonl", concept_span_links)
    _write_json(output_dir / "validation_report.json", validation_report)
    _write_json(output_dir / "manifest.json", manifest)
    return manifest
