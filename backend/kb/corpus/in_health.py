"""Prithvi Health Insurance (fictional) — India health-insurance corpus for Q1/Q2.

Deliberate data-quality problems (the pipeline must handle them):
- site chrome on every page (cookie banner, header, nav, aside, footer)
- website FAQ is stale: PED waiting "3 years" vs policy wording 2025 "24 months" (active conflict)
- brochure 2024 (36 months, superseded) vs brochure 2025 (24 months)
- brochure 2025 + blog duplicate website paragraphs (exact / near-duplicate)
- inconsistent terms: PED / pre-existing illness / existing conditions; SI / cover amount / sum assured
- mixed date formats and one invalid date (31/02/2025)
- rate table: one missing premium, one 10x outlier
- testimonials with customer PII; a filled proposal form (customer record); image-only scanned PDF
- a JS-only page and a dead link
"""

from __future__ import annotations

import csv
from pathlib import Path

from . import render

BRAND = {
    "name": "Prithvi Health Insurance",
    "tagline": "Health cover for every Indian family",
    "home": "/in_health/site/index.html",
    "helpline": "Toll-free 1800-000-1234 (8 AM - 10 PM)",
    "cookie": "We use cookies to personalise content and analyse traffic.",
    "footer": "© 2025 Prithvi Health Insurance Co. Ltd. IRDAI Reg. No. 999 (fictional). "
              "Insurance is the subject matter of solicitation. For more details on risk factors, terms and "
              "conditions, please read the sales brochure carefully before concluding a sale.",
    "nav": [
        ("Home", "/in_health/site/index.html"),
        ("Prithvi Secure", "/in_health/site/products/secure.html"),
        ("FamilyShield", "/in_health/site/products/familyshield.html"),
        ("Silver (Senior Citizen)", "/in_health/site/products/silver.html"),
        ("Claims", "/in_health/site/claims.html"),
        ("FAQs", "/in_health/site/faq.html"),
        ("Network Hospitals", "/in_health/site/network-hospitals.html"),
        ("Partner with us", "/in_health/site/partners.html"),
        ("Compare plans", "/in_health/site/compare.html"),
        ("Blog", "/in_health/site/blog/young-and-healthy.html"),
        ("Testimonials", "/in_health/site/testimonials.html"),
        ("Contact", "/in_health/site/contact.html"),
    ],
}

COMMON_BENEFITS = """
<h2>Key benefits</h2>
<ul>
<li>Cashless hospitalisation at 8,500+ network hospitals across India.</li>
<li>Pre-hospitalisation expenses covered for 60 days and post-hospitalisation expenses for 90 days.</li>
<li>All day-care procedures covered; AYUSH treatment covered up to the sum insured.</li>
<li>Road ambulance cover up to ₹2,000 per hospitalisation.</li>
<li>No-claim bonus: 10% increase in sum insured for every claim-free year, up to 100%.</li>
<li>Restore benefit: 100% of the sum insured is restored once a policy year if exhausted.</li>
<li>Free annual health check-up from the second policy year.</li>
</ul>
"""

PAGES: dict[str, tuple[str, str]] = {
    "index.html": ("Health insurance plans for individuals, families and seniors", """
<p>Prithvi Health Insurance offers three plans: <a href="/in_health/site/products/secure.html">Prithvi Secure</a> for individuals,
<a href="/in_health/site/products/familyshield.html">Prithvi FamilyShield</a> for families and
<a href="/in_health/site/products/silver.html">Prithvi Silver</a> for senior citizens aged 60 to 75.</p>
<h2>Why choose Prithvi</h2>
<p>We settle claims fast. Our company-reported claim settlement ratio for FY 2024-25 is 96.2%. Cashless approval for
planned hospitalisation is usually given within 2 hours of receiving complete documents.</p>
<p>Lifelong renewability on all plans. Tax benefit on premiums under Section 80D of the Income Tax Act, as per prevailing tax laws.</p>
<p>Read our <a href="/in_health/site/faq.html">FAQs</a>, learn how <a href="/in_health/site/claims.html">claims</a> work, or
<a href="/in_health/site/partners.html">become a branch partner</a>. See also <a href="/in_health/site/offers-2023.html">festive offers 2023</a>.</p>
"""),
    "products/secure.html": ("Prithvi Secure — individual health insurance", """
<p>Prithvi Secure is an individual health insurance plan for adults aged 18 to 65 years at entry.
Sum insured options are ₹3 lakh, ₹5 lakh, ₹10 lakh and ₹25 lakh. Policy term can be 1, 2 or 3 years.</p>
""" + COMMON_BENEFITS + """
<h2>Room rent</h2>
<p>For sum insured of ₹3 lakh and ₹5 lakh, room rent is covered up to 1% of the sum insured per day (single private room).
For sum insured of ₹10 lakh and above there is no room rent capping.</p>
<h2>Co-payment</h2>
<p>No co-payment if you join at age 60 or below. A 10% co-payment applies on every claim if the entry age is between 61 and 65 years.</p>
<h2>Who should buy</h2>
<p>Young professionals and single adults who want their own cover in addition to an employer group policy.</p>
"""),
    "products/familyshield.html": ("Prithvi FamilyShield — family floater plan", """
<p>Prithvi FamilyShield is a family floater health insurance plan where one sum insured is shared by the whole family.
It covers you, your spouse, up to 3 dependent children aged 91 days to 25 years, and dependent parents or parents-in-law up to entry age 65.
A maximum of 6 members can be covered in one policy.</p>
<p>Cover amount options: ₹5 lakh, ₹10 lakh, ₹25 lakh and ₹50 lakh.</p>
""" + COMMON_BENEFITS + """
<h2>Maternity add-on</h2>
<p>Optional maternity cover up to ₹50,000 per delivery, including newborn cover from day one, available after a waiting period of 24 months.</p>
<h2>Parents above 65</h2>
<p>Parents older than 65 cannot be added to FamilyShield. We recommend a separate Prithvi Silver policy for them.</p>
"""),
    "products/silver.html": ("Prithvi Silver — health insurance for senior citizens", """
<p>Prithvi Silver is designed for senior citizens with an entry age of 60 to 75 years. Sum insured options are ₹3 lakh, ₹5 lakh and ₹10 lakh.</p>
<p>A co-payment of 20% applies on all claims. A pre-policy medical check-up is mandatory for applicants aged 61 and above, done at our network
diagnostic centres; 50% of the check-up cost is refunded if the policy is issued.</p>
<p>Existing conditions such as diabetes and hypertension are covered after the pre-existing disease waiting period, subject to declaration at proposal stage.</p>
<p>Cashless hospitalisation at 8,500+ network hospitals across India.</p>
<p>Single private room covered for all sum insured options.</p>
"""),
    "faq.html": ("Frequently asked questions", """
<h3>What is the waiting period for pre-existing illnesses?</h3>
<p>Pre-existing illnesses are covered after a waiting period of 3 years from the first policy start date, provided they were declared in the proposal form.</p>
<h3>Is there an initial waiting period?</h3>
<p>Yes. Claims in the first 30 days are not payable except for accidents.</p>
<h3>Which illnesses have a specific waiting period?</h3>
<p>Cataract, hernia, joint replacement, kidney stones, sinusitis and other listed conditions are covered after 24 months.</p>
<h3>Can I pay my premium monthly?</h3>
<p>Yes. Premium can be paid annually, half-yearly, quarterly or monthly. Monthly and quarterly modes carry a 2% loading on the annual premium.</p>
<h3>Do I need a medical test to buy a policy?</h3>
<p>Medical tests are required if you are aged 46 or above, choose a sum insured of ₹25 lakh or more, or declare a pre-existing condition.
Otherwise the policy is issued on the basis of your declaration.</p>
<h3>What is the free look period?</h3>
<p>You get 30 days from receipt of the policy document to review it. If you cancel within this period, the premium is refunded after deducting stamp duty and medical test costs.</p>
<h3>What is the grace period for renewal?</h3>
<p>Renewal premium can be paid within 30 days after the due date without losing continuity benefits. Claims during the grace period are not payable.</p>
<h3>Can I port my existing policy to Prithvi?</h3>
<p>Yes. You can port your policy at renewal and carry forward waiting period credits for the sum insured you held earlier. Apply at least 15 days before renewal.</p>
<h3>Does the policy cover COVID-19 and other infectious diseases?</h3>
<p>Yes, hospitalisation for infectious diseases is covered like any other illness, subject to waiting periods.</p>
<h3>Can I get tax benefits?</h3>
<p>Premiums paid are eligible for deduction under Section 80D of the Income Tax Act as per prevailing tax laws. Please consult your tax advisor.</p>
<h3>Is OPD or dental treatment covered?</h3>
<p>Out-patient (OPD) consultations and routine dental treatment are not covered. Dental treatment needing hospitalisation due to an accident is covered.</p>
<h3>Will Prithvi ever ask for my OTP or card PIN?</h3>
<p>Never. Our staff and assistants will never ask for OTPs, card PINs, CVV or net-banking passwords. Report such calls to our helpline.</p>
"""),
    "claims.html": ("How to make a claim", """
<h2>Cashless claims</h2>
<p>For planned hospitalisation, intimate us at least 48 hours before admission. For emergency hospitalisation, intimate us within 24 hours of admission.
Show your Prithvi health card at the network hospital's insurance desk; the hospital sends the pre-authorisation request to us.</p>
<h2>Reimbursement claims</h2>
<p>If you are treated at a non-network hospital, pay the bills and submit the claim form with original documents within 30 days of discharge.
Documents: claim form, discharge summary, bills and receipts, investigation reports, prescriptions, KYC and cancelled cheque.</p>
<h2>Claim settlement timelines</h2>
<p>Reimbursement claims are settled or rejected within 30 days of receiving the last necessary document.</p>
<h2>Claims helpline</h2>
<p>Call 1800-000-1234 or email claims@prithvihealth.example.</p>
"""),
    "network-hospitals.html": ("Network hospitals", """
<p>Search 8,500+ network hospitals where cashless treatment is available. A few hospitals in major cities:</p>
<table>
<tr><th>Hospital</th><th>City</th><th>Speciality</th></tr>
<tr><td>Sanjeevani Multispeciality Hospital</td><td>Pune</td><td>Multispeciality</td></tr>
<tr><td>Arunodaya Heart Institute</td><td>Mumbai</td><td>Cardiology</td></tr>
<tr><td>Lakeview General Hospital</td><td>Bengaluru</td><td>Multispeciality</td></tr>
<tr><td>Ganga Care Hospital</td><td>Lucknow</td><td>General surgery</td></tr>
<tr><td>Coromandel Medical Centre</td><td>Chennai</td><td>Orthopaedics</td></tr>
</table>
<p>The network list is updated monthly. Always confirm with the hospital insurance desk before admission.</p>
"""),
    "partners.html": ("Branch partnership benefits", """
<p>Prithvi works with bank branches, NBFC branches and insurance marketing firms as branch partners.</p>
<h2>What partners receive</h2>
<p>Operational, marketing and technology support is provided to branch partners. Operational support includes a dedicated relationship manager
and policy issuance support. Marketing support includes co-branded collateral and lead campaigns. Technology support includes a partner portal,
instant quote tools and a mobile app for policy servicing.</p>
<h2>Commission and training</h2>
<p>Partners earn commission as per IRDAI regulations and receive product and compliance training before selling.</p>
"""),
    "blog/young-and-healthy.html": ("Young and healthy? Here's why you still need health insurance", """
<p class="meta">Posted on 31/02/2025 by Team Prithvi</p>
<p>Medical inflation in India runs in double digits, and a single hospitalisation can wipe out years of savings.</p>
<p>Prithvi Secure is an individual health insurance plan for adults aged 18 to 65 years at entry.
Sum insured options are ₹3 lakh, ₹5 lakh, ₹10 lakh and ₹25 lakh. Policy term can be 1, 2 or 3 years.</p>
<p>Buying early has three advantages: premiums are lowest when you are young, waiting periods get completed while you are healthy,
and you build a no-claim bonus over time.</p>
<p>Your employer's group cover usually ends when you change jobs and the cover amount is often only ₹3 lakh, so a personal policy keeps you protected.</p>
<p>Cashless hospitalisation at 8,500+ network hospitals across India.</p>
"""),
    "testimonials.html": ("What our customers say", """
<blockquote>"My father's bypass surgery was approved cashless within 3 hours. Thank you Prithvi!" — Ramesh Kumar, Pune, +91 98765 43210, ramesh.kumar@example.com</blockquote>
<blockquote>"Claim reimbursed in 12 days with zero follow-up." — Sunita Iyer, Chennai, sunita.iyer@example.net</blockquote>
<blockquote>"The advisor explained waiting periods very clearly before I bought." — Mohammed Arif, Hyderabad, call me on 9123456780</blockquote>
"""),
    "contact.html": ("Contact us", """
<p>Customer care: 1800-000-1234 (toll-free, 8 AM - 10 PM, all days). Email: care@prithvihealth.example.</p>
<p>Grievance Redressal Officer: gro@prithvihealth.example. If you are not satisfied with our response within 14 days, you may approach
the Insurance Ombudsman or register on the Bima Bharosa portal.</p>
<p>Registered office: Prithvi Towers, Bandra Kurla Complex, Mumbai 400051 (fictional address).</p>
"""),
}


def _verhoeff_check_digit(num: str) -> str:
    d = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
         [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
         [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
         [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
    p = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
         [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
         [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
    inv = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = d[c][p[(i + 1) % 8][int(ch)]]
    return str(inv[c])


SECURE_BASE = {"18-25": 5200, "26-35": 6400, "36-45": 8900, "46-55": 13800, "56-60": 19500, "61-65": 26000}
SECURE_SI = {"3 lakh": 0.72, "5 lakh": 1.0, "10 lakh": 1.45, "25 lakh": 2.1}
FAMILY_COMP = {"2 adults": 1.6, "2 adults + 1 child": 1.85, "2 adults + 2 children": 2.05}
FAMILY_SI = {"5 lakh": 1.0, "10 lakh": 1.4, "25 lakh": 2.0, "50 lakh": 2.6}
SILVER_BASE = {"60-65": 28500, "66-70": 36900, "71-75": 47200}
SILVER_SI = {"3 lakh": 0.75, "5 lakh": 1.0, "10 lakh": 1.5}


def _round10(x: float) -> int:
    return int(round(x / 10.0) * 10)


def rate_rows() -> list[list]:
    rows = [["product", "age_band", "members", "sum_insured", "annual_premium_inr", "zone"]]
    for band, base in SECURE_BASE.items():
        for si, m in SECURE_SI.items():
            prem = _round10(base * m)
            if band == "46-55" and si == "10 lakh":
                prem = prem * 10  # injected source error: 10x outlier
            rows.append(["Prithvi Secure", band, "1 adult", si, prem, "A"])
    for band, base in list(SECURE_BASE.items())[:5]:
        for comp, cm in FAMILY_COMP.items():
            for si, m in FAMILY_SI.items():
                prem = _round10(base * cm * m * 0.9)
                cell = "" if (band == "36-45" and comp == "2 adults + 1 child" and si == "10 lakh") else prem
                rows.append(["Prithvi FamilyShield", band, comp, si, cell, "A"])
    for band, base in SILVER_BASE.items():
        for si, m in SILVER_SI.items():
            rows.append(["Prithvi Silver", band, "1 adult", si, _round10(base * m), "A"])
    return rows


def build(root: Path) -> None:
    site = root / "site"
    for rel, (title, body) in PAGES.items():
        render.write(site / rel, render.html_page(brand=BRAND, title=title, body=body))
    render.write(site / "compare.html", render.js_only_page(brand=BRAND, title="Compare plans"))

    docs = root / "docs"
    header = "Prithvi Health Insurance Co. Ltd. | Policy Wording | UIN: PRHHLIP25001V022425 (fictional)"
    footer = "Registered office: Prithvi Towers, BKC, Mumbai | care@prithvihealth.example"
    render.pdf_document(docs / "policy_wording_2025.pdf", header=header, footer=footer,
                        title="Prithvi Secure and Prithvi FamilyShield — Policy Wording (effective 1st April 2025)", sections=[
        ("1. Preamble", [
            "This policy is a contract between the policyholder and Prithvi Health Insurance Co. Ltd. Cover is subject to the terms, "
            "conditions, waiting periods and exclusions in this policy wording. This version is effective from 1st April 2025 and "
            "replaces the wording effective 1st April 2024.",
        ]),
        ("2. Definitions", [
            "Pre-existing Disease (PED) means any condition, ailment, injury or disease that was diagnosed by a physician, or for which "
            "medical advice or treatment was recommended or received, within 36 months prior to the date of commencement of the first policy.",
            "Sum Insured means the maximum amount the company will pay in a policy year for all claims under the policy, including any "
            "no-claim bonus and restored amount.",
            "Co-payment means the percentage of each admissible claim borne by the insured person.",
            "Cashless facility means payment of treatment costs directly by the company to a network hospital as per the pre-authorisation approved.",
            "Grace period means 30 days after the premium due date during which renewal is allowed without loss of continuity benefits; "
            "coverage is not available during the grace period.",
        ]),
        ("3. Coverage", [
            "In-patient hospitalisation for a minimum of 24 hours, including room rent, ICU, doctor fees, medicines and diagnostics.",
            "Pre-hospitalisation medical expenses for 60 days before admission and post-hospitalisation expenses for 90 days after discharge.",
            "Day-care procedures, AYUSH in-patient treatment up to the sum insured, and road ambulance up to ₹2,000 per hospitalisation.",
            "Restore benefit of 100% of the sum insured once in a policy year; no-claim bonus of 10% per claim-free year up to 100%.",
        ]),
        ("4. Waiting Periods", [
            ("table", [["Waiting period", "Duration", "Notes"],
                       ["Initial waiting period", "30 days", "Accidents covered from day one"],
                       ["Specific illnesses and procedures", "24 months", "Cataract, hernia, joint replacement, kidney stones, sinusitis"],
                       ["Pre-existing diseases", "24 months", "Reduced from 36 months with effect from 1st April 2025"],
                       ["Maternity (add-on)", "24 months", "FamilyShield only"]]),
            "Pre-existing diseases declared in the proposal and accepted by the company are covered after 24 months of continuous coverage "
            "since the first policy. Waiting periods are reduced to the extent of prior continuous coverage when a policy is ported.",
        ]),
        ("5. Exclusions", [
            "The company is not liable for: cosmetic or aesthetic treatment; treatment of obesity unless medically necessary as per policy criteria; "
            "infertility treatment; self-inflicted injury; injuries from hazardous or adventure sports; war and nuclear perils; "
            "treatment outside India; out-patient consultations and routine dental care; experimental treatments.",
        ]),
        ("6. Claims Procedure", [
            "Cashless: intimation at least 48 hours before a planned admission and within 24 hours of an emergency admission.",
            "Reimbursement: submit the claim form and documents within 30 days of discharge. The company settles or rejects a claim within "
            "30 days of receipt of the last necessary document; delay attracts interest at 2% above the bank rate.",
        ]),
        ("7. Renewal, Portability and Free Look", [
            "The policy is renewable lifelong. Renewal premium may be paid within the grace period of 30 days.",
            "The policyholder may port the policy to another insurer or into this policy at renewal. Free look period: 30 days from receipt "
            "of the policy document; premium is refunded after deducting stamp duty and expenses on medical tests.",
        ]),
        ("8. Grievance Redressal", [
            "Contact the Grievance Redressal Officer at gro@prithvihealth.example. If unresolved within 14 days, the policyholder may approach "
            "the Insurance Ombudsman or the Bima Bharosa portal.",
        ]),
    ])

    bh = "Prithvi FamilyShield | Sales Brochure"
    render.pdf_document(docs / "brochure_familyshield_2024.pdf", header=bh + " | 2024", footer="Effective 01/04/2024",
                        title="Prithvi FamilyShield — one cover amount for your whole family", sections=[
        ("Highlights", [
            "One cover amount shared by you, your spouse, up to 3 children and dependent parents.",
            "Cash-less hospitalization at 8,000+ network hospitals.",
            "Pre-existing illnesses covered after a waiting period of 36 months.",
            "Cover amount options: ₹5 lakh, ₹10 lakh and ₹25 lakh.",
        ]),
        ("Important", ["Effective from 01/04/2024. Insurance is the subject matter of solicitation."]),
    ])
    render.pdf_document(docs / "brochure_familyshield_2025.pdf", header=bh + " | 2025", footer="Effective April 1, 2025",
                        title="Prithvi FamilyShield — one cover amount for your whole family", sections=[
        ("Highlights", [
            "Prithvi FamilyShield is a family floater health insurance plan where one sum insured is shared by the whole family. "
            "It covers you, your spouse, up to 3 dependent children aged 91 days to 25 years, and dependent parents or parents-in-law up to entry age 65. "
            "A maximum of 6 members can be covered in one policy.",
            "Cashless hospitalisation at 8,500+ network hospitals across India.",
            "PED covered after only 24 months — reduced from 36 months.",
            "SI options: ₹5 lakh, ₹10 lakh, ₹25 lakh and ₹50 lakh. Maternity add-on available.",
        ]),
        ("Why families choose FamilyShield", [
            "No-claim bonus: 10% increase in sum insured for every claim-free year, up to 100%.",
            "Restore benefit: 100% of the sum insured is restored once a policy year if exhausted.",
            "Free annual health check-up for all insured adults from the second year.",
        ]),
        ("Important", ["Effective from April 1, 2025. Insurance is the subject matter of solicitation."]),
    ])

    render.pdf_document(docs / "proposal_form.pdf", header="Prithvi Health Insurance | Proposal Form PF-01",
                        footer="Form PF-01 v3", title="Proposal Form — Individual and Family Floater", sections=[
        ("Section A: Proposer details", [
            "Proposer's Full Name: ____________", "D.O.B. (DD/MM/YYYY): ____________", "Gender: M / F / Other",
            "PAN No.: ____________", "Aadhaar No. (optional): ____________", "Mobile No.: ____________",
            "E-mail ID: ____________", "Residential Address with PIN: ____________", "Occupation: ____________",
        ]),
        ("Section B: Members to be insured", [
            ("table", [["Member", "Relationship", "D.O.B.", "Height (cm)", "Weight (kg)"], ["1", "", "", "", ""], ["2", "", "", "", ""]]),
        ]),
        ("Section C: Medical history", [
            "Has any member been diagnosed with diabetes, hypertension, heart disease, cancer, kidney disease or any other illness? (Y/N)",
            "Is any member currently under treatment or awaiting surgery? (Y/N)",
            "Nominee Name and Relationship: ____________",
        ]),
        ("Declaration", ["I declare that the information given is true and complete. Non-disclosure of material facts may lead to rejection of claims."]),
    ])
    aadhaar = "23456789012"
    aadhaar += _verhoeff_check_digit(aadhaar)
    render.pdf_document(docs / "proposal_form_filled_sample.pdf", header="Prithvi Health Insurance | Proposal Form PF-01",
                        footer="Form PF-01 v3", title="Proposal Form — Individual and Family Floater", sections=[
        ("Section A: Proposer details", [
            "Proposer's Full Name: Anil Verma", "D.O.B. (DD/MM/YYYY): 12/08/1988", "Gender: M",
            "PAN No.: ABCPV1234F", f"Aadhaar No. (optional): {aadhaar[:4]} {aadhaar[4:8]} {aadhaar[8:]}",
            "Mobile No.: +91 98200 12345", "E-mail ID: anil.verma@example.com",
            "Residential Address with PIN: 14 Lotus Residency, Kothrud, Pune 411038", "Occupation: Software engineer",
        ]),
        ("Section C: Medical history", ["Diabetes: Y (since 2021, on metformin)", "Nominee Name and Relationship: Priya Verma, spouse"]),
    ])
    render.image_only_pdf(docs / "scanned_endorsement.pdf", [
        "ENDORSEMENT No. E-2025-0042", "Change of nominee effective 15/05/2025", "Policy: PRH-FS-0009921",
        "Authorised signatory", "(scanned copy)",
    ])

    tables = root / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    with open(tables / "premium_rates_2025.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rate_rows())
    render.xlsx(tables / "eligibility_rules.xlsx", {
        "Eligibility": [
            ["rule_id", "product", "parameter", "condition", "outcome", "notes"],
            ["E01", "All", "proposer_age", "18 years or above", "eligible", "Minors cannot be proposers"],
            ["E02", "Prithvi Secure / FamilyShield", "entry_age", "maximum 65 years", "eligible", "Above 65: offer Prithvi Silver"],
            ["E03", "Prithvi Silver", "entry_age", "60 to 75 years", "eligible", "Above 75: not eligible"],
            ["E04", "Prithvi FamilyShield", "children", "91 days to 25 years, maximum 3 children", "eligible", ""],
            ["E05", "Prithvi FamilyShield", "parents_age", "maximum entry age 65", "eligible", "Older parents: separate Prithvi Silver policy"],
            ["E06", "All", "residency", "resident of India", "eligible", "Non-residents: not eligible"],
            ["E07", "All", "pre_existing_condition", "declared", "eligible subject to underwriting", "Covered after 24-month PED waiting period"],
            ["E08", "All", "active_serious_treatment", "under active cancer treatment, on dialysis, or awaiting organ transplant",
             "refer to underwriter", "No instant quote; escalate to human advisor"],
            ["E09", "All", "medical_tests", "age 46+ or sum insured ₹25 lakh+ or PED declared", "tests required", "Tele-medical or diagnostic centre"],
            ["E10", "Prithvi Secure", "co_payment", "entry age 61-65", "10% co-payment", ""],
            ["E11", "All", "recommended_sum_insured", "Zone A city: minimum ₹10 lakh; other cities: minimum ₹5 lakh", "advice", ""],
        ],
        "Zones": [
            ["zone", "cities", "premium_factor"],
            ["A", "Mumbai, Delhi NCR, Bengaluru, Chennai, Hyderabad, Kolkata, Pune, Ahmedabad", "1.00"],
            ["B", "Jaipur, Lucknow, Chandigarh, Indore, Kochi, Coimbatore, Nagpur, Surat, Bhopal, Visakhapatnam", "0.90"],
            ["C", "All other cities and towns", "0.80"],
        ],
        "Lead grading": [
            ["grade", "definition"],
            ["hot", "Eligible, indicative premium within budget (up to 15% above), wants a callback or to buy within 7 days"],
            ["warm", "Eligible but budget gap, or decision expected within 30 days, or needs family discussion"],
            ["cold", "No current need, only browsing, or decision beyond 30 days"],
            ["not_eligible", "Fails an eligibility rule (age, residency) or needs underwriter referral"],
        ],
    })

    internal = root / "internal"
    render.write(internal / "objection_playbook.md", OBJECTIONS)


OBJECTIONS = """# Objection Handling Playbook — Prithvi Health (internal, approved responses)

Version 2.1 — approved by Compliance on 2025-03-20. Use only these responses. Never promise that every claim will be paid,
never disparage competitors, never ask for OTP / card / bank details.

## Objection: "It's too expensive"
Acknowledge the concern. Offer a lower sum insured option or a shorter-term plan, mention that premium can be paid monthly or quarterly
(2% loading), and that premiums qualify for Section 80D tax deduction as per prevailing tax laws. One hospitalisation can cost far more than
several years of premium.

## Objection: "I already have insurance from my employer"
Group cover usually ends when you leave or change jobs, and the cover amount is often low (₹3 lakh is common). A personal policy keeps
continuity, so waiting periods are completed while you are still covered by your employer. You can keep both and claim from either.

## Objection: "I'm young and healthy, I don't need it now"
Premiums are lowest when you are young, waiting periods are completed while you are healthy, and the no-claim bonus grows every claim-free year.
Accidents and sudden illnesses do not depend on age.

## Objection: "Insurance companies reject claims"
Our company-reported claim settlement ratio for FY 2024-25 is 96.2%. Exclusions and waiting periods are explained clearly before purchase,
cashless approval is usually within 2 hours, and if a customer disagrees with a decision they can approach the Grievance Redressal Officer and
the Insurance Ombudsman. Do not say claims are guaranteed.

## Objection: "I need to discuss with my family first"
Respect the decision. Offer to share the brochure on WhatsApp or e-mail and schedule a callback at a time when the family is available.

## Objection: "I have a pre-existing condition, you will reject me"
Pre-existing conditions are accepted subject to underwriting and are covered after the 24-month waiting period, provided they are declared
honestly in the proposal form. Non-disclosure can lead to claim rejection, so always declare.

## Objection: "Is this call genuine? Is this a scam?"
Say the customer can verify us on the official website or the toll-free number 1800-000-1234. We never ask for OTPs, card PINs or passwords,
and payment is only made through the official website or payment link from our official domain.

## Objection: "Send me the details, I'll think about it"
Offer to send the brochure and ask for a convenient callback time within the next few days.
"""
