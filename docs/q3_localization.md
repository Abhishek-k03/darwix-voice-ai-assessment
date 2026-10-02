# Q3: Native-language voice bots (Philippines, Indonesia)

Both bots run on the Q1 worker. Only the pack changes (`backend/packs/ph_life`, `backend/packs/id_multifinance`):
- persona prompt, native script lines, field schema and reminder rules;
- compliance rules;
- STT/TTS chain, turn-taking lexicon and copilot signals.

Each market has its own KB namespace, built by the Q2 pipeline.

| | Philippines | Indonesia |
|---|---|---|
| Sector / flow | Life bancassurance (Bayanihan Life via Kalayaan Savings Bank): **premium due reminder and lapse prevention** | Multifinance motorbike loan (Maju Bersama Finance): **installment pre-due reminder and payment difficulty** |
| Languages | English, Filipino, Taglish | Formal and colloquial Bahasa Indonesia, English loanwords, Javanese/Sundanese particles |
| Identity check | Date of birth before any account detail (Data Privacy Act 2012) | Holder confirms their name. Never disclose to a spouse or other third party (POJK 22/2023). |
| Resolution paths | promise to pay (date + channel), need time (grace period), cannot pay (monthly auto-debit, advisor), refuse (lapse consequence stated once), already paid | promise to pay (date + channel), need time (late fee per day), cannot pay (free restructuring referral), already paid (1×24 h reconciliation), dispute (escalate) |
| Channels | GCash, Maya, Kalayaan branch / online banking, Bayad Center, auto-debit | Virtual account (BCA/BRI/Mandiri/BNI), Indomaret, Alfamart, MajuKu app, e-wallets, Kantor Pos |
| Compliance stressed | Not a bank deposit / not PDIC-insured; no guaranteed claims; no OTP; calls Mon–Sat 8 AM–8 PM | No threats (repossession, police, telling family or employer); official channels only; holder-only disclosure; calls Mon–Sat 08.00–20.00 local |

## Localization, not translation: adaptation examples

### Philippines

1. **Amounts are said in English inside Tagalog sentences.**
   - Literal translation: "Ang inyong premium ay *limang libo limang daan at limampung piso*."
   - Localized: "Paalala lang po, ang quarterly premium ninyo ay **five thousand five hundred fifty pesos**, due sa **October 15**."

   Everyday Taglish uses English numbers and month names. Pure-Tagalog numerals sound like a textbook. `voice/speech_format.php_spoken` produces the English form.
2. **Payday-based commitments.**
   - Literal: "Anong petsa po kayo magbabayad?"
   - Localized: the agent accepts "sa kinsenas", "sa sweldo" or "sa katapusan" (the 15th or 30th payday cycle). The extraction hints map these, and the reminder note offers the 31-day grace period that covers a payday just after the due date.
3. **Politeness system.**
   - Literal: "Paumanhin sa abala." (formal and literary)
   - Localized: "Pasensya na po sa abala", with "po/opo" and "Sir/Ma'am" throughout and "Ingat po!" to close. Mirroring rule: an English speaker gets English with "po"; a deep-Tagalog speaker gets fewer English words, but the standard insurance terms stay.
4. **Bancassurance framing.** In the Philippines a bank referral creates confusion with savings. The script and KB say "Hindi po ito bank deposit at hindi insured ng PDIC" when a customer compares the policy with saving in the bank ("mas mabuti pa mag-ipon"). This doesn't exist in the India version.
5. **Family decision objection.** "Kakausapin ko muna po ang asawa ko" leads to an offer of a callback when both spouses are available, rather than pushing.

### Indonesia

1. **Register mirroring while keeping hierarchy.**
   - Formal customer: "Apakah Bapak dapat melakukan pembayaran sebelum tanggal jatuh tempo?"
   - Colloquial customer ("belum gajian nih, Mbak"): "Oh begitu ya, Pak, nggak apa-apa. Kira-kira gajiannya tanggal berapa, Pak?"

   The reply relaxes but never drops "Bapak/Ibu".
2. **Late fee as an amount per day, not a percentage.**
   - Literal: "denda 0,2 persen per hari dari angsuran yang tertunggak".
   - Localized: "dendanya **dua ribu lima ratus rupiah per hari**, dihitung sejak hari setelah jatuh tempo". The amount is computed from the installment. Amounts and dates are spoken in Indonesian ("satu juta dua ratus lima puluh ribu rupiah", "tanggal 10 Oktober").
3. **Culturally expected opener.** "Selamat pagi / siang / sore / malam" is chosen from Jakarta time (WIB), followed by "mohon maaf mengganggu waktunya". The India and Philippine packs use their own local-time greetings.
4. **Collection ethics, not collection pressure.** Under POJK 22/2023, repossession talk ("motornya ditarik"), police, or telling family or an employer are prohibited. The bot's prompt forbids them. The Q4 copilot raises a P1 "Collection ethics" nudge if a human agent says them.
5. **Hardship goes to restructuring.** "Kena PHK" or "usaha lagi sepi" leads to the free restructuring program ("keringanan", tenor extension), cited from the KB policy, with "jangan bayar ke rekening pribadi" (don't pay into anyone's personal account).
6. **Regional speech.** Javanese particles ("nggih/inggih", "mboten", "to", "e", "sampun") are understood by the turn lexicon and the extraction hints. Replies stay in Indonesian.

## Terminology in use

| Philippines (Taglish) | How it's used |
|---|---|
| premium, due date, grace period | "due sa October 15 … may grace period po hanggang November 15" |
| policy, coverage, lapse | "kapag hindi nabayaran pagkatapos ng grace period, mag-la-lapse po ang policy at titigil ang coverage" (said once, factually) |
| beneficiary, rider | servicing questions answered from the KB (revocable vs irrevocable beneficiary; ADB/CI/WPD riders) |
| bank referral, auto-debit (ADA) | bancassurance explanation; switch to monthly auto-debit at the policy anniversary |

| Indonesia | How it's used |
|---|---|
| angsuran / cicilan | both understood. The KB normalizes cicilan → angsuran and the query side does the same. The bot follows the customer's word. |
| jatuh tempo, denda | "jatuh tempo tanggal 10 Oktober … denda dua ribu lima ratus rupiah per hari" |
| tenor, DP, pembiayaan | answered from the KB (tenor 12–36 months, DP from 15%, early payoff) |
| restrukturisasi, keringanan | hardship path, free, decided within 14 working days |

## Code-switching handling

| Layer | Philippines | Indonesia |
|---|---|---|
| ASR | Azure `fil-PH` with phrase list (default). Gladia code-switching `[tl, en]` and Deepgram `multi` are bake-off candidates. Deepgram has no Tagalog model. | Deepgram Nova-3 `id` with finance keyterms (default), Azure `id-ID`, Gladia `[id, en]` |
| Turn-taking | `tl` lexicon (opo, sige po, ganun ba… / kasi, pero, tapos, yung…) plus English | `id` lexicon (iya, nggih, oh gitu, sip… / soalnya, terus, kalau, yang…) plus English |
| Understanding | Fast-model extraction with market hints (payday words, channel aliases) | Same, with colloquial, Javanese and Sundanese yes/no and channel aliases |
| Retrieval | Multilingual e5: a Taglish query finds the English FAQ, and BM25 shares the English insurance terms | Query normalization (cicilan → angsuran) and an affix stemmer (menagih ↔ penagihan) |
| Generation | Prompt: Taglish style with mirroring rules; amounts and dates pre-formatted by tools | Prompt: Bapak/Ibu, register mirroring; amounts and dates pre-formatted |
| Fallback / escalation | Pre-approved Taglish lines from `script.yaml`, spoken without the LLM. They **never switch to English.** | Pre-approved Indonesian lines, spoken without the LLM |

## Voices (TTS) and compromises

| Market | Primary | Fallback | Compromises |
|---|---|---|---|
| PH | Azure `fil-PH-BlessicaNeural` (bot), `fil-PH-AngeloNeural` (test caller) | Deepgram Aura-2 (English-only) | Only two fil-PH neural voices exist on Azure. English words in Taglish come out with Filipino phonetics (natural for Taglish), but brand names can sound off. The Deepgram fallback mispronounces Tagalog and is a last resort only. |
| ID | Azure `id-ID-GadisNeural` (bot), `id-ID-ArdiNeural` (test caller) | Deepgram Aura-2 (English-only) | Azure Indonesian voices sound formal. Colloquial replies are correct but read somewhat newscaster-like. ElevenLabs multilingual voices are a drop-in option behind the same TTS interface. |

Azure synthesizes clause by clause over a pre-opened connection inside the persistent TTS worker. The barge-in purge and reconnect path is unchanged from the base repo.

## Regional accent (Indonesia)

There are no native-speaker recordings, so the regional-accent tests use **Javanese (`jv-ID-DimasNeural`) and Sundanese (`su-ID-JajangNeural`) neural voices reading Indonesian text with Javanese particles**. This approximates Central Java and West Java accented Indonesian. It is a synthetic proxy and is reported as such.

## Evidence

- ASR bake-off per market: `uv run python -m sim.asr_bench --market ph_life|id_multifinance`. Output: `evidence/q3/asr_<market>.md`, with WER/CER by STT, voice and utterance type, finance-term recall, latency, and the errors observed.
- Recorded calls (two per market) via the persona caller: `ph_life`: `cooperative_taglish`, `objection_escalation`; `id_multifinance`: `cooperative_formal`, `colloquial_regional`. Together they cover cooperative, sector objection, mixed English and finance terms, colloquial speech, human escalation and the Indonesian regional accent. Output: `evidence/calls/…`.
- Unit tests: `tests/test_reminder.py` (verification, privacy, spoken forms, resolution paths) and the turn-lexicon checks in `turn_arbiter.py`.
- Results summary: `evidence/q3/README.md`.

## Known gaps (native-speaker and compliance)

- Scripts and prompts were written by a non-native author with care for real usage. **They need native-speaker review** (Tagalog/Taglish, Bahasa and Javanese register) before production.
- Regional-accent ASR is measured on synthetic voices only. Real Medan, Javanese, Sundanese and Makassar speakers, and real phone-line noise, will score worse.
- The regulatory summaries (Insurance Commission, BSP, Data Privacy Act; OJK POJK 22/2023) come from public knowledge and have **not been legally reviewed**. Call-hour windows are documented but not enforced, because there is no outbound dialer in this prototype.
- DOB verification alone is weak. Production would add policy number or OTP-to-registered-mobile verification on official channels.
- Each LLM was chosen for latency on the free tier (Groq Llama 3.3 70B). Its Tagalog fluency is good but not native-level.
