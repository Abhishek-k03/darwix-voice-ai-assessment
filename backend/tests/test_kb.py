"""KB pipeline unit tests (no network, no index). Run from backend/: uv run python -m unittest discover -s tests -t ."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from kb import clean, conflicts, dedupe
from kb.chunk import _section_chunks, format_inr
from kb.normalize import Normalizer
from kb.retriever import BM25, tokenize
from kb.schema import Block, KBRecord, RawDoc, SourceRef

CFG = Path(__file__).resolve().parents[1] / "kb" / "config"
NORM = yaml.safe_load((CFG / "normalization.yaml").read_text(encoding="utf-8"))
TAX = yaml.safe_load((CFG / "taxonomy.yaml").read_text(encoding="utf-8"))


def _doc(**kw) -> RawDoc:
    base = dict(source_id="s", market="in_health", language="en", type="web", uri="/x", title="T", blocks=[],
                authority=2, doc_type="faq", doc_group="g", retrieved_at="now", raw_hash="h")
    base.update(kw)
    return RawDoc(**base)


def _rec(content: str, authority: int = 2, **kw) -> KBRecord:
    return KBRecord(title=kw.pop("title", "t"), content=content, doc_type="faq", market="in_health", language="en",
                    source=SourceRef(source_id="s", type="web", uri=kw.pop("uri", "/x")), authority=authority, **kw)


class CleaningTests(unittest.TestCase):
    def test_running_headers_footers_removed(self):
        pages = [["ACME | Policy Wording | UIN 1", "Body one.", "Footer text | Page 1"],
                 ["ACME | Policy Wording | UIN 1", "Body two.", "Footer text | Page 2"]]
        out, removed = clean.strip_running_lines(pages)
        self.assertEqual(out, [["Body one."], ["Body two."]])
        self.assertEqual(removed, 4)

    def test_rupee_glyph_repair(self):
        text, n = clean.repair_glyphs("ambulance up to n2,000 and ■5 lakh; not inner2", NORM["glyph_repairs"])
        self.assertEqual(text, "ambulance up to ₹2,000 and ₹5 lakh; not inner2")
        self.assertEqual(n, 2)


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.n = Normalizer(NORM, TAX)

    def test_terminology_variants(self):
        text, hits = self.n.terminology("PED covered after 24 months. Cover amount options. SIgnature stays.", "in_health")
        self.assertIn("pre-existing condition covered", text)
        self.assertIn("Sum insured options", text)
        self.assertIn("SIgnature", text)
        self.assertTrue({"PED", "cover amount"} <= hits)

    def test_dates_iso_and_invalid_flagged(self):
        text, bad = self.n.dates("From 1st April 2025, also 01/04/2024, April 1, 2025 and 1 Januari 2025; bad 31/02/2025")
        self.assertEqual(text.count("2025-04-01"), 2)
        self.assertIn("2024-04-01", text)
        self.assertIn("2025-01-01", text)
        self.assertEqual(bad, ["31/02/2025"])

    def test_heading_numbering_and_synonyms(self):
        self.assertEqual(self.n.heading("4. Waiting Periods"), "Waiting Periods")
        self.assertEqual(self.n.heading("WHAT IS NOT COVERED"), "Exclusions")

    def test_fixed_category_for_structured_doc_types(self):
        self.assertEqual(self.n.categorize("Indicative premium", "zone A", "premium_table"), "premium_and_payment")


class DedupeConflictTests(unittest.TestCase):
    def test_block_dedupe_keeps_highest_authority_with_trace(self):
        para = "Cashless hospitalisation at 8,500+ network hospitals across India for all plans."
        hi = _doc(source_id="policy", uri="/policy", authority=5, blocks=[Block(kind="paragraph", text=para)])
        lo = _doc(source_id="blog", uri="/blog", authority=1, blocks=[Block(kind="paragraph", text=para)])
        self.assertEqual(dedupe.dedupe_blocks([lo, hi]), 1)
        self.assertEqual(len(lo.blocks), 0)
        self.assertEqual(hi.blocks[0].also_found_in[0].uri, "/blog")

    def test_table_series_flags_missing_and_outlier(self):
        rows = [("18-25", "5000"), ("26-35", "6000"), ("36-45", "70000"), ("46-55", ""), ("56-60", "9000")]
        doc = _doc(doc_type="premium_table", blocks=[
            Block(kind="table_row", text="", cells={"product": "P", "members": "1", "sum_insured": "5", "age_band": b,
                                                    "annual_premium_inr": v}) for b, v in rows])
        src = {"value_column": "annual_premium_inr", "series_by": ["product", "members", "sum_insured"], "order_column": "age_band"}
        issues, flagged = conflicts.check_series(doc, src)
        self.assertEqual(flagged, {("P", "1", "5", "36-45"), ("P", "1", "5", "46-55")})
        self.assertEqual(len(issues), 2)

    def test_conflicting_fact_resolved_by_authority(self):
        good = _rec("Pre-existing condition declared are covered after 24 months of continuous coverage.", 5, uri="/policy")
        stale = _rec("Pre-existing condition are covered after a waiting period of 3 years.", 2, uri="/faq")
        good.record_id, stale.record_id = "kb_policy", "kb_faq"
        found = conflicts.detect_conflicts([good, stale], TAX["facts"])
        self.assertEqual(found[0]["resolution"], 24.0)
        self.assertTrue(stale.needs_review)
        self.assertFalse(good.needs_review)
        self.assertEqual(stale.conflicts[0]["authoritative_record"], "kb_policy")


class ChunkAndRetrievalTests(unittest.TestCase):
    def test_faq_question_becomes_title(self):
        doc = _doc(blocks=[Block(kind="heading", text="What is the grace period?", level=3),
                           Block(kind="paragraph", text="Renewal premium can be paid within 30 days after the due date.")])
        recs = _section_chunks(doc)
        self.assertEqual(recs[0].title, "What is the grace period?")

    def test_indian_number_format(self):
        self.assertEqual(format_inr(123450), "₹1,23,450")
        self.assertEqual(format_inr("6400"), "₹6,400")

    def test_indonesian_stemming_aligns_affixes(self):
        self.assertEqual(tokenize("menagih", "id_multifinance"), tokenize("penagihan", "id_multifinance"))

    def test_weighted_coverage_prefers_informative_terms(self):
        bm = BM25([["cosmetic", "exclusion"], ["covered", "dental"], ["covered", "opd"], ["covered", "room"]])
        q = ["cosmetic", "covered"]
        self.assertGreater(bm.weighted_coverage(q, {"cosmetic", "exclusion"}), bm.weighted_coverage(q, {"covered", "dental"}))


class PIITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kb.pii import PIIScrubber
        cls.s = PIIScrubber(NORM["pii_allow_list"])

    def test_direct_identifiers_redacted(self):
        out, types = self.s.redact("Call me on +91 98765 43210 or mail ramesh.k@example.com, PAN ABCPV1234F")
        self.assertNotIn("98765", out)
        self.assertNotIn("example.com", out)
        self.assertNotIn("ABCPV1234F", out)
        self.assertTrue({"PHONE", "EMAIL", "IN_PAN"} <= set(types))

    def test_corporate_helpline_and_places_kept(self):
        text = "Customer care: 1800-000-1234. Zone A cities: Mumbai, Delhi NCR, Bengaluru."
        out, types = self.s.redact(text)
        self.assertEqual(out, text)
        self.assertEqual(types, [])


if __name__ == "__main__":
    unittest.main()
