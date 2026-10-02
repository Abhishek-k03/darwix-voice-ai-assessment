"""Deterministic business rules. The LLM never decides eligibility or prices — these functions do,
using the same rate table the KB indexes (rows the KB flagged as source errors are never quoted)."""

from __future__ import annotations

import copy
import csv
import functools
from datetime import date, timedelta
from pathlib import Path

from kb.conflicts import check_series
from kb.schema import Block, RawDoc
from packs import Pack

from . import hindi, speech_format as speech
from .speech_format import date_spoken, idr_spoken, inr_spoken, lakh_spoken, php_spoken
from .state import CallState, FieldValue

SOURCES = Path(__file__).resolve().parents[2] / "data" / "sources"


@functools.lru_cache(maxsize=4)
def _rates(rel_path: str) -> dict[tuple, int | None]:
    """{(product, members, sum_insured, age_band): premium | None (missing/flagged)}"""
    with open(SOURCES / rel_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    doc = RawDoc(source_id="rates", market="", language="", type="csv", uri=rel_path, title="", authority=4,
                 doc_type="premium_table", doc_group="", retrieved_at="", raw_hash="",
                 blocks=[Block(kind="table_row", text="", cells=r) for r in rows])
    _, flagged = check_series(doc, {"value_column": "annual_premium_inr", "order_column": "age_band",
                                    "series_by": ["product", "members", "sum_insured"]})
    out = {}
    for r in rows:
        key = (r["product"], r["members"], r["sum_insured"], r["age_band"])
        out[key] = None if key in flagged or not r["annual_premium_inr"] else int(r["annual_premium_inr"])
    return out


def _band(age: int, bands: list[str]) -> str | None:
    for b in bands:
        lo, hi = (int(x) for x in b.split("-"))
        if lo <= age <= hi:
            return b
    return None


def zone_for(city: str | None, pack: Pack) -> str:
    c = (city or "").strip().lower()
    for z, spec in pack.rules["zones"].items():
        if any(name in c for name in spec["cities"]):
            return z
    return "C"


def options(state: CallState, pack: Pack, limit: int = 3) -> list[dict]:
    """Plan sizes the customer could pick from when they cannot name a budget: real indicative premiums only."""
    if pack.use_case != "lead_qualification":
        return []
    base = evaluate_in_health(state, pack)
    if not base.get("eligible"):
        return []
    floor = pack.rules["zones"][zone_for(state.get("city"), pack)]["min_sum_insured_lakh"]
    found = []
    for si in pack.rules["products"][base["product"]]["sum_insured_lakh"]:
        trial = copy.deepcopy(state)
        trial.fields["preferred_sum_insured_lakh"] = FieldValue(si, 1.0, trial.turn)
        e = evaluate_in_health(trial, pack)
        if si >= floor and e.get("eligible") and e.get("indicative_premium_inr") and e["sum_insured_lakh"] == si:
            found.append({"product": e["product"], "si": si, "premium": e["indicative_premium_inr"],
                          "si_spoken": e["sum_insured_spoken"], "premium_spoken": e["premium_spoken"]})
    return found if len(found) <= limit else [found[0], found[len(found) // 2], found[-1]]


def evaluate_in_health(state: CallState, pack: Pack) -> dict:
    r = pack.rules
    age, cover = state.get("age"), state.get("cover_for")
    reasons: list[str] = []
    if state.get("serious_treatment"):
        return {"eligible": False, "grade": "not_eligible", "refer_underwriter": True,
                "reasons": ["active serious treatment (rule E08): refer to underwriter / human advisor"]}

    if age is None and cover != "parents":     # "I don't know" twice: no quote without the age, an advisor takes over
        return {"eligible": False, "grade": "incomplete", "refer_underwriter": True,
                "reasons": ["age not provided: an advisor must confirm eligibility and the quote"]}
    if cover == "parents":
        ages = state.get("parents_ages") or []
        if not ages:
            return {"eligible": False, "grade": "incomplete", "refer_underwriter": True,
                    "reasons": ["parents' ages not provided: an advisor must confirm eligibility and the quote"]}
        if max(ages) > 75:
            return {"eligible": False, "grade": "not_eligible", "reasons": ["parent above 75 (rule E03)"]}
        product, eldest, members = "Prithvi Silver", max(ages), "1 adult"
        if min(ages) < 60:
            reasons.append("a parent below 60 would need Prithvi Secure instead; advisor to confirm")
    elif age > 75:
        return {"eligible": False, "grade": "not_eligible", "reasons": ["entry age above 75 (rules E02/E03)"]}
    elif age > 65:
        product, eldest, members = "Prithvi Silver", age, "1 adult"
        reasons.append("above 65: Prithvi Silver instead of Secure/FamilyShield (rule E02)")
    elif cover in ("self_spouse", "family"):
        product = "Prithvi FamilyShield"
        eldest = max(age, state.get("spouse_age") or age)
        kids = state.get("children_count") or 0
        members = "2 adults" if cover == "self_spouse" or kids == 0 else (
            "2 adults + 1 child" if kids == 1 else "2 adults + 2 children")
        if kids > 3:
            return {"eligible": False, "grade": "not_eligible", "reasons": ["more than 3 children (rule E04)"]}
        if kids == 3:
            reasons.append("3 children: exact premium from advisor")
    else:
        product, eldest, members = "Prithvi Secure", age, "1 adult"

    zone = zone_for(state.get("city"), pack)
    zspec = r["zones"][zone]
    options = r["products"][product]["sum_insured_lakh"]
    want = state.get("preferred_sum_insured_lakh") or zspec["min_sum_insured_lakh"]
    si = next((o for o in options if o >= want), options[-1])
    rates = _rates(r["rates_csv"])
    bands = sorted({k[3] for k in rates if k[0] == product}, key=lambda b: int(b.split("-")[0]))
    band = _band(eldest, bands)
    base = rates.get((product, members, f"{si} lakh", band)) if band else None
    premium = round(base * zspec["factor"]) if base else None
    if base is None:
        reasons.append("no indicative rate for this combination (missing or under review): advisor to quote")

    budget = state.get("budget_annual_inr")
    timeline = state.get("timeline")
    if timeline == "not_interested":
        grade = "cold"
    elif timeline == "later":
        grade = "cold"
    elif premium and budget and premium <= budget * r["budget_tolerance"] and timeline in (None, "immediate"):
        grade = "hot"
    else:
        grade = "warm"
        if premium and budget and premium > budget * r["budget_tolerance"]:
            reasons.append(f"budget gap: indicative {premium} vs budget {budget}")

    mt = r["medical_tests"]
    hi = pack.language == "hi"
    if state.get("tobacco"):
        reasons.append("tobacco use noted: advisor to confirm any premium loading")
    tests = eldest >= mt["min_age"] or si >= mt["min_sum_insured_lakh"] or bool(state.get("pre_existing"))
    copay = r["co_payment"].get(product, {})
    copay_pct = copay.get("percent") if eldest >= copay.get("min_entry_age", 0) else None
    return {
        "eligible": True, "grade": grade, "product": product, "members": members, "age_band": band, "zone": zone,
        "sum_insured_lakh": si, "sum_insured_spoken": (hindi if hi else speech).lakh_spoken(si),
        "indicative_premium_inr": premium, "premium_spoken": (hindi if hi else speech).inr_spoken(premium) if premium else None,
        "medical_tests_required": tests, "co_payment_percent": copay_pct,
        "rate_record": f"Indicative annual premium — {product}, age band {band}", "reasons": reasons,
    }


def evaluate_reminder(state: CallState, pack: Pack) -> dict:
    """Account summary for premium / installment reminders, in the market's spoken conventions."""
    c = state.customer or {}
    if not c.get("due_date"):
        return {"available": False}
    due = date.fromisoformat(c["due_date"])
    days = (due - date.today()).days
    out = {"available": True, "due_date": due.isoformat(), "due_spoken": date_spoken(due, pack.market), "days_to_due": days,
           "name": c.get("name"), "title": c.get("title", "")}
    if pack.market == "ph_life":
        grace_end = due + timedelta(days=pack.rules.get("grace_period_days", 31))
        out.update(amount=c["premium_php"], amount_spoken=php_spoken(c["premium_php"]), mode=c.get("mode"),
                   policy_no=c.get("policy_no"), product=c.get("product"), riders=c.get("riders", []),
                   beneficiary=c.get("beneficiary"), grace_end_spoken=date_spoken(grace_end, pack.market))
    else:
        fee = c["installment_idr"] * c.get("late_fee_pct_per_day", 0.2) / 100
        out.update(amount=c["installment_idr"], amount_spoken=idr_spoken(c["installment_idr"]), contract_no=c.get("contract_no"),
                   vehicle=c.get("vehicle"), installment_no=c.get("paid_installments", 0) + 1, tenor=c.get("tenor_months"),
                   late_fee_per_day_spoken=idr_spoken(fee))
    return out


EVALUATORS = {"lead_qualification": evaluate_in_health, "reminder": evaluate_reminder}


def evaluate(state: CallState, pack: Pack) -> dict | None:
    fn = EVALUATORS.get(pack.use_case)
    return fn(state, pack) if fn else None
