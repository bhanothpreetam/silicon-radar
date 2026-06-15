# Silicon Radar v0

> A personal semiconductor & AI hardware intelligence radar.
> Converts industry chaos into mental models — delivered to your phone.

Every notification answers: **What happened? Why does it technically matter? Why does it strategically matter? What should a new CS/ECE grad understand from this? What textbook concept does this connect to? What's the rabbit hole?**

---

## What it does

- Pulls from 14 free sources: Semiconductor Engineering, Chips & Cheese, ArXiv cs.AR, HN, Reddit r/chipdesign, NVIDIA/AMD/Intel blogs, and more
- Sends 3 levels of Telegram alerts: 🚨 Wake-up (major events), 📡 Brief (important), 💬 Ping (interesting)
- Generates teaching cards with ELI-new-grad explanations, textbook bridges, flashcards, quiz questions
- Morning digest at 9 AM, with `/quiz`, `/rabbit`, `/flashcards` commands
- All **free** — uses Gemini 2.5 Flash API (1,500 req/day free tier)

---

## Setup (takes about 30 minutes)

### Step 1 — Get your Gemini API key (5 minutes)

1. Go to https://aistudio.google.com/apikey
2. Click "Create API Key"
3. Copy the key — it looks like `AIzaSy...`

> This is separate from your Google One / Gemini Pro subscription.
> The API key accesses Gemini 2.5 Flash for free (1,500 requests/day, no credit card).

### Step 2 — Create a Supabase database (5 minutes)

1. Go to https://supabase.com and sign up (free)
2. Click "New Project", give it a name like `silicon-radar`
3. Wait for it to deploy (~2 minutes)
4. Go to **Settings → API** and copy:
   - Project URL (looks like `https://abc123.supabase.co`)
   - `anon` public key
5. Go to **Settings → Database → Connection String** and copy the URI format

### Step 3 — Set up the database schema (2 minutes)

1. In Supabase, go to the **SQL Editor**
2. Paste the contents of `db/schema.sql`
3. Click "Run"

You should see tables created: `sources`, `raw_items`, `intelligence_cards`, `topics`, etc.

### Step 4 — Create your Telegram bot (5 minutes)

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Follow the prompts (name it "Silicon Radar" or anything you like)
4. Copy the token it gives you (looks like `1234567890:AAF...`)
5. To get your Chat ID:
   - Search for `@userinfobot` on Telegram
   - It will reply with your user ID number

### Step 5 — Configure the project (2 minutes)

```bash
git clone <this-repo>
cd silicon-radar

# Copy the environment template
cp .env.example .env

# Edit .env and fill in your four values:
# GEMINI_API_KEY, DATABASE_URL, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
nano .env   # or use any text editor
```

### Step 6 — Install Python dependencies (2 minutes)

```bash
# Requires Python 3.11+
pip install -r requirements.txt
```

### Step 7 — Test it works (5 minutes)

```bash
# Load your .env
export $(cat .env | xargs)

# Test 1: Run the collector (should pull ~100 items first run)
python scripts/run_pipeline.py collect

# Test 2: Generate intelligence cards for 5 items (uses Gemini API)
python scripts/run_pipeline.py process

# Test 3: Push pending notifications to your Telegram
python scripts/run_pipeline.py notify

# Start the interactive bot (handles /digest, /quiz, etc.)
python scripts/run_pipeline.py bot
```

Your Telegram should receive notifications within a minute of step 3. If it's silent, check:
- `TELEGRAM_CHAT_ID` — must be your personal ID, not the bot's ID
- `TELEGRAM_TOKEN` — must include the number prefix like `1234567890:AAF...`

---

## Running on a schedule

### Option A — Your laptop (simplest)

Add to crontab (`crontab -e`):

```
# Run the full pipeline every 30 minutes
*/30 * * * * cd /path/to/silicon-radar && export $(cat .env | xargs) && python scripts/run_pipeline.py all >> logs/pipeline.log 2>&1

# Send morning digest at 9 AM
0 9 * * * cd /path/to/silicon-radar && export $(cat .env | xargs) && python scripts/run_pipeline.py digest >> logs/pipeline.log 2>&1
```

Keep a terminal open with the bot running:
```bash
export $(cat .env | xargs)
python scripts/run_pipeline.py bot
```

### Option B — GitHub Actions (free, runs in cloud)

Create `.github/workflows/pipeline.yml`:

```yaml
name: Silicon Radar Pipeline
on:
  schedule:
    - cron: '*/30 * * * *'  # every 30 min
  workflow_dispatch:          # manual trigger

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python scripts/run_pipeline.py all
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

Add secrets in: GitHub repo → Settings → Secrets and variables → Actions

> Note: GitHub Actions doesn't keep the bot running for /commands.
> For interactive commands, run `python scripts/run_pipeline.py bot` locally.

---

## Telegram commands

| Command | What it does |
|---|---|
| `/digest` | Today's top 10 signals with importance scores |
| `/quiz` | Random quiz question from today's news |
| `/answer` | Reveal the quiz answer |
| `/rabbit` | Today's rabbit holes — topics to explore |
| `/flashcards` | 3 spaced repetition cards from today |
| `/help` | Show all commands |

## Feedback buttons

Every notification has four buttons:

| Button | Meaning |
|---|---|
| 🔥 Important | High signal, remember this |
| 🧠 Learned something | Educational value |
| 🕳️ Rabbit hole | Want to go deep on this |
| 🗑️ Noise | Low signal, filter similar items |

Your feedback trains the system to know what *you* find valuable.

---

## Adding more sources

Edit `db/schema.sql` → `INSERT INTO sources` section, or run SQL directly in Supabase:

```sql
INSERT INTO sources (name, url, type, credibility) VALUES
    ('SemiAnalysis', 'https://semianalysis.com/feed/', 'rss', 9),
    ('The Chip Letter', 'https://thechipletter.substack.com/feed', 'rss', 8);
```

Source types: `rss`, `arxiv`, `hn`, `reddit`

---

## Free tier usage math

Gemini 2.5 Flash: **1,500 requests/day**

A typical day:
- ~150 new items across all sources
- Each item = 1 Gemini call
- Daily digest synthesis = 1 Gemini call
- Total: ~151 calls/day

That's **10% of your daily quota**. You have headroom for 10x growth before hitting limits.

---

## Project structure

```
silicon-radar/
  app/
    config.py              ← all settings, loaded from .env
  collectors/
    collector.py           ← RSS, HN, Reddit, ArXiv collectors
  processing/
    card_generator.py      ← Gemini intelligence card generation
  notifications/
    telegram_bot.py        ← Telegram bot, commands, feedback
  db/
    schema.sql             ← Supabase schema (run once)
    models.py              ← database read/write functions
  prompts/
    intelligence_card_v1.txt  ← THE PROMPT (most important file)
  scripts/
    run_pipeline.py        ← main entry point
  requirements.txt
  .env.example
```

---

## The most important file

`prompts/intelligence_card_v1.txt` — this is the soul of the system. It instructs Gemini to behave like a "senior semiconductor analyst and computer architecture mentor" and generate structured teaching cards.

Edit this prompt as you learn more. As you get better at the domain, you'll want harder questions, more technical depth, different analogies. Version your prompts by duplicating the file (`intelligence_card_v2.txt`) and updating the `PROMPT_VERSION` in `config.py`.

---

## What to do when Gemini quota runs out

Shouldn't happen with normal usage, but if it does:

1. **Wait until midnight PT** — quota resets daily
2. **Reduce `MAX_ITEMS_PER_SOURCE_PER_RUN`** in config to 10 instead of 20
3. **Only process high-credibility sources** (credibility >= 8) until quota recovers
