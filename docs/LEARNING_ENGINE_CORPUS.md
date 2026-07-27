# Radar Learning Engine — Corpus Foundation

This is the first implementation slice of the mystery-first learning engine
described in [`radar-flow.md`](../radar-flow.md). It is deliberately isolated
from the production news pipeline and Mini App.

## What exists

The corpus builder consumes the private Hennessy & Patterson extraction ZIP
without unpacking it:

```bash
python3 scripts/build_learning_corpus.py chapter_2_3_zipped.zip
```

The default build is written to the ignored directory
`corpus/build/hp7-v0.1/`. The original ZIP and the build output must remain
private; neither belongs in the public Mini App bundle.

The build creates:

| Artifact | Role |
|---|---|
| `manifest.json` | Corpus version, source hash, chapter/page inventory, and counts |
| `source_spans.jsonl` | Exact page-level semantic blocks with offsets and provenance |
| `assets.jsonl` | Logical page/figure IDs pointing into the source ZIP |
| `entities.jsonl` | Equations, tables, examples, problems, and references |
| `cross_references.jsonl` | Resolved or explicitly unresolved Figure/Table/Section references |
| `concepts.jsonl` | Proposed Phase 0 concept nodes |
| `concept_edges.jsonl` | Proposed typed prerequisite and Bridge edges |
| `concept_span_links.jsonl` | Reviewable lexical links from concepts to source evidence |
| `validation_report.json` | Machine checks and the remaining human-review boundaries |

Every derived record is replaceable. The archive SHA-256 and exact archive
member identify the immutable source.

## Trust boundary

The builder automates structural facts:

- archive integrity and safe paths;
- page coverage;
- referenced page and figure assets;
- stable IDs;
- exact span hashes and offsets;
- graph endpoint and cycle validation;
- conservative textual cross-reference resolution.

It does **not** automatically approve:

- concept granularity;
- prerequisite rationale;
- pedagogical source roles;
- figure semantic types;
- name leakage;
- content readiness.

Seed concepts and lexical source links stay `proposed`/`extracted`. A later
review tool must approve graph edges and source roles before the mystery
compiler may use them.

## Layer boundaries

```text
chapter_2_3_zipped.zip
        │ private, immutable source
        ▼
corpus builder
        │ reproducible structural normalization
        ▼
source spans + entities + assets
        │ reviewed enrichment
        ▼
concept graph + role-tagged source packs
        │ case authoring/compiler
        ▼
CaseBundle
        │ runtime observations
        ▼
AttemptEvent stream + learner state
```

The runtime contract intentionally separates `pre_reveal` from `reveal`.
Production endpoints must deliver them separately. Hiding an answer in the DOM
or CSS is not acceptable because it still sends the answer to the learner's
device before it is earned.

The canonical JSON Schema is
[`learning-engine.schema.json`](../learning_engine/schemas/learning-engine.schema.json).
Python invariant checks live in `learning_engine/contracts.py`.

## Adding later chapters

The builder discovers every `chapter_N/chapter.json` in the archive. Future
extractions can therefore use the same command after updating the private ZIP.
Assign a new immutable `--corpus-version`; do not silently rebuild a released
version from different source bytes.

Before expanding the full book, the next implementation slice should review
the current 16-node graph and author two complete cases:

1. local versus global miss rate as a Frontier mystery;
2. nonblocking caches ↔ dynamic scheduling as a cross-layer Bridge.

Those two cases exercise quantitative reasoning, misleading metrics,
cross-chapter retrieval, source grounding, and the title-reveal boundary.
