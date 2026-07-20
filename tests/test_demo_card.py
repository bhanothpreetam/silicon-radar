#!/usr/bin/env python3

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DemoCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.card = json.loads((ROOT / "miniapp" / "demo-card.json").read_text())
        cls.deep = cls.card["deep_dive"]

    def test_compact_contract(self):
        self.assertLessEqual(len(self.card["one_line_summary"]), 110)
        self.assertEqual(self.card["prompt_version"], "v2-preview")
        self.assertTrue(self.card["notify"])

    def test_reference_exercises_guided_reader(self):
        self.assertEqual(self.deep["format"], "guided_article_v1")
        self.assertGreaterEqual(len(self.deep["chapters"]), 4)
        self.assertTrue(self.deep["opening"]["initial_prompt"])
        self.assertGreaterEqual(len(self.deep["transfer_lab"]), 2)
        self.assertTrue(self.deep["research_frontiers"])
        self.assertTrue(self.deep["retention"]["tomorrow_question"])


if __name__ == "__main__":
    unittest.main()
