#!/usr/bin/env python3

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "miniapp" / "actual-preview-cards.json"


class ActualPreviewCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards = json.loads(PREVIEW.read_text())

    def test_bounded_real_evaluation_set(self):
        self.assertGreaterEqual(len(self.cards), 1)
        self.assertLessEqual(len(self.cards), 3)
        self.assertEqual(len({card["raw_item_id"] for card in self.cards}), len(self.cards))

    def test_every_card_exercises_v2_reader(self):
        for card in self.cards:
            with self.subTest(raw_item_id=card["raw_item_id"]):
                self.assertLessEqual(len(card["one_line_summary"]), 110)
                self.assertEqual(card["prompt_version"], "v2-preview")
                deep = card["deep_dive"]
                self.assertGreaterEqual(len(deep["sections"]), 4)
                self.assertGreaterEqual(len(deep["prerequisites"]), 2)
                self.assertGreaterEqual(len(deep["tradeoffs"]), 2)
                self.assertTrue(deep["research_frontier"]["open_questions"])
                self.assertTrue(deep["whiteboard_challenges"])


if __name__ == "__main__":
    unittest.main()
