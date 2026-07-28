#!/usr/bin/env python3
"""Browser smoke test for the isolated learning runtime.

The fixture is synthetic. No textbook source, Gemini call, Supabase access, or
production Mini App state is involved.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def fixture_payloads():
    case_id = "case-browser-smoke-r001"
    pre = {
        "case_id": case_id,
        "case_revision": 1,
        "experience_type": "frontier",
        "corpus_version": "synthetic-v1",
        "investigation_mode": "synthetic timing trace",
        "pre_reveal": {
            "mystery_title": "Three writes, one impossible ordering",
            "opening": {
                "scene": "A synthetic processor trace contains three operations.",
                "observations": ["Operation A waits.", "Operation B is ready."],
                "constraints": ["Final values must match program order."],
                "central_question": "Which ordering constraint is accidental?",
                "commitment_prompt": "Commit to a falsifiable explanation.",
                "confidence_prompt": "Confidence",
            },
            "evidence_beats": [
                {
                    "beat_id": f"e{index}",
                    "title": f"Trace fragment {index}",
                    "evidence": f"Synthetic observation {index}.",
                    "question": f"What does observation {index} eliminate?",
                    "response_mode": "explain",
                    "hints": ["Use the constraint.", "Track values.", "Compare names."],
                }
                for index in range(1, 4)
            ],
            "design_gate": {
                "prompt": "Construct a mechanism that removes accidental ordering.",
                "required_elements": ["preserve values", "recover state"],
                "confidence_prompt": "Confidence",
            },
        },
    }
    reveal = {
        "case_id": case_id,
        "case_revision": 1,
        "experience_type": "frontier",
        "corpus_version": "synthetic-v1",
        "concept_id": "synthetic-concept",
        "reveal": {
            "canonical_name": "Synthetic mechanism",
            "earned_title": "A browser-only title",
            "why_it_exists": "This synthetic mechanism exists only to test the UI.",
            "mechanism": [
                {"step": 1, "name": "Observe", "explanation": "Observe state."},
                {"step": 2, "name": "Separate", "explanation": "Separate identities."},
            ],
            "formalization": {
                "definition": "A synthetic definition.",
                "equations": [],
                "worked_trace": {
                    "setup": "Synthetic setup.",
                    "steps": ["Step one.", "Step two."],
                    "result": "Synthetic result.",
                    "architectural_meaning": "The UI rendered a trace.",
                },
            },
            "tradeoffs": [
                {
                    "axis": "Test complexity",
                    "gain": "Coverage",
                    "cost": "Fixture size",
                    "decision_condition": "Use in browser smoke tests.",
                },
                {
                    "axis": "Isolation",
                    "gain": "Privacy",
                    "cost": "No technical evaluation",
                    "decision_condition": "Use before external generation.",
                },
            ],
            "boundary_cases": [
                {
                    "condition": "JavaScript is disabled",
                    "consequence": "No progression",
                    "diagnostic": "The opening never renders.",
                }
            ],
            "common_misconceptions": [
                {
                    "belief": "This fixture teaches architecture.",
                    "why_it_fails": "It contains synthetic content.",
                    "replacement_model": "It tests runtime behavior only.",
                }
            ],
        },
        "transfer_lab": [
            {
                "lab_id": f"t{index}",
                "title": f"Synthetic transfer {index}",
                "scenario": "A changed browser fixture.",
                "task": "Explain the changed behavior.",
                "constraints": ["No external data."],
                "required_measurement": "Network requests",
                "falsifying_observation": "Reveal fetched early",
                "solution": {
                    "reasoning": "Inspect request order.",
                    "tempting_wrong_path": "Inspect only visible text.",
                    "answer_changes_if": "The payload is inlined.",
                },
            }
            for index in range(1, 3)
        ],
        "research_frontier": [
            {
                "question": "Can this runtime remain resumable?",
                "tension": "State size versus fidelity",
                "why_existing_techniques_are_insufficient": "This is a fixture.",
                "experiment": "Reload between beats.",
                "success_metric": "Exact restored state",
                "hardest_confounder": "Browser storage policy",
            },
            {
                "question": "Can hints remain adaptive?",
                "tension": "Privacy versus evaluation",
                "why_existing_techniques_are_insufficient": "No evaluator is connected.",
                "experiment": "Replay synthetic attempts.",
                "success_metric": "Correct branch selection",
                "hardest_confounder": "Ambiguous free-form answers",
            },
        ],
        "retention": {
            "retrieval_trigger": "A reveal arrives before commitment",
            "one_sentence_compression": "Keep answer delivery separate.",
            "delayed_probe": {
                "delay_days": 4,
                "changed_context": "Another browser",
                "prompt": "Reconstruct the delivery boundary.",
                "success_criteria": ["pre/reveal separation"],
            },
        },
    }
    index = {
        "schema_version": "1.0.0",
        "cases": [
            {
                "case_id": case_id,
                "case_revision": 1,
                "experience_type": "frontier",
                "pre_url": f"cases/{case_id}/pre.json",
                "reveal_url": f"cases/{case_id}/reveal.json",
                "preview_status": "ready_for_reader",
            }
        ],
    }
    return index, pre, reveal


def main() -> None:
    index, pre, reveal = fixture_payloads()
    case_id = pre["case_id"]
    bodies = {
        "": (
            (ROOT / "miniapp" / "learning" / "index.html").read_text(),
            "text/html",
        ),
        "index.html": (
            (ROOT / "miniapp" / "learning" / "index.html").read_text(),
            "text/html",
        ),
        "style.css": (
            (ROOT / "miniapp" / "learning" / "style.css").read_text(),
            "text/css",
        ),
        "app.js": (
            (ROOT / "miniapp" / "learning" / "app.js").read_text(),
            "application/javascript",
        ),
        "cases/index.json": (json.dumps(index), "application/json"),
        f"cases/{case_id}/pre.json": (json.dumps(pre), "application/json"),
        f"cases/{case_id}/reveal.json": (json.dumps(reveal), "application/json"),
    }
    requested: list[str] = []

    def fulfill(route):
        path = urlparse(route.request.url).path.lstrip("/")
        body = bodies.get(path)
        if body:
            route.fulfill(status=200, body=body[0], content_type=body[1])
        else:
            route.fulfill(status=404, body="not found")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.route("**/*", fulfill)
        page.on("request", lambda request: requested.append(request.url))
        page.goto("http://localhost/", wait_until="networkidle")
        assert "Three writes" in page.locator("h1").inner_text()
        assert not any(url.endswith("/reveal.json") for url in requested)

        page.locator("textarea").fill(
            "My falsifiable model preserves values but separates names."
        )
        page.get_by_role("button", name="Commit this model").click()
        for index in range(1, 4):
            assert f"Evidence {index} of 3" in page.locator("#status").inner_text()
            page.locator("textarea").fill(
                f"Observation {index} eliminates one accidental ordering."
            )
            page.locator(".primary-button").click()

        page.locator("textarea").fill(
            "Allocate distinct identities, preserve values, and retain recovery state."
        )
        page.get_by_role("button", name="Commit the design").click()
        assert not any(url.endswith("/reveal.json") for url in requested)

        page.get_by_role("button", name="Reveal and formalize").click()
        page.wait_for_selector("h1")
        assert page.locator("h1").inner_text() == "Synthetic mechanism"
        assert any(url.endswith("/reveal.json") for url in requested)

        event_types = page.evaluate(
            """
            JSON.parse(
              localStorage.getItem('radar.learning.preview.attempts.v1')
            ).map(event => event.event_type)
            """
        )
        assert "hypothesis_committed" in event_types
        assert event_types.count("model_revised") == 3
        assert "mechanism_proposed" in event_types
        assert "title_revealed" in event_types
        browser.close()

    print("Learning Lab smoke test passed.")


if __name__ == "__main__":
    main()
