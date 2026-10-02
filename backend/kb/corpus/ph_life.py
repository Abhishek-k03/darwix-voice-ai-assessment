"""Bayanihan Life Assurance (fictional) via Kalayaan Savings Bank — Philippines bancassurance corpus for Q3.

Website in English (typical for PH insurers), call-center playbook in natural Taglish.
"""

from __future__ import annotations

from pathlib import Path

from . import render

BRAND = {
    "name": "Bayanihan Life Assurance",
    "tagline": "Protection for every Filipino family",
    "home": "/ph_life/site/index.html",
    "helpline": "Hotline (02) 8000-5555 | Mon-Sat 8AM-8PM",
    "cookie": "This site uses cookies in accordance with the Data Privacy Act of 2012.",
    "footer": "© 2025 Bayanihan Life Assurance Corp. (fictional). Regulated by the Insurance Commission. "
              "Insurance products are not bank deposits, are not insured by PDIC, and are not obligations of Kalayaan Savings Bank.",
    "nav": [
        ("Home", "/ph_life/site/index.html"),
        ("FamilyCare Life", "/ph_life/site/familycare.html"),
        ("Premium payments", "/ph_life/site/premium-payments.html"),
        ("Policy servicing", "/ph_life/site/servicing.html"),
        ("Contact", "/ph_life/site/contact.html"),
    ],
}

PAGES = {
    "index.html": ("Life insurance through Kalayaan Savings Bank", """
<p>Bayanihan Life partners with Kalayaan Savings Bank to bring life insurance to bank clients. When a bank officer gives you a bank referral,
a licensed Bayanihan financial advisor explains the plan to you. Bank staff do not sell insurance.</p>
<p>Insurance products are not bank deposits, are not insured by the Philippine Deposit Insurance Corporation (PDIC), and are not obligations of Kalayaan Savings Bank.</p>
"""),
    "familycare.html": ("Bayanihan FamilyCare Life", """
<p>Bayanihan FamilyCare Life is a 20-year term life plan. Coverage (face amount) options range from ₱500,000 to ₱5,000,000.
If the insured passes away during the coverage period, the face amount is paid to the beneficiary.</p>
<h2>Optional riders</h2>
<ul>
<li>Accidental Death Benefit (ADB) rider: pays an additional amount equal to the face amount if death is due to an accident.</li>
<li>Critical Illness (CI) rider: pays 50% of the rider amount upon diagnosis of any of 36 covered critical illnesses.</li>
<li>Waiver of Premium on Disability (WPD) rider: future premiums are waived if the insured becomes totally and permanently disabled.</li>
</ul>
<p>Riders lapse together with the base policy if premiums are not paid.</p>
<h2>Premium modes</h2>
<p>Annual, semi-annual, quarterly or monthly. Monthly mode is available only through auto-debit from a Kalayaan Savings Bank account.</p>
<p>Sample premium: a 35-year-old non-smoker with ₱1,000,000 coverage pays about ₱1,850 per month (indicative only).</p>
"""),
    "premium-payments.html": ("Premium payments, grace period and lapse", """
<h3>When is my premium due?</h3>
<p>Your premium due date is shown in your policy data page and in the reminder we send by SMS and e-mail 15 days before the due date.</p>
<h3>What is the grace period?</h3>
<p>You have a grace period of 31 days from the due date to pay your premium. Your coverage stays in force during the grace period.</p>
<h3>What happens if I don't pay within the grace period?</h3>
<p>The policy lapses at the end of the grace period. Life coverage and all riders stop, and claims for events after the lapse date are not payable.</p>
<h3>Can I reinstate a lapsed policy?</h3>
<p>Yes, within 3 years from the lapse date. Submit a reinstatement application and an updated health declaration, and pay all overdue premiums
with interest at 6% per year. A medical exam may be required if the policy has been lapsed for more than 6 months.</p>
<h3>Where can I pay?</h3>
<p>Auto-debit arrangement (ADA) from your Kalayaan Savings Bank account, over-the-counter at any Kalayaan branch, Kalayaan online banking,
GCash, Maya, and Bayad Center outlets. Payments through GCash and Maya are posted within 1 banking day.</p>
<h3>Can I change my payment mode?</h3>
<p>Yes, on your policy anniversary. Switching to monthly auto-debit can make payments lighter on your budget.</p>
"""),
    "servicing.html": ("Policy servicing", """
<h3>How do I change my beneficiary?</h3>
<p>If your beneficiary is revocable, submit a Change of Beneficiary form with a valid ID. If the beneficiary is irrevocable, their written consent is required.</p>
<h3>How do I update my contact details?</h3>
<p>Through the Bayanihan app, at any Kalayaan branch, or by calling our hotline. Keep your mobile number updated to receive premium reminders.</p>
<h3>What is the free look period?</h3>
<p>You have 15 days from receipt of the policy to cancel and get a refund of premiums paid, less medical exam costs.</p>
<h3>What is the contestability period?</h3>
<p>Within 2 years from issue or reinstatement, the company may contest the policy for concealment or misrepresentation.</p>
"""),
    "contact.html": ("Contact us", """
<p>Hotline: (02) 8000-5555, Monday to Saturday, 8 AM to 8 PM. E-mail: care@bayanihanlife.example.</p>
<p>For complaints you may also contact the Insurance Commission's Public Assistance and Mediation Division.</p>
"""),
}

OBJECTIONS = """# Premium Reminder Call Playbook — Bayanihan Life (internal, Taglish)

Bersyon 1.3 — inaprubahan ng Compliance noong 2025-02-10. Laging gumamit ng "po" at "opo". Huwag manakot, huwag mangako ng hindi totoo,
at huwag humingi ng OTP o card PIN.

## Objection: "Wala pa po akong pera ngayon"
Intindihin muna. Ipaalala na may grace period na 31 days mula sa due date at tuloy-tuloy pa rin ang coverage habang nasa grace period.
Puwedeng i-suggest ang paglipat sa monthly auto-debit sa susunod na policy anniversary para mas magaan ang hulog.
Kung hindi pa rin kaya, mag-offer ng callback sa araw ng sweldo.

## Objection: "Hindi ko na po kailangan yung insurance"
Ipaalala na kapag nag-lapse ang policy, titigil ang life coverage pati ang mga riders, at mahirap nang kumuha ng bagong coverage habang tumatanda.
Itanong kung sino ang beneficiary at kung ano ang maiiwan sa pamilya kung wala ang coverage. Huwag pilitin.

## Objection: "Kakausapin ko muna po ang asawa ko"
Igalang ang desisyon. Mag-offer na i-send ang summary sa SMS o e-mail at mag-schedule ng callback kapag available silang dalawa.

## Objection: "Mas mabuti pa pong mag-ipon na lang sa bangko"
Ipaliwanag nang mahinahon na magkaiba ang savings at insurance: ang insurance ay agad na nagbibigay ng proteksyon na katumbas ng face amount
sa beneficiary, habang ang savings ay unti-unting naiipon. Ang Kalayaan bank account ay puwede pa ring gamitin para sa auto-debit.

## Objection: "Scam po ba ito?"
Sabihin na puwede nilang i-verify sa official hotline (02) 8000-5555 o sa kanilang Kalayaan branch. Hindi kami humihingi ng OTP, card PIN o password,
at ang bayad ay sa official channels lang: auto-debit, Kalayaan branch, online banking, GCash, Maya o Bayad Center.

## Objection: "Bakit bangko ang nag-refer sa akin?"
Ipaliwanag ang bank referral: ang bank officer ay nagre-refer lang, at ang licensed Bayanihan financial advisor ang nagpapaliwanag at nagbebenta.
Ang insurance ay hindi bank deposit at hindi insured ng PDIC.
"""


def build(root: Path) -> None:
    for rel, (title, body) in PAGES.items():
        render.write(root / "site" / rel, render.html_page(brand=BRAND, title=title, body=body))
    render.pdf_document(root / "docs" / "policy_servicing_guide_2025.pdf",
                        header="Bayanihan Life Assurance | Policy Servicing Guide", footer="Guide BL-SG-2025",
                        title="Policy Servicing Guide for Bancassurance Clients (2025)", sections=[
        ("Bancassurance disclosure", [
            "This is an insurance product of Bayanihan Life Assurance Corp. It is not a bank deposit, it is not insured by PDIC, "
            "and Kalayaan Savings Bank is not liable for policy obligations. Bank personnel may only give a bank referral; "
            "only licensed financial advisors may explain and sell the product.",
        ]),
        ("Premium reminders", [
            "Clients receive SMS and e-mail reminders 15 days and 3 days before the due date, and on day 15 of the grace period.",
            "Reminder calls may be made Monday to Saturday between 8:00 AM and 8:00 PM. Advisors must identify themselves and the company at the start of the call.",
        ]),
        ("Lapse and reinstatement", [
            "A policy lapses if the premium remains unpaid after the 31-day grace period. Reinstatement is allowed within 3 years from lapse, "
            "subject to evidence of insurability and payment of overdue premiums with 6% annual interest.",
        ]),
        ("Data privacy", [
            "Client information is processed under the Data Privacy Act of 2012. Advisors must verify identity using the policy number and "
            "date of birth before discussing policy details, and must never ask for OTPs or card PINs.",
        ]),
    ])
    render.write(root / "internal" / "objection_playbook_ph.md", OBJECTIONS)
