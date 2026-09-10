# Preliminary closure-to-open context findings

Last updated: 2026-09-10

This is research-only hypothesis generation. It does not define a buy rule,
recommend a stock, claim executable prices, or submit orders.

## Coverage and safeguards

The prior-session collection completed for all 14 research dates from
2026-07-27 through 2026-08-14. It added:

- 117,947 raw-adjusted daily bars;
- 35,366 raw-adjusted after-hours one-minute bars from 16:00 to 20:00 ET;
- the actual previous US trading session for each research date;
- previous-close, after-hours, premarket-transition, and exact 20-, 60-, and
  120-session dormancy measurements.

All 464 premarket-observed cases have context metadata. After-hours activity is
known for all 464, with 463 cases containing at least one after-hours bar and
one genuine zero-bar case. The 20-, 60-, and 120-session dormancy features are
available for 463, 456, and 450 cases respectively. Premarket 30-minute
reacceleration is available for 312 cases because both required sub-windows
must contain bars.

Daily, after-hours, and same-day prices use the same raw adjustment basis, but
corporate actions were not independently collected. Consequently, all 464
`true_gap_verified` flags remain false. Raw overnight-gap fields are retained
for descriptive checks only and must not be treated as split-safe true gaps.

## Main finding: recent dormancy has directional information

The strongest directional result supports part of the original hypothesis.
Stocks whose largest absolute daily close-to-close move during the preceding
20 sessions was smaller tended to perform better after the open.

| 20-session maximum prior daily move | Cases | Median 30m return | Median 60m return | Positive 60m | Median MFE | Median MAE |
|---|---:|---:|---:|---:|---:|---:|
| Lowest within-date quarter (more dormant) | 112 | +0.81% | +0.39% | 58.0% | 4.15% | -2.57% |
| Highest within-date quarter (less dormant) | 120 | -0.80% | -1.88% | 35.0% | 3.17% | -5.05% |

Across the full premarket-observed cohort, this feature's Spearman association
was -0.279 with 30-minute return, -0.284 with 60-minute return, and -0.215 with
close return. The 60-minute direction repeated on 13 of 14 dates. Lower
20-session close-return volatility gave a similar result: its least-volatile
quarter had a +0.35% median 60-minute return and -2.52% median MAE, compared
with -1.95% and -5.57% in its most-volatile quarter.

This is more specific than saying that a dormant stock simply has a narrow
historical daily range. Wider historical ranges predicted larger MFE, but also
larger adverse excursion. Recent absence of large daily jumps and low
close-return volatility appear more directionally useful in this selected
sample than historical range alone.

## After-hours behaviour: persistence helps, size alone does not

Closing after-hours nearer its after-hours high was associated with better
post-open quality. `after_hours_fade_from_high` is zero at the high and becomes
more negative as the stock fades.

| After-hours close versus high | Cases | Median 30m return | Median 60m return | Median close return | Median MFE | Median MAE |
|---|---:|---:|---:|---:|---:|---:|
| Lowest within-date quarter (largest fade) | 113 | -0.91% | -1.24% | -0.89% | 4.35% | -5.43% |
| Highest within-date quarter (best hold) | 132 | +0.04% | +0.05% | +0.26% | 3.49% | -2.90% |

The pooled associations were 0.142 with 30-minute return and 0.139 with
60-minute return, with the 60-minute direction repeating on 10 of 14 dates.
This is a modest confirmation feature, not a sufficient signal by itself.

By contrast, a large after-hours range primarily identified movement and risk.
Its association was 0.230 with later MFE and -0.347 with MAE. The widest
within-date quarter produced a 5.57% median MFE but a -5.68% median MAE and a
-1.06% median 60-minute return. The narrowest quarter produced 2.56%, -2.47%,
and +0.04% respectively. After-hours initiation, after-hours return, and the
raw close-versus-previous-close move had near-zero directional associations.

Raw overnight gap also had near-zero association with 30- and 60-minute
returns. This observation is secondary because the gaps are not yet
corporate-action verified.

## Premarket activation and reacceleration

Extreme premarket volume relative to the prior 20-session median did not
improve direction in this selected cohort. Its highest within-date quarter had
a -1.22% median 60-minute return and -5.91% median MAE, versus -0.18% and
-3.06% in the lowest quarter. It retained a small positive association with
MFE, so it again looks more like an intensity/risk measure than a continuation
signal.

The proposed 30-minute premarket reacceleration feature was weak and negative
for 30-minute, 60-minute, and close returns. It does not currently support a
buy rule. This does not show that activation is unnecessary: every case in the
current cohort was already selected from observed gainers, so the sample lacks
the quiet whole-market controls needed to estimate whether activation first
separates candidates from ordinary stocks.

An exploratory two-by-two comparison reinforces the distinction. Among the
more-dormant half, higher premarket activation increased median MFE from 3.49%
to 4.42%, but worsened median MAE from -2.31% to -4.11% and reduced median
60-minute return from +0.71% to +0.35%. This interaction was examined after
seeing the sample and is not a frozen rule.

## Interpretation for the engine

The original dormant-to-activation idea remains viable, but the 14 selected
sessions suggest three separate dimensions rather than one score:

1. **Dormancy quality:** low recent close-return volatility and no large daily
   jumps may help distinguish fresh activation from repeatedly volatile names.
2. **Movement potential:** after-hours and premarket range/activity indicate
   how much a stock may move, in either direction.
3. **Directional quality:** limited after-hours fade and post-open retention
   near the premarket high are more promising confirmation features.

Buying every observed gainer at 09:30 still had a -0.20% median 30-minute
return and -0.43% median 60-minute return. No threshold, composite weight, or
buy instruction is approved from these same 14 dates.

## What this study cannot answer

The cases came from recovered Revolut observations. They are appropriate for
learning the behaviour of known historical gainers, but they cannot measure
whole-market false positives or prove that an independent scanner would have
found them. Revolut must remain outside the future scanner's inputs.

The next decisive experiment is therefore a point-in-time whole-US-equity
universe pilot. Apply frozen versions of the dormancy, activation, persistence,
movement, and risk features to all eligible symbols available at the decision
time; retain ordinary stocks and failures as controls; and evaluate the next
unseen dates chronologically. Corporate-action reconciliation and quote-based
execution-risk data remain prerequisites for treating gap and spread features
as reliable.
