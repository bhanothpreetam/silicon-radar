-- Silicon Radar v0 — Database Schema
-- Run this in your Supabase SQL editor

-- Enable vector extension for semantic deduplication
CREATE EXTENSION IF NOT EXISTS vector;

-- Sources we collect from
CREATE TABLE sources (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    type        TEXT NOT NULL,  -- 'rss', 'arxiv', 'reddit', 'hn', 'github'
    credibility INTEGER DEFAULT 5  -- 1-10, controls importance weighting
);

-- Every raw article/paper/post we pull in
CREATE TABLE raw_items (
    id            SERIAL PRIMARY KEY,
    source_id     INTEGER REFERENCES sources(id),
    title         TEXT,
    url           TEXT UNIQUE,
    raw_text      TEXT,
    published_at  TIMESTAMPTZ,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    content_hash  TEXT UNIQUE,             -- SHA-256 for exact dedup
    embedding     vector(384)              -- for semantic dedup via pgvector
);

-- The intelligence cards Gemini generates
CREATE TABLE intelligence_cards (
    id                  SERIAL PRIMARY KEY,
    raw_item_id         INTEGER REFERENCES raw_items(id),
    -- Core card fields
    one_line_summary    TEXT,
    what_happened       TEXT,
    who_is_involved     TEXT,
    tech_layer          TEXT[],   -- ['memory', 'packaging', 'interconnect', ...]
    why_technical       TEXT,     -- deep technical reasoning
    why_strategic       TEXT,     -- industry/business implications
    -- The teaching fields — this is the soul of the app
    eli5_explanation    TEXT,     -- explain like I just graduated
    textbook_concepts   TEXT[],   -- ['roofline model', 'memory hierarchy', ...]
    textbook_bridge     TEXT,     -- how news connects to what you studied
    industry_bridge     TEXT,     -- how this fits the bigger industry picture
    -- Learning layer
    flashcard_q1        TEXT,
    flashcard_a1        TEXT,
    flashcard_q2        TEXT,
    flashcard_a2        TEXT,
    flashcard_q3        TEXT,
    flashcard_a3        TEXT,
    quiz_question       TEXT,
    quiz_answer         TEXT,
    rabbit_hole         TEXT,     -- one deep topic to explore next
    -- Research/opportunity layer
    research_angle      TEXT,     -- possible research idea
    startup_gap         TEXT,     -- possible startup wedge
    watch_next          TEXT[],   -- companies/papers/products to track
    -- Scoring
    importance_score    FLOAT,    -- 0-1 composite
    novelty_score       FLOAT,
    notify              BOOLEAN DEFAULT FALSE,
    notification_level  TEXT,     -- 'ping', 'brief', 'wake_up'
    -- Meta
    prompt_version      TEXT DEFAULT 'v1',
    generated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Topics taxonomy for filtering
CREATE TABLE topics (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    parent_id   INTEGER REFERENCES topics(id)
);

CREATE TABLE item_topics (
    raw_item_id INTEGER REFERENCES raw_items(id),
    topic_id    INTEGER REFERENCES topics(id),
    PRIMARY KEY (raw_item_id, topic_id)
);

-- Your feedback — this trains the system to know YOUR taste
CREATE TABLE feedback (
    id              SERIAL PRIMARY KEY,
    card_id         INTEGER REFERENCES intelligence_cards(id),
    reaction        TEXT NOT NULL,  -- 'fire', 'brain', 'rabbit_hole', 'trash', 'wrong', 'pin'
    reacted_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Outgoing notifications log
CREATE TABLE notifications (
    id              SERIAL PRIMARY KEY,
    card_id         INTEGER REFERENCES intelligence_cards(id),
    level           TEXT,
    message_text    TEXT,
    sent_at         TIMESTAMPTZ DEFAULT NOW(),
    telegram_msg_id INTEGER
);

-- Seed the topic taxonomy
INSERT INTO topics (name) VALUES
    ('Process node'), ('Microarchitecture'), ('Memory / HBM'), ('Chiplets / UCIe'),
    ('Advanced packaging'), ('Interconnect'), ('AI accelerator / ASIC'),
    ('EDA / VLSI'), ('Software stack'), ('Geopolitics / policy'),
    ('Startups'), ('Research paper'), ('India semiconductor'),
    ('RISC-V'), ('Co-packaged optics'), ('Foundry');

-- Seed initial sources
INSERT INTO sources (name, url, type, credibility) VALUES
    ('Semiconductor Engineering', 'https://semiengineering.com/feed/', 'rss', 9),
    ('Chips and Cheese', 'https://chipsandcheese.com/feed/', 'rss', 9),
    ('The Next Platform', 'https://www.nextplatform.com/feed/', 'rss', 8),
    ('ServeTheHome', 'https://www.servethehome.com/feed/', 'rss', 7),
    ('Phoronix', 'https://www.phoronix.com/rss.php', 'rss', 7),
    ('IEEE Spectrum', 'https://spectrum.ieee.org/feeds/feed.rss', 'rss', 8),
    ('NVIDIA Blog', 'https://blogs.nvidia.com/feed/', 'rss', 8),
    ('AMD Blog', 'https://community.amd.com/community/amd-blog/rss', 'rss', 8),
    ('Intel Newsroom', 'https://www.intel.com/content/www/us/en/newsroom/home.rss', 'rss', 8),
    ('Hacker News', 'https://hn.algolia.com/api/v1/search_by_date', 'hn', 7),
    ('ArXiv cs.AR', 'https://export.arxiv.org/rss/cs.AR', 'arxiv', 9),
    ('ArXiv cs.DC', 'https://export.arxiv.org/rss/cs.DC', 'arxiv', 8),
    ('Reddit r/hardware', 'https://www.reddit.com/r/hardware/top.json', 'reddit', 6),
    ('Reddit r/chipdesign', 'https://www.reddit.com/r/chipdesign/new.json', 'reddit', 8);
