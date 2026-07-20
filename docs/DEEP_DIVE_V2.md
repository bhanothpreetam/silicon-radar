# Deep Dive v2 content contract

The v2 Read more experience is an annotated research brief: the causal density
of paid semiconductor analysis, with the prerequisite support of a strong
architecture mentor. It is not a longer summary.

## Reader model

The reader knows undergraduate CS/ECE foundations and wants to develop the
judgment of a computer architect and systems researcher. They learn best when a
piece:

- derives behavior from mechanisms rather than labels;
- fills prerequisite gaps without replacing rigor with childish analogies;
- traces a choice across hardware, software, deployment, and economics;
- identifies bottlenecks, workload assumptions, and shifted constraints;
- explains historical evolution as a response to real design pressure;
- distinguishes evidence from inference;
- ends with research questions and adjacent material worth studying.

## Reference patterns

The initial editorial references define five useful patterns:

1. **Vertical co-design:** follow a system from silicon and numeric formats
   through memory, SerDes, networking, packaging, power, cooling, assembly, and
   total cost.
2. **Device-to-workload reasoning:** begin with the physical mechanism, derive
   latency/bandwidth/endurance behavior, then evaluate where it belongs in an AI
   memory hierarchy.
3. **Workload-to-datacenter reasoning:** start with agent or RL execution
   behavior, show why CPU pressure appears, then follow offload opportunities
   into SmartNICs, DPUs, and heterogeneous systems.
4. **Hidden economic constraint:** explain why an apparently inferior design can
   become strategically valuable when packaging capacity or availability is the
   governing bottleneck.
5. **Metric interrogation:** define local and global views formally, connect them
   algebraically, work a numerical example, explain selection bias in the
   hierarchy, and then use adversarial whiteboard questions to reveal where each
   metric stops being sufficient.

The fifth pattern comes from the user-provided Bits'nBrews article “Global Miss
Rate vs Local Miss Rate.” Its strongest teaching move is not the definition. It
is showing that the L2 sees a filtered, harder request distribution, then asking
how inclusion, heterogeneous cores, and inaccurate prefetching complicate the
apparently clean metric.

## Output layers

One Gemini call produces both:

- the existing compact fields used by Telegram and the card face; and
- a `deep_dive` JSON object used only by the Mini App's expanded reader.

RSS collection chooses the longest body exposed by the feed rather than taking
the summary first, strips feed HTML, and retains up to 40,000 characters.
YouTube transcripts use the same larger source budget. This improves depth
without adding Gemini requests. Sources that expose only an excerpt, and ArXiv
items where only the abstract is collected, must still declare that evidence
boundary instead of pretending the complete work was analyzed.

The deep dive contains:

- thesis and evidence boundary;
- source-grounded evidence;
- expandable prerequisites;
- a causal sequence of narrative sections;
- worked reasoning or calculations when evidence permits;
- cross-layer system consequences;
- architect's tradeoffs and break conditions;
- historical evolution and industry positioning;
- research frontier and open questions;
- aha insights, misconceptions, and whiteboard challenges;
- takeaways and an exploration path.

Sections are conditional. Sparse source material must produce a shorter brief
with an explicit limitation rather than padded prose or invented facts.

## Grounding rules

- Preserve useful numbers and state whether they are confirmed, claimed,
  reported, or inferred.
- Do not invent specifications, benchmarks, paper titles, URLs, or quotations.
- A strong thesis does not erase uncertainty. Confidence and source limitations
  are visible at the top of the brief.
- Research references must be real and relevant. When bibliographic detail is
  uncertain, provide a safe search direction instead of a fabricated citation.
- Historical context is included only when it explains why the present design
  exists.

## Activation

The experiment defaults to v1. To activate v2:

1. Apply [`docs/sql/2026-07-21_deep_dive_v2.sql`](sql/2026-07-21_deep_dive_v2.sql)
   in the Supabase SQL editor.
2. Set `INTELLIGENCE_PROMPT_VERSION=v2` in the pipeline environment.
3. Run a small manual batch and review output quality before changing scheduled
   workflows.

The Mini App is backward-compatible. Cards without `deep_dive` retain the legacy
expanded layout.

Branch previews can append `?demo=deep` to load the static Bits'nBrews-derived
reference card. Demo mode makes no Supabase reads or feedback writes and exists
only so the long-form reader can be reviewed before the migration and first v2
generation run.

Append `?demo=actual` to load the bounded real-source evaluation set created by
`scripts/generate_v2_preview.py`. The generator reads explicitly selected
`raw_items`, permits at most three model calls, and writes only a local static
fixture. It never inserts cards, logs notifications, or saves feedback.
