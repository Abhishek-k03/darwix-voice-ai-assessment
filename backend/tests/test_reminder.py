"""Q3 reminder flows (PH premium reminder, ID installment reminder): verification, privacy, resolution paths."""

from __future__ import annotations

import unittest

from crm import SEED_CUSTOMERS
from packs import load_pack
from voice.engine import FlowEngine
from voice.state import CallState


def ext(intents=("answer",), **updates) -> dict:
    return {"intents": list(intents), "updates": [{"field": k, "value": v, "confidence": 0.9} for k, v in updates.items()],
            "objection": None, "sentiment": 0.0}


def customer(pack_id: str) -> dict:
    from datetime import date, timedelta
    data = dict(next(d for _, p, d in SEED_CUSTOMERS if p == pack_id))
    data["due_date"] = (date.today() + timedelta(days=data["due_in_days"])).isoformat()
    return data


class PhilippinesReminderTests(unittest.TestCase):
    def setUp(self):
        self.pack = load_pack("ph_life")
        self.state = CallState(pack_id="ph_life", customer=customer("ph_life"))
        self.engine = FlowEngine(self.pack, self.state)

    def test_dob_verification_then_taglish_account_note(self):
        d = self.engine.apply(ext(), None, "Opo, ako po si Maria.")
        self.assertIn("date of birth", d.note)
        d = self.engine.apply(ext(dob_given="1989-03-12"), None, "March 12, 1989 po")
        self.assertIn("five thousand five hundred fifty pesos", d.note)
        self.assertIn("grace period until", d.note)

    def test_wrong_dob_twice_closes_without_disclosure(self):
        self.engine.apply(ext(), None, "opo")
        self.engine.apply(ext(dob_given="1990-01-01"), None, "January 1, 1990")
        d = self.engine.apply(ext(dob_given="1991-01-01"), None, "ay, 1991 pala")
        self.assertEqual(self.state.outcome, "verification_failed")
        self.assertEqual(d.say_exactly, self.pack.line("verify_fail"))
        self.assertNotIn("pesos", d.note)

    def test_promise_to_pay_via_gcash(self):
        self.engine.apply(ext(), None, "opo")
        self.engine.apply(ext(dob_given="1989-03-12"), None, "March 12, 1989")
        self.engine.apply(ext(payment_intent="will_pay"), None, "Opo, babayaran ko")
        d = self.engine.apply(ext(promised_date="sa 15", payment_channel="gcash"), None, "Sa 15 po, via GCash")
        self.assertEqual(self.state.outcome, "promise_to_pay")
        self.assertIn("GCash", d.say_exactly)
        self.assertTrue(d.end_call)

    def test_third_party_gets_no_details(self):
        d = self.engine.apply(ext(third_party=True), None, "Asawa po niya ito, wala siya ngayon")
        self.assertIn("hindi ko po maibabahagi", d.note)
        self.assertNotIn("pesos", d.note)


class IndonesiaReminderTests(unittest.TestCase):
    def setUp(self):
        self.pack = load_pack("id_multifinance")
        self.state = CallState(pack_id="id_multifinance", customer=customer("id_multifinance"))
        self.engine = FlowEngine(self.pack, self.state)

    def test_reminder_in_indonesian_spoken_forms(self):
        d = self.engine.apply(ext(identity_confirmed=True), None, "Iya, saya Budi")
        self.assertIn("satu juta dua ratus lima puluh ribu rupiah", d.note)
        self.assertIn("dua ribu lima ratus rupiah per hari", d.note)

    def test_hardship_leads_to_restructuring_referral(self):
        self.engine.apply(ext(identity_confirmed=True), None, "Iya betul")
        self.engine.apply(ext(payment_intent="cannot_pay", reason="kena PHK"), None, "Saya baru kena PHK, Mbak")
        d = self.engine.apply(ext(wants_restructuring=True), None, "Iya boleh, tolong dihubungi")
        self.assertEqual(self.state.outcome, "restructuring_referral")
        self.assertEqual(d.actions[0][0], "callback")
        self.assertIn("restrukturisasi", d.say_exactly)

    def test_already_paid(self):
        self.engine.apply(ext(identity_confirmed=True), None, "iya")
        d = self.engine.apply(ext(payment_intent="already_paid"), None, "Udah bayar kok kemarin")
        self.assertEqual(self.state.outcome, "already_paid")
        self.assertTrue(d.end_call)


if __name__ == "__main__":
    unittest.main()
