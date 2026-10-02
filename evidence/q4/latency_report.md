# Q4 latency report

Runs analysed: 14 (10 replays, 4 live calls). All times in ms, epoch-ms stage stamps across processes.

| component | n | P50 | P95 | max |
|---|---|---|---|---|
| ASR (interim results) | 756 | 488 | 1096 | 4592 |
| ASR (final segments) | 260 | 958 | 2413 | 5569 |
| Signal extraction: rules | 27 | 0.1 | 0.2 | 0.5 |
| Signal extraction: LLM call | 54 | 564 | 1184 | 1686 |
| LLM signal latency (emitted) | 1 | 570 | 570 | 570 |
| Nudge generation | 28 | 0.0 | 0.1 | 0.1 |
| Audio → nudge emitted | 28 | 941.8 | 2373.4 | 4438.6 |
| Delivery to hub | 4 | 3.7 | 399.6 | 399.6 |
| Delivery to display (ack) | 8 | 4.4 | 5.3 | 5.3 |
| E2E audio → hub | 4 | 945.5 | 2073.7 | 2073.7 |
| E2E audio → display | 8 | 1750.2 | 4441.6 | 4441.6 |

## Per run

| run | kind | ASR finals | nudges | E2E P50 | E2E P95 |
|---|---|---|---|---|---|
| replay-clean_compliant-on | replay | 18 | 1 | — | — |
| replay-compliance_risky-off | replay | 16 | 7 | — | — |
| replay-compliance_risky-on | replay | 16 | 5 | — | — |
| replay-missed_cross_sell-off | replay | 26 | 2 | 2073.7 | 2073.7 |
| replay-missed_cross_sell-on | replay | 27 | 2 | — | — |
| replay-noisy_ambiguous-off | replay | 4 | 0 | — | — |
| replay-noisy_ambiguous-on | replay | 4 | 0 | — | — |
| replay-q1-2fb5b84103 | replay | 35 | 0 | — | — |
| replay-q1-6072ab07af | replay | 26 | 2 | 945.5 | 945.5 |
| replay-rising_frustration-on | replay | 19 | 1 | — | — |
| live-compliance_risky | live | 16 | 5 | 1154.0 | 4441.6 |
| live-missed_cross_sell | live | 25 | 2 | 2378.0 | 2378.0 |
| live-noisy_ambiguous | live | 9 | 0 | — | — |
| live-rising_frustration | live | 19 | 1 | 960.2 | 960.2 |
