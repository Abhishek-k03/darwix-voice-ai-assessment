"""Flow engine: applies a turn's extraction + retrieval to the call state and produces the directive the main
LLM follows. Logic is deterministic and testable; the LLM only phrases it."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from packs import FieldSpec, Pack

from . import hindi, rules
from . import speech_format as speech
from .quick import _polarity, norm
from .state import UNVERIFIED, CallState, merge, missing_fields

QUESTION_INTENTS = {"question", "objection"}
# words a garbled question still carries; a plain answer ("whole family") that merely matches a record has none
QUESTIONISH = re.compile(
    r"\b(?:is|are|does|do|can|will|what|how|which|when|why|where|could|would|may|should|cover|covered|include|included|"
    r"claim|waiting|cost|price|pay|ano|paano|magkano|kailan|apa|apakah|bagaimana|berapa|kapan|bisa|boleh)\b|"
    "क्या|कितना|कितनी|कैसे|कब|क्यों|कहाँ|कौन|होगा|मिलेगा|कवर", re.I)
TIME_PHRASE = re.compile(
    r"\b(?:(?:today|tonight|tomorrow|day after tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next week|"
    r"this (?:morning|afternoon|evening)|in (?:an?|\d+|one|two|three) hours?)(?:[ ,]+(?:at |around |after |before )?"
    r"(?:morning|afternoon|evening|night|\d{1,2}(?::\d\d)? ?(?:am|pm|o'clock)?))?|(?:in the |at |around |after |before )"
    r"(?:morning|afternoon|evening|\d{1,2}(?::\d\d)? ?(?:am|pm|o'clock)?)|\d{1,2}(?::\d\d)? ?(?:am|pm))\b", re.I)
TIME_PHRASE_HI = re.compile(
    "(?:आज|कल|परसों|अगले हफ़्ते|अगले हफ्ते|सोमवार|मंगलवार|बुधवार|गुरुवार|शुक्रवार|शनिवार|रविवार)"
    "(?: ?(?:को )?(?:सुबह|दोपहर|शाम|रात|[0-9]{1,2} बजे))?(?: [0-9]{1,2} बजे)?|(?:सुबह|दोपहर|शाम|रात)(?: को)?|[0-9]{1,2} बजे|"
    r"\b(?:kal|aaj|parson)(?: (?:subah|shaam|dopahar|raat))?\b|\b(?:subah|shaam|dopahar|raat)\b", re.I)
CLEAN_OUTCOMES = {"set", "same", "widened", "confirmed"}


@dataclass
class Directive:
    note: str = ""
    say_exactly: str | None = None
    actions: list[tuple[str, dict]] = field(default_factory=list)
    end_call: bool = False
    knowledge_used: list[str] = field(default_factory=list)
    quick_reply: str | None = None   # pre-approved ack + next question, spoken without the LLM
    silent: bool = False             # say nothing this turn (waiting for the human advisor)


class FlowEngine:
    def __init__(self, pack: Pack, state: CallState) -> None:
        self.pack = pack
        self.state = state
        self.skipped: set[str] = set()
        self._offer_ok = True
        self._say: str | None = None          # set by a flow step that ends in a pre-approved line
        self._actions: list[tuple[str, dict]] = []
        self._ask_line: str | None = None    # script key of the plain question this turn's step asks

    # ── helpers ──
    def _missing(self) -> list:
        return [f for f in missing_fields(self.pack, self.state) if f.name not in self.skipped]

    def _state_line(self) -> str:
        known = ", ".join(f"{k}={'***' if k.startswith('dob') else v}" for k, v in self.state.known().items()) or "nothing yet"
        missing = ", ".join(f.name for f in self._missing()) or "none"
        return f"[CALL STATE] stage: {self.state.stage} | known: {known} | still needed: {missing}"

    def _ask(self, key: str, instruction: str) -> str | None:
        """Counts attempts; returns None once the question has been tried too often."""
        n = self.state.ask_attempts.get(key, 0) + 1
        self.state.ask_attempts[key] = n
        if n > self.pack.rules["escalation"]["max_field_attempts"]:
            return None
        retry = " They didn't answer clearly before; rephrase gently." if n > 1 else ""
        return f"[NEXT STEP] {instruction}{retry}"

    def _finish(self, line_key: str, outcome: str, **fmt) -> str:
        s = self.state
        s.outcome = s.outcome or outcome
        s.stage, s.end_requested = "CLOSE", True
        self._say = self.pack.line(line_key, **{**self._fmt(), **fmt})
        return ""

    def _when(self, text: str) -> str:
        return hindi.when_spoken(text) if self.pack.language == "hi" else speech.when_spoken(text)

    def _offer_lowest(self) -> str | None:
        """Budget below the cheapest plan that fits: say so, name that plan and its premium, and ask if they want it."""
        s, p = self.state, self.pack
        budget = s.get("budget_annual_inr")
        if not budget or s.lowest_offered or not p.lines.get("lowest_option"):
            return None
        opts = rules.options(s, p, limit=99)
        if not opts or opts[0]["premium"] <= budget * p.rules["budget_tolerance"]:
            return None
        low = opts[0]
        s.lowest_offered, s.options, s.awaiting, self._ask_line = True, [low], "lowest_option", None
        s.disclosed_waiting_period = True
        s.log("lowest_option_offered", si=low["si"], premium=low["premium"], budget=budget)
        line = p.line("lowest_option", disclosure=p.line("disclosure"), si=low["si_spoken"], premium=low["premium_spoken"])
        if self._offer_ok:
            self._say = line
            return ""
        return f'[NEXT STEP] After answering, say exactly this and nothing else: "{line}"'

    def _offer_budget_options(self) -> bool:
        """Unsure about the budget: offer real plan sizes with their indicative premiums and let them pick one."""
        s, p = self.state, self.pack
        if not self._offer_ok or s.options or not p.lines.get("budget_options"):
            return False
        opts = rules.options(s, p)
        if len(opts) < 2:
            return False
        s.options, s.awaiting, self._ask_line = opts, "budget_choice", None
        names = p.lines.get("ordinals", ["the first", "the second", "the third"])
        items = [p.line("option_item", ord=names[i], si=o["si_spoken"], premium=o["premium_spoken"]) for i, o in enumerate(opts)]
        text = "; ".join(items[:-1]) + f"; {p.lines.get('option_join', 'or')} " + items[-1]
        self._say = p.line("budget_options", product=opts[0]["product"], options=text, disclosure=p.line("disclosure"))
        s.disclosed_waiting_period = True
        s.log("budget_options_offered", options=[o["si"] for o in opts])
        return True

    def _spoken(self, field: str, value):
        """How a collected value is said back: amounts in words, everything else as is."""
        if field != "budget_annual_inr" or not isinstance(value, (int, float)):
            return value
        return (hindi if self.pack.language == "hi" else speech).inr_spoken(value)

    def _fmt(self) -> dict:
        c = self.state.customer or {}
        return {"title": c.get("title", ""), "name": c.get("name", "")}

    # ── reminder flow (Q3: premium / installment pre-due reminders) ──
    def _progress_reminder(self) -> str:
        s, p, r = self.state, self.pack, self.pack.rules
        if s.eligibility is None:
            s.eligibility = rules.evaluate(s, p)
        acct = s.eligibility or {}
        if s.stage in ("OPENING", "DISCOVERY"):
            s.stage = "VERIFY"
        if s.stage == "VERIFY":
            if s.get("third_party"):
                if s.get("callback_time"):
                    self._actions.append(("callback", {"when": s.get("callback_time"), "reason": "account holder unavailable"}))
                    s.callback = {"when": s.get("callback_time")}
                    return self._finish("callback_confirm", "third_party", when=s.get("callback_time"))
                s.outcome = "third_party"
                return f"[NEXT STEP] SAY: \"{p.line('third_party', **self._fmt())}\" Do not mention any account detail."
            verified = self._verified()
            if verified is False:
                return self._finish("verify_fail", "verification_failed")
            if verified is None:
                key = "dob_given" if r.get("verification") == "dob" else "identity_confirmed"
                s.awaiting = key
                step = self._ask("verify", f"Politely ask for verification: \"{p.line('verify_ask', **self._fmt())}\"")
                return step or self._finish("verify_fail", "verification_failed")
            s.stage = "REMINDER"
            s.log("verified")
            return self._reminder_note(acct)
        if s.stage in ("REMINDER", "RESOLUTION"):
            s.stage = "RESOLUTION"
            return self._resolution(acct)
        return f"[NEXT STEP] Close politely: \"{p.line('closing', **self._fmt())}\""

    def _verified(self) -> bool | None:
        s, r = self.state, self.pack.rules
        if r.get("verification") == "dob":
            given = s.get("dob_given")
            if not given:
                return None
            if given.strip()[:10] == (s.customer or {}).get("dob"):
                return True
            s.fields.pop("dob_given", None)
            s.log("verify_mismatch")
            return False if s.ask_attempts.get("verify", 0) >= r.get("max_verify_attempts", 2) else None
        confirmed = s.get("identity_confirmed")
        return None if confirmed is None else (True if confirmed else None)

    def _reminder_note(self, acct: dict) -> str:
        if not acct.get("available"):
            return "[NEXT STEP] Account details are unavailable. Apologise and offer a callback from an officer."
        if self.pack.market == "ph_life":
            facts = (f"[ACCOUNT] {acct['mode']} premium {acct['amount_spoken']} for policy {acct['policy_no']}, due {acct['due_spoken']} "
                     f"(in {acct['days_to_due']} days); grace period until {acct['grace_end_spoken']}; coverage continues during the grace period.")
        else:
            facts = (f"[ACCOUNT] angsuran ke-{acct['installment_no']} dari {acct['tenor']} sebesar {acct['amount_spoken']}, jatuh tempo "
                     f"{acct['due_spoken']} ({acct['days_to_due']} hari lagi), kendaraan {acct['vehicle']}. Denda keterlambatan "
                     f"{acct['late_fee_per_day_spoken']} per hari, dihitung sejak hari setelah jatuh tempo.")
        return (f"{facts}\n[NEXT STEP] Thank them for confirming, then give a friendly reminder of the amount and due date "
                "(use the spoken forms above), and ask if they can pay by the due date.")

    def _resolution(self, acct: dict) -> str:
        s, p, r = self.state, self.pack, self.pack.rules
        intent = s.get("payment_intent")
        channels = ", ".join(r.get("channel_names", {}).values())
        if intent is None:
            return self._ask("payment_intent", "Ask, kindly, whether they will be able to pay by the due date.") or \
                self._finish("callback_confirm", "no_commitment", when="soon")
        if intent in ("will_pay", "need_time"):
            extra = ""
            if intent == "need_time":
                extra = (f" Mention gently that the grace period ends {acct.get('grace_end_spoken')} and coverage continues until then."
                         if p.market == "ph_life" else
                         f" Mention gently that the late fee is {acct.get('late_fee_per_day_spoken')} per day after the due date.")
            if not s.get("promised_date"):
                return (self._ask("promised_date", "Acknowledge, then ask on what date they plan to pay." + extra)
                        or self._finish("closing", "promise_unclear"))
            if not s.get("payment_channel"):
                return (self._ask("payment_channel", f"Ask which channel they will use: {channels}.")
                        or self._promise(intent, "official channels"))
            return self._promise(intent, r["channel_names"].get(s.get("payment_channel"), s.get("payment_channel")))
        if intent == "already_paid":
            return self._finish("paid_confirm", "already_paid")
        if intent == "cannot_pay":
            if not s.get("reason") and s.ask_attempts.get("reason", 0) < 1:
                return self._ask("reason", "Empathise sincerely, then gently ask what is making it difficult right now.") or ""
            if p.market == "id_multifinance":
                if s.get("wants_restructuring"):
                    self._actions.append(("callback", {"when": "within 3 working days", "reason": "restructuring request"}))
                    s.callback = {"when": "dalam tiga hari kerja", "reason": "restructuring"}
                    return self._finish("restructuring_confirm", "restructuring_referral")
                if s.get("wants_restructuring") is False:
                    return self._finish("refused_close", "cannot_pay_declined_options")
                return (self._ask("restructuring", "Empathise. Explain briefly (from KNOWLEDGE) that there is a free restructuring "
                                  "program for customers whose income dropped, and ask if they'd like the restructuring team to call.")
                        or self._finish("refused_close", "cannot_pay"))
            if s.get("callback_consent") and s.get("callback_time"):
                self._actions.append(("callback", {"when": s.get("callback_time"), "reason": "payment difficulty"}))
                s.callback = {"when": s.get("callback_time")}
                return self._finish("callback_confirm", "advisor_callback", when=s.get("callback_time"))
            return (self._ask("ph_options", f"Empathise. Remind them the grace period runs until {acct.get('grace_end_spoken')} "
                              "and coverage continues; mention switching to monthly auto-debit at the policy anniversary to make it "
                              "lighter; offer a callback from their advisor and ask when is convenient.")
                    or self._finish("refused_close", "cannot_pay"))
        if intent in ("refuse",):
            return self._finish("refused_close", "refused")
        if intent == "dispute":
            self._actions.append(("escalate", {"reason": "billing dispute"}))
            s.escalated = True
            return self._finish("escalation", "dispute")
        return f"[NEXT STEP] Close politely: \"{p.line('closing', **self._fmt())}\""

    def _promise(self, intent: str, channel: str) -> str:
        return self._finish("promise_confirm", "promise_to_pay" if intent == "will_pay" else "promise_to_pay_late",
                            date=self.state.get("promised_date"), channel=channel)

    def _ask_next(self) -> str:
        nxt = self._missing()[0]
        n = self.state.ask_attempts.get(nxt.name, 0) + 1
        self.state.ask_attempts[nxt.name] = n
        if n > self.pack.rules["escalation"]["max_field_attempts"]:
            self.skipped.add(nxt.name)
            self.state.log("field_skipped", field=nxt.name)
            return self._progress()
        if nxt.name == "budget_annual_inr" and n > 1 and self._offer_budget_options():
            return ""
        retry = " The customer did not answer this clearly before; rephrase gently and say it's fine if they don't know." if n > 1 else ""
        self.state.awaiting, self._ask_line = nxt.name, (f"ask_{nxt.name}" if n == 1 else None)
        return f"[NEXT STEP] Briefly acknowledge, then ask {nxt.ask}.{retry}"

    def _progress(self) -> str:
        s = self.state
        if self.pack.use_case == "reminder":
            return self._progress_reminder()
        if s.stage in ("OPENING", "DISCOVERY"):
            s.stage = "QUALIFICATION"
        if s.stage == "QUALIFICATION":
            if self._missing():
                return self._ask_next()
            lowest = self._offer_lowest()
            if lowest is not None:
                return lowest
            s.eligibility = rules.evaluate(s, self.pack)
            s.stage = "RECOMMENDATION"
            s.log("eligibility", **(s.eligibility or {}))
        if s.stage == "RECOMMENDATION":
            return self._recommendation()
        if s.stage == "NEXT_STEP":
            if s.get("callback_consent") is False:
                s.stage, s.end_requested = "CLOSE", True
                return f"[NEXT STEP] Thank them warmly and close the call: \"{self.pack.line('closing')}\""
            s.awaiting = "callback_consent"
            return ("[NEXT STEP] Ask if they would like a licensed advisor to call them back to complete the application, "
                    "and if yes, when is convenient.")
        return f"[NEXT STEP] Close politely: \"{self.pack.line('closing')}\""

    def _recommendation(self) -> str:
        e = self.state.eligibility or {}
        self.state.stage, self.state.awaiting = "NEXT_STEP", "callback_consent"
        if not e.get("eligible"):
            reasons = "; ".join(e.get("reasons", []))
            if e.get("refer_underwriter"):
                return (f"[ELIGIBILITY] not eligible for an instant quote ({reasons}). [NEXT STEP] Explain kindly that a "
                        "licensed advisor must review their case, and offer to connect them to an advisor now or arrange a callback.")
            return (f"[ELIGIBILITY] not eligible ({reasons}). [NEXT STEP] Explain kindly and briefly why, without technical "
                    "rule codes, and offer a callback from an advisor for alternatives.")
        self.state.disclosed_waiting_period = True
        premium = (f"indicative premium about {e['premium_spoken']} per year (indicative, subject to underwriting)"
                   if e.get("premium_spoken") else "an advisor will share the exact premium (no indicative rate available)")
        extras = []
        if e.get("medical_tests_required"):
            extras.append("medical tests will be required")
        if e.get("co_payment_percent"):
            extras.append(f"a {e['co_payment_percent']} percent co-payment applies")
        extra = ("; " + "; ".join(extras)) if extras else ""
        return (f"[ELIGIBILITY] eligible for {e['product']} with {e['sum_insured_spoken']} sum insured, {premium}{extra}. "
                f"[NEXT STEP] First mention that {self.pack.rules['pre_quote_disclosure']}. Then recommend the plan and the "
                "indicative premium in two short sentences. Then ask if they'd like a licensed advisor to call back to complete the application.")

    # ── main ──
    def apply(self, extraction: dict, kb: dict | None, customer_said: str) -> Directive:
        s, p = self.state, self.pack
        s.turn += 1
        answered, s.awaiting, self._ask_line = s.awaiting, None, None
        checked, s.checking = s.checking, None
        intents = set(extraction.get("intents") or [])
        s.intents.append(",".join(sorted(intents)))
        outcomes = self.merge_updates(extraction.get("updates", []), answered)
        decline = p.rules.get("callback_decline")
        if answered == "callback_consent" and s.get("callback_consent") is None and decline and \
                re.search(decline, customer_said, re.I):
            outcomes["callback_consent"] = merge(s, p, "callback_consent", False, 0.9)  # no second push
        if answered in ("callback_consent", "callback_time") and s.get("callback_time") is None and s.get("callback_consent") is not False:
            m = TIME_PHRASE.search(customer_said) or TIME_PHRASE_HI.search(customer_said)       # extraction can time out: read the time deterministically
            if m:
                outcomes["callback_time"] = merge(s, p, "callback_time", m.group(0).strip(), 0.9)
                if s.get("callback_consent") is None:
                    merge(s, p, "callback_consent", True, 0.9)
        if answered == "lowest_option" and s.options:
            if _polarity(norm(customer_said), FieldSpec(name="lowest_option", quick="consent")):
                o = s.options[0]
                merge(s, p, "preferred_sum_insured_lakh", o["si"], 0.95)
                merge(s, p, "budget_annual_inr", o["premium"], 0.9, correction=True)
            s.options = []
        recheck = ""
        if checked and checked in s.fields and not outcomes.get(checked):
            said = _polarity(norm(customer_said), FieldSpec(name=checked, quick="yesno"))
            if said:
                s.fields[checked].confidence = 0.95
            elif said is False:
                del s.fields[checked]
                recheck = (f"[CHECK] The {checked.replace('_', ' ')} you read back was wrong. Apologise in a few words and "
                           "ask them to say it again, spelling it if needed.\n")
        if extraction.get("objection"):
            s.objections.append(str(extraction["objection"]))
        sentiment = float(extraction.get("sentiment") or 0.0)
        s.negative_streak = s.negative_streak + 1 if sentiment <= -0.4 else 0
        s.log("turn", intents=sorted(intents), updates=outcomes, sentiment=sentiment)

        d = Directive()
        esc = p.rules["escalation"]
        # 1) terminal / global intents
        if extraction.get("outside_market") and p.lines.get("out_of_market") and not s.escalated:
            s.outcome, s.end_requested = "out_of_market", True
            d.say_exactly, d.end_call = p.line("out_of_market"), True
            return d
        if "dnc" in intents:
            s.dnc, s.outcome, s.end_requested = True, "do_not_call", True
            d.say_exactly, d.end_call = p.line("dnc"), True
            d.actions.append(("dnc", {}))
            return d
        if s.escalated and not s.handoff_active:   # waiting for the advisor: one short hold line, then silence
            n = s.ask_attempts.get("hold", 0)
            s.ask_attempts["hold"] = n + 1
            d.say_exactly = p.line("escalation_hold", **self._fmt()) if n == 0 else None
            d.silent = not d.say_exactly
            return d
        if "human_request" in intents or s.negative_streak >= esc["negative_turns"]:
            reason = "customer requested a human" if "human_request" in intents else "customer frustrated"
            return self._escalate(d, reason)
        if "not_interested" in intents and s.stage not in ("NEXT_STEP", "CLOSE"):
            merge(s, p, "timeline", "not_interested", 0.9, correction=True)
            s.outcome, s.end_requested = "not_interested", True
            d.say_exactly, d.end_call = p.line("not_interested_close"), True
            return d
        if s.get("callback_time") and (s.get("callback_consent") or {"callback_request", "busy"} & intents):
            return self._schedule(d, s.get("callback_time"))
        if "goodbye" in intents and not intents & QUESTION_INTENTS:
            s.stage, s.end_requested = "CLOSE", True     # the customer is leaving: close politely, never re-prompt
            d.say_exactly, d.end_call = p.line("closing", **self._fmt()), True
            return d
        if {"busy", "callback_request"} & intents:
            d.note = (f"{self._state_line()}\n[NEXT STEP] The customer can't talk now. Ask when would be a convenient "
                      "time for a callback (day and time).")
            return d

        if (answered == "good_time" and intents == {"greeting"} and not outcomes and s.get("good_time") is None
                and not s.ask_attempts.get("hello") and p.lines.get("reask_good_time")):
            s.ask_attempts["hello"], s.awaiting = 1, "good_time"      # "Hello?" is not a yes: ask the question once more
            d.say_exactly = p.line("reask_good_time")
            return d

        # 2) questions / objections / out of scope (answered first, even while a conflict is open)
        prefix = ""
        kb_ok = bool(kb and kb.get("status") == "ok")
        if "out_of_scope" in intents and not kb_ok:     # "do you also do car insurance?": not a KB miss
            prefix = f"[OUT OF SCOPE] Say: \"{p.line('out_of_scope')}\" Then continue with the next step.\n"
        elif intents & QUESTION_INTENTS or "?" in customer_said:
            if kb_ok:
                s.fallback_streak = 0
                d.knowledge_used = [h["record_id"] for h in kb.get("hits", [])[:3]]
                prefix = ("[KNOWLEDGE]\n" + kb["llm_context"] + "\n[ANSWER FIRST] Answer the customer's question or "
                          "objection in one or two sentences using only the KNOWLEDGE above, then continue with the next step.\n")
            else:
                s.fallback_streak += 1
                if s.fallback_streak >= esc["max_fallbacks"]:
                    s.fallback_streak = 0
                    return self._offer_human(d)
                prefix = f"[NO KNOWLEDGE] Say: \"{p.line('fallback')}\" Then continue with the next step.\n"
        elif kb_ok and QUESTIONISH.search(customer_said):  # ASR can garble a question ("is maternity cover two")
            prefix = ("[KNOWLEDGE, use only if the customer asked something]\n" + kb["llm_context"] + "\nIf the "
                      "customer's words contain a question this answers, answer it in one sentence first; otherwise "
                      "ignore this block entirely.\n")

        unverified = [f for f, o in outcomes.items() if o in ("set", "corrected") and s.fields[f].confidence <= UNVERIFIED]
        prefix += recheck
        if unverified and not prefix and not s.pending_conflicts and p.lines.get(f"confirm_{unverified[0]}"):
            f = unverified[0]
            s.checking = f                      # read the value back verbatim instead of letting the LLM improvise
            d.say_exactly = p.line(f"confirm_{f}", **{f: self._spoken(f, s.get(f))})
            return d
        if unverified:
            f = unverified[0]
            prefix += (f"[CHECK] '{s.get(f)}' may be a mishearing of the {f.replace('_', ' ')}. Briefly confirm it "
                       "(e.g. \"Sorry, was that ...?\") before moving on.\n")

        volunteered = {f: s.get(f) for f, o in outcomes.items() if o in ("set", "widened", "corrected") and f != answered}
        if volunteered:  # "I need to insure my parents, 74 and 78" while answering something else
            facts = ", ".join(f"{k.replace('_', ' ')}={v}" for k, v in volunteered.items())
            prefix += f"[ACKNOWLEDGE] They also told you: {facts}. Acknowledge it in a few words before the next question.\n"

        # 3) conflicts need confirmation before the flow moves on
        if s.pending_conflicts:
            c = s.pending_conflicts[0]
            d.note = (f"{self._state_line()}\n{prefix}[CONFLICT] The customer said {c.field}={c.old} earlier and now {c.new}. "
                      f"[NEXT STEP] Politely ask which is correct, e.g. \"{p.line('reconfirm', field=p.lines.get('field_names', {}).get(c.field) or c.field.replace('_', ' '), old=c.old, new=c.new)}\"")
            return d

        # 4) progress the flow
        self._offer_ok = not prefix              # a pending knowledge answer must not be replaced by a scripted offer
        if s.stage == "NEXT_STEP" and s.get("callback_consent") and not s.get("callback_time"):
            step = "[NEXT STEP] Ask what day and time suits them for the advisor's call."
            s.awaiting, self._ask_line = "callback_time", "ask_callback_time"
        else:
            step = self._progress()
        d.note = f"{self._state_line()}\n{prefix}{step}"
        if (self._ask_line and not prefix and not self._say and all(o in CLEAN_OUTCOMES for o in outcomes.values())):
            d.quick_reply = self._fast_reply(answered)
        if self._say:
            d.say_exactly, self._say = self._say, None
        d.actions += self._actions
        self._actions = []
        d.end_call = s.end_requested
        return d

    def _fast_reply(self, answered: str | None) -> str | None:
        """Ack + the next plain question from the pack's approved lines (variants rotate by turn)."""
        if os.getenv("FAST_REPLIES", "on").lower() == "off":
            return None
        s, p = self.state, self.pack
        fmt = {"name": s.get("name") or self._fmt().get("name", "")}
        ask = p.variant(self._ask_line, s.turn, **fmt)
        if not ask:
            return None
        ack = p.variant(f"ack_{answered}", s.turn, **fmt) or p.variant("ack", s.turn, **fmt)
        return f"{ack} {ask}".strip()

    def merge_updates(self, updates: list[dict], answered: str | None = None) -> dict:
        outcomes = {}
        for u in updates:
            if u["field"] == "name" and self._not_customer_name(str(u.get("value", "")), answered == "name"):
                continue  # "Hi Mira" names the agent; brand words come from ASR keyterm bias
            outcomes[u["field"]] = merge(self.state, self.pack, u["field"], u.get("value"),
                                         float(u.get("confidence") or 0.7), bool(u.get("correction")))
        return outcomes

    def _not_customer_name(self, value: str, asked_for_name: bool = False) -> bool:
        v = value.strip().lower()
        if asked_for_name and v == self.pack.persona.lower():
            return False                       # asked "your first name?" and they really are called that
        brand = {w.lower() for w in (self.pack.persona, *self.pack.company.split())}
        return not v or v in brand or any(w in brand for w in v.split())

    def _escalate(self, d: Directive, reason: str) -> Directive:
        s = self.state
        s.escalated, s.outcome = True, "escalated"
        d.say_exactly = self.pack.line("escalation")
        d.actions.append(("escalate", {"reason": reason}))
        s.log("escalate", reason=reason)
        return d

    def _offer_human(self, d: Directive) -> Directive:
        d.note = (f"{self._state_line()}\n[NO KNOWLEDGE] You could not answer several questions. Say you don't have that "
                  "information and offer to connect them to a licensed advisor now or arrange a callback.")
        return d

    def _schedule(self, d: Directive, when: str) -> Directive:
        s = self.state
        if not s.callback:
            s.callback = {"when": when}
            d.actions.append(("callback", {"when": when}))
        s.stage, s.end_requested = "CLOSE", True
        s.outcome = s.outcome or "callback_scheduled"
        d.say_exactly, d.end_call = self.pack.line("callback_confirm", when=self._when(when)), True
        return d

    def opening_note(self) -> str:
        return f"{self._state_line()}\n[NEXT STEP] Wait for the customer's reply to the greeting."
