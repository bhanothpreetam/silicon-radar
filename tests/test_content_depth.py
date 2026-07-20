#!/usr/bin/env python3

import unittest

from collectors.collector import MAX_RAW_TEXT_CHARS, _rss_body, _truncate


class ContentDepthTests(unittest.TestCase):
    def test_rss_uses_full_content_instead_of_short_summary(self):
        entry = {
            "summary": "Short teaser.",
            "content": [
                {
                    "value": (
                        "<article><h2>Mechanism</h2><p>The complete technical "
                        "argument explains the workload and bottleneck.</p></article>"
                    )
                }
            ],
        }

        body = _rss_body(entry)
        self.assertIn("complete technical argument", body)
        self.assertNotIn("<article>", body)

    def test_source_budget_supports_long_form_analysis(self):
        source = "x" * (MAX_RAW_TEXT_CHARS + 500)
        self.assertEqual(len(_truncate(source)), MAX_RAW_TEXT_CHARS)
        self.assertGreater(MAX_RAW_TEXT_CHARS, 8_000)


if __name__ == "__main__":
    unittest.main()
