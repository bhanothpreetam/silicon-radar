"use strict";

const app = document.querySelector("#app");
const statusText = document.querySelector("#status");
const nextCaseButton = document.querySelector("#next-case");
const exportDataButton = document.querySelector("#export-data");
const responseTemplate = document.querySelector("#response-template");

const STORAGE = {
  deck: "radar.learning.preview.deck.v1",
  attempts: "radar.learning.preview.attempts.v1",
  progress: "radar.learning.preview.progress.v1",
};

let caseIndex = [];
let activeRecord = null;
let activeCase = null;
let currentProgress = null;
let attemptId = null;
let sequence = 0;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function addText(parent, tag, className, text) {
  const node = element(tag, className, text);
  parent.append(node);
  return node;
}

function addEvidence(parent, text) {
  const container = element("div", "evidence");
  const lines = String(text || "").split("\n");
  let paragraph = [];

  function flushParagraph() {
    const value = paragraph.join("\n").trim();
    if (value) container.append(element("p", "", value));
    paragraph = [];
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    const next = (lines[index + 1] || "").trim();
    const startsTable = line.startsWith("|")
      && /^\|?[\s:|-]+\|?$/.test(next);
    if (!startsTable) {
      if (line) paragraph.push(line);
      else flushParagraph();
      continue;
    }

    flushParagraph();
    const cells = (value) => value
      .replace(/^\||\|$/g, "")
      .split("|")
      .map((cell) => cell.trim());
    const rows = [cells(line)];
    index += 2;
    while (index < lines.length && lines[index].trim().startsWith("|")) {
      rows.push(cells(lines[index].trim()));
      index += 1;
    }
    index -= 1;

    const table = element("table", "evidence-table");
    const head = element("thead");
    const headRow = element("tr");
    for (const value of rows[0]) headRow.append(element("th", "", value));
    head.append(headRow);
    table.append(head);

    const body = element("tbody");
    for (const row of rows.slice(1)) {
      const tableRow = element("tr");
      for (const value of row) {
        tableRow.append(element("td", "", value || "—"));
      }
      body.append(tableRow);
    }
    table.append(body);
    container.append(table);
  }
  flushParagraph();
  parent.append(container);
}

function list(parent, values, className, itemClass = "") {
  const container = element("ul", className);
  for (const value of values || []) {
    container.append(element("li", itemClass, value));
  }
  parent.append(container);
  return container;
}

function readStored(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback));
  } catch {
    return fallback;
  }
}

function progressMap() {
  return readStored(STORAGE.progress, {});
}

function persistProgress(patch = {}) {
  if (!activeCase || !currentProgress) return;
  currentProgress = {
    ...currentProgress,
    ...patch,
    case_id: activeCase.case_id,
    case_revision: activeCase.case_revision,
    attempt_id: attemptId,
    sequence,
    updated_at: new Date().toISOString(),
  };
  const all = progressMap();
  all[activeCase.case_id] = currentProgress;
  localStorage.setItem(STORAGE.progress, JSON.stringify(all));
}

function clearProgress(caseId) {
  const all = progressMap();
  delete all[caseId];
  localStorage.setItem(STORAGE.progress, JSON.stringify(all));
}

function setResponse(path, value) {
  const responses = currentProgress.responses || {};
  persistProgress({
    responses: {
      ...responses,
      [path]: value,
    },
  });
}

function storedResponse(path) {
  return (currentProgress?.responses || {})[path] || null;
}

function fillResponse(response, saved) {
  if (!saved) return;
  response.textarea.value = saved.response || "";
  response.slider.value = String(saved.confidence ?? 50);
  response.slider.dispatchEvent(new Event("input"));
}

function reviewIsDue() {
  return Boolean(
    currentProgress?.stage === "completed"
    && currentProgress.review_due_at
    && !currentProgress.review_completed_at
    && Date.parse(currentProgress.review_due_at) <= Date.now()
  );
}

function formatReviewDate(value) {
  if (!value) return "not scheduled";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function randomIndex(length) {
  const values = new Uint32Array(1);
  crypto.getRandomValues(values);
  return values[0] % length;
}

function drawRecord() {
  const validIds = new Set(caseIndex.map((record) => record.case_id));
  let deck = [];
  try {
    deck = JSON.parse(localStorage.getItem(STORAGE.deck) || "[]")
      .filter((caseId) => validIds.has(caseId));
  } catch {
    deck = [];
  }
  if (!deck.length) {
    deck = caseIndex.map((record) => record.case_id);
    for (let i = deck.length - 1; i > 0; i -= 1) {
      const j = randomIndex(i + 1);
      [deck[i], deck[j]] = [deck[j], deck[i]];
    }
  }
  const selectedId = deck.shift();
  localStorage.setItem(STORAGE.deck, JSON.stringify(deck));
  return caseIndex.find((record) => record.case_id === selectedId);
}

function recordEvent(eventType, payload = {}) {
  sequence += 1;
  const event = {
    event_id: crypto.randomUUID(),
    attempt_id: attemptId,
    learner_id: "local-preview",
    case_id: activeCase.case_id,
    case_revision: activeCase.case_revision,
    event_type: eventType,
    sequence,
    occurred_at: new Date().toISOString(),
    payload,
  };
  const events = readStored(STORAGE.attempts, []);
  events.push(event);
  localStorage.setItem(STORAGE.attempts, JSON.stringify(events.slice(-1000)));
  if (currentProgress) persistProgress();
}

function responseBlock(prompt, confidencePrompt) {
  const fragment = responseTemplate.content.cloneNode(true);
  const root = fragment.querySelector(".response-block");
  const label = root.querySelector(":scope > label");
  const textarea = root.querySelector("textarea");
  const slider = root.querySelector('input[type="range"]');
  const output = root.querySelector("output");
  label.textContent = prompt || "Your current model";
  textarea.setAttribute("aria-label", prompt || "Your current model");
  if (confidencePrompt) {
    root.querySelector(".confidence-row label").firstChild.textContent =
      `${confidencePrompt} `;
  }
  slider.addEventListener("input", () => {
    output.textContent = `${slider.value}%`;
  });
  return {fragment, root, textarea, slider};
}

function primaryButton(label) {
  return element("button", "primary-button", label);
}

async function loadCase(record) {
  activeRecord = record;
  const response = await fetch(`./${record.pre_url}`, {cache: "no-store"});
  if (!response.ok) throw new Error(`Could not load ${record.pre_url}`);
  activeCase = await response.json();
  const saved = progressMap()[activeCase.case_id];
  const canResume = saved?.case_revision === activeCase.case_revision;
  if (canResume) {
    currentProgress = saved;
    attemptId = saved.attempt_id;
    sequence = Number(saved.sequence || 0);
  } else {
    attemptId = crypto.randomUUID();
    sequence = 0;
    currentProgress = {
      case_id: activeCase.case_id,
      case_revision: activeCase.case_revision,
      attempt_id: attemptId,
      sequence,
      stage: "opening",
      evidence_index: 0,
      responses: {},
      started_at: new Date().toISOString(),
    };
    persistProgress();
    recordEvent("case_started", {
      experience_type: activeCase.experience_type,
      investigation_mode: activeCase.investigation_mode,
    });
  }
  nextCaseButton.hidden = true;
  nextCaseButton.textContent = caseIndex.length > 1 ? "Next case" : "Restart case";
  await resumeCase();
}

async function resumeCase() {
  const stage = currentProgress?.stage || "opening";
  if (stage === "opening") {
    renderOpening();
  } else if (stage === "evidence") {
    renderEvidenceBeat(Number(currentProgress.evidence_index || 0));
  } else if (stage === "design") {
    renderDesignGate();
  } else if (stage === "intermission") {
    renderIntermission();
  } else if (stage === "reveal" || stage === "completed") {
    const payload = await fetchRevealPayload();
    if (reviewIsDue()) renderDelayedProbe(payload);
    else renderReveal(payload);
  } else {
    renderOpening();
  }
}

function renderOpening() {
  const pre = activeCase.pre_reveal;
  const opening = pre.opening;
  app.replaceChildren();
  statusText.textContent = "Commit before the evidence moves.";

  addText(app, "p", "case-number", "Unlabeled case / opening");
  addText(app, "h1", "", pre.mystery_title);
  addText(app, "p", "lede", opening.scene);

  const facts = element("div", "fact-grid");
  for (const observation of opening.observations || []) {
    facts.append(element("div", "fact", observation));
  }
  app.append(facts);
  list(app, opening.constraints, "constraint-list");
  addText(app, "p", "question", opening.central_question);

  const response = responseBlock(
    opening.commitment_prompt,
    opening.confidence_prompt,
  );
  fillResponse(response, storedResponse("opening"));
  app.append(response.fragment);
  const commit = primaryButton("Commit this model");
  commit.disabled = response.textarea.value.trim().length < 12;
  response.textarea.addEventListener("input", () => {
    commit.disabled = response.textarea.value.trim().length < 12;
    setResponse("opening", {
      response: response.textarea.value,
      confidence: Number(response.slider.value),
    });
  });
  response.slider.addEventListener("input", () => {
    setResponse("opening", {
      response: response.textarea.value,
      confidence: Number(response.slider.value),
    });
  });
  commit.addEventListener("click", () => {
    const saved = {
      response: response.textarea.value.trim(),
      confidence: Number(response.slider.value),
    };
    recordEvent("hypothesis_committed", {
      ...saved,
      stage: "opening",
    });
    setResponse("opening", saved);
    persistProgress({stage: "evidence", evidence_index: 0});
    renderEvidenceBeat(0);
  });
  app.append(commit);
  addText(
    app,
    "p",
    "privacy-note",
    "Pilot mode: your writing stays in this browser unless you export it.",
  );
}

function renderEvidenceBeat(index) {
  const beats = activeCase.pre_reveal.evidence_beats;
  if (index >= beats.length) {
    renderDesignGate();
    return;
  }
  const beat = beats[index];
  app.replaceChildren();
  statusText.textContent = `Evidence ${index + 1} of ${beats.length}`;

  const section = element("section", "beat");
  addText(section, "p", "section-label", `Evidence ${index + 1}`);
  addText(section, "h2", "", beat.title);
  addEvidence(section, beat.evidence);
  addText(section, "p", "question", beat.question);

  const hints = element("div", "hint-stack");
  const responseKey = `beat:${beat.beat_id}`;
  const savedBeat = storedResponse(responseKey);
  let hintIndex = Number(savedBeat?.hints_used || 0);
  for (const hint of (beat.hints || []).slice(0, hintIndex)) {
    hints.append(element("div", "hint", hint));
  }
  const hintButton = element("button", "hint-button", "Use one hint");
  hintButton.disabled = hintIndex >= (beat.hints || []).length;
  hintButton.addEventListener("click", () => {
    const hint = (beat.hints || [])[hintIndex];
    if (!hint) return;
    hints.append(element("div", "hint", hint));
    hintIndex += 1;
    recordEvent("hint_requested", {
      beat_id: beat.beat_id,
      hint_depth: hintIndex,
    });
    setResponse(responseKey, {
      response: storedResponse(responseKey)?.response || "",
      confidence: storedResponse(responseKey)?.confidence ?? 50,
      hints_used: hintIndex,
    });
    if (hintIndex >= beat.hints.length) hintButton.disabled = true;
  });
  section.append(hintButton, hints);

  const response = responseBlock("Your revised model", "Confidence");
  fillResponse(response, savedBeat);
  section.append(response.fragment);
  const commit = primaryButton(
    index === beats.length - 1 ? "Face the design constraint" : "Release next evidence",
  );
  commit.disabled = response.textarea.value.trim().length < 10;
  response.textarea.addEventListener("input", () => {
    commit.disabled = response.textarea.value.trim().length < 10;
    setResponse(responseKey, {
      response: response.textarea.value,
      confidence: Number(response.slider.value),
      hints_used: hintIndex,
    });
  });
  response.slider.addEventListener("input", () => {
    setResponse(responseKey, {
      response: response.textarea.value,
      confidence: Number(response.slider.value),
      hints_used: hintIndex,
    });
  });
  commit.addEventListener("click", () => {
    const saved = {
      response: response.textarea.value.trim(),
      confidence: Number(response.slider.value),
      hints_used: hintIndex,
    };
    recordEvent("model_revised", {
      beat_id: beat.beat_id,
      ...saved,
    });
    setResponse(responseKey, saved);
    const nextIndex = index + 1;
    if (nextIndex >= beats.length) {
      persistProgress({stage: "design", evidence_index: nextIndex});
      renderDesignGate();
    } else {
      persistProgress({stage: "evidence", evidence_index: nextIndex});
      renderEvidenceBeat(nextIndex);
    }
  });
  section.append(commit);
  app.append(section);
  window.scrollTo({top: 0, behavior: "smooth"});
}

function renderDesignGate() {
  const gate = activeCase.pre_reveal.design_gate;
  app.replaceChildren();
  statusText.textContent = "Build the missing mechanism.";

  addText(app, "p", "section-label", "Design gate");
  addText(app, "h2", "", "You have enough evidence.");
  addText(app, "p", "question", gate.prompt);
  list(app, gate.required_elements, "constraint-list");

  const response = responseBlock("Your proposed mechanism", gate.confidence_prompt);
  fillResponse(response, storedResponse("design"));
  app.append(response.fragment);
  const commit = primaryButton("Commit the design");
  commit.disabled = response.textarea.value.trim().length < 20;
  response.textarea.addEventListener("input", () => {
    commit.disabled = response.textarea.value.trim().length < 20;
    setResponse("design", {
      response: response.textarea.value,
      confidence: Number(response.slider.value),
    });
  });
  response.slider.addEventListener("input", () => {
    setResponse("design", {
      response: response.textarea.value,
      confidence: Number(response.slider.value),
    });
  });
  commit.addEventListener("click", () => {
    const saved = {
      response: response.textarea.value.trim(),
      confidence: Number(response.slider.value),
    };
    recordEvent("mechanism_proposed", saved);
    setResponse("design", saved);
    persistProgress({stage: "intermission"});
    renderIntermission();
  });
  app.append(commit);
}

function renderIntermission() {
  app.replaceChildren();
  statusText.textContent = "Intermission";
  const section = element("section", "intermission");
  addText(section, "p", "section-label", "The design already has a name");
  addText(section, "h2", "", "Earn the title.");
  addText(
    section,
    "p",
    "lede",
    "Now compare the mechanism you constructed with the established architecture.",
  );
  const revealButton = primaryButton("Reveal and formalize");
  revealButton.addEventListener("click", revealCase);
  section.append(revealButton);
  app.append(section);
}

function renderObjectCards(parent, values, titleField, bodyFields) {
  const container = element("div", "detail-list");
  for (const value of values || []) {
    const card = element("article", "detail-card");
    addText(card, "h3", "", value[titleField] || titleField);
    for (const [label, field] of bodyFields) {
      if (!value[field]) continue;
      addText(card, "p", "section-label", label);
      addText(card, "p", "", value[field]);
    }
    container.append(card);
  }
  parent.append(container);
}

async function fetchRevealPayload() {
  const response = await fetch(`./${activeRecord.reveal_url}`, {cache: "no-store"});
  if (!response.ok) throw new Error(`Could not load ${activeRecord.reveal_url}`);
  return response.json();
}

async function revealCase() {
  const payload = await fetchRevealPayload();
  recordEvent("title_revealed", {
    concept_id: payload.concept_id,
  });
  persistProgress({
    stage: "reveal",
    revealed_at: new Date().toISOString(),
  });
  renderReveal(payload);
}

function renderReveal(payload) {
  const reveal = payload.reveal;
  app.replaceChildren();
  app.className = "reveal";
  statusText.textContent = "Formalization and transfer";

  addText(app, "p", "section-label", "Intermission / title reveal");
  addText(app, "h1", "", reveal.canonical_name);
  addText(app, "p", "lede", reveal.earned_title);
  addText(app, "p", "", reveal.why_it_exists);

  const mechanism = element("section", "reveal-section");
  addText(mechanism, "p", "section-label", "Mechanism");
  addText(mechanism, "h2", "", "Trace it without hand-waving");
  const mechanismList = element("div", "mechanism-list");
  for (const step of reveal.mechanism || []) {
    const card = element("article", "mechanism-step");
    addText(card, "p", "section-label", `Step ${step.step}`);
    addText(card, "h3", "", step.name);
    addText(card, "p", "", step.explanation);
    mechanismList.append(card);
  }
  mechanism.append(mechanismList);
  app.append(mechanism);

  const formal = element("section", "reveal-section");
  addText(formal, "p", "section-label", "Canonical form");
  addText(formal, "h2", "", "What the mechanism means precisely");
  addText(formal, "p", "", reveal.formalization.definition);
  for (const equation of reveal.formalization.equations || []) {
    addText(formal, "pre", "equation", equation.latex);
    addText(formal, "p", "", equation.interpretation);
  }
  const trace = reveal.formalization.worked_trace;
  if (trace) {
    addText(formal, "h3", "", "Worked trace");
    addText(formal, "p", "", trace.setup);
    list(formal, trace.steps, "detail-list");
    addText(formal, "p", "", trace.result);
    addText(formal, "p", "lede", trace.architectural_meaning);
  }
  app.append(formal);

  const decisions = element("section", "reveal-section");
  addText(decisions, "p", "section-label", "Design review");
  addText(decisions, "h2", "", "Where the clean model starts fighting reality");
  renderObjectCards(
    decisions,
    reveal.tradeoffs,
    "axis",
    [["Gain", "gain"], ["Cost", "cost"], ["Choose it when", "decision_condition"]],
  );
  renderObjectCards(
    decisions,
    reveal.boundary_cases,
    "condition",
    [["Consequence", "consequence"], ["Diagnostic", "diagnostic"]],
  );
  renderObjectCards(
    decisions,
    reveal.common_misconceptions,
    "belief",
    [["Why it fails", "why_it_fails"], ["Replacement model", "replacement_model"]],
  );
  app.append(decisions);

  const transfer = element("section", "reveal-section");
  addText(transfer, "p", "section-label", "Transfer lab");
  addText(transfer, "h2", "", "Can the thought appear somewhere else?");
  for (const lab of payload.transfer_lab || []) {
    const card = element("article", "transfer-card");
    addText(card, "h3", "", lab.title);
    addText(card, "p", "", lab.scenario);
    addText(card, "p", "question", lab.task);
    list(card, lab.constraints, "constraint-list");
    const response = responseBlock("Your diagnosis or design", "Confidence");
    const responseKey = `transfer:${lab.lab_id}`;
    const savedTransfer = storedResponse(responseKey);
    fillResponse(response, savedTransfer);
    card.append(response.fragment);
    const solutionButton = element("button", "hint-button", "Commit and compare");
    const showSolution = () => {
      if (card.querySelector(".solution")) return;
      const solution = element("div", "solution");
      addText(solution, "p", "section-label", "Reasoning");
      addText(solution, "p", "", lab.solution.reasoning);
      addText(solution, "p", "section-label", "Tempting wrong path");
      addText(solution, "p", "", lab.solution.tempting_wrong_path);
      addText(solution, "p", "section-label", "Answer changes if");
      addText(solution, "p", "", lab.solution.answer_changes_if);
      card.append(solution);
      solutionButton.disabled = true;
      response.textarea.disabled = true;
      response.slider.disabled = true;
    };
    response.textarea.addEventListener("input", () => {
      setResponse(responseKey, {
        response: response.textarea.value,
        confidence: Number(response.slider.value),
        submitted: false,
      });
    });
    response.slider.addEventListener("input", () => {
      setResponse(responseKey, {
        response: response.textarea.value,
        confidence: Number(response.slider.value),
        submitted: false,
      });
    });
    solutionButton.addEventListener("click", () => {
      if (response.textarea.value.trim().length < 12) return;
      const saved = {
        response: response.textarea.value.trim(),
        confidence: Number(response.slider.value),
        submitted: true,
      };
      recordEvent("transfer_submitted", {
        lab_id: lab.lab_id,
        ...saved,
      });
      setResponse(responseKey, saved);
      showSolution();
    });
    card.append(solutionButton);
    if (savedTransfer?.submitted) showSolution();
    transfer.append(card);
  }
  app.append(transfer);

  const frontier = element("section", "reveal-section");
  addText(frontier, "p", "section-label", "Research frontier");
  addText(frontier, "h2", "", "What remains genuinely unsettled?");
  for (const item of payload.research_frontier || []) {
    const card = element("article", "frontier-card");
    addText(card, "h3", "", item.question);
    addText(card, "p", "section-label", "Unresolved tension");
    addText(card, "p", "", item.tension);
    addText(card, "p", "section-label", "Experiment");
    addText(card, "p", "", item.experiment);
    addText(card, "p", "section-label", "Success metric");
    addText(card, "p", "", item.success_metric);
    addText(card, "p", "section-label", "Hardest confounder");
    addText(card, "p", "", item.hardest_confounder);
    frontier.append(card);
  }
  app.append(frontier);

  const retention = element("section", "reveal-section memory-handle");
  addText(retention, "p", "section-label", "Retrieval handle");
  addText(retention, "h2", "", payload.retention.retrieval_trigger);
  addText(retention, "p", "", payload.retention.one_sentence_compression);
  if (currentProgress?.stage === "completed" && currentProgress.review_due_at) {
    addText(
      retention,
      "p",
      "review-due",
      currentProgress.review_completed_at
        ? "Closed-book review completed"
        : `Closed-book review: ${formatReviewDate(currentProgress.review_due_at)}`,
    );
  }
  app.append(retention);

  const complete = primaryButton("Close this investigation");
  if (currentProgress?.stage === "completed") {
    nextCaseButton.hidden = false;
    complete.disabled = true;
    complete.textContent = "Investigation saved";
  } else {
    complete.addEventListener("click", () => {
      const completedAt = new Date();
      const delayDays = Number(payload.retention.delayed_probe.delay_days || 4);
      const dueAt = new Date(
        completedAt.getTime() + delayDays * 24 * 60 * 60 * 1000,
      );
      recordEvent("case_completed", {
        delayed_probe_days: delayDays,
        review_due_at: dueAt.toISOString(),
      });
      persistProgress({
        stage: "completed",
        completed_at: completedAt.toISOString(),
        review_due_at: dueAt.toISOString(),
      });
      statusText.textContent = `Saved · closed-book review ${formatReviewDate(dueAt)}`;
      nextCaseButton.hidden = false;
      complete.disabled = true;
      complete.textContent = "Investigation saved";
    });
  }
  app.append(complete);
  window.scrollTo({top: 0, behavior: "smooth"});
}

function renderDelayedProbe(payload) {
  const probe = payload.retention.delayed_probe;
  app.className = "";
  app.replaceChildren();
  statusText.textContent = "Closed-book retrieval is due.";

  const panel = element("section", "review-panel");
  addText(panel, "p", "review-due", "Delayed review / no notes");
  addText(panel, "h1", "", "Can the mechanism return on demand?");
  addText(panel, "p", "lede", probe.changed_context);
  addText(panel, "p", "question", probe.prompt);

  const response = responseBlock(
    "Your closed-book reconstruction",
    "Retrieval confidence",
  );
  fillResponse(response, storedResponse("delayed_probe"));
  panel.append(response.fragment);
  const submit = primaryButton("Commit closed-book reconstruction");
  submit.disabled = response.textarea.value.trim().length < 20;
  response.textarea.addEventListener("input", () => {
    submit.disabled = response.textarea.value.trim().length < 20;
    setResponse("delayed_probe", {
      response: response.textarea.value,
      confidence: Number(response.slider.value),
      submitted: false,
    });
  });
  response.slider.addEventListener("input", () => {
    setResponse("delayed_probe", {
      response: response.textarea.value,
      confidence: Number(response.slider.value),
      submitted: false,
    });
  });
  submit.addEventListener("click", () => {
    const saved = {
      response: response.textarea.value.trim(),
      confidence: Number(response.slider.value),
      submitted: true,
    };
    recordEvent("delayed_retrieval_submitted", saved);
    setResponse("delayed_probe", saved);
    persistProgress({
      stage: "completed",
      review_completed_at: new Date().toISOString(),
    });
    response.textarea.disabled = true;
    response.slider.disabled = true;
    submit.disabled = true;
    submit.textContent = "Reconstruction saved";
    addText(panel, "p", "section-label", "Self-check criteria");
    list(panel, probe.success_criteria, "constraint-list");
    const returnButton = primaryButton("Return to the formalization");
    returnButton.addEventListener("click", () => renderReveal(payload));
    panel.append(returnButton);
    nextCaseButton.hidden = false;
    statusText.textContent = "Delayed retrieval recorded.";
  });
  panel.append(submit);
  addText(
    panel,
    "p",
    "privacy-note",
    "This reconstruction stays in this browser and is included in Export.",
  );
  app.append(panel);
  window.scrollTo({top: 0, behavior: "smooth"});
}

async function start() {
  try {
    const response = await fetch("./cases/index.json", {cache: "no-store"});
    if (!response.ok) throw new Error("No compiled cases are available yet.");
    const index = await response.json();
    const reviewMode = new URLSearchParams(window.location.search).has("review");
    caseIndex = (index.cases || []).filter((record) => (
      record.preview_status === "ready_for_reader"
      || (reviewMode && record.preview_status === "awaiting_human_review")
    ));
    if (!caseIndex.length) throw new Error("No compiled cases are available yet.");
    await loadCase(drawRecord());
  } catch (error) {
    app.replaceChildren();
    const empty = element("section", "empty-panel");
    addText(empty, "h2", "", "The lab is built. Its first case is not.");
    addText(
      empty,
      "p",
      "",
      "Run scripts/prepare_learning_cases.py, then reload this page.",
    );
    addText(empty, "p", "status", error.message);
    app.append(empty);
    statusText.textContent = "Waiting for a compiled case";
  }
}

nextCaseButton.addEventListener("click", async () => {
  if (caseIndex.length === 1 && activeCase) {
    clearProgress(activeCase.case_id);
  }
  app.className = "";
  await loadCase(drawRecord());
  window.scrollTo({top: 0, behavior: "smooth"});
});

exportDataButton.addEventListener("click", () => {
  const payload = {
    schema_version: "radar-learning-export-v1",
    exported_at: new Date().toISOString(),
    privacy: "Browser-local pilot data; no server-side learner account.",
    attempts: readStored(STORAGE.attempts, []),
    progress: progressMap(),
  };
  const blob = new Blob(
    [JSON.stringify(payload, null, 2)],
    {type: "application/json"},
  );
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `radar-learning-export-${new Date()
    .toISOString()
    .slice(0, 10)}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
  statusText.textContent = "Private learning history exported.";
});

start();
