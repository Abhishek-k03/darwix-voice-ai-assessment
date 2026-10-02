"""Expected-answer fast path (voice/quick.py) and the engine's approved fast replies. No LLM, no network."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from packs import load_pack
from voice.engine import FlowEngine
from voice.quick import number, resolve
from voice.state import CallState


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.pack = load_pack("in_health")
        self.state = CallState(pack_id="in_health")

    def ask(self, field: str, utterance: str, agent_said: str = "", exact: bool = True):
        self.state.awaiting, self.state.awaiting_exact = field, exact
        return resolve(self.pack, self.state, agent_said, utterance)

    def value(self, field: str, utterance: str, **kw):
        r = self.ask(field, utterance, **kw)
        return None if r is None else r["updates"][0]["value"]

    def test_yes_no_variants(self):
        for u in ("No.", "Nope, nothing.", "No, none of us have any pre-existing conditions.", "Nahi ji.",
                  "None of us have any preexisting conditions."):
            self.assertIs(self.value("pre_existing", u), False, u)
        for u in ("Yes.", "Yeah", "Haan ji.", "Yes, we do.", "Correct."):
            self.assertIs(self.value("pre_existing", u), True, u)
        self.assertIs(self.value("existing_cover", "No, I don't have any health insurance."), False)

    def test_hedges_extra_content_and_questions_go_to_the_llm(self):
        for u in ("I think so.", "Not sure.", "No, but my father has diabetes.", "Maybe.", "Yes, I have employer cover of 3 lakh.",
                  "Yes, through my employer.", "Is maternity covered?", "Okay."):
            self.assertIsNone(self.ask("pre_existing", u), u)  # "Okay." is not a factual yes

    def test_consent_accepts_soft_yes_and_no_means_busy(self):
        self.assertIs(self.value("good_time", "Sure, I have a few minutes."), True)
        self.assertIs(self.value("good_time", "Yes, this works."), True)
        r = self.ask("good_time", "No.")
        self.assertEqual((r["updates"][0]["value"], r["intents"]), (False, ["busy"]))
        self.assertIsNone(self.ask("good_time", "Not now, I'm driving."))

    def test_numbers_amounts_cities_names(self):
        self.assertEqual(self.value("age", "I'm 34 years old."), 34)
        self.assertEqual(self.value("age", "Thirty four."), 34)
        self.assertEqual(self.value("spouse_age", "She's 31."), 31)
        self.assertEqual(self.value("children_count", "Just one daughter."), 1)
        self.assertIsNone(self.ask("age", "34, Pune."))
        self.assertIsNone(self.ask("age", "34 and 31"))
        self.assertEqual(self.value("budget_annual_inr", "Around 20,000 rupees per year."), 20000)
        self.assertEqual(self.value("budget_annual_inr", "1.5 lakh"), 150000)
        self.assertEqual(self.value("budget_annual_inr", "2000 a month"), 24000)
        self.assertEqual(self.value("budget_annual_inr", "twenty thousand"), 20000)
        self.assertIsNone(self.ask("budget_annual_inr", "Maybe 5 or 6 thousand."))
        self.assertEqual(self.value("city", "I'm based in Pune."), "Pune")
        self.assertIsNone(self.ask("city", "Nashik"))  # unknown city: the LLM + confirm path handles it
        self.assertEqual(self.value("name", "Yeah, it's Ravi."), "Ravi")
        self.assertEqual(self.value("name", "My name is Ravi Sharma"), "Ravi Sharma")
        self.assertIsNone(self.ask("name", "Hi Mira, yes I have a few minutes"))

    def test_llm_worded_question_needs_the_fields_cues(self):
        self.assertIs(self.value("pre_existing", "No.", agent_said="Does anyone have diabetes or heart problems?",
                                 exact=False), False)
        self.assertIsNone(self.ask("pre_existing", "No.", agent_said="Sorry, are you still there?", exact=False))

    def test_identity_confirm_only_resolves_yes(self):
        pack, state = load_pack("id_multifinance"), CallState(pack_id="id_multifinance")
        state.awaiting, state.awaiting_exact = "identity_confirmed", True
        self.assertIs(resolve(pack, state, "", "Iya, betul.")["updates"][0]["value"], True)
        self.assertIsNone(resolve(pack, state, "", "Bukan."))  # spouse / wrong person: the LLM reads it

    def test_number_parser(self):
        self.assertEqual(number("one hundred and five".split()), None)  # "and" only after a scale word
        self.assertEqual(number("one lakh and fifty thousand".split()), 150000)
        self.assertIsNone(number("four thirty".split()))


class FastReplyTests(unittest.TestCase):
    def setUp(self):
        self.pack = load_pack("in_health")
        self.state = CallState(pack_id="in_health")
        self.engine = FlowEngine(self.pack, self.state)
        self.state.awaiting, self.state.awaiting_exact = "good_time", True

    def turn(self, utterance: str):
        q = resolve(self.pack, self.state, "", utterance)
        self.assertIsNotNone(q, utterance)
        d = self.engine.apply(q, None, utterance)
        self.state.awaiting_exact = bool(d.quick_reply)
        return d

    def test_plain_answers_get_approved_next_question(self):
        d = self.turn("Sure, I have a few minutes.")
        self.assertEqual(d.quick_reply, "Great, thank you. May I have your first name, please?")
        d = self.turn("Ravi.")
        self.assertTrue(d.quick_reply.startswith(("Nice to meet you, Ravi.", "Thank you, Ravi.")))
        self.assertIn("age", d.quick_reply)
        d = self.turn("34.")
        self.assertIn("city", d.quick_reply)
        self.assertEqual(self.state.awaiting, "city")

    def test_unknown_answer_or_conflict_falls_back_to_llm(self):
        self.turn("Yes.")
        self.turn("Ravi.")
        d = self.engine.apply({"updates": [{"field": "age", "value": 140, "confidence": 0.95}], "intents": ["answer"],
                               "quick": True}, None, "140")
        self.assertIsNone(d.quick_reply)  # invalid value: the LLM re-asks gently
        self.state.fields.pop("age", None)
        self.engine.apply({"updates": [{"field": "age", "value": 34, "confidence": 0.95}], "intents": ["answer"]}, None, "34")
        d = self.engine.apply({"updates": [{"field": "age", "value": 43, "confidence": 0.95}], "intents": ["answer"],
                               "quick": True}, None, "43")
        self.assertIsNone(d.quick_reply)
        self.assertIn("[CONFLICT]", d.note)

    def test_switch_off(self):
        with mock.patch.dict(os.environ, {"FAST_REPLIES": "off"}):
            self.assertIsNone(self.turn("Yes.").quick_reply)


if __name__ == "__main__":
    unittest.main()
