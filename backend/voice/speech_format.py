"""Spoken forms for amounts and dates per market (tools return text the TTS can say naturally)."""

from __future__ import annotations

import re
from datetime import date

from num2words import num2words

ID_MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
             "November", "Desember"]


def inr_spoken(amount: float) -> str:
    """11320 -> 'about eleven thousand three hundred rupees' (rounded to the nearest hundred, Indian system)."""
    n = int(round(amount / 100.0) * 100)
    words = num2words(n, lang="en_IN").replace(",", "").replace("-", " ")
    return f"{words} rupees"


def php_spoken(amount: float) -> str:
    """Taglish convention: amounts are said in English. 1850 -> 'one thousand eight hundred fifty pesos'."""
    words = num2words(int(round(amount)), lang="en").replace(",", "").replace(" and ", " ").replace("-", " ")
    return f"{words} pesos"


def idr_spoken(amount: float) -> str:
    """Indonesian words. 1250000 -> 'satu juta dua ratus lima puluh ribu rupiah'."""
    return f"{num2words(int(round(amount)), lang='id')} rupiah"


def date_spoken(d: date, market: str) -> str:
    if market == "id_multifinance":
        return f"tanggal {d.day} {ID_MONTHS[d.month - 1]}"
    if market == "ph_life":
        return f"{d.strftime('%B')} {d.day}"
    return f"{d.day} {d.strftime('%B')}"


_DAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"


def when_spoken(text: str) -> str:
    """A callback time as the customer typed or said it, made readable after 'will call you': 'sunday 3pm' -> 'on Sunday at 3 PM'."""
    t = re.sub(r"(\d{1,2}(?::\d\d)?)\s*(am|pm)\b", lambda m: f"{m.group(1)} {m.group(2).upper()}", text.strip(), flags=re.I)
    t = re.sub(rf"\b({_DAYS})\b", lambda m: m.group(1).capitalize(), t, flags=re.I)
    t = re.sub(rf"^((?:{_DAYS}))[ ,]+(?=\d)", r"\1 at ", t, flags=re.I)
    t = re.sub(r"(?i)^(today|tomorrow|tonight)[ ,]+(?=\d)", r"\1 at ", t)
    if re.match(rf"(?i)^(?:{_DAYS})\b", t):
        return "on " + t
    if re.match(r"(?i)^(this |the )?weekend\b", t):
        rest = re.sub(r"(?i)^(this |the )?weekend", "", t)
        return "on the weekend" + re.sub(r"(?i)[ ,]+(morning|afternoon|evening)$", r", in the \1", rest)
    return "at " + t if re.match(r"^\d", t) else t


def lakh_spoken(lakh: float) -> str:
    n = int(lakh) if float(lakh).is_integer() else lakh
    return f"{num2words(n, lang='en_IN')} lakh"
