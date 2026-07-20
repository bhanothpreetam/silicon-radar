/* Silicon Radar — Mini App
   Fetches recent intelligence cards directly from Supabase (anon key,
   read + feedback-insert only) and renders a swipeable, expandable feed. */

const SUPABASE_URL = "https://qyfwvrdgbykzvahxoyyy.supabase.co";
const SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InF5Znd2cmRnYnlrenZhaHhveXl5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEzNzQxOTYsImV4cCI6MjA5Njk1MDE5Nn0.J4Tc_GANy3gjNonsHZzcNbtgvTjCJgCTASyBj5V20xo";

const CARD_LIMIT = 60;

const LAYER_EMOJI = {
  process_node: "⚙️", microarchitecture: "🏗️", memory_hbm: "💾",
  chiplets_ucie: "🔗", advanced_packaging: "📦", interconnect: "🌐",
  ai_accelerator_asic: "🤖", eda_vlsi: "🔬", software_stack: "💻",
  geopolitics_policy: "🌏", startups: "🚀", research_paper: "📄",
  india_semiconductor: "🇮🇳", risc_v: "🔓", co_packaged_optics: "💡", foundry: "🏭",
};

const LAYER_COLOR = {
  process_node: "#f59e0b", microarchitecture: "#8b5cf6", memory_hbm: "#3b82f6",
  chiplets_ucie: "#06b6d4", advanced_packaging: "#ec4899", interconnect: "#14b8a6",
  ai_accelerator_asic: "#a855f7", eda_vlsi: "#6366f1", software_stack: "#22c55e",
  geopolitics_policy: "#ef4444", startups: "#f97316", research_paper: "#64748b",
  india_semiconductor: "#fb923c", risc_v: "#10b981", co_packaged_optics: "#eab308",
  foundry: "#d946ef",
};

const LEVEL_ICON = { wake_up: "🚨", brief: "📡", ping: "💬" };
const REACTIONS = [
  { key: "fire", emoji: "🔥" },
  { key: "brain", emoji: "🧠" },
  { key: "rabbit_hole", emoji: "🕳️" },
  { key: "trash", emoji: "🗑️" },
];

// ---------------------------------------------------------------------------
// Telegram WebApp integration
// ---------------------------------------------------------------------------

const tg = window.Telegram && window.Telegram.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  try { tg.setHeaderColor("#08080c"); tg.setBackgroundColor("#08080c"); } catch (e) {}
}
function haptic(kind) {
  if (!tg || !tg.HapticFeedback) return;
  if (kind === "select") tg.HapticFeedback.selectionChanged();
  else if (kind === "success") tg.HapticFeedback.notificationOccurred("success");
  else tg.HapticFeedback.impactOccurred(kind || "light");
}
function openUrl(url) {
  if (tg && tg.openLink) tg.openLink(url);
  else window.open(url, "_blank");
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function sb(path) {
  const res = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${SUPABASE_ANON_KEY}` },
  });
  if (!res.ok) throw new Error(`Supabase ${path} -> ${res.status}`);
  return res.json();
}

async function loadCards() {
  const cards = await sb(
    `intelligence_cards?select=*&notify=eq.true&order=generated_at.desc&limit=${CARD_LIMIT}`
  );
  if (!cards.length) return [];

  const itemIds = [...new Set(cards.map((c) => c.raw_item_id))];
  const items = await sb(`raw_items?select=id,title,url,source_id&id=in.(${itemIds.join(",")})`);
  const itemsById = Object.fromEntries(items.map((i) => [i.id, i]));

  const sourceIds = [...new Set(items.map((i) => i.source_id).filter(Boolean))];
  let sourcesById = {};
  if (sourceIds.length) {
    const sources = await sb(`sources?select=id,name,status&id=in.(${sourceIds.join(",")})`);
    sourcesById = Object.fromEntries(sources.map((s) => [s.id, s]));
  }

  const cardIds = cards.map((c) => c.id);
  const feedback = await sb(
    `feedback?select=card_id,reaction,reacted_at&card_id=in.(${cardIds.join(",")})&order=reacted_at.asc`
  );
  const reactionByCard = {};
  for (const f of feedback) reactionByCard[f.card_id] = f.reaction; // latest wins (ascending order)

  return cards.map((c) => {
    const item = itemsById[c.raw_item_id] || {};
    const source = sourcesById[item.source_id] || {};
    return {
      ...c,
      url: item.url || "",
      isLearning: (item.title || "").startsWith("[Learning]"),
      sourceName: source.name || "Unknown source",
      sourceStatus: source.status || "trusted",
      userReaction: reactionByCard[c.id] || null,
    };
  });
}

async function postFeedback(cardId, reaction) {
  await fetch(`${SUPABASE_URL}/rest/v1/feedback`, {
    method: "POST",
    headers: {
      apikey: SUPABASE_ANON_KEY,
      Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify({ card_id: cardId, reaction }),
  });
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}

function primaryColor(card) {
  const layers = card.tech_layer || [];
  return LAYER_COLOR[layers[0]] || "#8b5cf6";
}

function feedbackBar(card, compact) {
  const btns = REACTIONS.map(
    (r) => `<button class="fb-btn ${card.userReaction === r.key ? "active" : ""} ${
      card.userReaction && card.userReaction !== r.key ? "disabled" : ""
    }" data-card="${card.id}" data-reaction="${r.key}">${r.emoji}</button>`
  ).join("");
  return `<div class="feedback-bar">${btns}</div>`;
}

function renderCard(card, index) {
  const color = primaryColor(card);
  const layers = card.tech_layer || [];
  const layerBadges = layers
    .slice(0, 3)
    .map((l) => `<span class="badge layer">${LAYER_EMOJI[l] || "•"} ${l.replace(/_/g, " ")}</span>`)
    .join("");
  const levelIcon = LEVEL_ICON[card.notification_level] || "📡";
  const pct = Math.round((card.importance_score || 0) * 100);

  const specialBadge = card.sourceStatus === "probation"
    ? `<span class="badge probation">🧪 probation</span>`
    : card.isLearning
    ? `<span class="badge learning">📚 learning</span>`
    : "";

  const sections = [
    ["💥", "What happened", card.what_happened],
    ["🔧", "Why it matters — technical", card.why_technical],
    ["📈", "Why it matters — strategic", card.why_strategic],
    ["🎓", "ELI5", card.eli5_explanation],
    ["📚", "Textbook bridge", card.textbook_bridge],
    ["🕳️", "Rabbit hole", card.rabbit_hole],
  ]
    .filter(([, , text]) => text)
    .map(
      ([icon, label, text]) => `
      <div class="section">
        <div class="section-label">${icon} ${label}</div>
        <div class="section-text">${esc(text)}</div>
      </div>`
    )
    .join("");

  const el = document.createElement("div");
  el.className = "card";
  el.style.setProperty("--accent", color);
  el.dataset.index = index;

  el.innerHTML = `
    <div class="card-face">
      <div class="badge-row">
        <span class="badge level-${card.notification_level}">${levelIcon}</span>
        ${layerBadges}
        ${specialBadge}
      </div>
      <div class="card-title">${esc(card.one_line_summary || "New signal")}</div>
      <div class="card-brief">${esc(card.what_happened || "")}</div>
      <div class="card-footer">
        <div class="score-row">
          <div class="score-bar"><div class="score-fill" style="width:${pct}%"></div></div>
          <div class="score-pct">${pct}%</div>
        </div>
        <div class="source-row">
          <span class="source-name">${esc(card.sourceName)}</span>
          <button class="more-btn" data-expand="${card.id}">Read more ↓</button>
        </div>
        ${feedbackBar(card)}
      </div>
    </div>

    <div class="card-detail">
      <div class="detail-header">
        <div class="detail-title">${esc(card.one_line_summary || "")}</div>
        <button class="close-btn" data-collapse="${card.id}">✕</button>
      </div>
      <div class="detail-scroll">
        ${sections}
        <button class="source-btn" data-source-url="${esc(card.url)}">🔗 Read source</button>
      </div>
      ${feedbackBar(card)}
    </div>
  `;
  return el;
}

// ---------------------------------------------------------------------------
// App state + swipe/drag
// ---------------------------------------------------------------------------

let cards = [];
let index = 0;
let expandedId = null;
let dragStartX = 0;
let dragging = false;
let trackEl, counterEl, progressEl, stackEl;

function goTo(newIndex) {
  index = Math.max(0, Math.min(cards.length - 1, newIndex));
  trackEl.style.transform = `translateX(-${index * 100}vw)`;
  counterEl.textContent = `${index + 1} / ${cards.length}`;
  progressEl.style.width = `${((index + 1) / cards.length) * 100}%`;
  progressEl.style.background = primaryColor(cards[index]);
  haptic("select");
}

function expandCard(cardId) {
  expandedId = cardId;
  document.querySelectorAll(".card").forEach((c) => {
    c.classList.toggle("expanded", Number(c.dataset.cardId) === cardId);
  });
  haptic("light");
}

function collapseCard() {
  expandedId = null;
  document.querySelectorAll(".card").forEach((c) => c.classList.remove("expanded"));
  haptic("light");
}

async function handleReaction(cardId, reaction) {
  const card = cards.find((c) => c.id === cardId);
  if (!card || card.userReaction) return;
  card.userReaction = reaction;
  document.querySelectorAll(`.fb-btn[data-card="${cardId}"]`).forEach((btn) => {
    const isThis = btn.dataset.reaction === reaction;
    btn.classList.toggle("active", isThis);
    btn.classList.toggle("disabled", !isThis);
  });
  haptic("success");
  try {
    await postFeedback(cardId, reaction);
  } catch (e) {
    console.error("feedback post failed", e);
  }
}

function attachDrag() {
  // Axis is undecided until the finger has moved a few px — only then do we
  // commit to horizontal (capture the pointer, drive the swipe) or bail and
  // let the browser's native vertical scroll take over untouched.
  const AXIS_LOCK_PX = 10;
  const HORIZONTAL_BIAS = 1.4; // dx must clearly dominate dy -- real fingers wobble
  let startX = 0, startY = 0, currentDX = 0;
  let axis = null; // null | "x" | "y"
  let activePointerId = null;

  stackEl.addEventListener("pointerdown", (e) => {
    if (expandedId !== null) return; // detail view scrolls vertically instead
    if (e.target.closest("button, a")) return;
    startX = e.clientX;
    startY = e.clientY;
    currentDX = 0;
    axis = null;
    activePointerId = e.pointerId;
  });

  stackEl.addEventListener("pointermove", (e) => {
    if (activePointerId === null || e.pointerId !== activePointerId) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;

    if (axis === null) {
      if (Math.abs(dx) < AXIS_LOCK_PX && Math.abs(dy) < AXIS_LOCK_PX) return;
      // Vertical is the safe default -- a real finger's first few px often
      // wobble diagonally, so only commit to horizontal swipe when dx clearly
      // dominates dy, not just barely edges it out.
      axis = Math.abs(dx) > Math.abs(dy) * HORIZONTAL_BIAS ? "x" : "y";
      if (axis === "x") {
        dragging = true;
        trackEl.classList.add("dragging");
        stackEl.setPointerCapture(activePointerId);
      } else {
        activePointerId = null; // vertical: hand off to native scroll, we're done
        return;
      }
    }

    if (axis !== "x") return;
    currentDX = dx;
    const base = -index * window.innerWidth;
    trackEl.style.transform = `translateX(${base + currentDX}px)`;
  });

  function endDrag() {
    activePointerId = null;
    axis = null;
    if (!dragging) return;
    dragging = false;
    trackEl.classList.remove("dragging");
    const threshold = window.innerWidth * 0.18;
    if (currentDX < -threshold && index < cards.length - 1) goTo(index + 1);
    else if (currentDX > threshold && index > 0) goTo(index - 1);
    else goTo(index);
    currentDX = 0;
  }

  stackEl.addEventListener("pointerup", endDrag);
  stackEl.addEventListener("pointercancel", endDrag);

  document.addEventListener("keydown", (e) => {
    if (expandedId !== null) {
      if (e.key === "Escape") collapseCard();
      return;
    }
    if (e.key === "ArrowRight") goTo(index + 1);
    if (e.key === "ArrowLeft") goTo(index - 1);
  });
}

function attachDelegatedEvents() {
  stackEl.addEventListener("click", (e) => {
    const expandBtn = e.target.closest("[data-expand]");
    if (expandBtn) return expandCard(Number(expandBtn.dataset.expand));

    const collapseBtn = e.target.closest("[data-collapse]");
    if (collapseBtn) return collapseCard();

    const srcBtn = e.target.closest("[data-source-url]");
    if (srcBtn && srcBtn.dataset.sourceUrl) return openUrl(srcBtn.dataset.sourceUrl);

    const fbBtn = e.target.closest(".fb-btn");
    if (fbBtn) return handleReaction(Number(fbBtn.dataset.card), fbBtn.dataset.reaction);
  });
}

// ---------------------------------------------------------------------------
// Fit compact-card text to available space (kills the need to scroll it)
// ---------------------------------------------------------------------------

function fitCardBrief(cardEl) {
  const face = cardEl.querySelector(".card-face");
  const brief = cardEl.querySelector(".card-brief");
  if (!face || !brief) return;

  // Verify against REAL measured overflow (face.scrollHeight vs clientHeight)
  // instead of estimating from line-height -- estimation broke on devices
  // where computed line-height/font-scaling didn't match assumptions.
  // .card-title has its own hard CSS cap (3 lines), so it can no longer be
  // the unbounded culprit; this loop only has to handle .card-brief now.
  for (let lines = 6; lines >= 1; lines--) {
    brief.style.setProperty("-webkit-line-clamp", String(lines));
    if (face.scrollHeight <= face.clientHeight + 1) return; // +1: rounding slack
  }
  // Even 1 line doesn't fit (extreme case: many wrapped badges + long title) --
  // touch-action:pan-y + overflow-y:auto on .card-face remains the fallback.
}

function fitAllCards() {
  document.querySelectorAll(".card").forEach(fitCardBrief);
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot() {
  stackEl = document.getElementById("stack");
  counterEl = document.getElementById("counter");
  progressEl = document.getElementById("progress-fill");

  trackEl = document.createElement("div");
  trackEl.className = "track";
  stackEl.appendChild(trackEl);

  try {
    cards = await loadCards();
  } catch (e) {
    console.error(e);
    document.getElementById("loading").classList.add("hidden");
    document.getElementById("empty-state").classList.remove("hidden");
    document.querySelector(".empty-title").textContent = "Couldn't load the feed";
    document.querySelector(".empty-sub").textContent = "Check your connection and reopen.";
    return;
  }

  document.getElementById("loading").classList.add("hidden");

  if (!cards.length) {
    document.getElementById("empty-state").classList.remove("hidden");
    return;
  }

  cards.forEach((card, i) => {
    const el = renderCard(card, i);
    el.dataset.cardId = card.id;
    trackEl.appendChild(el);
  });

  attachDrag();
  attachDelegatedEvents();
  fitAllCards();
  window.addEventListener("resize", fitAllCards);
  goTo(0);

  const hint = document.createElement("div");
  hint.className = "swipe-hint";
  hint.textContent = "← swipe →";
  document.getElementById("app").appendChild(hint);
  setTimeout(() => hint.remove(), 5000);
}

boot();
