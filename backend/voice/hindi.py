"""Hindi spoken forms for amounts (Devanagari), so premiums and covers are read exactly, not translated by the LLM."""

from __future__ import annotations

import re

_W = ("शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस इक्कीस बाईस तेईस चौबीस "
      "पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस "
      "बयालीस तैंतालीस चौवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन "
      "अट्ठावन उनसठ साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर "
      "छिहत्तर सतहत्तर अठहत्तर उनासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानवे "
      "बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे").split()


def words(n: int) -> str:
    """Indian-system number words: 7500 -> 'सात हज़ार पाँच सौ', 1000000 -> 'दस लाख'."""
    if n < 100:
        return _W[n]
    parts = []
    for size, name in ((10_000_000, "करोड़"), (100_000, "लाख"), (1000, "हज़ार"), (100, "सौ")):
        q, n = divmod(n, size)
        if q:
            parts.append(f"{_W[q] if q < 100 else words(q)} {name}")
    if n:
        parts.append(_W[n])
    return " ".join(parts)


def inr_spoken(amount: float) -> str:
    return f"{words(int(round(amount / 100.0) * 100))} रुपये"


def lakh_spoken(lakh: float) -> str:
    return f"{words(int(lakh))} लाख" if float(lakh).is_integer() else f"{lakh} लाख"


_WORDS = {"kal": "कल", "tomorrow": "कल", "aaj": "आज", "today": "आज", "parso": "परसों", "parson": "परसों",
          "shaam": "शाम", "sham": "शाम", "evening": "शाम", "subah": "सुबह", "subha": "सुबह", "morning": "सुबह",
          "dopahar": "दोपहर", "dophar": "दोपहर", "afternoon": "दोपहर", "raat": "रात", "night": "रात",
          "bje": "बजे", "baje": "बजे", "bajey": "बजे", "somvar": "सोमवार", "mangalvar": "मंगलवार", "budhvar": "बुधवार",
          "guruvar": "गुरुवार", "veervar": "गुरुवार", "shukravar": "शुक्रवार", "shanivar": "शनिवार", "ravivar": "रविवार",
          "itwar": "रविवार", "weekend": "वीकेंड", "ko": "को"}


def when_spoken(text: str) -> str:
    """A callback time typed in Roman letters ("kal 7 bje") in Devanagari, so the Hindi voice reads it as Hindi."""
    out, words = [], text.replace(",", " ").split()
    i = 0
    while i < len(words):
        w = words[i].lower().strip(".")
        if w in ("am", "pm") and out and out[-1].isdigit():
            n = int(out.pop())
            out += [("दोपहर" if n in (12, 1, 2, 3) else "शाम") if w == "pm" and n != 11 else "सुबह", str(n), "बजे"]
        elif re.fullmatch(r"\d{1,2}(am|pm)", w):
            words[i:i + 1] = [w[:-2], w[-2:]]
            continue
        else:
            out.append(_WORDS.get(w, words[i]))
        i += 1
    return " ".join(out)
