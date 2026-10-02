# KB build report — v1.0.0

Built 2026-10-01T11:50:12+00:00 in 15.7s. Records: 136 (134 active).

## Pipeline statistics

- boilerplate blocks removed: 0
- web chrome chars removed: 16462
- web pages extracted: 20
- running header footer lines removed: 12
- pdf extracted: 7
- csv extracted: 1
- xlsx extracted: 1
- markdown extracted: 4
- glyphs repaired: 8
- terminology variants normalized: 20
- duplicate blocks removed: 11
- near duplicate records merged: 0

## Records

| market | count |
|---|---|
| in_health | 84 |
| id_multifinance | 25 |
| ph_life | 27 |

| doc_type | count |
|---|---|
| policy_rule | 18 |
| premium_table | 14 |
| qualification_rule | 13 |
| objection | 22 |
| compliance | 4 |
| form_field | 1 |
| product_info | 22 |
| contact | 3 |
| process | 4 |
| faq | 28 |
| marketing | 6 |
| testimonial | 1 |

## Extraction failures, quarantines and source errors

| kind | source | uri | detail |
|---|---|---|---|
| extraction_failure | in_site | http://127.0.0.1:64676/in_health/site/offers-2023.html | HTTP 404 (dead link) |
| extraction_failure | in_site | http://127.0.0.1:64676/in_health/site/compare.html | no server-rendered content (JavaScript-rendered page) |
| extraction_failure | in_scanned_endorsement | in_health/docs/scanned_endorsement.pdf | no text layer (scanned image) — OCR required |
| quarantined | in_proposal_form_filled | in_health/docs/proposal_form_filled_sample.pdf | customer record with personal data (EMAIL_ADDRESS, IN_AADHAAR, IN_PAN, IN_PHONE, PERSON, PHONE_NUMBER); excluded from KB |
| source_error | in_premium_rates_2025 | in_health/tables/premium_rates_2025.csv | outlier annual_premium_inr=200100 for Prithvi Secure / 1 adult / 10 lakh / 46-55 (>3x neighbouring values 9280, 12900, 28280, 37700) |
| source_error | in_premium_rates_2025 | in_health/tables/premium_rates_2025.csv | missing annual_premium_inr for Prithvi FamilyShield / 2 adults + 1 child / 10 lakh / 36-45 |
| conflict | multiple | in_health/docs/policy_wording_2025.pdf | in_health.ped_waiting_period_months: values [24.0, 36.0]; resolved to 24.0 from kb_in_policy_008 |

## Conflicts (resolved by authority, then recency)

- **in_health.ped_waiting_period_months** → 24.0 (kb_in_policy_008, in_health/docs/policy_wording_2025.pdf)
  - 24.0 — kb_in_policy_008 [in_health/docs/policy_wording_2025.pdf, authority 5]: “pre-existing condition declared in the proposal and accepted by the company are covered after 24 months of continuous”
  - 36.0 — kb_in_faq_010 [/in_health/site/faq.html, authority 2]: “pre-existing condition are covered after a waiting period of 3 years”
  - 24.0 — kb_in_marketing_003 [in_health/docs/brochure_familyshield_2025.pdf, authority 1]: “pre-existing condition covered after only 24 months”

## Superseded documents

- in_health/docs/brochure_familyshield_2024.pdf (superseded by in_health/docs/brochure_familyshield_2025.pdf)

## Near-duplicates merged


## Records containing redacted PII

- kb_in_testimonial_001: EMAIL, PERSON, PHONE

## Changes vs previous build

- added: 136
- updated: 0
- removed: 0
