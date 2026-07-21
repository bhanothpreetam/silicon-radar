#!/usr/bin/env python3
"""Browser smoke test for the vNext Mini App.

Uses mocked Supabase responses and real CDP touch input. This deliberately
tests the gesture path with hardware-level touch events instead of synthetic
DOM TouchEvents, which cannot verify native scrolling.
"""

import contextlib
import json
import os
import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
MINIAPP = ROOT / "miniapp"


DEEP_DIVE = {
    "article_type": "technical_explainer",
    "title": "HBM pressure moves the accelerator bottleneck into packaging",
    "subtitle": "More compute only matters when memory and assembly scale with it.",
    "reading_time_minutes": 11,
    "thesis": (
        "The constraint is no longer the GPU alone. Memory bandwidth, package yield, "
        "and assembly throughput now determine how much accelerator compute can ship."
    ),
    "source_assessment": {
        "evidence_quality": "strong_secondary",
        "confidence": "high",
        "limitations": "Supplier allocation data is directional rather than a complete market census.",
    },
    "evidence": [
        {
            "fact": "Memory capacity and packaging throughput tightened in the same delivery window.",
            "significance": "Adding GPU wafers cannot raise shipments if packaged HBM systems remain scarce.",
            "status": "reported",
        }
    ],
    "prerequisites": [
        {
            "term": "Memory bandwidth",
            "explanation": "Bandwidth is the rate at which operands can reach the compute fabric.",
            "why_it_matters_here": "Idle arithmetic units cannot convert theoretical FLOPS into useful throughput.",
        }
    ],
    "sections": [
        {
            "heading": "The bottleneck moved above the die",
            "kind": "mechanism",
            "content": (
                "Accelerator delivery is a pipeline: fabricate logic, fabricate memory, "
                "assemble the package, validate it, and integrate the server.\n\n"
                "Increasing capacity at one stage exposes the next constrained stage."
            ),
            "key_insight": "A faster GPU design has zero market value until the complete system can ship.",
        }
    ],
    "worked_examples": [
        {
            "title": "A constrained delivery pipeline",
            "setup": "Assume 100 GPU dies but packaging capacity for only 70 complete modules.",
            "steps": ["Start with 100 good dies", "Package 70 modules", "Leave 30 dies waiting"],
            "result": "Shipment capacity is 70 modules, so extra die supply does not improve delivery.",
        }
    ],
    "system_connections": [
        {
            "layer": "manufacturing",
            "connection": "HBM and logic must be assembled into one high-yield package.",
            "consequence": "Package yield becomes a system-level performance constraint.",
        }
    ],
    "tradeoffs": [
        {
            "decision": "Increase HBM bandwidth through wider interfaces",
            "gains": "More sustained accelerator utilization",
            "costs": "Package area, routing, power, and assembly complexity",
            "breaks_when": "The workload is compute-bound or packaging yield collapses",
        }
    ],
    "historical_arc": {
        "before": "Accelerators were discussed primarily as individual chips.",
        "change": "Model scale made memory and rack integration first-order constraints.",
        "now": "The deployable rack is the meaningful unit of compute.",
    },
    "industry_map": [
        {
            "actor": "Memory suppliers",
            "position": "They control qualified HBM volume.",
            "implication": "Their execution directly gates accelerator shipments.",
        }
    ],
    "research_frontier": {
        "state_of_the_art": "Systems co-design compute, memory, packaging, and software scheduling.",
        "bottlenecks": ["Thermal density", "Package yield"],
        "open_questions": ["How should runtimes adapt when memory capacity varies by deployment?"],
        "relevant_work": ["Search: heterogeneous accelerator memory scheduling"],
    },
    "aha_insights": [
        {
            "insight": "Manufacturing throughput can become an architectural property.",
            "why_non_obvious": "Architecture diagrams usually stop at the package boundary.",
        }
    ],
    "misconceptions": [
        {
            "misconception": "Peak FLOPS determines delivered AI capacity.",
            "correction": "Delivered capacity is bounded by the slowest stage from fabrication through deployment.",
        }
    ],
    "whiteboard_challenges": [
        {
            "question": "If package capacity rises 20% but HBM supply stays flat, what changes?",
            "why_it_matters": "It tests whether the reader identifies the active bottleneck.",
            "answer_outline": "Model each supply stage and take the minimum available throughput.",
        }
    ],
    "key_takeaways": [
        "The complete package, not the bare GPU, determines shippable compute.",
        "Optimizing one stage frequently exposes another bottleneck.",
    ],
    "explore_next": [
        {
            "topic": "Advanced packaging yield",
            "reason": "It connects physical assembly defects to system availability.",
            "resource_hint": "CoWoS yield and known-good-die testing",
        }
    ],
}


CARDS = [
    {
        "id": 101,
        "raw_item_id": 1,
        "one_line_summary": "HBM supply becomes the constraint that decides accelerator shipments",
        "what_happened": " ".join(["Memory capacity and packaging throughput tightened together."] * 55),
        "why_technical": "The memory wall is now a system delivery wall.",
        "why_strategic": "Allocation power shifts toward suppliers with packaging access.",
        "eli5_explanation": "A fast engine cannot ship without enough fuel tanks.",
        "textbook_bridge": "Bandwidth and capacity constraints compound at system level.",
        "rabbit_hole": "CoWoS capacity planning",
        "tech_layer": ["memory_hbm", "advanced_packaging"],
        "importance_score": 0.94,
        "notification_level": "wake_up",
        "generated_at": "2026-07-21T08:00:00Z",
        "notify": True,
        "prompt_version": "v2",
        "deep_dive": DEEP_DIVE,
    },
    {
        "id": 102,
        "raw_item_id": 2,
        "one_line_summary": "A new UCIe implementation lowers the cost of mixing chiplets",
        "what_happened": "A vendor published interoperability results.",
        "tech_layer": ["chiplets_ucie"],
        "importance_score": 0.79,
        "notification_level": "brief",
        "generated_at": "2026-07-21T07:00:00Z",
        "notify": True,
    },
    {
        "id": 103,
        "raw_item_id": 3,
        "one_line_summary": "Why cache coherence gets harder across chiplets",
        "what_happened": "A learning card connects coherence protocols to modern packages.",
        "tech_layer": ["microarchitecture"],
        "importance_score": 0.70,
        "notification_level": "ping",
        "generated_at": "2026-07-20T08:00:00Z",
        "notify": True,
    },
    {
        "id": 104,
        "raw_item_id": 4,
        "one_line_summary": "A probation source spots a useful EDA workflow change",
        "what_happened": "The candidate source surfaced a concrete compiler improvement.",
        "tech_layer": ["eda_vlsi"],
        "importance_score": 0.69,
        "notification_level": "ping",
        "generated_at": "2026-07-19T08:00:00Z",
        "notify": True,
    },
]

ITEMS = [
    {"id": 1, "title": "HBM update", "url": "https://example.com/hbm", "source_id": 11},
    {"id": 2, "title": "UCIe update", "url": "https://example.com/ucie", "source_id": 12},
    {"id": 3, "title": "[Learning] Cache coherence", "url": "https://example.com/learn", "source_id": 13},
    {"id": 4, "title": "EDA update", "url": "https://example.com/eda", "source_id": 14},
]

SOURCES = [
    {"id": 11, "name": "Memory Wire", "status": "trusted"},
    {"id": 12, "name": "Interconnect Review", "status": "trusted"},
    {"id": 13, "name": "Radar Learning", "status": "trusted"},
    {"id": 14, "name": "Candidate EDA", "status": "probation"},
]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass


@contextlib.contextmanager
def serve_miniapp():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(MINIAPP), **kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join()


def route_api(route):
    url = route.request.url
    headers = {"access-control-allow-origin": "*", "content-type": "application/json"}
    if "telegram.org/js/" in url:
        route.fulfill(status=200, content_type="application/javascript", body="")
    elif route.request.method == "POST" and "/feedback" in url:
        route.fulfill(status=201, headers=headers, body="{}")
    elif "/intelligence_cards?" in url:
        route.fulfill(status=200, headers=headers, body=json.dumps(CARDS))
    elif "/raw_items?" in url:
        route.fulfill(status=200, headers=headers, body=json.dumps(ITEMS))
    elif "/sources?" in url:
        route.fulfill(status=200, headers=headers, body=json.dumps(SOURCES))
    elif "/feedback?" in url:
        route.fulfill(status=200, headers=headers, body="[]")
    else:
        route.continue_()


def touch(cdp, event_type, x, y):
    points = [] if event_type == "touchEnd" else [{"x": x, "y": y}]
    cdp.send("Input.dispatchTouchEvent", {"type": event_type, "touchPoints": points})


def run():
    with serve_miniapp() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            has_touch=True,
            is_mobile=True,
        )
        page = context.new_page()
        page.route("**/*", route_api)
        page.goto(base_url, wait_until="networkidle")

        assert page.locator(".card").count() == 4
        assert page.locator('[data-lens-count="all"]').inner_text() == "4"
        assert page.locator('[data-lens-count="priority"]').inner_text() == "2"
        assert page.locator('[data-lens-count="learning"]').inner_text() == "1"
        assert page.locator('[data-lens-count="probation"]').inner_text() == "1"

        page.get_by_text("Priority", exact=True).click()
        assert page.locator(".card").count() == 2
        assert page.locator("#counter").inner_text() == "1 / 2"

        page.get_by_text("Learn", exact=True).click()
        assert page.locator(".card").count() == 1
        assert "cache coherence" in page.locator(".card-title").inner_text().lower()

        page.get_by_text("Trial", exact=True).click()
        assert page.locator(".card").count() == 1
        assert page.locator(".badge.probation").count() == 1

        # Switching to a superset preserves the selected card. Move through a
        # lens that excludes the trial card so the touch checks start at card 1.
        page.get_by_text("Priority", exact=True).click()
        page.get_by_text("All", exact=True).click()
        assert page.locator("#counter").inner_text() == "1 / 4"
        assert page.locator(".more-btn").first.inner_text().startswith("Deep dive")
        page.locator(".more-btn").first.click()
        assert page.locator(".card").first.evaluate("el => el.classList.contains('expanded')")
        assert page.locator(".deep-dive").count() == 1
        assert "package" in page.locator(".deep-thesis").inner_text().lower()
        assert page.locator(".foundation-card").count() == 1
        assert page.locator(".challenge-card").count() == 1
        assert page.locator("#header").is_hidden()
        if screenshot_path := os.getenv("MINIAPP_SCREENSHOT"):
            page.screenshot(path=screenshot_path, full_page=False)
        page.locator(".foundation-card summary").click()
        assert page.locator(".foundation-card").evaluate("el => el.open")
        page.locator(".detail-scroll").first.evaluate(
            "el => { el.scrollTop = 300; el.dispatchEvent(new Event('scroll')); }"
        )
        assert page.locator(".detail-read-progress").first.evaluate(
            "el => parseFloat(el.style.width) > 0"
        )
        page.locator(".close-btn").first.click()
        assert page.locator("#header").is_visible()

        # Real touch: a horizontal gesture that begins inside the independently
        # scrollable description must still advance the feed. The brief is the
        # nearest scroll container, so the touch-action contract must live there.
        cdp = context.new_cdp_session(page)
        brief = page.locator(".card-brief").first
        brief_box = brief.bounding_box()
        assert brief_box
        swipe_y = int(brief_box["y"] + brief_box["height"] / 2)
        swipe_start_x = int(brief_box["x"] + brief_box["width"] - 25)
        assert page.evaluate(
            "([x, y]) => document.elementFromPoint(x, y).closest('.card-brief') !== null",
            [swipe_start_x, swipe_y],
        )
        touch(cdp, "touchStart", swipe_start_x, swipe_y)
        touch(cdp, "touchMove", swipe_start_x - 110, swipe_y + 2)
        touch(cdp, "touchMove", swipe_start_x - 230, swipe_y + 4)
        touch(cdp, "touchEnd", swipe_start_x - 230, swipe_y + 4)
        page.wait_for_timeout(500)
        assert page.locator("#counter").inner_text() == "2 / 4"

        # Return to the long first card. A vertical gesture must produce native
        # scroll in the brief instead of being stolen by the swipe handler.
        page.keyboard.press("ArrowLeft")
        page.wait_for_timeout(500)
        assert page.locator("#counter").inner_text() == "1 / 4"
        brief = page.locator(".card-brief").first
        box = brief.bounding_box()
        assert box and brief.evaluate("el => el.scrollHeight > el.clientHeight")
        x = int(box["x"] + box["width"] / 2)
        start_y = int(box["y"] + min(box["height"] - 20, 180))
        touch(cdp, "touchStart", x, start_y)
        page.wait_for_timeout(40)
        for step in range(1, 8):
            touch(cdp, "touchMove", x + min(step, 5), start_y - step * 22)
            page.wait_for_timeout(25)
        touch(cdp, "touchEnd", x + 5, start_y - 140)
        page.wait_for_timeout(500)
        scroll_state = page.locator(".card").first.evaluate(
            """el => ({
                briefTop: el.querySelector('.card-brief').scrollTop,
                briefHeight: el.querySelector('.card-brief').clientHeight,
                briefScrollHeight: el.querySelector('.card-brief').scrollHeight,
                faceTop: el.querySelector('.card-face').scrollTop,
                faceHeight: el.querySelector('.card-face').clientHeight,
                faceScrollHeight: el.querySelector('.card-face').scrollHeight,
            })"""
        )
        assert scroll_state["briefTop"] > 0, scroll_state

        # A history/BFCache restore refreshes stale data. If the reader is in a
        # deep dive, defer the rerender until it closes; then preserve that card
        # while prepending the newly generated card.
        page.locator(".more-btn").first.click()
        assert page.locator(".card.expanded").count() == 1
        new_card = {
            **CARDS[1],
            "id": 105,
            "raw_item_id": 5,
            "one_line_summary": "A newly generated card arrives while the reader is studying",
            "generated_at": "2026-07-21T09:00:00Z",
        }
        CARDS.insert(0, new_card)
        ITEMS.append({
            "id": 5,
            "title": "New architecture signal",
            "url": "https://example.com/new-signal",
            "source_id": 12,
        })
        page.evaluate(
            "window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))"
        )
        page.wait_for_timeout(150)
        assert page.locator(".card").count() == 4
        assert page.locator(".card.expanded").count() == 1
        page.locator(".close-btn").first.click()
        page.wait_for_function("document.querySelectorAll('.card').length === 5")
        assert page.locator("#counter").inner_text() == "2 / 5"
        assert page.locator("#refresh-notice").inner_text() == "1 new card · swipe right"
        assert page.locator("#refresh-notice").evaluate("el => el.classList.contains('show')")
        page.keyboard.press("ArrowLeft")
        page.wait_for_timeout(400)
        assert page.locator("#counter").inner_text() == "1 / 5"
        assert "newly generated" in page.locator(".card-title").first.inner_text().lower()

        # The deployable preview fixture must exercise the full reader without
        # touching Supabase or posting demo reactions into production data.
        demo_posts = []
        page.on(
            "request",
            lambda request: demo_posts.append(request.url)
            if request.method == "POST" else None,
        )
        page.goto(f"{base_url}/?demo=deep", wait_until="networkidle")
        assert page.locator(".card").count() == 1
        assert "cache miss rates" in page.locator(".card-title").inner_text().lower()
        page.locator(".more-btn").click()
        assert "Cache Miss Rates" in page.locator(".guided-hero h2").inner_text()
        assert page.locator(".guided-chapter").count() >= 4
        assert page.locator(".transfer-problem").count() >= 2
        assert page.locator(".frontier-proposal").count() >= 1
        demo_reveal = page.locator(".guided-reveal").first
        assert not demo_reveal.get_attribute("open")
        demo_reveal.locator("summary").click()
        assert demo_reveal.get_attribute("open") is not None
        if demo_screenshot_path := os.getenv("DEMO_PREVIEW_SCREENSHOT"):
            page.screenshot(path=demo_screenshot_path, full_page=False)
        page.locator('.fb-btn[data-reaction="brain"]').last.click()
        page.wait_for_timeout(100)
        assert demo_posts == []

        page.goto(f"{base_url}/?demo=actual", wait_until="networkidle")
        assert page.locator(".card").count() == 2
        page.locator(".more-btn").first.click()
        assert page.locator(".guided-article").count() == 2
        assert page.locator(".card.expanded .guided-chapter").count() >= 4
        first_reveal = page.locator(".card.expanded .guided-reveal").first
        assert not first_reveal.get_attribute("open")
        first_reveal.locator("summary").click()
        assert first_reveal.get_attribute("open") is not None
        assert page.locator(".card.expanded .transfer-problem").count() >= 2
        assert page.locator(".card.expanded .frontier-proposal").count() >= 1
        first_solution = page.locator(".card.expanded .transfer-solution").first
        first_solution.locator("summary").click()
        assert first_solution.locator("strong").count() >= 1
        assert "**" not in first_solution.inner_text()
        if actual_screenshot_path := os.getenv("ACTUAL_PREVIEW_SCREENSHOT"):
            page.screenshot(path=actual_screenshot_path, full_page=False)

        browser.close()
        print("Mini App vNext smoke test passed")


if __name__ == "__main__":
    run()
