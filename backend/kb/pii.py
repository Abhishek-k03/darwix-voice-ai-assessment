"""PII detection and redaction (Presidio + spaCy NER + custom IN/PH/ID recognizers).

Policy: records are stored and indexed redacted; raw PII never reaches the index. Documents that are
customer records (e.g. a filled proposal form) are quarantined entirely — they are data, not knowledge.
"""

from __future__ import annotations

import logging
import re

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

logger = logging.getLogger("kb.pii")
logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)

ENTITIES = ["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "CREDIT_CARD", "IN_PAN", "IN_AADHAAR",
            "IN_PHONE", "PH_PHONE", "ID_PHONE", "PH_TIN", "ID_NIK", "ID_NPWP"]
CUSTOMER_RECORD_MIN_TYPES = 3
PERSON_WINDOW = 100
PERSON_CONTEXT_DOC_TYPES = {"testimonial"}

_VERHOEFF_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
               [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
               [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
               [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VERHOEFF_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
               [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
               [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_valid(num: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


class _AadhaarRecognizer(PatternRecognizer):
    def __init__(self) -> None:
        super().__init__(supported_entity="IN_AADHAAR",
                         patterns=[Pattern("aadhaar", r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b", 0.5)],
                         context=["aadhaar", "uid", "uidai"])

    def validate_result(self, pattern_text: str) -> bool | None:
        digits = re.sub(r"\D", "", pattern_text)
        return len(digits) == 12 and verhoeff_valid(digits)


def _pattern(entity: str, regex: str, score: float, context: list[str] | None = None) -> PatternRecognizer:
    return PatternRecognizer(supported_entity=entity, patterns=[Pattern(entity.lower(), regex, score)],
                             context=context or [])


class PIIScrubber:
    def __init__(self, allow_list: list[str] | None = None) -> None:
        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]})
        self.analyzer = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
        reg = self.analyzer.registry
        reg.add_recognizer(_AadhaarRecognizer())
        reg.add_recognizer(_pattern("IN_PAN", r"\b[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]\b", 0.85, ["pan"]))
        reg.add_recognizer(_pattern("IN_PHONE", r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)", 0.7))
        reg.add_recognizer(_pattern("PH_PHONE", r"(?<!\d)(?:\+63[\s-]?|0)9\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)", 0.7))
        reg.add_recognizer(_pattern("ID_PHONE", r"(?<!\d)(?:\+62[\s-]?|0)8\d{2}[\s-]?\d{3,4}[\s-]?\d{3,4}(?!\d)", 0.7))
        reg.add_recognizer(_pattern("PH_TIN", r"\b\d{3}-\d{3}-\d{3}(?:-\d{3})?\b", 0.4, ["tin", "taxpayer"]))
        reg.add_recognizer(_pattern("ID_NIK", r"\b\d{16}\b", 0.4, ["nik", "ktp"]))
        reg.add_recognizer(_pattern("ID_NPWP", r"\b\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.\d{3}\b", 0.8))
        # quote attributions ("— Ramesh Kumar, Pune") and labelled names ("Name: Anil Verma") that small NER misses
        reg.add_recognizer(_pattern("PERSON", r"(?<=[—–-] )[A-Z][a-z]+(?: [A-Z][a-z]+){1,2}(?=,)", 0.6))
        reg.add_recognizer(_pattern("PERSON", r"(?<=Name: )[A-Z][a-z]+(?: [A-Z][a-z]+){1,2}", 0.7))
        self.anonymizer = AnonymizerEngine()
        self.allow = [a.lower() for a in (allow_list or [])]

    def _keep(self, text: str, r: RecognizerResult) -> bool:
        span = text[r.start:r.end]
        low = span.lower()
        if any(a in low or low in a for a in self.allow):
            return False
        if r.entity_type == "PERSON":
            tokens = [t for t in re.split(r"\s+", span) if t]
            if len(tokens) < 2 or not all(t[0].isupper() for t in tokens):
                return False
        return r.score >= 0.4

    def analyze(self, text: str, person_context: bool = False) -> list[RecognizerResult]:
        """PERSON (small NER, noisy on place/product names) is kept only when a direct identifier
        (phone/email/ID) is within PERSON_WINDOW chars, or the caller marks the text as people-centric."""
        results = [r for r in self.analyzer.analyze(text=text, language="en", entities=ENTITIES) if self._keep(text, r)]
        direct = [r for r in results if r.entity_type != "PERSON"]
        return [r for r in results if r.entity_type != "PERSON" or person_context
                or any(abs(d.start - r.end) <= PERSON_WINDOW or abs(r.start - d.end) <= PERSON_WINDOW for d in direct)]

    def redact(self, text: str, person_context: bool = False) -> tuple[str, list[str]]:
        results = self.analyze(text, person_context)
        if not results:
            return text, []
        ops = {r.entity_type: OperatorConfig("replace", {"new_value": f"[REDACTED_{_label(r.entity_type)}]"})
               for r in results}
        out = self.anonymizer.anonymize(text=text, analyzer_results=results, operators=ops)
        return out.text, sorted({_label(r.entity_type) for r in results})


def _label(entity: str) -> str:
    return "PHONE" if entity.endswith("PHONE") or entity == "PHONE_NUMBER" else entity.replace("_ADDRESS", "")
