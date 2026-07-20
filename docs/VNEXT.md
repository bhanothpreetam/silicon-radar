# Silicon Radar vNext

This branch is the experimentation lane for improving Silicon Radar without
changing the production version on `main`.

## Product direction

Silicon Radar should become a decision-quality learning system, not simply a
larger news feed. The next version should make three loops progressively better:

1. **Triage** — surface the few signals that deserve attention now.
2. **Understanding** — connect news to durable semiconductor and architecture
   mental models.
3. **Taste** — learn which topics, source styles, and depths consistently repay
   the user's attention.

## First experimental slice: feed lenses

The Mini App now exposes four views over the same fetched card set:

- **All** preserves the existing feed and remains the default.
- **Priority** contains `wake_up` and `brief` cards.
- **Learn** isolates daily concept cards.
- **Trial** isolates probation-source auditions where reactions directly affect
  source promotion.

This slice is intentionally frontend-only. It adds no Supabase tables, makes no
additional API calls, and does not change collection, scoring, notification, or
probation behavior. Card age is also visible beside the source so users can
distinguish a new signal from backlog at a glance.

## Guardrails

- `main` remains the production branch.
- Experiments live on `experiment/vnext` until explicitly promoted.
- No schema change is assumed to be deployed. Schema-dependent ideas require a
  separate SQL handoff and confirmation before code relies on them.
- Touch and scroll work must be tested with CDP `Input.dispatchTouchEvent`, not
  synthetic DOM touch events.
- Sparse reactions are normal. Silence is not a negative preference signal.
- Gemini daily quota is scarce and server-enforced per key; features should not
  add model calls unless their expected information gain justifies the cost.

## Candidate next slices

### 1. Personal ranking without extra Gemini calls

Compute a deterministic taste-alignment score from existing `tech_layer`,
importance, recency, and reactions. Show it as an optional “For me” lens before
using it to change notifications.

### 2. Confluence detection

Cluster independent cards about the same event within 48 hours and synthesize a
single story only when three or more credible sources converge. This spends one
Gemini call to replace several redundant cards, rather than increasing call
volume.

### 3. Reading state

Track viewed cards locally first. Validate that “unread” is useful before adding
a database table or cross-device state.

### 4. Source observability

Add a compact weekly report for source yield: scraped, card-worthy, pushed,
reacted, and quota cost. This makes probation decisions inspectable instead of
opaque.

### 5. Evaluation fixtures

Build a small checked-in corpus of representative raw items and expected card
properties. Prompt changes should be compared against that corpus before being
promoted, with model calls run manually to protect quota.

## Verification

Run the browser smoke test from the repository root:

```bash
python3 tests/miniapp_vnext_smoke.py
```

It mocks Supabase, checks lens counts and filtering, expands a card, performs a
real horizontal touch swipe, and verifies that a vertical touch scrolls the card
brief natively.
