"""Flow engine + business rules (Q1). Deterministic: no LLM, no network."""

from __future__ import annotations

import unittest

from packs import load_pack
from voice import rules
from voice.engine import FlowEngine
from voice.speech_format import idr_spoken, inr_spoken, php_spoken
from voice.state import CallState, merge


def ext(intents=("answer",), **updates) -> dict:
    return {"intents": list(intents), "updates": [{"field": k, "value": v, "confidence": 0.9} for k, v in updates.items()],
            "objection": None, "sentiment": 0.1}


KB_OK = {"status": "ok", "hits": [{"record_id": "kb_in_faq_002"}], "llm_context": "[kb_in_faq_002] Monthly mode..."}
KB_NONE = {"status": "no_match", "hits": [], "llm_context": "NO_RELEVANT_INFO"}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.pack = load_pack("in_health")
        self.state = CallState(pack_id="in_health")
        self.engine = FlowEngine(self.pack, self.state)

    def run_turns(self, *turns):
        d = None
        for e in turns:
            d = self.engine.apply(e, None, "")
        return d

    def test_cooperative_flow_reaches_recommendation_with_disclosure(self):
        d = self.run_turns(ext(), ext(name="Ravi"), ext(age=34), ext(city="Pune"), ext(cover_for="self"),
                           ext(pre_existing=False), ext(tobacco=False), ext(existing_cover=False), ext(budget_annual_inr=15000))
        self.assertEqual(self.state.stage, "NEXT_STEP")
        self.assertIn("[ELIGIBILITY] eligible for Prithvi Secure", d.note)
        self.assertIn("30-day initial waiting period", d.note)
        self.assertTrue(self.state.disclosed_waiting_period)
        self.assertEqual(self.state.eligibility["grade"], "hot")

    def test_declined_callback_closes_without_a_second_push(self):
        self.run_turns(ext(), ext(name="Ravi"), ext(age=34), ext(city="Pune"), ext(cover_for="self"),
                       ext(pre_existing=False), ext(tobacco=False), ext(existing_cover=False), ext(budget_annual_inr=5000))
        self.assertEqual(self.state.awaiting, "lowest_option")
        self.engine.apply(ext(), None, "No")
        self.assertEqual(self.state.awaiting, "callback_consent")
        d = self.engine.apply(ext(intents=("objection",)), KB_NONE, "Too expensive for me. No callback for now.")
        self.assertIs(self.state.get("callback_consent"), False)
        self.assertTrue(d.end_call)

    def test_asks_next_missing_field_in_order(self):
        d = self.run_turns(ext(), ext(name="Ravi"))
        self.assertIn("customer's age", d.note)

    def test_conflicting_age_requires_confirmation_then_correction(self):
        self.run_turns(ext(name="Ravi"), ext(age=34))
        d = self.engine.apply(ext(age=43), None, "I'm 43")
        self.assertIn("[CONFLICT]", d.note)
        self.assertEqual(self.state.get("age"), 34)
        self.engine.apply(ext(age=43), None, "43 is right")
        self.assertEqual(self.state.get("age"), 43)
        self.assertEqual(self.state.resolved_conflicts[0]["old"], 34)

    def test_unknown_budget_skipped_after_max_attempts(self):
        self.run_turns(ext(name="A"), ext(age=30), ext(city="Pune"), ext(cover_for="self"), ext(pre_existing=False), ext(tobacco=False),
                       ext(existing_cover=True))
        d = None
        for _ in range(2):  # 1st ask happened on the previous turn; 2nd = rephrase; 3rd attempt -> skip
            d = self.engine.apply(ext(), None, "not sure")
        self.assertIn("budget_annual_inr", self.engine.skipped)
        self.assertIn("[ELIGIBILITY]", d.note)
        self.assertEqual(self.state.eligibility["grade"], "warm")

    def test_human_request_escalates_with_script_line(self):
        d = self.engine.apply(ext(intents=("human_request",)), None, "let me talk to a real person")
        self.assertEqual(d.actions[0][0], "escalate")
        self.assertEqual(d.say_exactly, self.pack.line("escalation"))
        self.assertTrue(self.state.escalated)

    def test_dnc_ends_call(self):
        d = self.engine.apply(ext(intents=("dnc",)), None, "don't call me again")
        self.assertTrue(d.end_call and self.state.dnc)

    def test_question_with_knowledge_vs_without(self):
        d = self.engine.apply(ext(intents=("question",)), KB_OK, "can I pay monthly?")
        self.assertIn("[KNOWLEDGE]", d.note)
        self.assertEqual(d.knowledge_used, ["kb_in_faq_002"])
        d = self.engine.apply(ext(intents=("question",)), KB_NONE, "do you cover pets?")
        self.assertIn(self.pack.line("fallback"), d.note)

    def test_repeated_unanswerable_questions_offer_human(self):
        self.engine.apply(ext(intents=("question",)), KB_NONE, "q1?")
        d = self.engine.apply(ext(intents=("question",)), KB_NONE, "q2?")
        self.assertIn("licensed advisor", d.note)

    def test_invalid_value_rejected(self):
        self.assertEqual(merge(self.state, self.pack, "age", 140, 0.9), "invalid")
        self.assertIsNone(self.state.get("age"))

    def test_waiting_for_advisor_holds_once_then_stays_quiet(self):
        self.engine.apply(ext(intents=("human_request",)), KB_NONE, "Connect me to a real person.")
        d = self.engine.apply(ext(intents=("answer",)), KB_NONE, "Okay, I'll wait.")
        self.assertEqual(d.say_exactly, self.pack.line("escalation_hold"))
        d = self.engine.apply(ext(intents=("other",)), KB_NONE, "Hello?")
        self.assertTrue(d.silent)

    def test_out_of_scope_question_gets_out_of_scope_line_not_kb_fallback(self):
        d = self.engine.apply(ext(intents=("question", "out_of_scope")), KB_NONE, "Do you also do car insurance?")
        self.assertIn("[OUT OF SCOPE]", d.note)
        self.assertEqual(self.state.fallback_streak, 0)

    def test_customer_goodbye_closes_instead_of_continuing(self):
        self.run_turns(ext(name="Anita"), ext(age=29))
        d = self.engine.apply(ext(intents=("goodbye",)), KB_NONE, "Thanks. Have a good day.")
        self.assertTrue(d.end_call)
        self.assertEqual(d.say_exactly, self.pack.line("closing"))

    def test_adding_members_widens_cover_without_conflict(self):
        merge(self.state, self.pack, "cover_for", "self_spouse", 0.9)
        self.assertEqual(merge(self.state, self.pack, "cover_for", "family", 0.9), "widened")
        self.assertFalse(self.state.pending_conflicts)
        self.assertEqual(merge(self.state, self.pack, "cover_for", "self", 0.9), "conflict")

    def test_reconfirming_old_value_clears_conflict_and_questions_still_answered(self):
        merge(self.state, self.pack, "children_count", 1, 0.9)
        self.assertEqual(merge(self.state, self.pack, "children_count", 2, 0.9), "conflict")
        d = self.engine.apply(ext(intents=("question",)), KB_OK, "Is maternity covered too?")
        self.assertIn("[KNOWLEDGE]", d.note)
        self.assertIn("[CONFLICT]", d.note)
        self.assertEqual(merge(self.state, self.pack, "children_count", 1, 0.9), "confirmed")
        self.assertFalse(self.state.pending_conflicts)

    def test_slow_extraction_is_merged_late_not_lost(self):
        import asyncio
        from unittest import mock

        from voice import extract

        async def slow(_messages):
            await asyncio.sleep(0.1)
            return {**extract.EMPTY, "updates": [{"field": "budget_annual_inr", "value": 20000, "confidence": 0.9}]}

        async def run():
            with mock.patch.object(extract, "_call", slow), mock.patch.object(extract, "TIMEOUT_S", 0.01):
                out = await extract.extract_turn(self.pack, self.state, "Budget?", "Around 20,000 a year.")
                self.assertEqual(out["updates"], [])
                self.engine.merge_updates((await out["late"])["updates"])

        asyncio.run(run())
        self.assertEqual(self.state.get("budget_annual_inr"), 20000)

    def test_unknown_city_confirmed_once_then_replaced_without_conflict(self):
        d = self.engine.apply(ext(city="Ten"), KB_NONE, "Ten.")
        self.assertEqual(d.say_exactly, "Sorry, did you say Ten?")
        d = self.engine.apply(ext(city="Pune"), KB_NONE, "Pune.")
        self.assertEqual(self.state.get("city"), "Pune")
        self.assertFalse(self.state.pending_conflicts)
        self.assertNotIn("[CHECK]", d.note)

    def test_callback_time_read_from_words_when_extraction_returns_nothing(self):
        self.run_turns(ext(name="A"), ext(age=30), ext(city="Pune"), ext(cover_for="self"), ext(pre_existing=False), ext(tobacco=False),
                       ext(existing_cover=False), ext(budget_annual_inr=15000))
        d = self.engine.apply(ext(intents=("callback_request",)), KB_NONE, "Yes. Tomorrow evening.")
        self.assertEqual(self.state.callback["when"], "Tomorrow evening")
        self.assertTrue(d.end_call and "Tomorrow evening" in d.say_exactly)

    def test_unlisted_name_is_read_back_then_confirmed_or_redone(self):
        d = self.engine.apply(ext(name="Kieran"), KB_NONE, "Kieran")
        self.assertEqual(d.say_exactly, "Sorry, did I get your name right, Kieran?")
        self.assertEqual(self.state.checking, "name")
        self.engine.apply(ext(), None, "Yes")
        self.assertEqual(self.state.fields["name"].confidence, 0.95)
        self.assertEqual(self.state.get("name"), "Kieran")

    def test_rejected_readback_drops_name_and_asks_again(self):
        self.engine.apply(ext(name="Kieran"), KB_NONE, "Kieran")
        d = self.engine.apply(ext(), None, "No")
        self.assertIsNone(self.state.get("name"))
        self.assertIn("[CHECK]", d.note)

    def test_listed_name_needs_no_confirmation(self):
        d = self.engine.apply(ext(name="Abhishek"), KB_NONE, "Abhishek")
        self.assertFalse(d.say_exactly)
        self.assertNotIn("[CHECK]", d.note)

    def test_implausible_yearly_premium_budget_is_read_back_then_confirmed_or_redone(self):
        d = self.engine.apply(ext(budget_annual_inr=500000), KB_NONE, "total budget 5 lakh and otherwise 15000")
        self.assertEqual(d.say_exactly, "Just to confirm, you would like to spend about five lakh rupees a year on the premium, is that right?")
        self.engine.apply(ext(), None, "No")
        self.assertIsNone(self.state.get("budget_annual_inr"))
        self.engine.apply(ext(budget_annual_inr=15000), None, "fifteen thousand a year")
        self.assertEqual(self.state.get("budget_annual_inr"), 15000)
        self.assertEqual(self.state.fields["budget_annual_inr"].confidence, 0.9)

    def test_ordinary_budget_is_not_questioned(self):
        d = self.engine.apply(ext(budget_annual_inr=15000), KB_NONE, "15000")
        self.assertFalse(d.say_exactly and "Just to confirm" in d.say_exactly)

    def reach_budget_question(self, city="Jaipur"):
        self.run_turns(ext(), ext(name="Ravi"), ext(age=34), ext(city=city), ext(cover_for="self"),
                       ext(pre_existing=False), ext(tobacco=False), ext(existing_cover=False))
        self.assertEqual(self.state.awaiting, "budget_annual_inr")

    def test_unsure_about_budget_offers_real_plan_options_and_a_pick_sets_the_budget(self):
        from voice.quick import resolve
        self.reach_budget_question()
        d = self.engine.apply(ext(), None, "I don't know")
        self.assertEqual(self.state.awaiting, "budget_choice")
        self.assertEqual(len(self.state.options), 3)
        premiums = [o["premium"] for o in self.state.options]
        self.assertEqual(premiums, sorted(premiums))
        self.assertIn("Which one would you like to try?", d.say_exactly)
        self.assertIn("the second is a", d.say_exactly)
        quick = resolve(self.pack, self.state, d.say_exactly, "the second one")
        chosen = self.state.options[1]
        self.assertEqual({u["field"]: u["value"] for u in quick["updates"]},
                         {"preferred_sum_insured_lakh": chosen["si"], "budget_annual_inr": chosen["premium"]})
        d = self.engine.apply(quick, None, "the second one")
        self.assertEqual(self.state.stage, "NEXT_STEP")
        self.assertEqual(self.state.eligibility["sum_insured_lakh"], chosen["si"])
        self.assertEqual(self.state.eligibility["grade"], "hot")

    def test_a_zone_a_city_is_offered_the_two_sizes_its_rules_allow(self):
        self.reach_budget_question(city="Pune")
        d = self.engine.apply(ext(), None, "no idea")
        self.assertEqual([o["si"] for o in self.state.options], [10, 25])
        self.assertIn("the first is a ten lakh cover", d.say_exactly)

    def test_option_picks_by_ordinal_size_price_and_word(self):
        from voice.quick import pick_option
        o = [{"si": 3, "premium": 5000}, {"si": 5, "premium": 7000}, {"si": 10, "premium": 9300}]
        for said, si in (("the first", 3), ("second", 5), ("option 3", 10), ("ten lakh", 10), ("5 lakh please", 5),
                         ("the cheapest", 3), ("the biggest one", 10), ("9300", 10), ("seven thousand", 5), ("the second one", 5)):
            self.assertEqual(pick_option(said, o)["si"], si, said)
        for said in ("I don't know", "none of them", "maybe", "what is co-payment"):
            self.assertIsNone(pick_option(said, o), said)

    def test_question_while_unsure_is_answered_first_options_come_next_turn(self):
        self.reach_budget_question()
        d = self.engine.apply(ext(intents=("question",)), KB_OK, "Not sure. Is maternity covered?")
        self.assertIn("[KNOWLEDGE]", d.note)
        self.assertFalse(d.say_exactly)
        self.assertFalse(self.state.options)

    def test_still_unclear_after_the_options_the_budget_is_skipped(self):
        self.reach_budget_question()
        self.engine.apply(ext(), None, "I don't know")
        self.engine.apply(ext(), None, "hmm no idea")
        self.assertIn("budget_annual_inr", self.engine.skipped)

    def test_budget_below_the_cheapest_plan_gets_the_lowest_option_with_the_disclosure_first(self):
        from voice.quick import resolve
        self.reach_budget_question(city="Pune")
        d = self.engine.apply(ext(budget_annual_inr=5000), None, "5000")
        self.assertEqual(self.state.awaiting, "lowest_option")
        self.assertLess(d.say_exactly.index("waiting period"), d.say_exactly.index("a year"))
        self.assertIn("ten lakh cover at about nine thousand three hundred rupees a year", d.say_exactly)
        self.assertTrue(self.state.disclosed_waiting_period)
        quick = resolve(self.pack, self.state, d.say_exactly, "Yes, okay")
        self.assertEqual(quick["updates"], [])
        self.engine.apply(quick, None, "Yes, okay")
        self.assertEqual((self.state.get("budget_annual_inr"), self.state.get("preferred_sum_insured_lakh")), (9280, 10))
        self.assertEqual(self.state.eligibility["grade"], "hot")
        self.assertFalse(self.state.pending_conflicts)

    def test_declining_the_lowest_option_keeps_the_customers_budget_and_grades_warm(self):
        self.reach_budget_question(city="Pune")
        self.engine.apply(ext(budget_annual_inr=5000), None, "5000")
        self.engine.apply(ext(), None, "No, that's too much")
        self.assertEqual(self.state.get("budget_annual_inr"), 5000)
        self.assertEqual(self.state.eligibility["grade"], "warm")
        self.assertIn("budget gap", " ".join(self.state.eligibility["reasons"]))

    def test_a_budget_that_fits_is_never_second_guessed(self):
        self.reach_budget_question(city="Pune")
        self.engine.apply(ext(budget_annual_inr=10000), None, "10000")
        self.assertFalse(self.state.lowest_offered)
        self.assertEqual(self.state.stage, "NEXT_STEP")

    def test_question_in_the_same_turn_is_answered_first_then_the_lowest_option_is_said_exactly(self):
        self.reach_budget_question(city="Pune")
        d = self.engine.apply(ext(intents=("question",), budget_annual_inr=5000), KB_OK, "5000. Is maternity covered?")
        self.assertIn("[KNOWLEDGE]", d.note)
        self.assertIn("say exactly this", d.note)
        self.assertEqual(self.state.awaiting, "lowest_option")

    def test_offer_lines_never_quote_before_disclosing_the_waiting_period(self):
        from copilot.pipeline import load_config
        from copilot.signals_rules import RuleDetector
        from copilot.events import Utterance, now_ms

        det = RuleDetector(load_config(self.pack))
        self.reach_budget_question(city="Jaipur")
        for said, budget in (("I don't know", None), ("", 3000)):
            engine = FlowEngine(self.pack, CallState(pack_id="in_health"))
            engine.state.fields = dict(self.state.fields)
            engine.state.fields.pop("budget_annual_inr", None)
            engine.state.turn = self.state.turn
            if budget:
                merge(engine.state, self.pack, "budget_annual_inr", budget, 0.9)
                d = engine.apply(ext(), None, "x")
            else:
                engine.state.ask_attempts["budget_annual_inr"] = 1
                d = engine.apply(ext(), None, said)
            t = now_ms()
            out = det.on_utterance(Utterance(speaker="agent", text=d.say_exactly, final=True, utterance_id=str(t),
                                             audio_received_at=t, asr_at=t, confidence=0.99))
            self.assertNotIn("compliance_gap", [s.type for s in out], d.say_exactly)

    def test_an_answer_the_llm_had_to_read_still_gets_the_approved_next_question(self):
        """'occasional smoke' is not a plain yes/no: the LLM extracted it, but the next question must still be the engine's."""
        self.run_turns(ext(), ext(name="Abhishek"), ext(age=21), ext(city="Delhi"), ext(cover_for="self"), ext(pre_existing=False))
        d = self.engine.apply(ext(tobacco=True), KB_NONE, "occasional smoke")          # no "quick" flag: read by the LLM
        self.assertIn("health insurance", d.quick_reply)
        self.assertNotIn("budget", d.quick_reply.lower())

    def test_callback_time_is_read_back_as_a_sentence(self):
        from voice.speech_format import when_spoken
        for said, want in (("sunday 3pm", "on Sunday at 3 PM"), ("tomorrow evening", "tomorrow evening"),
                           ("weekend, evening", "on the weekend, in the evening"), ("6 pm", "at 6 PM"), ("tomorrow 8 pm", "tomorrow at 8 PM")):
            self.assertEqual(when_spoken(said), want)

    def test_unlisted_city_is_read_back_by_the_script_and_confirmed_by_a_plain_yes(self):
        from voice.quick import resolve
        self.run_turns(ext(), ext(name="Raj"), ext(age=27))
        d = self.engine.apply(ext(city="Sonipat"), KB_NONE, "sonipat")
        self.assertEqual(d.say_exactly, "Sorry, did you say Sonipat?")
        quick = resolve(self.pack, self.state, d.say_exactly, "yes")
        self.assertIsNotNone(quick)
        d = self.engine.apply(quick, None, "yes")
        self.assertEqual(self.state.fields["city"].confidence, 0.95)
        self.assertIn("cover for", d.quick_reply.lower())

    def test_a_plain_answer_that_matches_a_record_still_gets_the_fast_scripted_reply(self):
        self.run_turns(ext(), ext(name="Raj"), ext(age=27), ext(city="Pune"))
        d = self.engine.apply(ext(cover_for="family"), KB_OK, "whole family")          # KB hit on the family floater
        self.assertTrue(d.quick_reply)
        d2 = self.engine.apply(ext(spouse_age=31), KB_OK, "31 is maternity cover too")  # garbled question: knowledge still offered
        self.assertIn("[KNOWLEDGE", d2.note)

    def test_a_customer_outside_india_hears_why_and_the_call_ends_itself(self):
        self.run_turns(ext(), ext(name="Raj"), ext(age=20))
        d = self.engine.apply({**ext(), "outside_market": True}, KB_NONE, "oklahoma")
        self.assertIn("India only", d.say_exactly)
        self.assertTrue(d.end_call)
        self.assertEqual(self.state.outcome, "out_of_market")

    def test_extraction_flag_is_read_whether_top_level_or_filed_as_an_update(self):
        import asyncio
        from types import SimpleNamespace
        from unittest import mock

        from voice import extract

        def fake(payload):
            async def create(*_a, **_k):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])
            return create

        for payload in ('{"updates":[],"intents":["answer"],"outside_market":true}',
                        '{"updates":[{"field":"city","value":"London"},{"field":"outside_market","value":true}],"intents":["answer"]}'):
            with mock.patch.object(extract, "create_completion", fake(payload)), mock.patch.object(extract, "_get_client", lambda: (None, None)):
                out = asyncio.run(extract._call([]))
            self.assertTrue(out["outside_market"], payload)
            self.assertNotIn("outside_market", [u["field"] for u in out["updates"]])

    def test_the_agents_own_name_is_accepted_only_as_the_answer_to_your_name(self):
        self.engine.apply(ext(), None, "hi")                                  # greeting answered; now the name is awaited
        self.assertEqual(self.state.awaiting, "name")
        self.engine.apply(ext(name="Mira"), None, "Mira")
        self.assertEqual(self.state.get("name"), "Mira")
        other = FlowEngine(self.pack, CallState(pack_id="in_health"))
        other.apply(ext(name="Mira"), None, "Hi Mira, is this a good time?")   # addressing the agent, not telling their name
        self.assertIsNone(other.state.get("name"))


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.pack = load_pack("in_health")

    def state(self, **fields):
        s = CallState(pack_id="in_health")
        for k, v in fields.items():
            merge(s, self.pack, k, v, 0.9)
        return s

    def test_family_floater_zone_and_rate(self):
        e = rules.evaluate(self.state(age=34, spouse_age=31, children_count=1, cover_for="family", city="Lucknow",
                                      budget_annual_inr=20000), self.pack)
        self.assertEqual(e["product"], "Prithvi FamilyShield")
        self.assertEqual(e["zone"], "B")
        self.assertEqual(e["sum_insured_lakh"], 5)
        self.assertEqual(e["indicative_premium_inr"], round(10660 * 0.9))  # 26-35 base 6400 x 1.85 x 0.9 -> 10660

    def test_flagged_rate_never_quoted(self):
        e = rules.evaluate(self.state(age=50, cover_for="self", city="Mumbai", budget_annual_inr=30000), self.pack)
        self.assertIsNone(e["indicative_premium_inr"])
        self.assertIn("advisor to quote", " ".join(e["reasons"]))

    def test_unknown_age_or_parents_ages_hand_over_to_an_advisor_instead_of_crashing(self):
        e = rules.evaluate(self.state(cover_for="self", city="Pune"), self.pack)
        self.assertEqual((e["eligible"], e["grade"], e["refer_underwriter"]), (False, "incomplete", True))
        e = rules.evaluate(self.state(cover_for="parents", city="Pune"), self.pack)
        self.assertEqual(e["grade"], "incomplete")
        self.assertNotIn("above 75", " ".join(e["reasons"]))

    def test_senior_moves_to_silver_with_copay(self):
        e = rules.evaluate(self.state(age=68, cover_for="self", city="Pune"), self.pack)
        self.assertEqual(e["product"], "Prithvi Silver")
        self.assertEqual(e["co_payment_percent"], 20)

    def test_serious_treatment_refers_to_underwriter(self):
        e = rules.evaluate(self.state(age=40, cover_for="self", serious_treatment=True), self.pack)
        self.assertFalse(e["eligible"])
        self.assertTrue(e["refer_underwriter"])

    def test_spoken_amounts(self):
        self.assertEqual(inr_spoken(11320), "eleven thousand three hundred rupees")
        self.assertEqual(php_spoken(1850), "one thousand eight hundred fifty pesos")
        self.assertEqual(idr_spoken(1250000), "satu juta dua ratus lima puluh ribu rupiah")


if __name__ == "__main__":
    unittest.main()
