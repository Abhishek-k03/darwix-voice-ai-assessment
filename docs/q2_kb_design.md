# Q2: Production-ready knowledge base

The knowledge base turns mixed, messy business content into versioned, citable records. It feeds the voice agent (Q1), the native-language bots (Q3) and the live copilot's nudges (Q4) through one service, `GET /kb/search`. The knowledge page uses `POST /kb/answer`: it retrieves, has the LLM write a short answer that may cite only the retrieved records (invalid citations are dropped; with none left, or if the LLM is unavailable, the page quotes the records themselves), and returns the sources with their match percentage.

- **Build:** `uv run python -m kb.build` (idempotent, about 15 s)
- **Evaluate:** `uv run python -m kb.eval`
- **Browse:** `/kb` in the web app

Outputs:
- `data/kb/records.jsonl`, `manifest.json` and `changelog.json`
- `build_report.md` (every flagged issue)
- `evidence/q2/retrieval_report.md`

## 1. Source corpus

No source material came with the assignment, so `backend/kb/corpus/` generates a realistic corpus for three fictional brands. It contains the problems the assignment lists, injected deliberately:

| Market | Sources | Injected problems |
|---|---|---|
| India health (Q1) | 13-page website (product, FAQ, claims, network, partners, blog, testimonials, contact); policy-wording PDF; brochure PDF in 2024 and 2025 editions; blank and filled proposal forms; scanned endorsement; premium CSV; eligibility XLSX; objection playbook | Navigation, header, footer and cookie banner on every page. The blog and the 2025 brochure copy website paragraphs. Terms vary (PED / pre-existing illness / existing conditions; SI / cover amount / sum assured). Dates come in four formats, plus one invalid date (31/02/2025). The FAQ still says "3 years" PED waiting while the 2025 policy says 24 months. The PDF font has no ₹ glyph. The rate table has one missing value and one 10× outlier. Testimonials and a filled form contain PII. There is a JS-only page and a dead link. |
| Philippines life (Q3) | Website (English), servicing-guide PDF, objection playbook in Taglish | Bancassurance disclosures; Taglish internal content |
| Indonesia multifinance (Q3) | Website (formal Bahasa), restructuring-policy PDF, collection-ethics summary, playbook | Colloquial vs formal register; cicilan/angsuran synonyms |

## 2. Extraction (`kb/extract.py`)

- **Websites:** a real HTTP crawl, served locally so it is reproducible.
  - Breadth-first from seed URLs, restricted to a path prefix, with a `robots.txt` check, retries, and content-type filtering.
  - trafilatura extracts the main content as structured XML (headings, paragraphs, lists, tables, quotes), with a BeautifulSoup fallback.
  - `--include-external` adds a public Wikipedia page to show live web extraction.
- **PDFs:** pdfplumber, layout-aware.
  - Font size and weight identify the title and section headings.
  - Tables are extracted separately and merged back in reading order by vertical position.
  - Running headers and footers are removed by frequency across pages, with digits normalized so "Page 1" and "Page 2" match.
- **CSV/XLSX:** each row becomes a block carrying its header context, one sheet per section.
- **Failures never abort the build.** They are recorded in `build_report.md`:
  - HTTP 404 (dead link);
  - "no server-rendered content (JavaScript-rendered page)";
  - "no text layer (scanned image), OCR required".

## 3. Cleaning and normalization

| Step | How | Evidence (build v1.0.0) |
|---|---|---|
| Boilerplate | trafilatura, then removal of short blocks repeated on 50% or more of a site's pages | 16,462 chars of site chrome removed |
| Headers/footers | Per-page frequency, page-number lines, `A \| B \| C` banners | 12 lines removed |
| Glyph repair | `■2,000` / `n2,000` back to `₹2,000` (regex rules in `normalization.yaml`) | 8 repaired |
| Terminology | Glossary maps variants to canonical terms; variants kept as tags for lexical recall | 20 variants normalized |
| Dates | Four formats (EN/ID/TL month names, DMY) converted to ISO 8601; invalid dates flagged | `31/02/2025` flagged |
| Headings | Numbering stripped, synonyms mapped ("What is not covered" → Exclusions) | |
| Form fields | Labels mapped to canonical snake_case (`D.O.B.` → `date_of_birth`) | `kb_in_form_001` |

## 4. PII protection (`kb/pii.py`)

- **Detection:** Presidio with spaCy NER, plus custom recognizers:
  - India: PAN, Aadhaar (with Verhoeff checksum validation), +91 mobile;
  - Philippines: +63 mobile, TIN;
  - Indonesia: +62 mobile, NIK, NPWP.
- **Redact before indexing:** records are stored as `[REDACTED_PHONE]` and similar, with `pii=true` and `pii_types`. Raw values never reach the index.
- **PERSON precision:** the small spaCy model tags places and products ("Delhi NCR", "Family Floater") as names. A PERSON hit is therefore redacted only when a direct identifier (phone, email or ID) is within 100 characters, or the record is a testimonial. Quote attributions ("— Ramesh Kumar,") use a dedicated pattern.
- **Allow-list:** corporate helplines, emails and brand names are public business data and are not treated as PII.
- **Quarantine:** a form containing three or more PII types is treated as a customer record, not knowledge, and excluded entirely. The filled proposal form is quarantined this way.

## 5. Duplicates, versions and conflicts

- **Exact duplicates (paragraph level, before chunking):** the highest-authority copy is kept, and the others become `also_found_in` source references. 11 blocks were merged.
- **Near duplicates (record level):** MinHash LSH (Jaccard ≥ 0.8) on word 3-shingles.
- **Superseded documents:** within one `doc_group`, the newest `effective_date` wins. The 2024 brochure is `status=superseded`: kept for traceability, not indexed.
- **Conflicts (`kb/conflicts.py`):**
  - Facts declared in `taxonomy.yaml` (PED waiting, grace period, free-look period, late fee…) are extracted from every active record and normalized to one unit.
  - If values disagree, authority decides (policy wording 5 > approved internal 4 > forms 3 > website 2 > marketing 1), then recency.
  - The losing record stays, but gets `needs_review=true` plus a `conflicts` annotation. Retrieval demotes it ×0.5, and the LLM context marks it "OUTDATED: use kb_in_policy_008".
- **Table source errors:** a missing value, or a value more than 3× its neighbours in the age-band series, is flagged. That premium is withheld in the KB record ("premium unavailable (flagged for review)"). The voice agent's pricing reads the same check, so it can never quote it.

## 6. Schema and sample records

`kb/schema.py` (pydantic). Fields:
- identity and content: `record_id`, `title`, `content`;
- classification: `category` (taxonomy), `subcategory`, `doc_type` (faq | product_info | policy_rule | qualification_rule | premium_table | objection | form_field | process | contact | marketing | testimonial | compliance), `product`, `market`, `language`;
- source: `source {source_id, type, uri, section, page, retrieved_at, content_hash}`;
- versioning: `version`, `effective_date`, `status`;
- quality flags: `authority`, `pii`, `pii_types`, `also_found_in`, `conflicts`, `needs_review`, `tags`;
- structure: `parent_id`, `chunk_index`, `token_count`, `kb_version`.

| Field | Example (authoritative) | Example (conflicting, flagged) | Example (PII redacted) |
|---|---|---|---|
| record_id | `kb_in_policy_008` | `kb_in_faq_010` | `kb_in_testimonial_001` |
| title | Policy Wording (effective 2025-04-01) › Waiting Periods | What is the waiting period for pre-existing condition? | What our customers say |
| content | "Waiting period: Pre-existing condition \| Duration: 24 months \| Notes: Reduced from 36 months…" | "Pre-existing condition are covered after a waiting period of 3 years…" | "…approved cashless within 3 hours…" — [REDACTED_PERSON], Pune, [REDACTED_PHONE], [REDACTED_EMAIL] |
| category / doc_type | waiting_periods / policy_rule | waiting_periods / faq | testimonials / testimonial |
| source | in_health/docs/policy_wording_2025.pdf p.1 › Waiting Periods | /in_health/site/faq.html | /in_health/site/testimonials.html |
| version / effective | 1.0 / 2025-04-01 | 1.0 / — | 1.0 / — |
| authority | 5 | 2 | 1 |
| PII | false | false | true (EMAIL, PERSON, PHONE) |
| conflicts | — | `ped_waiting_period_months`: 36 vs authoritative 24 (`kb_in_policy_008`), needs_review | — |
| tags | PED, pre-existing illness… | pre-existing illnesses | |

## 7. Chunking and metadata

Chunks are structure-aware, not fixed-size:
- one **FAQ Q&A pair** per record, with the question as title;
- one **policy section** per record, at most about 320 tokens, split at block boundaries with one block of overlap;
- one **rate-table group** (product × age band) per record, with Indian-format amounts;
- one **eligibility rule** row per record;
- one **form schema** per form.

Every record carries the document and section title as context for embedding and display. Totals: 136 records (134 active): 84 India, 27 Philippines, 25 Indonesia.

## 8. Taxonomy

The taxonomy has 22 topic categories, e.g. waiting_periods, exclusions, eligibility, premium_and_payment, claims, renewal_portability, lapse_reinstatement, late_fees, restructuring, collections_ethics, objection_handling and compliance_disclosure.
- Structured doc types (rates, rules, objections, forms, testimonials, contact, compliance) take a fixed category.
- Prose is scored on multilingual keywords: title ×3 + content.
- Products are detected per market (Secure, FamilyShield, Silver; FamilyCare; Pembiayaan Motor).

## 9. Versioning and indexing

- **Stable IDs:** `kb_{market}_{type}_{nnn}` from a stable source key (source + section + chunk index), reused across builds.
- **Record version:** bumped when its content hash changes.
- **KB version (semver):** minor when records are added or removed, patch when content is updated. A changelog is kept.
- **One Chroma collection per KB version** (`kb-1.0.0`, cosine distance), keeping the primary repo's vector store, so a bad build can be rolled back by switching the active version.
- **Embeddings:** `intfloat/multilingual-e5-small` via fastembed ONNX on CPU: 384 dimensions, 100 languages including Tagalog, about 8 ms per query.
  - The original all-MiniLM-L6-v2 is English-only.
  - paraphrase-multilingual-MiniLM doesn't cover Tagalog.
  - e5-large is 2.2 GB.
- **A single KB service** (the FastAPI backend) serves every worker. There is one model instance per deployment and one source of truth for the active version.

## 10. Retrieval and ranking (`kb/retriever.py`)

1. **Query normalization:** the same glossary as the KB (cicilan → angsuran, PED → pre-existing condition), plus query-side synonyms (mother → parents, sugar/BP → pre-existing condition, "how long before" → waiting period).
2. **Metadata filter:** market, doc type and active status.
3. **Dense candidates:** e5 + Chroma, top 20.
4. **Lexical candidates:** in-house BM25, top 20. It uses a multilingual stopword list and a light Indonesian affix stemmer (menagih / penagihan → nagih).
5. **Fusion:** RRF (k = 60), then scaled by:
   - IDF-weighted query coverage (informative words like "cosmetic" or "GCash" outweigh "covered" or "pwede");
   - a doc-type prior (marketing ×0.9, testimonials ×0.8);
   - product-mention and age-band boosts (×1.3);
   - the conflict demotion (×0.5).
6. **Optional cross-encoder rerank** (`KB_RERANK=true`): jina-reranker-v2 multilingual. Off by default for the latency budget.
7. **No-match gate:** the top hit must have dense ≥ 0.79, and either dense ≥ 0.845 or weighted coverage ≥ 0.30. Otherwise the result is `NO_RELEVANT_INFO`, and the agent says it doesn't have the information and offers an advisor.

## 11. Citations

Every hit returns `[record_id] title — file p.N › section`. The voice agent doesn't read citations aloud. They are:
- logged per turn in the call transcript;
- shown in the call console's KB panel;
- attached to Q4 nudges (e.g. the "Budget concern" nudge cites the approved objection-playbook record).

## 12. Retrieval test results (`evidence/q2/retrieval_report.md`)

29 queries: 25 in the tuning set plus 4 held out after calibration. They cover product, policy, qualification, FAQ, objection, out-of-scope, Taglish and Bahasa.

| Metric | Value |
|---|---|
| Verdicts | **24 correct · 3 partially correct · 2 incorrect** |
| hit@1 / hit@3 / MRR (in-scope) | 0.79 / 0.92 / 0.85 |
| Out-of-scope rejected | 5/5 (capital of France, flights, mutual funds, motorcycle insurance, Bali tickets) |
| Latency (CPU, no rerank) | P50 9 ms, P95 11 ms |
| Held-out only (4) | 2 correct · 1 partially correct · 1 incorrect |

Honest notes:
- The gate thresholds were calibrated on the same 25 queries; the held-out set is small. Production needs a larger labelled set per market and periodic recalibration, or the cross-encoder gate.
- **q10** ("premium for a 30 year old"): the age-band boost lifts both Secure 26-35 and FamilyShield 26-35, and nothing says "individual", so FamilyShield ranks first (partially correct). The voice agent never quotes from retrieval anyway; prices come from the deterministic rate lookup.
- **q24** "jam 10 malam" (10 pm) vs "pukul 20.00" needs semantic time understanding. The "Larangan" record wins on the shared "petugas menagih".
- **h02** (Hinglish: "Kya claim ke liye OTP dena padega?") is rejected by the gate. Hinglish needs transliteration/translation of the query or Hinglish synonyms. This is a known gap.

## 13. Limitations and next steps

- OCR (Tesseract or a cloud OCR) for scanned PDFs instead of only flagging them.
- JS-rendered pages need a headless browser (Playwright) in the crawler.
- A human review queue for `needs_review` records and quarantined documents.
- spaCy multilingual NER (xx_ent_wiki_sm) for Tagalog and Indonesian names; PII is regex-only there today.
- Larger evaluation sets, LLM-judged relevance labels, and an online feedback loop from agent citations.
