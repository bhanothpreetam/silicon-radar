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
        self.assertEqual(self.card["prompt_version"], "v2")
        self.assertTrue(self.card["notify"])

    def test_reference_exercises_research_reader(self):
        self.assertGreaterEqual(len(self.deep["sections"]), 5)
        self.assertGreaterEqual(len(self.deep["prerequisites"]), 3)
        self.assertGreaterEqual(len(self.deep["tradeoffs"]), 3)
        self.assertGreaterEqual(len(self.deep["whiteboard_challenges"]), 3)
        self.assertGreaterEqual(len(self.deep["key_takeaways"]), 5)


if __name__ == "__main__":
    unittest.main()
