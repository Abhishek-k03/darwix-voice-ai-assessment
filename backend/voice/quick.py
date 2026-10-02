"""Expected-answer fast path: resolves a short answer to the field the agent just asked without the extraction LLM.

Strict by design: anything it is not sure about returns None and the turn takes the normal LLM path, so the worst case
is today's latency. Never resolves hedges ("I think so", "not sure"), contrasts ("no, but my father..."), extra facts
(digits beside a yes/no) or a "no" to an identity check (spouse, wrong person: needs the LLM).
"""

from __future__ import annotations

import re

from packs import FieldSpec, Pack

from .state import CallState

YES = {"yes", "yeah", "yep", "yup", "ya", "yah", "yes yes", "correct", "thats correct", "that is correct",
       "thats right", "that is right", "absolutely", "definitely", "i do", "we do", "yes i do", "yes we do",
       "haan", "han", "haanji", "ji haan", "oo", "opo", "oho", "tama", "iya", "iya iya", "betul", "benar", "inggih", "nggih"}
YES_SOFT = {"sure", "okay", "ok", "alright", "all right", "of course", "go ahead", "fine", "please do", "sounds good",
            "this works", "that works", "sige", "pwede", "boleh", "bisa", "oke", "baik", "siap", "yes sure", "sure sure"}
NO = {"no", "nope", "nah", "no no", "not really", "none", "nothing", "no one", "nobody", "i dont", "we dont",
      "i do not", "we do not", "not at all", "nahi", "nahin", "bilkul nahi", "hindi", "wala", "hindi pa",
      "tidak", "nggak", "enggak", "gak", "ndak", "belum", "tidak ada", "nggak ada", "bukan", "mboten"}
YES |= {"हाँ", "हां", "हा", "बिल्कुल", "बिलकुल", "सही", "जी हाँ", "जी हां", "haan ji", "bilkul", "sahi"}
YES_SOFT |= {"ठीक है", "ठीक", "चलेगा", "बोलिए", "बोलो", "ओके", "theek hai", "thik hai", "chalega", "boliye", "bolo"}
NO |= {"नहीं", "नही", "ना", "कोई नहीं", "कोई नही", "बिल्कुल नहीं", "जी नहीं", "koi nahi", "na", "nahi hai", "nahin hai"}
HEDGE = {"maybe", "think", "guess", "probably", "not sure", "dont know", "no idea", "depends", "might", "perhaps",
         "but", "except", "although", "however", "actually", "only", "sometimes",
         "pata nahi", "shayad", "lekin", "magar", "पता नहीं", "शायद", "लेकिन", "मगर", "पर"}
# words a yes/no answer may restate without adding information ("No, none of us have any")
RESTATE = {"i", "we", "me", "us", "my", "our", "of", "have", "has", "had", "any", "do", "does", "did", "is", "are", "am",
           "it", "its", "a", "an", "the", "there", "currently", "right", "now", "at", "all", "really", "them", "anyone",
           "few", "some", "minute", "time", "good", "talk", "free", "yet", "one", "else", "this", "that", "works",
           "fine", "here", "still", "to", "spare", "bit",
           "hai", "hain", "hoon", "mujhe", "mere", "mera", "ko", "koi", "bhi", "toh", "abhi", "kuch", "sab",
           "है", "हैं", "हूँ", "हूं", "मुझे", "मेरे", "मेरा", "को", "कोई", "भी", "तो", "अभी", "कुछ", "सब"}
NEGATORS = {"no", "not", "none", "nothing", "dont", "nobody", "nahi", "nahin", "hindi", "wala", "tidak", "nggak", "belum",
            "bukan", "नहीं", "नही"}
POLITE = {"ji", "जी", "po", "sir", "maam", "madam", "please", "thanks", "thank", "you", "pak", "bu", "mbak", "mas", "kak", "bhai"}
LEAD = {"so", "well", "uh", "um", "umm", "hmm", "oh", "ah", "sure", "yes", "yeah", "okay", "ok", "haan"}

NUM_FILLERS = {"im", "i", "am", "shes", "she", "hes", "he", "is", "its", "it", "my", "age", "years", "year", "old",
               "yrs", "about", "around", "almost", "nearly", "wife", "husband", "spouse", "just", "only", "turned",
               "child", "children", "kid", "kids", "son", "sons", "daughter", "daughters", "we", "have"}
AMOUNT_FILLERS = {"around", "about", "roughly", "approximately", "approx", "maybe", "max", "maximum", "up", "to", "upto",
                  "under", "below", "rupees", "rupee", "rs", "inr", "per", "a", "year", "yearly", "annually", "annum",
                  "annual", "each", "every", "premium", "budget", "my", "is", "i", "can", "spend", "would", "like",
                  "of", "only", "just"}
MONTHLY = {"month", "monthly", "mahina"}
PLACE_PREFIX = ("i live in", "we live in", "i stay in", "i am in", "im in", "im based in", "i am based in", "based in",
                "im from", "i am from", "from", "in", "its", "it is", "the city is", "city is")
NAME_PREFIX = ("mera naam", "mera name", "main", "my name is", "my names", "name is", "this is", "its", "it is", "im", "i am", "call me", "you can call me")

UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * (i + 2) for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
SCALES = {"thousand": 1_000, "k": 1_000, "hazaar": 1_000, "hazar": 1_000, "lakh": 100_000, "lakhs": 100_000,
          "lac": 100_000, "crore": 10_000_000}
DEVANAGARI = chr(0x900) + "-" + chr(0x97F)
_GROUPED = re.compile(r"(\d),(\d{2,3})\b")


def norm(text: str) -> str:
    t = text.lower().replace("’", "'").replace("pre-existing", "preexisting").replace("pre existing", "preexisting")
    while _GROUPED.search(t):
        t = _GROUPED.sub(r"\1\2", t)                       # 20,000 / 1,50,000 -> plain digits
    t = re.sub(r"(\d+(?:\.\d+)?)\s*k\b", r"\1 k", t)       # 15k -> 15 k
    t = t.replace("'", "").replace("-", " ").replace("₹", " rupees ").replace("।", " ")
    t = re.sub(r"[^\w\s." + DEVANAGARI + "]", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)              # keep 1.5, drop sentence dots
    return " ".join(w for w in t.split() if w not in POLITE)


def number(tokens: list[str]) -> float | None:
    """'thirty four' / '34' / 'twenty thousand' / '1.5 lakh' -> number; None for anything else or two numbers."""
    total, current, seen, after_scale = 0.0, 0.0, False, False
    for tok in tokens:
        if re.fullmatch(r"\d+(?:\.\d+)?", tok):
            if current:
                return None
            current, seen = float(tok), True
        elif tok in TENS:
            if current % 100:
                return None
            current, seen = current + TENS[tok], True
        elif tok in UNITS:
            v = UNITS[tok]
            if (v < 10 and current % 10) or (v >= 10 and current % 100):
                return None
            current, seen = current + v, True
        elif tok == "hundred":
            if not current or current >= 100:
                return None
            current *= 100
        elif tok in SCALES:
            total, current, seen, after_scale = total + (current or 1) * SCALES[tok], 0.0, True, True
            continue
        elif tok == "and" and after_scale:
            continue
        else:
            return None
        after_scale = False
    return total + current if seen else None


def _strip_prefix(text: str, prefixes) -> str:
    for p in sorted(prefixes, key=len, reverse=True):
        if text == p or text.startswith(p + " "):
            return text[len(p):].strip()
    return text


def _lead_strip(text: str) -> str:
    words = text.split()
    while len(words) > 1 and words[0] in LEAD:
        words = words[1:]
    return " ".join(words)


def _polarity(text: str, spec: FieldSpec) -> bool | None:
    padded = f" {text} "
    if any(f" {h} " in padded for h in HEDGE) or re.search(r"\d", text):
        return None
    yes = YES | (YES_SOFT if spec.quick in ("consent", "confirm") else set())
    for phrase in sorted(yes | NO, key=len, reverse=True):
        if text == phrase or text.startswith(phrase + " "):
            rest, polarity = text[len(phrase):].split(), phrase not in NO
            break
    else:
        rest, polarity = text.split(), False               # "None of us..." without a leading yes/no word
        if not any(w in NEGATORS for w in rest):
            return None
    allowed = RESTATE | NEGATORS | yes | {w for c in spec.cues for w in norm(c).split()}
    if any(w not in allowed and w.rstrip("s") not in allowed for w in rest):
        return None                                        # extra content: let the LLM read it
    if polarity and any(w in NEGATORS for w in rest):
        return None                                        # "yes, I don't..." is contradictory
    if polarity is False and spec.quick == "confirm":
        return None                                        # "no" to "is this X?" needs nuance (spouse, wrong number)
    return polarity


STRONG = [{"first", "1st", "pehla", "pehli", "पहला", "पहली", "पहले"},
          {"second", "2nd", "middle", "medium", "dusra", "दूसरा", "दूसरी", "दूसरे"},
          {"third", "3rd", "teesra", "तीसरा", "तीसरी", "तीसरे"}]
WEAK = [{"one", "1", "a"}, {"two", "2", "b"}, {"three", "3", "c"}]     # "option 2", "number two"
LOW = {"cheapest", "lowest", "smallest", "least", "minimum", "cheaper", "basic", "sasta", "सस्ता", "छोटा"}
HIGH = {"biggest", "highest", "largest", "maximum", "most", "last", "best", "bada", "बड़ा"}


def pick_option(text: str, options: list[dict]) -> dict | None:
    """'the second one' / '10 lakh' / 'the cheapest' / '9000' -> the offered option, else None (the LLM reads it)."""
    t = norm(text)
    words = t.split()
    if not words or any(f" {h} " in f" {t} " for h in HEDGE) or any(w in NEGATORS for w in words):
        return None
    ws = set(words)
    if ws & {"lakh", "lakhs", "लाख"}:
        n = number([w for w in words if w in UNITS or w in TENS or re.fullmatch(r"\d+(?:\.\d+)?", w)])
        hit = [o for o in options if n is not None and o["si"] == n]
        if hit:
            return hit[0]
    amount = number([w for w in words if w in UNITS or w in TENS or w in SCALES or w == "hundred" or re.fullmatch(r"\d+", w)])
    if amount and amount >= 1000:
        hit = [o for o in options if abs(o["premium"] - amount) <= max(250, 0.05 * o["premium"])]
        if hit:
            return hit[0]
    for i, o in enumerate(options[:3]):
        if STRONG[i] & ws:
            return o
    if LOW & ws:
        return options[0]
    if HIGH & ws:
        return options[-1]
    for i, o in enumerate(options[:3]):      # last: bare "one"/"2" ("option 2"), which the words above must not shadow
        if WEAK[i] & ws:
            return o
    return None


def _cued(spec: FieldSpec, agent_said: str) -> bool:
    said = norm(agent_said)
    return any(norm(c) in said for c in spec.cues)


def resolve(pack: Pack, state: CallState, agent_said: str, utterance: str) -> dict | None:
    """Extraction-shaped result for a plain answer to the awaited field, else None."""
    if state.awaiting == "budget_choice" and state.options and utterance.strip() and "?" not in utterance:
        o = pick_option(utterance, state.options)
        if o:
            return {"updates": [{"field": "preferred_sum_insured_lakh", "value": o["si"], "confidence": 0.95},
                                {"field": "budget_annual_inr", "value": o["premium"], "confidence": 0.9}],
                    "intents": ["answer"], "objection": None, "sentiment": 0.0, "quick": True, "latency_ms": 0.0}
    if state.awaiting == "lowest_option" and state.options and utterance.strip() and "?" not in utterance:
        if _polarity(norm(utterance), FieldSpec(name="lowest_option", quick="consent")) is not None:
            return _result("", None, ["answer"])               # the engine applies the yes / keeps the budget on a no
    if state.checking and utterance.strip() and "?" not in utterance:
        if _polarity(norm(utterance), FieldSpec(name=state.checking, quick="yesno")) is not None:
            return _result("", None, ["answer"])               # "yes"/"no" to a read-back: the engine applies it
    spec = pack.field(state.awaiting or "")
    if not spec or not spec.quick or not utterance.strip() or "?" in utterance:
        return None
    if not state.awaiting_exact and not _cued(spec, agent_said):
        return None                                        # the LLM may have asked something else
    text = norm(utterance)
    if spec.quick in ("yesno", "consent", "confirm"):
        value = _polarity(text, spec)
        if value is None:
            return None
        return _result(spec.name, value, ["busy"] if value is False and spec.on_no == "busy" else ["answer"])
    text, value = _lead_strip(text), None
    if spec.quick == "number":
        n = number([w for w in text.split() if w not in NUM_FILLERS])
        value = int(n) if n is not None and n == int(n) else None
    elif spec.quick == "amount":
        words = text.split()
        n = number([w for w in words if w not in AMOUNT_FILLERS and w not in MONTHLY])
        value = int(round(n * (12 if any(w in MONTHLY for w in words) else 1))) if n else None
    elif spec.quick == "city":
        place = _strip_prefix(text, PLACE_PREFIX)
        value = place.title() if place in spec.known else None
    elif spec.quick == "name":
        name = _strip_prefix(text, NAME_PREFIX).split()
        name = [w for w in name if w not in ("hai", "hoon", "hun", "है", "हूँ")]
        blocked = YES | YES_SOFT | NO | LEAD | HEDGE | {"hi", "hello", "hey"}
        if 1 <= len(name) <= 2 and all(w.isascii() and w.isalpha() and w not in blocked for w in name):
            value = " ".join(w.title() for w in name)
    return _result(spec.name, value, ["answer"]) if value is not None else None


def _result(field: str, value, intents: list[str]) -> dict:
    return {"updates": [{"field": field, "value": value, "confidence": 0.95}] if field else [], "intents": intents, "objection": None,
            "sentiment": 0.0, "quick": True, "latency_ms": 0.0}
