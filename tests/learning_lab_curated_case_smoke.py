#!/usr/bin/env python3
"""Exercise the curated case through the real isolated Learning Lab UI."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "learning_lab"


def main() -> None:
    index = json.loads((LAB / "cases" / "index.json").read_text())
    candidates = [
        record
        for record in index["cases"]
        if record["preview_status"] in {"awaiting_human_review", "ready_for_reader"}
        and record["case_revision"] == 6
    ]
    assert len(candidates) == 1, candidates
    record = candidates[0]
    case_id = record["case_id"]
    query = "?review=1" if record["preview_status"] == "awaiting_human_review" else ""

    paths = {
        "": (LAB / "index.html", "text/html"),
        "index.html": (LAB / "index.html", "text/html"),
        "style.css": (LAB / "style.css", "text/css"),
        "app.js": (LAB / "app.js", "application/javascript"),
        "cases/index.json": (LAB / "cases" / "index.json", "application/json"),
        record["pre_url"]: (LAB / record["pre_url"], "application/json"),
        record["reveal_url"]: (LAB / record["reveal_url"], "application/json"),
    }
    requested: list[str] = []

    def fulfill(route):
        path = urlparse(route.request.url).path.lstrip("/")
        resource = paths.get(path)
        if resource:
            route.fulfill(
                status=200,
                body=resource[0].read_text(encoding="utf-8"),
                content_type=resource[1],
            )
        else:
            route.fulfill(status=404, body="not found")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.route("**/*", fulfill)
        page.on("request", lambda request: requested.append(request.url))
        page.goto(f"http://localhost/{query}", wait_until="networkidle")

        assert page.locator("h1").inner_text() == "The Overlapping Operations Anomaly"
        assert not any(url.endswith("/reveal.json") for url in requested)

        page.locator("textarea").fill(
            "I predict each free stage can accept a different operation without conflict."
        )
        page.get_by_role("button", name="Commit this model").click()

        assert page.locator(".evidence-table").count() == 1
        assert page.locator(".evidence-table tbody tr").count() == 3
        assert "|---|" not in page.locator(".evidence").inner_text()

        for beat in range(1, 5):
            assert f"Evidence {beat} of 4" in page.locator("#status").inner_text()
            page.locator("textarea").fill(
                f"My revised model for beat {beat} preserves stage exclusivity and timing."
            )
            page.locator(".primary-button").click()

        assert page.locator("#status").inner_text() == "Build the missing mechanism."
        page.locator("textarea").fill(
            "Use distinct concurrent stages, admit work when its stage is free, "
            "and stall on an unavailable operand or resource."
        )
        page.get_by_role("button", name="Commit the design").click()
        assert not any(url.endswith("/reveal.json") for url in requested)

        page.get_by_role("button", name="Reveal and formalize").click()
        page.wait_for_selector("h1")
        assert page.locator("h1").inner_text() == "Instruction pipelining and overlap"
        assert any(url.endswith("/reveal.json") for url in requested)
        body = page.locator("body").inner_text()
        assert "[c1]" not in body
        assert "[pipe-f" not in body
        assert "The Design That Appears to Dominate" in body
        assert "When a CPI Residual Pretends to Be a Cause" in body
        assert "Can a CPI decomposition uniquely attribute lost overlap" in body

        events = page.evaluate(
            """
            (caseId) =>
            JSON.parse(
              localStorage.getItem('radar.learning.preview.attempts.v1')
            ).filter(event => event.case_id === caseId)
            """,
            case_id,
        )
        event_types = [event["event_type"] for event in events]
        assert event_types.count("model_revised") == 4
        assert "mechanism_proposed" in event_types
        assert "title_revealed" in event_types

        normal = browser.new_page(viewport={"width": 390, "height": 844})
        normal.route("**/*", fulfill)
        normal.goto("http://localhost/", wait_until="networkidle")
        assert normal.locator("h1").inner_text() == "The Overlapping Operations Anomaly"
        assert "Paged address translation" not in normal.locator("body").inner_text()
        browser.close()

    print(f"Curated Learning Lab case smoke test passed: {case_id}")


if __name__ == "__main__":
    main()
