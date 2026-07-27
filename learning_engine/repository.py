"""Read-only access to a built learning corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RepositoryError(ValueError):
    """Raised when a corpus build is absent or internally inconsistent."""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise RepositoryError(f"Corpus artifact is missing: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise RepositoryError(
                    f"Invalid JSON on {path.name}:{line_number}: {error}"
                ) from error
    return rows


class CorpusRepository:
    """Indexes normalized JSONL artifacts without mutating the corpus build."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        manifest_path = self.root / "manifest.json"
        if not manifest_path.exists():
            raise RepositoryError(
                f"Corpus manifest is missing: {manifest_path}. "
                "Run scripts/build_learning_corpus.py first."
            )
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.corpus_version = str(self.manifest["corpus_version"])

        self.concepts = _read_jsonl(self.root / "concepts.jsonl")
        self.edges = _read_jsonl(self.root / "concept_edges.jsonl")
        self.spans = _read_jsonl(self.root / "source_spans.jsonl")
        self.links = _read_jsonl(self.root / "concept_span_links.jsonl")
        self.assets = _read_jsonl(self.root / "assets.jsonl")
        self.entities = _read_jsonl(self.root / "entities.jsonl")

        self.concept_by_id = {
            concept["concept_id"]: concept for concept in self.concepts
        }
        self.span_by_id = {span["span_id"]: span for span in self.spans}
        self.asset_by_id = {asset["asset_id"]: asset for asset in self.assets}
        self.entity_by_id = {
            entity["entity_id"]: entity for entity in self.entities
        }

        self.links_by_concept: dict[str, list[dict[str, Any]]] = {
            concept_id: [] for concept_id in self.concept_by_id
        }
        for link in self.links:
            self.links_by_concept.setdefault(link["concept_id"], []).append(link)

        self.edges_from: dict[str, list[dict[str, Any]]] = {
            concept_id: [] for concept_id in self.concept_by_id
        }
        self.edges_to: dict[str, list[dict[str, Any]]] = {
            concept_id: [] for concept_id in self.concept_by_id
        }
        for edge in self.edges:
            self.edges_from.setdefault(edge["from_concept_id"], []).append(edge)
            self.edges_to.setdefault(edge["to_concept_id"], []).append(edge)

    def concept(self, concept_id: str) -> dict[str, Any]:
        try:
            return self.concept_by_id[concept_id]
        except KeyError as error:
            raise RepositoryError(f"Unknown concept: {concept_id}") from error

    def hard_prerequisites(self, concept_id: str) -> list[str]:
        return [
            edge["to_concept_id"]
            for edge in self.edges_from.get(concept_id, [])
            if edge["edge_type"] == "hard_requires"
        ]

    def concept_links(self, concept_id: str) -> list[dict[str, Any]]:
        return list(self.links_by_concept.get(concept_id, []))

    def neighboring_edges(self, concept_id: str) -> list[dict[str, Any]]:
        return list(self.edges_from.get(concept_id, [])) + list(
            self.edges_to.get(concept_id, [])
        )
