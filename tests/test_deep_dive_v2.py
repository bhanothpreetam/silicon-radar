#!/usr/bin/env python3

import unittest
from pathlib import Path
from unittest.mock import patch

from db.models import COMPACT_CARD_COLUMNS, insert_intelligence_card


ROOT = Path(__file__).resolve().parents[1]


class FakeRequest:
    def __init__(self):
        self.payload = None

    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        return type("Response", (), {"data": [{"id": 91}]})()


class FakeClient:
    def __init__(self):
        self.request = FakeRequest()
        self.table_name = None

    def table(self, name):
        self.table_name = name
        return self.request


class DeepDiveV2Tests(unittest.TestCase):
    def test_backend_compact_reads_exclude_long_form_json(self):
        self.assertNotIn("deep_dive", COMPACT_CARD_COLUMNS.split(","))

    def test_prompt_formats_with_python_format(self):
        template = (ROOT / "prompts" / "intelligence_card_v2.txt").read_text()
        rendered = template.format(
            raw_text="A cache metric article with {literal source braces}.",
            url="https://example.com/article",
            source_type="rss",
        )
        self.assertIn("A cache metric article", rendered)
        self.assertIn('"deep_dive": {', rendered)
        self.assertNotIn("{raw_text}", rendered)

    def test_v2_payload_persists_prompt_version_and_deep_dive(self):
        client = FakeClient()
        with patch("db.models.get_client", return_value=client):
            card_id = insert_intelligence_card(
                17,
                {
                    "one_line_summary": "A concise signal",
                    "prompt_version": "v2",
                    "deep_dive": {"thesis": "The bottleneck moved."},
                },
            )

        self.assertEqual(card_id, 91)
        self.assertEqual(client.table_name, "intelligence_cards")
        self.assertEqual(client.request.payload["prompt_version"], "v2")
        self.assertEqual(
            client.request.payload["deep_dive"],
            {"thesis": "The bottleneck moved."},
        )

    def test_v1_payload_does_not_require_optional_column(self):
        client = FakeClient()
        with patch("db.models.get_client", return_value=client):
            insert_intelligence_card(18, {"one_line_summary": "Legacy card"})

        self.assertEqual(client.request.payload["prompt_version"], "v1")
        self.assertNotIn("deep_dive", client.request.payload)


if __name__ == "__main__":
    unittest.main()
