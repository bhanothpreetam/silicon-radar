# Radar Learning Engine — First Runtime Slice

The runtime is isolated from the current Mini App. It turns the normalized
private corpus into a prerequisite-gated, mystery-first experience without
altering the production feed.

## Implemented flow

```text
concept graph + learner state
        ↓
hard-prerequisite eligibility
        ↓
persistent random shuffle bag
        ↓
bounded private source pack
        ↓
concept-sensitive mystery compiler
        ↓
structural + grounding + leakage gates
        ↓
pre-reveal payload ── learner commitments ── reveal payload
        ↓
immutable attempt events
```

Important distinctions:

- Authoring may prepare future cases ahead of time.
- Delivery may draw only cases the learner has legally unlocked.
- Randomness operates after prerequisite and case-readiness gates.
- A concept needs demonstrated delayed retrieval, not exposure, before it
  unlocks a dependant.
- The article about local/global miss rate is a quality regression reference,
  not a case template or preferred concept.

## Build and inspect source packs

Build the corpus:

```bash
python3 scripts/build_learning_corpus.py chapter_2_3_zipped.zip
```

Exercise random selection and source-pack assembly without any external model
call:

```bash
python3 scripts/prepare_learning_cases.py --dry-run --count 3
```

For a fresh learner, the current graph exposes three roots:

- temporal/spatial locality;
- instruction pipelining and overlap;
- paged virtual-memory translation.

Their order is randomized and persisted. Advanced concepts remain locked.

## External-generation privacy boundary

Generating a real case with the current Gemini compiler sends a bounded private
source pack to Google:

- at most 12 selected source spans;
- currently approximately 6–9k source characters for a root concept;
- relevant normalized equation/table/example metadata where present;
- the private concept name and graph relationships.

It does not send page scans, full chapters, Supabase records, Telegram data, or
learner history.

Because the excerpts originate from a private textbook corpus, perform the real
generation call only with explicit authorization. The dry-run pipeline, graph,
selection, validation, UI, and synthetic browser test require no such transfer.

## Preview interface

After at least one real case has been generated:

```bash
python3 -m http.server 8090 --directory learning_lab
```

Then open `http://localhost:8090`.

The browser initially fetches only `pre.json`. It records hypotheses,
confidence, hints, evidence-driven revisions, the invented mechanism, transfer
responses, and completion as attempt events in local storage. `reveal.json` is
not requested until the learner commits at the design gate.

The generated cases, evaluator payloads, source packs, and learner/deck state
are ignored by Git.

## Validation

Run deterministic Python tests:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Run the synthetic browser test:

```bash
python3 tests/learning_lab_smoke.py
```

The browser test verifies:

- the answer is absent before reveal;
- the reveal file is not fetched early;
- the learner must submit an opening hypothesis;
- all evidence beats require a response;
- the design gate precedes the title;
- attempt events are recorded in sequence.

## Not implemented yet

- human graph/source-link review interface;
- free-form causal evaluation against reasoning atoms;
- misconception-dependent repair branching;
- Cold Probe and Bridge renderers;
- persistent server-side learner state;
- Supabase schema and production APIs;
- nightly compilation and public deployment.

Those should follow only after the first generated cases pass human review for
technical accuracy, mystery solvability, authored voice, question timing,
transfer quality, and research depth.
