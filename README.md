# Silicon Radar

Silicon Radar is a personal intelligence and learning system for the
semiconductor and AI-hardware industry. It collects material from trusted and
probationary sources, turns high-signal items into analyst-grade intelligence
cards with Gemini, and delivers them through Telegram and a swipeable Telegram
Mini App.

The goal is not to summarize more news. It is to explain what changed, why it
matters technically and strategically, what durable concept it connects to, and
what deserves attention next.

## System overview

```text
RSS / X / YouTube
        │
        ▼
raw_items ──► Gemini card generation ──► intelligence_cards
                                                │
                          ┌─────────────────────┴─────────────────────┐
                          ▼                                           ▼
                 Telegram notifications                    Telegram Mini App

Trusted-source citations ──► discovery ──► probation ──► reactions ──► verdict
```

Three production layers share Supabase as their data store:

- **Pipeline:** collects, deduplicates, scores, generates, and notifies.
- **Discovery and probation:** finds sources through search and citation edges,
  auditions them, and uses explicit reactions to graduate, shelve, or blacklist
  them.
- **Mini App:** a static HTML/CSS/JavaScript reader that fetches cards directly
  from Supabase and runs inside Telegram.

## What is live

- Two-hourly quick pipeline through GitHub Actions
- RSS, X/Twitter, and YouTube collection
- Gemini key rotation across a configured key list
- Telegram push notifications with four feedback reactions
- Daily digest and concept-learning card
- Weekly industry map
- Search-based and citation-graph source discovery
- Probation promotion and evaluation
- Swipeable, expandable Mini App

The interactive polling bot commands exist, but they need a persistent host with
working access to Telegram's network. One-shot production notifications run from
GitHub Actions and are unaffected by the local ISP limitation documented in the
project handoff.

## Mini App

The production app on `main` is the stable single-feed reader. The
`experiment/vnext` branch adds frontend-only feed lenses:

- **All** — the unchanged default feed
- **Priority** — `wake_up` and `brief` signals
- **Learn** — concept-learning cards
- **Trial** — probation-source auditions

See [docs/VNEXT.md](docs/VNEXT.md) for the experiment guardrails and roadmap.

## Configuration

Python 3.11 or newer is recommended. Copy `.env.example` to `.env` and configure:

```dotenv
GEMINI_API_KEYS=key1,key2,key3
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_key
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TWITTER_USERNAME=your_x_username
TWITTER_COOKIES=auth_token=...; ct0=...
```

`GEMINI_API_KEY` is supported as a single-key fallback. The observed Gemini 2.5
Flash free-tier quota is 20 requests per day per key, which is why key rotation
and quota-conscious source evaluation are core design constraints.

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Running the system

The main entry point is `scripts/run_pipeline.py`:

```bash
python3 scripts/run_pipeline.py quick      # production-style frequent run
python3 scripts/run_pipeline.py collect    # collect all configured sources
python3 scripts/run_pipeline.py process    # generate cards for queued items
python3 scripts/run_pipeline.py notify     # send pending notifications
python3 scripts/run_pipeline.py digest     # daily digest
python3 scripts/run_pipeline.py learn      # one concept-learning card
python3 scripts/run_pipeline.py map        # weekly industry synthesis
python3 scripts/run_pipeline.py promote    # probation promotion/evaluation
python3 scripts/run_pipeline.py bot        # persistent interactive bot
```

Discovery has separate wrappers:

```bash
python3 scripts/run_discovery.py
python3 scripts/run_citations.py
python3 scripts/send_discovery_digest.py
```

## Testing the vNext Mini App

The browser smoke test mocks Supabase, loads the static app at a mobile viewport,
checks filtering and expansion, and uses Chrome DevTools Protocol touch input to
verify horizontal swipe and native vertical scrolling:

```bash
python3 tests/miniapp_vnext_smoke.py
```

It requires Python Playwright and its Chromium browser. The production Mini App
has no build step.

## Project map

```text
app/             configuration
collectors/      RSS, X/Twitter, and YouTube ingestion
db/              Supabase REST access and bootstrap schema
intelligence/    discovery, citation graph, learning, and probation
miniapp/         static Telegram Mini App
notifications/   Telegram formatting, delivery, feedback, and commands
processing/      relevance, deduplication, Gemini generation, scoring
prompts/         intelligence-card and concept-card prompts
scripts/         pipeline and discovery entry points
.github/         scheduled production workflows
```

## Important operating constraints

- Supabase access uses REST rather than direct Postgres connections.
- The Mini App currently embeds the anon key and production tables currently
  have no RLS. This is a deliberately accepted tradeoff, not an accidental
  omission. Enabling RLS requires coordinating backend credentials and policies
  so the pipeline is not broken.
- Explicit feedback is sparse. Silence must not be interpreted as dislike.
- Main Twitter source lists are currently configured in Python; probationary X
  and YouTube sources are database-driven.
- Database changes are applied manually through the Supabase SQL editor. There
  is no migration framework to assume.
- Prompt edits to `intelligence_card_v1.txt` must escape literal braces because
  the template is rendered with Python `.format()`.

## Scheduled workflows

- `pipeline.yml` — quick pipeline every two hours
- `digest.yml` — daily digest and learning track
- `weekly.yml` — weekly industry map
- `discovery.yml` — weekly discovery, citation mining, digest, and promotion

The production Vercel project deploys from `main`. Experimental branches do not
change the live Mini App unless they are explicitly promoted.
