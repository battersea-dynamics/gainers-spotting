# Preliminary 14-session premarket/open findings

Last updated: 2026-09-10

This is research-only hypothesis generation. It does not define a buy rule,
recommend a stock, claim executable prices, or submit orders.

## Coverage and method

The analysis combines the five collected sessions from 2026-07-27 through
2026-07-31 with nine sessions from 2026-08-03 through 2026-08-14:

- 14 market sessions;
- 297,388 Alpaca SIP one-minute bars;
- 796 usable collected symbol-date cases;
- 464 cases classified as observed before the open;
- 434 cases with non-empty premarket bars for price/range calculations;
- 420 cases joined to exact recovered premarket screenshot checkpoints.

Features for 09:30 ET use bars strictly before the open. The 09:45 and 10:00
variants add only completed regular-session bars before those decision times.
Later bars supply outcomes only. Screenshot membership and displayed values are
retrospective labels; they are not scanner inputs.

The actual UK phone time was converted to America/New_York before phase
assignment. This corrects two nominally “premarket” captures: 00:39 UK on
2026-08-04 was 19:39 ET on 2026-08-03, and 01:10 UK on 2026-08-07 was 20:10 ET
on 2026-08-06. They are previous-session context, not same-session premarket
observations.

## Main result: movement potential is not directional edge

Buying every premarket-observed case at the decision benchmark did not produce
a positive median short-horizon return:

| Decision ET | Median 30m return | Median 60m return | Median MFE | Median MAE | Median close return |
|---|---:|---:|---:|---:|---:|
| 09:30 | -0.20% | -0.43% | 3.24% | -3.98% | -0.11% |
| 09:45 | -0.07% | -0.13% | 2.74% | -2.97% | 0.00% |
| 10:00 | -0.17% | -0.07% | 2.69% | -2.55% | 0.12% |

The clearest 09:30 associations with later MFE were:

| Premarket feature | Spearman rho with MFE | Same direction by date | Interpretation |
|---|---:|---:|---|
| Range percentage | 0.234 | 13/14 | Wider premarket ranges tended to precede more later movement. |
| Price at decision | -0.200 | 11/14 | Lower-priced cases tended to have more percentage upside excursion. |
| Drawdown from premarket high | -0.150 | 10/14 | Deeper pullbacks sometimes rebounded more after the open. |

These are primarily volatility effects. Wider premarket range also correlated
with worse MAE (-0.310, the same direction on 13/14 dates), while its
correlations with 30-minute and close returns were negative. Lower price and
greater activity showed the same broad trade-off: more possible excursion,
but also more downside. This supports keeping cheap stocks discoverable while
treating price, range and liquidity as explicit risk dimensions.

## What the repeated screenshots show

Repeated Revolut appearance was not a positive confirmation signal:

| Screenshot persistence | Cases | Median MFE | Median MAE | Median 30m return | Median close return |
|---|---:|---:|---:|---:|---:|
| 1 checkpoint | 161 | 3.07% | -4.08% | -0.60% | -0.65% |
| 2 checkpoints | 105 | 3.98% | -3.38% | 0.05% | 0.76% |
| 3+ checkpoints | 154 | 3.07% | -4.79% | -0.69% | -1.01% |

The pattern is not monotonic, so “two checkpoints” is not a rule. Treated as a
continuous within-date measure, greater persistence had Spearman rho -0.162
with 30-minute return and -0.161 with close return. The 30-minute direction was
negative on 11 of 13 dates with enough variation. First appearance time had
near-zero pooled association with 30-minute return and only a weak, unstable
association with MFE.

The working interpretation is overextension: appearing repeatedly in a
top-gainers list may identify sustained attention and volatility, but does not
by itself distinguish continuation from exhaustion.

## Entry timing and opening confirmation

Waiting reduced adverse excursion. Relative to the same case at 09:30, median
MAE improved by 0.88 percentage points at 09:45 and 1.12 points at 10:00.
Waiting also surrendered median MFE of 0.48 and 0.71 points respectively.

One directional-quality hypothesis deserves further testing: whether price
holds or recovers toward the premarket high after the open. At 09:45,
`decision_vs_pm_high` correlated 0.152 with close return, in the same direction
on 12/14 dates. In within-date quartiles at 10:00, the quarter closest to the
premarket high had a +0.27% median close return and -2.64% median MAE, versus
-1.16% and -4.21% for the bottom quarter. This is a descriptive comparison,
not a frozen cutoff or validated entry rule.

Large opening range predicted both larger MFE and worse MAE extremely
consistently. Like premarket range, it measures movement potential more clearly
than direction.

## Current ranking models

The equal-weight `composite_v1` score did not rank later MFE consistently. Its
median per-date Spearman correlation with MFE was 0.018 at 09:30, -0.053 at
09:45 and -0.044 at 10:00. Simple premarket volume was stronger for MFE at
09:45, while simple premarket return was stronger at 09:30, but both changed
materially between the July and August subsets.

Chronological model-selection checks were weak: median next-date MFE rank
correlations were 0.113, 0.029 and 0.099 at 09:30, 09:45 and 10:00. This is not
enough evidence to approve the current composite or any baseline as a trading
strategy.

## Engine implications

The next engine iteration should keep three concepts separate:

1. **Movement potential:** premarket range, activity, trade count and price.
2. **Directional quality:** late momentum, recovery/retention versus the
   premarket high, VWAP position and opening confirmation.
3. **Execution risk:** spread when quotes become available, thin trading,
   halts, extreme volatility and adverse excursion.

The 09:30 variant currently has the weakest evidence for direction. The 09:45
and 10:00 variants sacrifice some upside but provide useful confirmation and
smaller typical drawdowns.

## What remains untested

The collected windows begin at 04:00 ET. They do not yet contain the previous
official close or the complete previous-session 16:00–20:00 ET path. Therefore
the original closure-to-premarket idea is only partially tested: same-day
premarket and post-open behaviour are covered, but exact gap and overnight
after-hours structure are not.

The sample is also screenshot-selected. It can reveal behaviour among known
historical gainers, but cannot measure whole-market false positives or prove
that the engine could have discovered them independently. The next evidence
step is to add prior-close/after-hours bars, then run the frozen feature logic
against an independently constructed broad US-equity universe with negative
controls.
