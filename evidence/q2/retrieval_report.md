# Retrieval test report (KB v1.0.0)

29 queries · correct 24 · partially correct 3 · incorrect 2

- hit@1 0.792 · hit@3 0.917 · MRR 0.854 (in-scope queries)
- out-of-scope rejected: 5/5
- retrieval latency p50 9.1 ms · p95 10.6 ms (CPU, no rerank)

| # | type | market | question | retrieved record | source | verdict |
|---|---|---|---|---|---|---|
| q01 | product | in_health | What sum insured options are available in the family floater plan? | `kb_in_product_009` Prithvi FamilyShield — family floater plan | family floater plan — familyshield.html | **correct** |
| q02 | policy | in_health | How long is the waiting period for pre-existing diseases? | `kb_in_policy_008` Prithvi Secure and Prithvi FamilyShield — Policy Wording (ef | Policy Wording (effective 2025-04-01) › Waiting Periods — policy_wording_2025.pdf p.1 › Waiting Periods | **correct** |
| q03 | qualification | in_health | Can I add my 68 year old mother to the family floater? | `kb_in_product_009` Prithvi FamilyShield — family floater plan | family floater plan — familyshield.html | **correct** |
| q04 | qualification | in_health | Do I need a medical test if I am 50 years old? | `kb_in_faq_004` Do I need a medical test to buy a policy? | faq.html › Do I need a medical test to buy a policy? | **correct** |
| q05 | faq | in_health | Can I pay the premium every month instead of yearly? | `kb_in_faq_002` Can I pay my premium monthly? | faq.html › Can I pay my premium monthly? | **correct** |
| q06 | faq | in_health | If I don't like the policy can I cancel and get my money back? | `kb_in_faq_008` What is the free look period? | faq.html › What is the free look period? | **correct** |
| q07 | objection | in_health | The customer says health insurance is too expensive for them | `kb_in_objection_007` Objection Handling Playbook — Prithvi Health (internal, appr | Prithvi Health (internal, approved responses) › Objection: "It's too expensive" — objection_playbook.md › Objection: "It's too expensive" | **correct** |
| q08 | objection | in_health | I already get health cover from my employer, why buy another policy? | `kb_in_objection_001` Objection Handling Playbook — Prithvi Health (internal, appr | Prithvi Health (internal, approved responses) › Objection: "I already have insurance from my employer" — objection_playbook.md › Objection: "I already have insurance from my employer" | **correct** |
| q09 | faq | in_health | How do I get cashless treatment for a planned surgery? | `kb_in_product_003` Network hospitals | network-hospitals.html | **partially correct** |
| q10 | qualification | in_health | What is the premium for a 30 year old for 10 lakh cover? | `kb_in_rates_002` Indicative annual premium — Prithvi FamilyShield, age band 2 | Prithvi FamilyShield, age band 26-35 — premium_rates_2025.csv › Prithvi FamilyShield 26-35 | **partially correct** |
| q11 | product | in_health | Is there a co-payment in the senior citizen plan? | `kb_in_product_015` Prithvi Silver — health insurance for senior citizens | health insurance for senior citizens — silver.html | **correct** |
| q12 | product | in_health | What support do branch partners get? | `kb_in_product_005` Branch partnership benefits › What partners receive | partners.html › What partners receive | **correct** |
| q13 | policy | in_health | Is cosmetic surgery covered? | `kb_in_policy_004` Prithvi Secure and Prithvi FamilyShield — Policy Wording (ef | Policy Wording (effective 2025-04-01) › Exclusions — policy_wording_2025.pdf p.1 › Exclusions | **correct** |
| q14 | negative | in_health | What is the capital of France? | — (NO_RELEVANT_INFO) | — | **correct** |
| q15 | negative | in_health | Can you book me a flight to Goa next week? | — (NO_RELEVANT_INFO) | — | **correct** |
| q16 | negative | in_health | What's the best mutual fund to invest in right now? | — (NO_RELEVANT_INFO) | — | **correct** |
| q17 | faq | ph_life | Ilang araw ang grace period bago ma-lapse yung policy ko? | `kb_ph_objection_006` Premium Reminder Call Playbook — Bayanihan Life (internal, T | Bayanihan Life (internal, Taglish) › Objection: "Wala pa po akong pera ngayon" — objection_playbook_ph.md › Objection: "Wala pa po akong pera ngayon" | **correct** |
| q18 | policy | ph_life | Pwede ko pa bang ibalik yung na-lapse kong policy? | `kb_ph_policy_003` Policy Servicing Guide for Bancassurance Clients (2025) › La | policy_servicing_guide_2025.pdf p.1 › Lapse and reinstatement | **correct** |
| q19 | objection | ph_life | Wala pa po akong pera pambayad ng premium ngayon | `kb_ph_objection_006` Premium Reminder Call Playbook — Bayanihan Life (internal, T | Bayanihan Life (internal, Taglish) › Objection: "Wala pa po akong pera ngayon" — objection_playbook_ph.md › Objection: "Wala pa po akong pera ngayon" | **correct** |
| q20 | faq | ph_life | Saan po ako pwedeng magbayad, pwede ba sa GCash? | `kb_ph_faq_006` Where can I pay? | premium-payments.html › Where can I pay? | **correct** |
| q21 | faq | id_multifinance | Kalau telat bayar cicilan kena denda berapa? | `kb_id_objection_001` Playbook Panggilan Pengingat Angsuran — Maju Bersama Finance | Maju Bersama Finance (internal) › Keberatan: "Belum gajian, Mbak/Mas" — objection_playbook_id.md › Keberatan: "Belum gajian, Mbak/Mas" | **correct** |
| q22 | policy | id_multifinance | Saya baru kena PHK, apa ada keringanan angsuran? | `kb_id_objection_003` Playbook Panggilan Pengingat Angsuran — Maju Bersama Finance | Maju Bersama Finance (internal) › Keberatan: "Lagi susah, usaha lagi sepi" / "Saya baru kena PHK" — objection_playbook_id.md › Keberatan: "Lagi susah, usaha lagi sepi" / "Saya baru kena PHK" | **correct** |
| q23 | faq | id_multifinance | Bisa bayar angsuran lewat Indomaret nggak? | `kb_id_faq_005` Di mana saya bisa membayar angsuran? | pembayaran.html › Di mana saya bisa membayar angsuran? | **correct** |
| q24 | policy | id_multifinance | Bolehkah petugas menagih jam 10 malam? | `kb_id_compliance_002` Ringkasan Etika Penagihan (internal) › Larangan | etika_penagihan.md › Larangan | **incorrect** |
| q25 | negative | id_multifinance | Berapa harga tiket pesawat ke Bali bulan depan? | — (NO_RELEVANT_INFO) | — | **correct** |
| h01 | policy | in_health | My father has sugar, how long before it gets covered? | `kb_in_policy_008` Prithvi Secure and Prithvi FamilyShield — Policy Wording (ef | Policy Wording (effective 2025-04-01) › Waiting Periods — policy_wording_2025.pdf p.1 › Waiting Periods | **correct** |
| h02 | faq | in_health | Kya claim ke liye OTP dena padega? | — (NO_RELEVANT_INFO) | — | **incorrect** |
| h03 | negative | in_health | Do you sell motorcycle insurance? | — (NO_RELEVANT_INFO) | — | **correct** |
| h04 | faq | ph_life | Paano magpalit ng beneficiary sa policy ko? | `kb_ph_objection_002` Premium Reminder Call Playbook — Bayanihan Life (internal, T | Bayanihan Life (internal, Taglish) › Objection: "Hindi ko na po kailangan yung insurance" — objection_playbook_ph.md › Objection: "Hindi ko na po kailangan yung insurance" | **partially correct** |

## Details

### q01 — What sum insured options are available in the family floater plan?

- **Status:** ok · **Verdict:** correct · latency 42.1 ms
- **Retrieved:** `kb_in_product_009` — Prithvi FamilyShield — family floater plan
- **Chunk:** Prithvi FamilyShield is a family floater health insurance plan where one sum insured is shared by the whole family. It covers you, your spouse, up to 3 dependent children aged 91 days to 25 years, and dependent parents or parents-in-law up to entry age 65. A maximum of 6 members can be covered in on…
- **Source:** [kb_in_product_009] Prithvi FamilyShield — family floater plan — familyshield.html
- **Relevance:** Matches the expected record. Lexical overlap: family, floater, insured, options, plan, sum; dense similarity 0.880; doc type product_info; category product_overview

### q02 — How long is the waiting period for pre-existing diseases?

- **Status:** ok · **Verdict:** correct · latency 10.6 ms
- **Retrieved:** `kb_in_policy_008` — Prithvi Secure and Prithvi FamilyShield — Policy Wording (effective 2025-04-01) › Waiting Periods
- **Chunk:** Waiting period: Initial waiting period | Duration: 30 days | Notes: Accidents covered from day one Waiting period: Specific illnesses and procedures | Duration: 24 months | Notes: Cataract, hernia, joint replacement, kidney stones, sinusitis Waiting period: Pre-existing condition | Duration: 24 mont…
- **Source:** [kb_in_policy_008] Prithvi Secure and Prithvi FamilyShield — Policy Wording (effective 2025-04-01) › Waiting Periods — policy_wording_2025.pdf p.1 › Waiting Periods
- **Relevance:** Matches the expected record. Lexical overlap: condition, existing, period, pre, waiting; dense similarity 0.892; doc type policy_rule; category waiting_periods

### q03 — Can I add my 68 year old mother to the family floater?

- **Status:** ok · **Verdict:** correct · latency 10.2 ms
- **Retrieved:** `kb_in_product_009` — Prithvi FamilyShield — family floater plan
- **Chunk:** Prithvi FamilyShield is a family floater health insurance plan where one sum insured is shared by the whole family. It covers you, your spouse, up to 3 dependent children aged 91 days to 25 years, and dependent parents or parents-in-law up to entry age 65. A maximum of 6 members can be covered in on…
- **Source:** [kb_in_product_009] Prithvi FamilyShield — family floater plan — familyshield.html
- **Relevance:** Matches the expected record. Lexical overlap: family, floater, parents; dense similarity 0.847; doc type product_info; category product_overview

### q04 — Do I need a medical test if I am 50 years old?

- **Status:** ok · **Verdict:** correct · latency 9.5 ms
- **Retrieved:** `kb_in_faq_004` — Do I need a medical test to buy a policy?
- **Chunk:** Medical tests are required if you are aged 46 or above, choose a sum insured of ₹25 lakh or more, or declare a pre-existing condition. Otherwise the policy is issued on the basis of your declaration.
- **Source:** [kb_in_faq_004] Do I need a medical test to buy a policy? — faq.html › Do I need a medical test to buy a policy?
- **Relevance:** Matches the expected record. Lexical overlap: medical, need, test; dense similarity 0.913; doc type faq; category eligibility

### q05 — Can I pay the premium every month instead of yearly?

- **Status:** ok · **Verdict:** correct · latency 8.6 ms
- **Retrieved:** `kb_in_faq_002` — Can I pay my premium monthly?
- **Chunk:** Yes. Premium can be paid annually, half-yearly, quarterly or monthly. Monthly and quarterly modes carry a 2% loading on the annual premium.
- **Source:** [kb_in_faq_002] Can I pay my premium monthly? — faq.html › Can I pay my premium monthly?
- **Relevance:** Matches the expected record. Lexical overlap: pay, premium, yearly; dense similarity 0.928; doc type faq; category premium_and_payment

### q06 — If I don't like the policy can I cancel and get my money back?

- **Status:** ok · **Verdict:** correct · latency 9.6 ms
- **Retrieved:** `kb_in_faq_008` — What is the free look period?
- **Chunk:** You get 30 days from receipt of the policy document to review it. If you cancel within this period, the premium is refunded after deducting stamp duty and medical test costs.
- **Source:** [kb_in_faq_008] What is the free look period? — faq.html › What is the free look period?
- **Relevance:** Matches the expected record. Lexical overlap: cancel, get, policy; dense similarity 0.856; doc type faq; category renewal_portability

### q07 — The customer says health insurance is too expensive for them

- **Status:** ok · **Verdict:** correct · latency 8.8 ms
- **Retrieved:** `kb_in_objection_007` — Objection Handling Playbook — Prithvi Health (internal, approved responses) › Objection: "It's too expensive"
- **Chunk:** Acknowledge the concern. Offer a lower sum insured option or a shorter-term plan, mention that premium can be paid monthly or quarterly (2% loading), and that premiums qualify for Section 80D tax deduction as per prevailing tax laws. One hospitalisation can cost far more than several years of premiu…
- **Source:** [kb_in_objection_007] Objection Handling Playbook — Prithvi Health (internal, approved responses) › Objection: "It's too expensive" — objection_playbook.md › Objection: "It's too expensive"
- **Relevance:** Matches the expected record. Lexical overlap: expensive, health; dense similarity 0.864; doc type objection; category objection_handling

### q08 — I already get health cover from my employer, why buy another policy?

- **Status:** ok · **Verdict:** correct · latency 9.3 ms
- **Retrieved:** `kb_in_objection_001` — Objection Handling Playbook — Prithvi Health (internal, approved responses) › Objection: "I already have insurance from my employer"
- **Chunk:** Group cover usually ends when you leave or change jobs, and the sum insured is often low (₹3 lakh is common). A personal policy keeps continuity, so waiting periods are completed while you are still covered by your employer. You can keep both and claim from either.
- **Source:** [kb_in_objection_001] Objection Handling Playbook — Prithvi Health (internal, approved responses) › Objection: "I already have insurance from my employer" — objection_playbook.md › Objection: "I already have insurance from my employer"
- **Relevance:** Matches the expected record. Lexical overlap: already, cover, employer, health, policy; dense similarity 0.877; doc type objection; category objection_handling

### q09 — How do I get cashless treatment for a planned surgery?

- **Status:** ok · **Verdict:** partially correct · latency 9.0 ms
- **Retrieved:** `kb_in_product_003` — Network hospitals
- **Chunk:** Search 8,500+ network hospitals where cashless treatment is available. A few hospitals in major cities: Hospital: Sanjeevani Multispeciality Hospital | City: Pune | Speciality: Multispeciality Hospital: Arunodaya Heart Institute | City: Mumbai | Speciality: Cardiology Hospital: Lakeview General Hosp…
- **Source:** [kb_in_product_003] Network hospitals — network-hospitals.html
- **Relevance:** Does not match the expected record. Lexical overlap: cashless, surgery, treatment; dense similarity 0.852; doc type product_info; category network_hospitals

### q10 — What is the premium for a 30 year old for 10 lakh cover?

- **Status:** ok · **Verdict:** partially correct · latency 9.0 ms
- **Retrieved:** `kb_in_rates_002` — Indicative annual premium — Prithvi FamilyShield, age band 26-35
- **Chunk:** - 2 adults, sum insured ₹5 lakh: ₹9,220 per year - 2 adults, sum insured ₹10 lakh: ₹12,900 per year - 2 adults, sum insured ₹25 lakh: ₹18,430 per year - 2 adults, sum insured ₹50 lakh: ₹23,960 per year - 2 adults + 1 child, sum insured ₹5 lakh: ₹10,660 per year - 2 adults + 1 child, sum insured ₹10 …
- **Source:** [kb_in_rates_002] Indicative annual premium — Prithvi FamilyShield, age band 26-35 — premium_rates_2025.csv › Prithvi FamilyShield 26-35
- **Relevance:** Does not match the expected record. Lexical overlap: 10, 30, lakh, premium, year; dense similarity 0.852; doc type premium_table; category premium_and_payment

### q11 — Is there a co-payment in the senior citizen plan?

- **Status:** ok · **Verdict:** correct · latency 8.6 ms
- **Retrieved:** `kb_in_product_015` — Prithvi Silver — health insurance for senior citizens
- **Chunk:** Prithvi Silver is designed for senior citizens with an entry age of 60 to 75 years. Sum insured options are ₹3 lakh, ₹5 lakh and ₹10 lakh. A co-payment of 20% applies on all claims. A pre-policy medical check-up is mandatory for applicants aged 61 and above, done at our network diagnostic centres; 5…
- **Source:** [kb_in_product_015] Prithvi Silver — health insurance for senior citizens — silver.html
- **Relevance:** Matches the expected record. Lexical overlap: co, payment, senior; dense similarity 0.833; doc type product_info; category eligibility

### q12 — What support do branch partners get?

- **Status:** ok · **Verdict:** correct · latency 9.3 ms
- **Retrieved:** `kb_in_product_005` — Branch partnership benefits › What partners receive
- **Chunk:** Operational, marketing and technology support is provided to branch partners. Operational support includes a dedicated relationship manager and policy issuance support. Marketing support includes co-branded collateral and lead campaigns. Technology support includes a partner portal, instant quote to…
- **Source:** [kb_in_product_005] Branch partnership benefits › What partners receive — partners.html › What partners receive
- **Relevance:** Matches the expected record. Lexical overlap: branch, partners, support; dense similarity 0.896; doc type product_info; category partnership_benefits

### q13 — Is cosmetic surgery covered?

- **Status:** ok · **Verdict:** correct · latency 8.5 ms
- **Retrieved:** `kb_in_policy_004` — Prithvi Secure and Prithvi FamilyShield — Policy Wording (effective 2025-04-01) › Exclusions
- **Chunk:** The company is not liable for: cosmetic or aesthetic treatment; treatment of obesity unless medically necessary as per policy criteria; infertility treatment; self-inflicted injury; injuries from hazardous or adventure sports; war and nuclear perils; treatment outside India; out-patient consultation…
- **Source:** [kb_in_policy_004] Prithvi Secure and Prithvi FamilyShield — Policy Wording (effective 2025-04-01) › Exclusions — policy_wording_2025.pdf p.1 › Exclusions
- **Relevance:** Matches the expected record. Lexical overlap: cosmetic; dense similarity 0.806; doc type policy_rule; category exclusions

### q14 — What is the capital of France?

- **Status:** no_match · **Verdict:** correct · latency 8.0 ms
- **Relevance:** Out-of-scope query rejected by the no-match gate

### q15 — Can you book me a flight to Goa next week?

- **Status:** no_match · **Verdict:** correct · latency 8.8 ms
- **Relevance:** Out-of-scope query rejected by the no-match gate

### q16 — What's the best mutual fund to invest in right now?

- **Status:** no_match · **Verdict:** correct · latency 9.3 ms
- **Relevance:** Out-of-scope query rejected by the no-match gate

### q17 — Ilang araw ang grace period bago ma-lapse yung policy ko?

- **Status:** ok · **Verdict:** correct · latency 9.0 ms
- **Retrieved:** `kb_ph_objection_006` — Premium Reminder Call Playbook — Bayanihan Life (internal, Taglish) › Objection: "Wala pa po akong pera ngayon"
- **Chunk:** Intindihin muna. Ipaalala na may grace period na 31 days mula sa due date at tuloy-tuloy pa rin ang coverage habang nasa grace period. Puwedeng i-suggest ang paglipat sa monthly auto-debit sa susunod na policy anniversary para mas magaan ang hulog. Kung hindi pa rin kaya, mag-offer ng callback sa ar…
- **Source:** [kb_ph_objection_006] Premium Reminder Call Playbook — Bayanihan Life (internal, Taglish) › Objection: "Wala pa po akong pera ngayon" — objection_playbook_ph.md › Objection: "Wala pa po akong pera ngayon"
- **Relevance:** Matches the expected record. Lexical overlap: araw, grace, period, policy; dense similarity 0.882; doc type objection; category objection_handling

### q18 — Pwede ko pa bang ibalik yung na-lapse kong policy?

- **Status:** ok · **Verdict:** correct · latency 10.2 ms
- **Retrieved:** `kb_ph_policy_003` — Policy Servicing Guide for Bancassurance Clients (2025) › Lapse and reinstatement
- **Chunk:** A policy lapses if the premium remains unpaid after the 31-day grace period. Reinstatement is allowed within 3 years from lapse, subject to evidence of insurability and payment of overdue premiums with 6% annual interest.
- **Source:** [kb_ph_policy_003] Policy Servicing Guide for Bancassurance Clients (2025) › Lapse and reinstatement — policy_servicing_guide_2025.pdf p.1 › Lapse and reinstatement
- **Relevance:** Matches the expected record. Lexical overlap: lapse, policy, reinstatement; dense similarity 0.823; doc type policy_rule; category lapse_reinstatement

### q19 — Wala pa po akong pera pambayad ng premium ngayon

- **Status:** ok · **Verdict:** correct · latency 8.5 ms
- **Retrieved:** `kb_ph_objection_006` — Premium Reminder Call Playbook — Bayanihan Life (internal, Taglish) › Objection: "Wala pa po akong pera ngayon"
- **Chunk:** Intindihin muna. Ipaalala na may grace period na 31 days mula sa due date at tuloy-tuloy pa rin ang coverage habang nasa grace period. Puwedeng i-suggest ang paglipat sa monthly auto-debit sa susunod na policy anniversary para mas magaan ang hulog. Kung hindi pa rin kaya, mag-offer ng callback sa ar…
- **Source:** [kb_ph_objection_006] Premium Reminder Call Playbook — Bayanihan Life (internal, Taglish) › Objection: "Wala pa po akong pera ngayon" — objection_playbook_ph.md › Objection: "Wala pa po akong pera ngayon"
- **Relevance:** Matches the expected record. Lexical overlap: akong, pera, premium; dense similarity 0.871; doc type objection; category objection_handling

### q20 — Saan po ako pwedeng magbayad, pwede ba sa GCash?

- **Status:** ok · **Verdict:** correct · latency 9.1 ms
- **Retrieved:** `kb_ph_faq_006` — Where can I pay?
- **Chunk:** Auto-debit arrangement from your Kalayaan Savings Bank account, over-the-counter at any Kalayaan branch, Kalayaan online banking, GCash, Maya, and Bayad Center outlets. Payments through GCash and Maya are posted within 1 banking day.
- **Source:** [kb_ph_faq_006] Where can I pay? — premium-payments.html › Where can I pay?
- **Relevance:** Matches the expected record. Lexical overlap: gcash; dense similarity 0.849; doc type faq; category premium_and_payment

### q21 — Kalau telat bayar cicilan kena denda berapa?

- **Status:** ok · **Verdict:** correct · latency 8.9 ms
- **Retrieved:** `kb_id_objection_001` — Playbook Panggilan Pengingat Angsuran — Maju Bersama Finance (internal) › Keberatan: "Belum gajian, Mbak/Mas"
- **Chunk:** Tanyakan tanggal gajian. Jelaskan bahwa denda 0,2% per hari dihitung sejak hari setelah jatuh tempo, jadi membayar sedekat mungkin dengan jatuh tempo akan mengurangi denda. Tawarkan pengingat ulang di tanggal gajian.
- **Source:** [kb_id_objection_001] Playbook Panggilan Pengingat Angsuran — Maju Bersama Finance (internal) › Keberatan: "Belum gajian, Mbak/Mas" — objection_playbook_id.md › Keberatan: "Belum gajian, Mbak/Mas"
- **Relevance:** Matches the expected record. Lexical overlap: angsur, bayar, denda; dense similarity 0.849; doc type objection; category objection_handling

### q22 — Saya baru kena PHK, apa ada keringanan angsuran?

- **Status:** ok · **Verdict:** correct · latency 9.1 ms
- **Retrieved:** `kb_id_objection_003` — Playbook Panggilan Pengingat Angsuran — Maju Bersama Finance (internal) › Keberatan: "Lagi susah, usaha lagi sepi" / "Saya baru kena PHK"
- **Chunk:** Tunjukkan empati. Sampaikan bahwa ada program restrukturisasi untuk konsumen yang penghasilannya menurun, dan tawarkan agar tim restrukturisasi menghubungi kembali. Jangan menjanjikan persetujuan.
- **Source:** [kb_id_objection_003] Playbook Panggilan Pengingat Angsuran — Maju Bersama Finance (internal) › Keberatan: "Lagi susah, usaha lagi sepi" / "Saya baru kena PHK" — objection_playbook_id.md › Keberatan: "Lagi susah, usaha lagi sepi" / "Saya baru kena PHK"
- **Relevance:** Matches the expected record. Lexical overlap: angsur, baru, phk; dense similarity 0.857; doc type objection; category objection_handling

### q23 — Bisa bayar angsuran lewat Indomaret nggak?

- **Status:** ok · **Verdict:** correct · latency 9.5 ms
- **Retrieved:** `kb_id_faq_005` — Di mana saya bisa membayar angsuran?
- **Chunk:** Melalui virtual account BCA, BRI, Mandiri, dan BNI; gerai Indomaret, Alfamart, dan Kantor Pos; aplikasi MajuKu; serta dompet digital GoPay, OVO, DANA, dan ShopeePay. Pembayaran terkonfirmasi otomatis paling lambat 1x24 jam.
- **Source:** [kb_id_faq_005] Di mana saya bisa membayar angsuran? — pembayaran.html › Di mana saya bisa membayar angsuran?
- **Relevance:** Matches the expected record. Lexical overlap: angsur, bayar, indomaret; dense similarity 0.866; doc type faq; category premium_and_payment

### q24 — Bolehkah petugas menagih jam 10 malam?

- **Status:** ok · **Verdict:** incorrect · latency 8.2 ms
- **Retrieved:** `kb_id_compliance_002` — Ringkasan Etika Penagihan (internal) › Larangan
- **Chunk:** Petugas dilarang menggunakan ancaman, kekerasan, atau tindakan yang mempermalukan konsumen; dilarang menekan secara fisik maupun verbal; dilarang menagih kepada pihak selain konsumen; dan dilarang menghubungi secara terus-menerus sehingga mengganggu.
- **Source:** [kb_id_compliance_002] Ringkasan Etika Penagihan (internal) › Larangan — etika_penagihan.md › Larangan
- **Relevance:** Does not match the expected record. Lexical overlap: agih, tugas; dense similarity 0.800; doc type compliance; category compliance_disclosure

### q25 — Berapa harga tiket pesawat ke Bali bulan depan?

- **Status:** no_match · **Verdict:** correct · latency 9.0 ms
- **Relevance:** Out-of-scope query rejected by the no-match gate

### h01 — My father has sugar, how long before it gets covered?

- **Status:** ok · **Verdict:** correct · latency 11.0 ms
- **Retrieved:** `kb_in_policy_008` — Prithvi Secure and Prithvi FamilyShield — Policy Wording (effective 2025-04-01) › Waiting Periods
- **Chunk:** Waiting period: Initial waiting period | Duration: 30 days | Notes: Accidents covered from day one Waiting period: Specific illnesses and procedures | Duration: 24 months | Notes: Cataract, hernia, joint replacement, kidney stones, sinusitis Waiting period: Pre-existing condition | Duration: 24 mont…
- **Source:** [kb_in_policy_008] Prithvi Secure and Prithvi FamilyShield — Policy Wording (effective 2025-04-01) › Waiting Periods — policy_wording_2025.pdf p.1 › Waiting Periods
- **Relevance:** Matches the expected record. Lexical overlap: condition, covered, existing, period, pre, waiting; dense similarity 0.880; doc type policy_rule; category waiting_periods

### h02 — Kya claim ke liye OTP dena padega?

- **Status:** no_match · **Verdict:** incorrect · latency 9.6 ms
- **Relevance:** Rejected by the no-match gate (false negative). Does not match the expected record. Lexical overlap: claim, otp; dense similarity 0.817; doc type objection; category objection_handling

### h03 — Do you sell motorcycle insurance?

- **Status:** no_match · **Verdict:** correct · latency 9.5 ms
- **Relevance:** Out-of-scope query rejected by the no-match gate

### h04 — Paano magpalit ng beneficiary sa policy ko?

- **Status:** ok · **Verdict:** partially correct · latency 9.2 ms
- **Retrieved:** `kb_ph_objection_002` — Premium Reminder Call Playbook — Bayanihan Life (internal, Taglish) › Objection: "Hindi ko na po kailangan yung insurance"
- **Chunk:** Ipaalala na kapag nag-lapse ang policy, titigil ang life coverage pati ang mga riders, at mahirap nang kumuha ng bagong coverage habang tumatanda. Itanong kung sino ang beneficiary at kung ano ang maiiwan sa pamilya kung wala ang coverage. Huwag pilitin.
- **Source:** [kb_ph_objection_002] Premium Reminder Call Playbook — Bayanihan Life (internal, Taglish) › Objection: "Hindi ko na po kailangan yung insurance" — objection_playbook_ph.md › Objection: "Hindi ko na po kailangan yung insurance"
- **Relevance:** Does not match the expected record. Lexical overlap: beneficiary, policy; dense similarity 0.856; doc type objection; category objection_handling
