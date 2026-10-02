"""Hindi/Hinglish pack: loader inheritance, number words, fast path, turn lexicon, copilot patterns, name read-back."""

from __future__ import annotations

import re
import unittest

import yaml

from copilot.pipeline import load_config
from packs import PACKS_DIR, load_pack
from turn_arbiter import _fast_path_classify
from voice import hindi, rules
from voice.engine import FlowEngine
from voice.quick import resolve
from voice.state import CallState, merge

from .test_engine import KB_NONE, ext


class HindiPackTests(unittest.TestCase):
    def setUp(self):
        self.pack = load_pack("in_health_hi")
        self.state = CallState(pack_id="in_health_hi")
        self.engine = FlowEngine(self.pack, self.state)

    def test_pack_inherits_rules_and_overrides_language(self):
        en = load_pack("in_health")
        self.assertEqual([f.name for f in self.pack.fields], [f.name for f in en.fields])
        self.assertEqual((self.pack.language, self.pack.turn_lexicon, self.pack.tts[0]["provider"]), ("hi", "hi", "sarvam"))
        self.assertIn("नमस्ते", self.pack.line("greeting"))
        self.assertEqual(self.pack.line("ack_tobacco"), "")                      # no ack_tobacco anywhere: generic ack used
        self.assertIn("तंबाकू", self.pack.field("tobacco").cues)
        self.assertTrue(self.pack.field("name").known)                           # names list inherited from the base pack

    def test_every_english_script_line_has_a_hindi_version(self):
        def keys(pack_id):
            return set(yaml.safe_load((PACKS_DIR / pack_id / "script.yaml").read_text(encoding="utf-8")))

        self.assertEqual(keys("in_health") - keys("in_health_hi"), set())

    def test_indian_number_words(self):
        self.assertEqual(hindi.words(7500), "सात हज़ार पाँच सौ")
        self.assertEqual(hindi.words(1_000_000), "दस लाख")
        self.assertEqual(hindi.words(250_000), "दो लाख पचास हज़ार")
        self.assertEqual(hindi.inr_spoken(14920), "चौदह हज़ार नौ सौ रुपये")

    def test_quote_is_spoken_in_hindi_for_this_pack_only(self):
        for k, v in dict(name="Abhishek", age=34, city="Pune", cover_for="self", pre_existing=False, tobacco=False,
                         existing_cover=False, budget_annual_inr=15000).items():
            merge(self.state, self.pack, k, v, 0.9)
        e = rules.evaluate(self.state, self.pack)
        self.assertRegex(e["premium_spoken"], "रुपये")
        self.assertRegex(e["sum_insured_spoken"], "लाख")
        en = load_pack("in_health")
        self.assertIn("rupees", rules.evaluate(self.state, en)["premium_spoken"])

    def test_fast_path_reads_devanagari_yes_no(self):
        self.state.awaiting, self.state.awaiting_exact = "pre_existing", True
        for said, want in (("नहीं।", False), ("हाँ जी।", True), ("नहीं, कोई नहीं है।", False), ("nahi ji", False)):
            r = resolve(self.pack, self.state, "", said)
            self.assertIsNotNone(r, said)
            self.assertIs(r["updates"][0]["value"], want, said)
        for said in ("पता नहीं", "शायद", "नहीं पर मेरे पापा को है"):
            self.assertIsNone(resolve(self.pack, self.state, "", said), said)

    def test_devanagari_name_goes_to_the_llm_not_the_fast_path(self):
        self.state.awaiting, self.state.awaiting_exact = "name", True
        self.assertIsNone(resolve(self.pack, self.state, "", "मेरा नाम अभिषेक है"))
        self.assertEqual(resolve(self.pack, self.state, "", "mera naam Rahul hai")["updates"][0]["value"], "Rahul")

    def test_hindi_question_cues_are_required_for_llm_worded_questions(self):
        self.state.awaiting, self.state.awaiting_exact = "age", False
        self.assertIsNone(resolve(self.pack, self.state, "आप किस शहर में रहते हैं?", "21"))
        self.assertEqual(resolve(self.pack, self.state, "आपकी उम्र कितनी है?", "21")["updates"][0]["value"], 21)

    def test_turn_lexicon_knows_hindi_backchannels_and_open_clauses(self):
        self.assertTrue(_fast_path_classify("हाँ जी", "hi").is_backchannel)
        self.assertTrue(_fast_path_classify("मेरे पापा और", "hi").requires_pause_extension)
        self.assertTrue(_fast_path_classify("मेरी उम्र बत्तीस है।", "hi").is_complete_turn)

    def test_unlisted_name_is_read_back_in_hindi(self):
        d = self.engine.apply(ext(name="Kieran"), KB_NONE, "Kieran")
        self.assertEqual(d.say_exactly, "माफ़ कीजिए, क्या आपका नाम Kieran है?")

    def test_hindi_callback_time_booked_when_extraction_is_empty(self):
        for k, v in dict(name="Abhishek", age=34, city="Pune", cover_for="self", pre_existing=False, tobacco=False,
                         existing_cover=False, budget_annual_inr=15000).items():
            self.engine.apply(ext(**{k: v}), KB_NONE, "x")
        d = self.engine.apply(ext(intents=("callback_request",)), KB_NONE, "हाँ जी, कल शाम को")
        self.assertTrue(d.end_call)
        self.assertEqual(d.say_exactly, "ठीक है, लाइसेंस प्राप्त सलाहकार आपको कल शाम कॉल करेंगे। आपके समय के लिए धन्यवाद, अपना ध्यान रखिए।")

    def test_roman_hindi_callback_times_are_read_in_devanagari(self):
        from voice.hindi import when_spoken
        for said, want in (("kal 7 bje", "कल 7 बजे"), ("kal shaam", "कल शाम"), ("7 pm", "शाम 7 बजे"), ("tomorrow evening", "कल शाम"),
                           ("कल शाम", "कल शाम")):
            self.assertEqual(when_spoken(said), want)

    def test_hello_to_the_good_time_question_is_asked_again_once_in_both_languages(self):
        for pid, expect in (("in_health_hi", "अच्छा समय"), ("in_health", "good time")):
            pack = load_pack(pid)
            state = CallState(pack_id=pid)
            state.awaiting = "good_time"
            engine = FlowEngine(pack, state)
            d = engine.apply(ext(intents=("greeting",)), KB_NONE, "Hello")
            self.assertIn(expect, d.say_exactly)
            self.assertEqual(state.awaiting, "good_time")
            d = engine.apply(ext(intents=("greeting",)), KB_NONE, "Hello")      # a second hello moves on instead of looping
            self.assertFalse(d.say_exactly and expect in d.say_exactly)

    def test_conflict_question_names_the_field_in_hindi(self):
        self.engine.apply(ext(age=34), KB_NONE, "34")
        d = self.engine.apply(ext(age=43), KB_NONE, "43")
        self.assertIn("उम्र", d.note)


class HindiCopilotTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(load_pack("in_health_hi"))

    def hits(self, signal: str, text: str) -> bool:
        return any(re.search(p, text, re.I) for p in self.cfg["signals"][signal]["patterns"])

    def test_english_patterns_are_kept_and_hindi_added(self):
        self.assertTrue(self.hits("human", "I want to talk to a real person"))
        self.assertTrue(self.hits("human", "मुझे किसी इंसान से बात करनी है"))
        self.assertIn("nudges", self.cfg)

    def test_budget_question_is_not_a_quote_but_the_quote_is(self):
        self.assertFalse(self.hits("quote", "आप सालाना प्रीमियम में लगभग कितना ख़र्च करना चाहेंगे?"))
        self.assertTrue(self.hits("quote", "सालाना प्रीमियम लगभग सात हज़ार पाँच सौ रुपये होगा।"))

    def test_disclosures_and_risky_statements(self):
        self.assertTrue(self.hits("recording_disclosed", "यह कॉल क्वालिटी और ट्रेनिंग के लिए रिकॉर्ड की जा रही है"))
        self.assertTrue(self.hits("waiting_disclosed", "इसमें तीस दिन का वेटिंग पीरियड है"))
        self.assertTrue(self.hits("risky_guaranteed", "क्लेम की गारंटी है, मंज़ूर होगा"))
        self.assertTrue(self.hits("cross_sell_parents", "मेरे माता-पिता भी हैं"))


if __name__ == "__main__":
    unittest.main()
