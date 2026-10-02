"""Copilot signal + nudge logic on the scripted scenarios (text mode, virtual clock, no ASR/LLM/network)."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

from copilot.events import Signal, Utterance, now_ms
from copilot.nudge_engine import Controls, NudgeEngine
from copilot.replay import replay_text

SCRIPTS = Path(__file__).resolve().parents[1] / "sim" / "scripts" / "in_health"


async def _no_kb(*_a, **_k):
    return {"status": "error", "hits": []}


def run(name: str, controls: bool = True) -> dict:
    with patch("copilot.pipeline.rag.search", _no_kb):
        return asyncio.run(replay_text(SCRIPTS / f"{name}.yaml", use_llm=False, controls_on=controls))


def keys(res: dict) -> list[str]:
    return [n["key"] for n in res["nudges"]]


class ScenarioTests(unittest.TestCase):
    def test_missed_cross_sell_escalates(self):
        k = keys(run("missed_cross_sell"))
        self.assertEqual(k, ["cross_sell_parents", "missed_opportunity"])

    def test_compliance_and_risky_statements(self):
        k = keys(run("compliance_risky"))
        for expected in ("waiting_period_before_quote", "no_waiting_claim", "guaranteed_claim", "recording_missing"):
            self.assertIn(expected, k)

    def test_rising_frustration(self):
        self.assertIn("frustration", keys(run("rising_frustration")))

    def test_benign_calls_stay_quiet(self):
        self.assertEqual(keys(run("noisy_ambiguous")), [])
        self.assertTrue(set(keys(run("clean_compliant"))) <= {"buying_signal"})

    def test_controls_reduce_volume(self):
        on, off = run("rising_frustration"), run("rising_frustration", controls=False)
        self.assertLess(len(on["nudges"]), len(off["nudges"]))


class EngineControlTests(unittest.TestCase):
    TPL = {"frustration": {"priority": 2, "title": "t", "text": "x", "ttl_s": 30, "topic": "sentiment"},
           "guaranteed_claim": {"priority": 1, "title": "t", "text": "x", "ttl_s": 45, "topic": "compliance"},
           "callback_need": {"priority": 3, "title": "t", "text": "x", "ttl_s": 45, "topic": "closing"}}

    def sig(self, nudge: str, conf: float = 0.9, asr: float = 0.95, text: str = "this is taking far too long") -> Signal:
        u = Utterance("customer", text, True, "u", now_ms(), now_ms(), asr)
        return Signal(type=nudge, nudge=nudge, confidence=conf, source="rules", speaker="customer", evidence=text, utterance=u)

    def test_low_asr_confidence_suppresses_non_p1(self):
        e = NudgeEngine(self.TPL)
        out = e.consider(self.sig("frustration", asr=0.4), {})
        self.assertEqual(out[0]["reason"], "low_asr_confidence")

    def test_p1_passes_noisy_gate_and_rate_limit(self):
        e = NudgeEngine(self.TPL)
        e.consider(self.sig("callback_need"), {})
        out = e.consider(self.sig("guaranteed_claim", asr=0.4), {})
        self.assertEqual(out[-1]["type"], "nudge")

    def test_duplicate_refreshes_instead_of_new_card(self):
        e = NudgeEngine(self.TPL)
        e.consider(self.sig("frustration"), {})
        out = e.consider(self.sig("frustration"), {})
        self.assertEqual(out[0]["reason"], "duplicate_active_refreshed")
        self.assertEqual(len(e.active), 1)

    def test_global_rate_limit(self):
        e = NudgeEngine(self.TPL)
        e.consider(self.sig("frustration"), {})
        out = e.consider(self.sig("callback_need"), {})
        self.assertEqual(out[0]["reason"], "global_rate_limit")

    def test_ablation_baseline_emits_everything(self):
        e = NudgeEngine(self.TPL, controls=Controls(enabled=False))
        for _ in range(3):
            e.consider(self.sig("frustration", asr=0.3, conf=0.2), {})
        self.assertEqual(sum(d["decision"] == "emitted" for d in e.decisions), 3)


if __name__ == "__main__":
    unittest.main()


class MissedOpportunityTests(unittest.TestCase):
    def setUp(self):
        from copilot.signals_rules import RuleDetector
        from packs import load_pack

        from copilot.pipeline import load_config

        self.det = RuleDetector(load_config(load_pack("in_health")))
        self.t = now_ms()

    def say(self, speaker, text, dt):
        self.t += dt * 1000
        return self.det.on_utterance(Utterance(speaker=speaker, text=text, final=True, utterance_id=str(self.t),
                                               audio_received_at=self.t, asr_at=self.t, confidence=0.95))

    def test_one_agent_turn_split_into_two_finals_counts_once(self):
        self.say("customer", "I am also worried about my parents, they have no insurance", 1)
        out = self.say("agent", "Okay noted. Do you have any existing", 2) + self.say("agent", "cover for yourself?", 1)
        self.assertNotIn("missed_opportunity", [s.type for s in out])
        self.say("customer", "Only the company policy", 2)
        out = self.say("agent", "Alright. Any pre existing conditions for you?", 2)
        self.assertIn("missed_opportunity", [s.type for s in out])

    def test_held_back_missed_opportunity_is_raised_again(self):
        self.say("customer", "I am also worried about my parents, they have no insurance", 1)
        self.say("agent", "Okay noted.", 2)
        self.say("customer", "Hmm", 1)
        out = self.say("agent", "Alright.", 2)
        self.assertIn("missed_opportunity", [x.type for x in out])
        u = Utterance(speaker="agent", text="x", final=True, utterance_id="x", audio_received_at=self.t, asr_at=self.t, confidence=0.9)
        self.det.retry_missed("cross_sell_parents", self.t)           # the engine held the nudge back
        self.assertEqual(self.det.check_missed(u, self.t + 1000), [])  # not before the retry delay
        again = self.det.check_missed(u, self.t + 10000)
        self.assertEqual([x.type for x in again], ["missed_opportunity"])


class NoisyGapTests(unittest.TestCase):
    def test_quote_after_garbled_agent_audio_does_not_claim_a_missed_disclosure(self):
        from copilot.pipeline import load_config
        from copilot.signals_rules import RuleDetector
        from packs import load_pack

        det = RuleDetector(load_config(load_pack("in_health")))
        t = now_ms()

        def say(text, conf, dt):
            nonlocal t
            t += dt * 1000
            return det.on_utterance(Utterance(speaker="agent", text=text, final=True, utterance_id=str(t),
                                              audio_received_at=t, asr_at=t, confidence=conf))

        say("Hello this is Amit from Prithvi", 0.95, 1)
        out = say("The premium is around 6,400 rupees a year.", 0.74, 5)
        sig = next(s for s in out if s.type == "compliance_gap")
        engine = NudgeEngine(load_config(load_pack("in_health"))["nudges"], controls=Controls())
        ev = engine.consider(sig, {"audio_received_at": t, "asr_at": t, "signal_at": t, "source": "rules", "signal_ms": 0})
        self.assertEqual(ev[0]["reason"], "noisy_agent_audio")


class TypedTurnTests(unittest.TestCase):
    def test_a_typed_customer_line_becomes_a_final_utterance_and_spoken_or_agent_lines_do_not(self):
        from copilot.events import typed_utterance

        u = typed_utterance({"role": "customer", "text": " My parents are 64 and 67 ", "t": 31.2, "typed": True}, 3)
        self.assertEqual((u.speaker, u.text, u.final, u.utterance_id, u.start_s, u.asr_latency_ms), ("customer", "My parents are 64 and 67", True, "customer-typed-3", 31.2, 0))
        self.assertIsNone(typed_utterance({"role": "customer", "text": "yes", "t": 2.0}, 0))          # spoken: the audio path has it
        self.assertIsNone(typed_utterance({"role": "agent", "text": "hello", "typed": True}, 0))
        self.assertIsNone(typed_utterance({"role": "customer", "text": "  ", "typed": True}, 0))
