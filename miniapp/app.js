/* Silicon Radar — Mini App
   Fetches recent intelligence cards directly from Supabase (anon key,
   read + feedback-insert only) and renders a swipeable, expandable feed. */

const SUPABASE_URL = "https://qyfwvrdgbykzvahxoyyy.supabase.co";
const SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InF5Znd2cmRnYnlrenZhaHhveXl5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEzNzQxOTYsImV4cCI6MjA5Njk1MDE5Nn0.J4Tc_GANy3gjNonsHZzcNbtgvTjCJgCTASyBj5V20xo";

const CARD_LIMIT = 60;
const DEMO_MODE = new URLSearchParams(window.location.search).get("demo");

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

const LENSES = {
  all: {
    emptyTitle: "No signals yet",
    emptySub: "Check back after the next pipeline run.",
    matches: () => true,
  },
  priority: {
    emptyTitle: "Radar is quiet",
    emptySub: "No priority signals in the latest batch.",
    matches: (card) => card.notification_level === "wake_up" || card.notification_level === "brief",
  },
  learning: {
    emptyTitle: "No learning cards yet",
    emptySub: "The daily learning track will add the next one.",
    matches: (card) => card.isLearning,
  },
  probation: {
    emptyTitle: "No sources on trial",
    emptySub: "Newly discovered sources will appear here during probation.",
    matches: (card) => card.sourceStatus === "probation",
  },
};

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
  if (DEMO_MODE === "deep" || DEMO_MODE === "actual") {
    const fixture = DEMO_MODE === "actual" ? "actual-preview-cards.json?v=1" : "demo-card.json?v=1";
    const response = await fetch(fixture);
    if (!response.ok) throw new Error(`Demo card -> ${response.status}`);
    const payload = await response.json();
    const demos = Array.isArray(payload) ? payload : [payload];
    return demos.map((demo) => ({
      ...demo,
      isDemo: true,
      isLearning: false,
      sourceName: demo.sourceName || "Bits'nBrews · demo",
      sourceStatus: demo.sourceStatus || "trusted",
      userReaction: null,
    }));
  }

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

function relativeAge(isoDate) {
  const timestamp = new Date(isoDate).getTime();
  if (!Number.isFinite(timestamp)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) return "now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function values(value) {
  return Array.isArray(value) ? value.filter(Boolean) : [];
}

function paragraphs(text) {
  if (!text) return "";
  return String(text)
    .split(/\n\s*\n/)
    .filter(Boolean)
    .map((paragraph) => `<p>${esc(paragraph.trim())}</p>`)
    .join("");
}

function bulletList(items, className = "deep-list") {
  const rows = values(items).map((item) => `<li>${esc(item)}</li>`).join("");
  return rows ? `<ul class="${className}">${rows}</ul>` : "";
}

function renderDeepDive(card) {
  const deep = card.deep_dive;
  if (!deep || typeof deep !== "object" || !deep.thesis) return "";

  const blocks = [];
  const toc = [];
  let blockIndex = 0;

  function addBlock(label, icon, body, className = "") {
    if (!body) return;
    const anchor = `deep-${card.id}-${blockIndex++}`;
    toc.push(`<button type="button" data-scroll-target="${anchor}">${esc(label)}</button>`);
    blocks.push(`
      <section class="deep-section ${className}" data-deep-section="${anchor}">
        <div class="deep-section-heading"><span>${icon}</span><h3>${esc(label)}</h3></div>
        ${body}
      </section>`);
  }

  const assessment = deep.source_assessment || {};
  const articleType = String(deep.article_type || "analysis").replace(/_/g, " ");
  const readingTime = Number(deep.reading_time_minutes) || null;
  const assessmentMeta = [
    assessment.confidence ? `${assessment.confidence} confidence` : null,
    assessment.evidence_quality ? String(assessment.evidence_quality).replace(/_/g, " ") : null,
  ].filter(Boolean);

  const hero = `
    <div class="deep-hero">
      <div class="deep-kicker">Research brief · ${esc(articleType)}</div>
      <h2>${esc(deep.title || card.one_line_summary || "Deep dive")}</h2>
      ${deep.subtitle ? `<div class="deep-subtitle">${esc(deep.subtitle)}</div>` : ""}
      <div class="deep-meta">
        ${readingTime ? `<span>◷ ${readingTime} min</span>` : ""}
        ${assessmentMeta.map((item) => `<span>${esc(item)}</span>`).join("")}
      </div>
      <div class="deep-thesis"><span>Thesis</span>${paragraphs(deep.thesis)}</div>
      ${assessment.limitations ? `
        <div class="deep-limit"><b>Evidence boundary</b>${paragraphs(assessment.limitations)}</div>` : ""}
    </div>`;

  const evidence = values(deep.evidence)
    .map((item) => `
      <article class="evidence-card">
        <div class="evidence-status">${esc(item.status || "source")}</div>
        <div class="evidence-fact">${esc(item.fact)}</div>
        ${item.significance ? `<div class="evidence-why">${esc(item.significance)}</div>` : ""}
      </article>`)
    .join("");
  addBlock("Evidence", "◉", evidence ? `<div class="evidence-grid">${evidence}</div>` : "");

  const prerequisites = values(deep.prerequisites)
    .map((item) => `
      <details class="foundation-card">
        <summary>${esc(item.term)}</summary>
        <div class="foundation-body">
          ${paragraphs(item.explanation)}
          ${item.why_it_matters_here ? `<div class="foundation-link"><b>Why it matters here</b>${paragraphs(item.why_it_matters_here)}</div>` : ""}
        </div>
      </details>`)
    .join("");
  addBlock("Foundations", "◇", prerequisites, "foundations-section");

  values(deep.sections).forEach((section) => {
    if (!section || !section.content) return;
    const kind = section.kind ? `<span class="section-kind">${esc(String(section.kind).replace(/_/g, " "))}</span>` : "";
    const insight = section.key_insight
      ? `<div class="key-insight"><b>Key insight</b>${paragraphs(section.key_insight)}</div>`
      : "";
    addBlock(
      section.heading || "Analysis",
      "◆",
      `${kind}<div class="deep-prose">${paragraphs(section.content)}</div>${insight}`,
      "narrative-section"
    );
  });

  const examples = values(deep.worked_examples)
    .map((item) => `
      <article class="worked-card">
        <h4>${esc(item.title || "Worked reasoning")}</h4>
        ${paragraphs(item.setup)}
        ${bulletList(item.steps, "reasoning-steps")}
        ${item.result ? `<div class="worked-result"><b>Result</b>${paragraphs(item.result)}</div>` : ""}
      </article>`)
    .join("");
  addBlock("Worked reasoning", "∑", examples);

  const connections = values(deep.system_connections)
    .map((item) => `
      <article class="connection-card">
        <div class="connection-layer">${esc(String(item.layer || "system").replace(/_/g, " "))}</div>
        <div>${esc(item.connection)}</div>
        ${item.consequence ? `<div class="connection-consequence">→ ${esc(item.consequence)}</div>` : ""}
      </article>`)
    .join("");
  addBlock("Across the system", "⌘", connections ? `<div class="connection-grid">${connections}</div>` : "");

  const tradeoffs = values(deep.tradeoffs)
    .map((item) => `
      <article class="tradeoff-card">
        <h4>${esc(item.decision)}</h4>
        <dl>
          <div><dt>Gains</dt><dd>${esc(item.gains)}</dd></div>
          <div><dt>Costs</dt><dd>${esc(item.costs)}</dd></div>
          <div><dt>Breaks when</dt><dd>${esc(item.breaks_when)}</dd></div>
        </dl>
      </article>`)
    .join("");
  addBlock("Architect's tradeoffs", "⇄", tradeoffs);

  const history = deep.historical_arc || {};
  const historyBody = [
    ["Before", history.before],
    ["What changed", history.change],
    ["Now", history.now],
  ]
    .filter(([, text]) => text)
    .map(([label, text]) => `<div class="timeline-step"><b>${label}</b>${paragraphs(text)}</div>`)
    .join("");
  addBlock("How we got here", "↝", historyBody, "history-section");

  const industry = values(deep.industry_map)
    .map((item) => `
      <article class="industry-card">
        <h4>${esc(item.actor)}</h4>
        <div>${esc(item.position)}</div>
        ${item.implication ? `<div class="industry-implication">${esc(item.implication)}</div>` : ""}
      </article>`)
    .join("");
  addBlock("Industry map", "▦", industry ? `<div class="industry-grid">${industry}</div>` : "");

  const frontier = deep.research_frontier || {};
  const frontierBody = [
    frontier.state_of_the_art ? `<div class="deep-prose">${paragraphs(frontier.state_of_the_art)}</div>` : "",
    bulletList(frontier.bottlenecks),
    values(frontier.open_questions).length
      ? `<h4 class="subhead">Open questions</h4>${bulletList(frontier.open_questions)}` : "",
    values(frontier.relevant_work).length
      ? `<h4 class="subhead">Relevant work</h4>${bulletList(frontier.relevant_work)}` : "",
  ].join("");
  addBlock("Research frontier", "⌬", frontierBody, "research-section");

  const insights = values(deep.aha_insights)
    .map((item) => `
      <article class="insight-card">
        <div>${esc(item.insight)}</div>
        ${item.why_non_obvious ? `<p>${esc(item.why_non_obvious)}</p>` : ""}
      </article>`)
    .join("");
  addBlock("Aha insights", "✦", insights);

  const misconceptions = values(deep.misconceptions)
    .map((item) => `
      <article class="misconception-card">
        <div class="misconception-wrong">Not quite: ${esc(item.misconception)}</div>
        <div>${esc(item.correction)}</div>
      </article>`)
    .join("");
  addBlock("Common misconceptions", "≠", misconceptions);

  const challenges = values(deep.whiteboard_challenges)
    .map((item, challengeIndex) => `
      <details class="challenge-card">
        <summary><span>${challengeIndex + 1}</span>${esc(item.question)}</summary>
        <div class="challenge-body">
          ${item.why_it_matters ? `<p><b>Why this matters:</b> ${esc(item.why_it_matters)}</p>` : ""}
          ${item.answer_outline ? `<p><b>Reasoning path:</b> ${esc(item.answer_outline)}</p>` : ""}
        </div>
      </details>`)
    .join("");
  addBlock("Whiteboard challenges", "□", challenges);

  addBlock("Key takeaways", "✓", bulletList(deep.key_takeaways, "takeaway-list"));

  const explore = values(deep.explore_next)
    .map((item) => `
      <article class="explore-card">
        <h4>${esc(item.topic)}</h4>
        <div>${esc(item.reason)}</div>
        ${item.resource_hint ? `<div class="resource-hint">Search: ${esc(item.resource_hint)}</div>` : ""}
      </article>`)
    .join("");
  addBlock("Explore next", "→", explore);

  return `
    <div class="deep-dive">
      ${hero}
      ${toc.length ? `<nav class="deep-toc" aria-label="Deep dive sections">${toc.join("")}</nav>` : ""}
      ${blocks.join("")}
    </div>`;
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
  const age = relativeAge(card.generated_at);

  const specialBadge = card.sourceStatus === "probation"
    ? `<span class="badge probation">🧪 probation</span>`
    : card.isLearning
    ? `<span class="badge learning">📚 learning</span>`
    : "";

  const legacySections = [
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
  const detailContent = renderDeepDive(card) || legacySections;

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
          <span class="source-meta">
            <span class="source-name">${esc(card.sourceName)}</span>
            ${age ? `<span class="source-age">${age}</span>` : ""}
          </span>
          <button class="more-btn" data-expand="${card.id}">${card.deep_dive ? "Deep dive" : "Read more"} ↓</button>
        </div>
        ${feedbackBar(card)}
      </div>
    </div>

    <div class="card-detail">
      <div class="detail-header">
        <div class="detail-title">${esc(card.one_line_summary || "")}</div>
        <button class="close-btn" data-collapse="${card.id}">✕</button>
      </div>
      <div class="detail-read-track"><div class="detail-read-progress"></div></div>
      <div class="detail-scroll">
        ${detailContent}
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

let allCards = [];
let cards = [];
let index = 0;
let expandedId = null;
let dragStartX = 0;
let dragging = false;
let activeLens = "all";
let trackEl, counterEl, progressEl, stackEl, emptyEl, lensBarEl;

function goTo(newIndex, withHaptic = true) {
  if (!cards.length) return;
  index = Math.max(0, Math.min(cards.length - 1, newIndex));
  trackEl.style.transform = `translateX(-${index * 100}vw)`;
  counterEl.textContent = `${index + 1} / ${cards.length}`;
  progressEl.style.width = `${((index + 1) / cards.length) * 100}%`;
  progressEl.style.background = primaryColor(cards[index]);
  if (withHaptic) haptic("select");
}

function expandCard(cardId) {
  expandedId = cardId;
  document.getElementById("app").classList.add("detail-open");
  const hint = document.querySelector(".swipe-hint");
  if (hint) hint.remove();
  document.querySelectorAll(".card").forEach((c) => {
    c.classList.toggle("expanded", Number(c.dataset.cardId) === cardId);
  });
  haptic("light");
}

function collapseCard() {
  expandedId = null;
  document.getElementById("app").classList.remove("detail-open");
  document.querySelectorAll(".card").forEach((c) => c.classList.remove("expanded"));
  haptic("light");
}

function updateLensCounts() {
  Object.entries(LENSES).forEach(([name, lens]) => {
    const count = allCards.filter(lens.matches).length;
    const el = lensBarEl.querySelector(`[data-lens-count="${name}"]`);
    if (el) el.textContent = count;
  });
}

function showEmptyState(lensName) {
  const lens = LENSES[lensName];
  emptyEl.querySelector(".empty-title").textContent = lens.emptyTitle;
  emptyEl.querySelector(".empty-sub").textContent = lens.emptySub;
  emptyEl.classList.remove("hidden");
  counterEl.textContent = "0 / 0";
  progressEl.style.width = "0%";
}

function renderFeed(preferredCardId = null) {
  const lens = LENSES[activeLens];
  cards = allCards.filter(lens.matches);
  expandedId = null;
  trackEl.replaceChildren();

  lensBarEl.querySelectorAll("[data-lens]").forEach((button) => {
    const selected = button.dataset.lens === activeLens;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });

  if (!cards.length) {
    showEmptyState(activeLens);
    return;
  }

  emptyEl.classList.add("hidden");
  cards.forEach((card, cardIndex) => {
    const el = renderCard(card, cardIndex);
    el.dataset.cardId = card.id;
    trackEl.appendChild(el);
  });

  const preferredIndex = preferredCardId
    ? cards.findIndex((card) => card.id === preferredCardId)
    : -1;
  goTo(preferredIndex >= 0 ? preferredIndex : 0, false);
}

function applyLens(lensName) {
  if (!LENSES[lensName] || lensName === activeLens) return;
  const currentCardId = cards[index] ? cards[index].id : null;
  activeLens = lensName;
  renderFeed(currentCardId);
  haptic("select");
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
  if (card.isDemo) return;
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
    if (!cards.length || expandedId !== null) return; // detail view scrolls vertically instead
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

    const scrollBtn = e.target.closest("[data-scroll-target]");
    if (scrollBtn) {
      const cardEl = scrollBtn.closest(".card");
      const target = cardEl && cardEl.querySelector(
        `[data-deep-section="${scrollBtn.dataset.scrollTarget}"]`
      );
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }

    const fbBtn = e.target.closest(".fb-btn");
    if (fbBtn) return handleReaction(Number(fbBtn.dataset.card), fbBtn.dataset.reaction);
  });

  // scroll does not bubble, so capture it at the stack and update the active
  // article's compact reading-progress indicator.
  stackEl.addEventListener("scroll", (e) => {
    if (!e.target.classList || !e.target.classList.contains("detail-scroll")) return;
    const maxScroll = e.target.scrollHeight - e.target.clientHeight;
    const progress = maxScroll > 0 ? (e.target.scrollTop / maxScroll) * 100 : 100;
    const bar = e.target.closest(".card-detail").querySelector(".detail-read-progress");
    if (bar) bar.style.width = `${Math.min(100, Math.max(0, progress))}%`;
  }, true);
}

function attachLensEvents() {
  lensBarEl.addEventListener("click", (e) => {
    const button = e.target.closest("[data-lens]");
    if (button) applyLens(button.dataset.lens);
  });
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot() {
  stackEl = document.getElementById("stack");
  counterEl = document.getElementById("counter");
  progressEl = document.getElementById("progress-fill");
  emptyEl = document.getElementById("empty-state");
  lensBarEl = document.getElementById("lens-bar");

  trackEl = document.createElement("div");
  trackEl.className = "track";
  stackEl.appendChild(trackEl);

  try {
    allCards = await loadCards();
  } catch (e) {
    console.error(e);
    document.getElementById("loading").classList.add("hidden");
    emptyEl.classList.remove("hidden");
    emptyEl.querySelector(".empty-title").textContent = "Couldn't load the feed";
    emptyEl.querySelector(".empty-sub").textContent = "Check your connection and reopen.";
    return;
  }

  document.getElementById("loading").classList.add("hidden");

  attachDrag();
  attachDelegatedEvents();
  attachLensEvents();
  updateLensCounts();
  renderFeed();

  if (allCards.length) {
    const hint = document.createElement("div");
    hint.className = "swipe-hint";
    hint.textContent = "← swipe →";
    document.getElementById("app").appendChild(hint);
    setTimeout(() => hint.remove(), 5000);
  }
}

boot();
