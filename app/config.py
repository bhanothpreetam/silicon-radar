"""
Silicon Radar — Configuration
All secrets loaded from environment variables.
Copy this to .env and fill in your values.
"""

import os
from dataclasses import dataclass


@dataclass
class Config:
    # --- Gemini API (get from https://aistudio.google.com/apikey) ---
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = "gemini-2.5-flash"    # Free tier: separate quota from 2.0-flash
    INTELLIGENCE_PROMPT_VERSION: str = os.getenv("INTELLIGENCE_PROMPT_VERSION", "v1").lower()

    # --- Supabase (get from your project's Settings > API) ---
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")   # Use the anon/public key
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")   # postgres://... connection string

    # --- Telegram Bot (get from @BotFather) ---
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")  # your personal chat ID

    # --- Rate limiting ---
    # The observed Gemini 2.5 Flash free-tier quota was 20 requests/day/project.
    # Rotation helps only across keys backed by independent quota projects;
    # this counter remains a coarse per-process safety ceiling.
    GEMINI_REQUESTS_PER_MINUTE: int = 12       # stay under 15 RPM limit
    GEMINI_REQUESTS_PER_DAY: int = 1400
    DELAY_BETWEEN_REQUESTS: float = 5.0        # seconds between Gemini calls

    # --- Collection settings ---
    MAX_ITEMS_PER_SOURCE_PER_RUN: int = 20     # don't flood on first run
    MIN_IMPORTANCE_TO_NOTIFY: float = 0.65
    MIN_IMPORTANCE_FOR_DIGEST: float = 0.45
    SEMANTIC_DEDUP_THRESHOLD: float = 0.92     # cosine similarity for dedup

    # --- HN search keywords (what to watch on Hacker News) ---
    HN_KEYWORDS: list = (
        "TSMC", "NVIDIA", "AMD", "Intel foundry", "HBM", "chiplet",
        "UCIe", "RISC-V", "semiconductor", "process node", "AI chip",
        "accelerator", "packaging", "CoWoS", "EUV", "ASIC", "Qualcomm",
        "Arm", "memory bandwidth", "inference", "silicon photonics"
    )

    # --- Reddit subreddits to watch ---
    REDDIT_SUBREDDITS: list = (
        "hardware", "chipdesign", "ECE", "MachineLearning",
        "singularity", "FPGA", "PrintedCircuitBoard",
        "embedded", "electronics", "LocalLLaMA",
    )

    # --- ArXiv categories to watch ---
    ARXIV_CATEGORIES: list = ("cs.AR", "cs.DC", "cs.LG", "eess.SY")

    # --- Twitter/X credentials ---
    TWITTER_USERNAME: str = os.getenv("TWITTER_USERNAME", "")
    TWITTER_PASSWORD: str = os.getenv("TWITTER_PASSWORD", "")
    TWITTER_EMAIL: str = os.getenv("TWITTER_EMAIL", "")
    # Cookie-based auth (bypasses Cloudflare IP blocks on password login).
    # Paste: auth_token=<value>; ct0=<value>
    # Get from browser DevTools → Application → Cookies → x.com
    TWITTER_COOKIES: str = os.getenv("TWITTER_COOKIES", "")

    # --- Twitter/X accounts to monitor ---
    TWITTER_TIER1: tuple = (
        "cHHillee",          # Chip Huyen — ML systems/hardware, 50K followers
        "dylan522p",         # Dylan Patel — SemiAnalysis founder
        "jimkxa",            # Jim Keller — Tenstorrent CEO, 52K followers
        "PatrickMoorhead",   # Patrick Moorhead — Moor Insights analyst
        "Asianometry",       # Jon Y — geopolitics + supply chain
        "IanCutress",        # Ian Cutress — The Chip Letter, CPU/GPU microarch
    )
    TWITTER_TIER2: tuple = (
        "chiakokhua",
        "HotChips",
    )
    TWITTER_TIER3: tuple = (
        "gwern", "MLPerf",
        "IEEESpectrum",
    )
    TWITTER_VLSI_EDA: tuple = (
        "matthewvenn", "OpenROAD_EDA", "synopsys",
        "Cadence", "efabless", "SKundojjala",
    )
    TWITTER_DIGITAL_DESIGN: tuple = (
        "AbnerHung", "zipcpu", "YosysHQ",
        "YCS_Yang", "duke_cpu", "Cardyak",
    )
    TWITTER_OPEN_SILICON: tuple = (
        "lowRISC", "ChipsAlliance",
        "TheHackerFab", "tinytapeout",
    )
    TWITTER_CHIP_ARCH: tuple = (
        "onurmutlu_", "SAFARI_ETH_CMU", "MicroArchConf",
    )
    TWITTER_INDUSTRY: tuple = (
        "SemiAnalysis_", "semivision_tw", "mooreslawisdead", "Vikramskr",
    )
    TWITTER_AI_HARDWARE: tuple = (
        "tenstorrent", "always_ff_rohan", "GPUsAreMagic", "LeetGPU", "beaversteever",
    )
    TWITTER_FPGA: tuple = (
        "FPGA_Zealot", "ATaylorFPGA", "regymm0", "splinedrive",
        "ptrschmdtnlsn", "wren6991", "nand2mario",
    )
    TWITTER_COMPANIES: tuple = (
        "intel", "AMD", "Qualcomm", "Arm", "AlteraFPGA_", "ChipsandCheese9",
    )


config = Config()

# Parse multi-key list: GEMINI_API_KEYS=key1,key2,key3 (falls back to GEMINI_API_KEY)
def _parse_gemini_keys() -> list:
    raw = os.getenv("GEMINI_API_KEYS", "")
    if raw:
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if keys:
            return keys
    return [config.GEMINI_API_KEY] if config.GEMINI_API_KEY else []

config.GEMINI_API_KEYS = _parse_gemini_keys()

# YouTube channels to monitor (handle → channel_id, resolved 2026-07)
YOUTUBE_CHANNELS = {
    "Asianometry":       "UC1LpsuAUaKoMzzJSEt5WImw",  # semiconductor history/business deep dives
    "TechTechPotato":    "UC1r0DG-KEPyqOeW6o79PByw",  # Ian Cutress — industry analysis
    "HighYield":         "UCmMwHbw2j8LfvTKVh3O7Vdw",  # die shots, chip architecture analysis
    "AnastasiInTech":    "UCORX3Cl7ByidjEgzSCgv9Yw",  # chip engineering
    "Coreteks":          "UCX_t3BvnQtS5IHzto_y7tbw",  # hardware analysis
    "brancheducation":   "UCdp4_l1vPmpN-gDbUwhaRUQ",  # visual chip education
    "SemiAnalysis":      "UCf_KhBXw5TIV0A7butjgFhg",  # Dylan Patel — industry deep dives
    "MooresLawIsDead":   "UCRPdsCVuH53rcbTcEkuY4uQ",  # leaks, roadmap analysis
    "OnurMutluLectures": "UCIwQ8uOeRFgOEvBLYc3kc3g",  # comp arch lectures (ETH/CMU)
    "ServeTheHomeVideo": "UCv6J_jJa8GJqFwQNgNrMuww",  # server/datacenter hardware
    "Level1Techs":       "UC4w1YQAJMWOz4qtxinq55LQ",  # enterprise hardware analysis
}

# Curated Tier1 list for quick/frequent runs (~18 accounts)
TWITTER_TIER1 = [
    "dylan522p", "jimkxa", "PatrickMoorhead",
    "IanCutress", "SemiAnalysis_", "semivision_tw",
    "mooreslawisdead", "Asianometry", "IEEESpectrum",
    "always_ff_rohan", "GPUsAreMagic", "Vikramskr",
    "AMD", "intel", "Qualcomm", "tenstorrent",
    "ChipsandCheese9",
]

# Flat list of all Twitter accounts
TWITTER_ACCOUNTS = (
    list(config.TWITTER_TIER1) + list(config.TWITTER_TIER2) +
    list(config.TWITTER_TIER3) + list(config.TWITTER_VLSI_EDA) +
    list(config.TWITTER_DIGITAL_DESIGN) + list(config.TWITTER_OPEN_SILICON) +
    list(config.TWITTER_CHIP_ARCH) + list(config.TWITTER_INDUSTRY) +
    list(config.TWITTER_AI_HARDWARE) + list(config.TWITTER_FPGA) +
    list(config.TWITTER_COMPANIES)
)


# .env file template (copy to .env and fill in)
ENV_TEMPLATE = """
GEMINI_API_KEY=your_key_from_aistudio_google_com
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key
DATABASE_URL=postgresql://postgres:password@db.your-project.supabase.co:5432/postgres
TELEGRAM_TOKEN=your_bot_token_from_botfather
TELEGRAM_CHAT_ID=your_personal_chat_id
"""
