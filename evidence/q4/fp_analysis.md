# Q4 false-positive analysis

## Logic level (perfect transcripts, virtual clock): controls on vs off

| script | controls | nudges | TP | missed | false positives | suppressed (reason: count) |
|---|---|---|---|---|---|---|
| collection_ethics | on | 3 | 3 | — | — | global_rate_limit: 1, duplicate_active_refreshed: 2 |
| collection_ethics | off | 6 | 4 | — | payment_difficulty @29.4s “lagi susah”; payment_difficulty @38.9s “lagi susah” | — |
| clean_compliant | on | 1 | 1 | — | — | — |
| clean_compliant | off | 1 | 1 | — | — | — |
| compliance_risky | on | 5 | 5 | — | — | max_active: 1 |
| compliance_risky | off | 6 | 6 | — | — | — |
| missed_cross_sell | on | 2 | 2 | — | — | — |
| missed_cross_sell | off | 2 | 2 | — | — | — |
| noisy_ambiguous | on | 0 | 0 | — | — | — |
| noisy_ambiguous | off | 0 | 0 | — | — | — |
| rising_frustration | on | 1 | 1 | — | — | duplicate_active_refreshed: 1 |
| rising_frustration | off | 2 | 1 | — | frustration @47.0s “I said” | — |

Totals: controls ON → 12 nudges, 0 FP; controls OFF → 17 nudges, 3 FP.

## Audio level (real-time replay and live-room runs through streaming ASR)

| run | mode | script | noise | controls | LLM | nudges | TP | missed | false positives | suppressed |
|---|---|---|---|---|---|---|---|---|---|---|
| replay-clean_compliant-on | replay | clean_compliant | — | True | True | 1 | 1 | — | — | — |
| replay-compliance_risky-off | replay | compliance_risky | — | False | True | 7 | 6 | — | — | — |
| replay-compliance_risky-on | replay | compliance_risky | — | True | True | 5 | 5 | — | — | max_active: 2 |
| replay-missed_cross_sell-off | replay | missed_cross_sell | — | False | True | 2 | 2 | — | — | — |
| replay-missed_cross_sell-on | replay | missed_cross_sell | — | True | True | 2 | 2 | — | — | — |
| replay-noisy_ambiguous-off | replay | noisy_ambiguous | {'type': 'babble', 'snr_db': 5} | False | True | 0 | 0 | — | — | — |
| replay-noisy_ambiguous-on | replay | noisy_ambiguous | {'type': 'babble', 'snr_db': 5} | True | True | 0 | 0 | — | — | — |
| replay-rising_frustration-on | replay | rising_frustration | — | True | True | 1 | 1 | — | — | duplicate_active_refreshed: 3 |
| live-compliance_risky | live room | compliance_risky | — | True | True | 5 | 5 | — | — | max_active: 2 |
| live-missed_cross_sell | live room | missed_cross_sell | — | True | True | 2 | 2 | — | — | — |
| live-noisy_ambiguous | live room | noisy_ambiguous | {'type': 'babble', 'snr_db': 5} | True | True | 0 | 0 | — | — | — |
| live-rising_frustration | live room | rising_frustration | — | True | True | 1 | 1 | — | — | low_confidence: 1, duplicate_active_refreshed: 3 |

Precision ≈ 1.00, recall ≈ 1.00 over 12 audio runs (replays and live-room runs).
