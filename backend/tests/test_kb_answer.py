"""Grounded answer composition for the knowledge page: parsing, citation validation, extractive fallback."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from kb import answer

HITS = [
    {"record_id": "kb_1", "title": "Waiting periods", "content": "Pre-existing conditions are covered after 24 months. Accidents are covered from day one.",
     "source": {"section": "Policy wording", "uri": "/policy.pdf"}, "dense": 0.91, "citation": "kb_1"},
    {"record_id": "kb_2", "title": "FAQ", "content": "The initial waiting period is 30 days.", "source": {}, "dense": 0.84, "citation": "faq"},
]


def llm_returning(text):
    async def fake(*_a, **_k):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
    return fake


class ParseTests(unittest.TestCase):
    def test_citations_follow_their_sentence_and_followups_split_off(self):
        paras, fu = answer.parse("Covered after 24 months [1]. Initial wait is 30 days [2].\n\nAsk an advisor.\nFOLLOWUPS:\n- Is maternity covered?\n- What is a co-payment?", 2)
        self.assertEqual([s.get("c") for s in paras[0]], [1, 2, None])
        self.assertEqual(paras[0][1]["t"], ". Initial wait is 30 days ")   # the full stop after [1] leads the next segment
        self.assertEqual(paras[1], [{"t": "Ask an advisor."}])
        self.assertEqual(fu, ["Is maternity covered?", "What is a co-payment?"])

    def test_invented_source_numbers_are_dropped(self):
        paras, _ = answer.parse("It is free [7].", 2)
        self.assertFalse(answer.cited(paras))

    def test_sources_carry_path_and_match_percent(self):
        s = answer.sources(HITS)
        self.assertEqual((s[0]["n"], s[0]["rel"], s[0]["path"]), (1, 91, "Policy wording › /policy.pdf"))
        self.assertEqual(s[1]["path"], "faq")


class ComposeTests(unittest.TestCase):
    def run_compose(self, fake):
        with mock.patch.object(answer, "create_completion", fake), mock.patch.object(answer, "_llm", lambda: (None, None)):
            return asyncio.run(answer.compose("waiting period?", HITS))

    def test_llm_answer_with_valid_citations_is_used(self):
        out = self.run_compose(llm_returning("Pre-existing conditions wait 24 months [1].\nFOLLOWUPS:\nWhat about accidents?"))
        self.assertEqual(out["mode"], "llm")
        self.assertEqual(out["followups"], ["What about accidents?"])

    def test_uncited_answer_falls_back_to_the_records_own_words(self):
        out = self.run_compose(llm_returning("It is probably around a year."))
        self.assertEqual(out["mode"], "extractive")
        self.assertIn("24 months", out["paragraphs"][0][0]["t"])

    def test_no_answer_marker_and_llm_failure(self):
        self.assertEqual(self.run_compose(llm_returning("NO_ANSWER"))["mode"], "no_answer")

        async def boom(*_a, **_k):
            raise RuntimeError("429")
        self.assertEqual(self.run_compose(boom)["mode"], "extractive")


if __name__ == "__main__":
    unittest.main()
