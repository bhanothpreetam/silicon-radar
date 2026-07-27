#!/usr/bin/env python3

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from learning_engine.contracts import (
    ContractError,
    validate_case_bundle,
    validate_concept_graph,
)
from learning_engine.corpus import CorpusBuildError, build_corpus


def _chapter_fixture() -> dict:
    return {
        "book": "hp7",
        "chapter": 2,
        "title": "Memory Hierarchy Design",
        "source_note": "test fixture",
        "sections": [
            {
                "number": "2.1",
                "title": "Introduction",
                "page_start": 94,
                "page_index_start": 1,
                "page_end": 94,
                "page_index_end": 1,
                "text": "Locality makes a hierarchy useful.",
                "equations": [],
                "subsections": [],
            }
        ],
        "figures": [
            {
                "label": "Figure 2.1",
                "caption": "A hierarchy.",
                "page": 94,
                "page_index": 1,
                "image": "figures/figure-2-1.png",
                "description": "Blocks at several levels.",
                "bbox_pct": {"x": 1, "y": 2, "w": 3, "h": 4},
            }
        ],
        "tables": [],
        "examples": [],
        "problems": [],
        "references": [],
        "pages": [
            {
                "n": 1,
                "book_page": 94,
                "image": "pages/page-001.jpg",
                "confidence": "high",
                "needs_review": False,
                "notes": "",
                "book_page_inferred": False,
            }
        ],
    }


def _raw_page_fixture() -> dict:
    return {
        "book_page": 94,
        "running_header": "Chapter Two",
        "page_kind": "body",
        "full_text": (
            "## 2.1 Introduction\n\n"
            "Locality makes a hierarchy useful. See Figure 2.1."
        ),
        "section_headings": [{"number": "2.1", "title": "Introduction"}],
        "equations": [],
        "tables": [],
        "figures": [],
        "examples": [],
        "problems": [],
        "references": [],
        "confidence": "high",
        "needs_review": False,
        "notes": "",
        "_page_index": 1,
        "_image": "pages/page-001.jpg",
        "_source_image_complete": True,
    }


class CorpusBuilderTests(unittest.TestCase):
    def _make_archive(self, root: Path, *, unsafe: bool = False) -> Path:
        archive_path = root / "corpus.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(
                "chapter_2/chapter.json", json.dumps(_chapter_fixture())
            )
            archive.writestr(
                "chapter_2/work/manifest.json",
                json.dumps(
                    [
                        {
                            "n": 1,
                            "width": 3000,
                            "height": 4000,
                            "complete_image": True,
                        }
                    ]
                ),
            )
            archive.writestr(
                "chapter_2/work/page-001.json",
                json.dumps(_raw_page_fixture()),
            )
            archive.writestr("chapter_2/pages/page-001.jpg", b"page")
            archive.writestr("chapter_2/figures/figure-2-1.png", b"figure")
            if unsafe:
                archive.writestr("../escape.txt", b"unsafe")
        return archive_path

    def test_builds_traceable_spans_without_unpacking_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self._make_archive(root)
            output = root / "build"
            manifest = build_corpus(
                archive,
                output,
                corpus_version="test-v1",
                knowledge_seed_path=None,
            )

            self.assertEqual(manifest["counts"]["chapters"], 1)
            self.assertEqual(manifest["counts"]["pages"], 1)
            self.assertEqual(manifest["counts"]["source_spans"], 2)
            self.assertEqual(manifest["counts"]["cross_references"], 1)
            self.assertEqual(
                manifest["counts"]["unresolved_cross_references"], 0
            )
            spans = [
                json.loads(line)
                for line in (output / "source_spans.jsonl").read_text().splitlines()
            ]
            self.assertEqual(spans[0]["span_id"], "hp7-ch02-p001-span-001")
            self.assertEqual(
                spans[1]["text"],
                "Locality makes a hierarchy useful. See Figure 2.1.",
            )
            self.assertFalse((output / "pages").exists())

    def test_rejects_archive_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self._make_archive(root, unsafe=True)
            with self.assertRaisesRegex(CorpusBuildError, "Unsafe archive path"):
                build_corpus(
                    archive,
                    root / "build",
                    corpus_version="test-v1",
                    knowledge_seed_path=None,
                )


class ContractTests(unittest.TestCase):
    def test_hard_prerequisite_cycle_is_rejected(self):
        concepts = [{"concept_id": "a"}, {"concept_id": "b"}]
        edges = [
            {
                "from_concept_id": "a",
                "to_concept_id": "b",
                "edge_type": "hard_requires",
                "rationale": "a needs b",
            },
            {
                "from_concept_id": "b",
                "to_concept_id": "a",
                "edge_type": "hard_requires",
                "rationale": "b needs a",
            },
        ]
        with self.assertRaisesRegex(ContractError, "Cycle"):
            validate_concept_graph(concepts, edges)

    def test_case_pre_reveal_cannot_contain_answer(self):
        bundle = {
            "case_id": "case-1",
            "case_revision": 1,
            "concept_id": "concept-1",
            "experience_type": "frontier",
            "corpus_version": "test-v1",
            "pre_reveal": {"canonical_name": "The answer"},
            "reveal": {
                "canonical_name": "The answer",
                "formalization": {},
            },
            "evaluation": {},
            "claim_ledger": [
                {
                    "claim_id": "claim-1",
                    "source_span_ids": ["span-1"],
                }
            ],
        }
        with self.assertRaisesRegex(ContractError, "pre_reveal"):
            validate_case_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
