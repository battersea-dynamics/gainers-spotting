# Research Methodology

## Empirical approach

Scanner rules should be derived by studying actual outcomes and reconstructing what was knowable before the outcome occurred.

For each research date:

1. Record the candidate population at predetermined premarket checkpoints.
2. Determine the eventual leading gainers using a documented outcome measure.
3. Retrieve the underlying minute bars and relevant reference data.
4. Reconstruct the first abnormal price and volume behaviour.
5. Measure when each potential signal became observable.
6. Apply the assumed market-data delay to determine the actionable timestamp.
7. Compare winners, missed winners and early candidates that subsequently faded.
8. Preserve raw inputs and derived features so results can be reproduced.

The core question is:

> What information was available early enough to identify eventual exceptional gainers before most of their move had occurred?

## Initial observation schedule

The proposed delayed-SIP research checkpoints are:

| UK time | Typical Eastern time | Purpose |
|---|---:|---|
| 09:16 | 04:16 | First usable observation after the 04:00 ET premarket open and a 15-minute delay |
| 11:00 | 06:00 | Evolution of early candidates |
| 13:00 | 08:00 | Later premarket development |
| 14:00 | 09:00 | Final phase before the regular-market open |

UK and US daylight-saving transitions do not always occur on the same dates. Stored observations must therefore include timezone-aware timestamps rather than assuming a permanent five-hour difference.

Four checkpoints are enough for the initial candidate-history record. Complete one-minute bars can be downloaded later, so continuous full-universe polling is not required merely to reconstruct candle behaviour.

## Timeline reconstruction

`catalyst → abnormal volume → initial price movement → acceleration → consolidation/pullback → breakout → premarket high → market open → intraday high/close`

Potential measurements include cumulative premarket change and volume; 5-, 15- and 30-minute returns; price and volume velocity and acceleration; dollar volume and time-normalised relative volume; candle-range and volatility expansion; distance from premarket high and VWAP; pullback depth and recovery; higher highs, higher lows and new-high frequency; spread and liquidity where supported; and catalyst timing.

These are research variables, not approved production rules.

## Avoiding look-ahead bias

At every historical checkpoint, calculations must use only observations that would have been available then.

For delayed SIP:

`market event time + 15-minute delay = earliest assumed information time`

Evaluation should record when the market event occurred, when the scanner could have known, price at the actionable time, gain already completed, maximum and closing gain afterward, and remaining move after detection.

Features that only become apparent after most of the move are descriptive, not useful early-detection signals.

## Comparison groups

Research must include eventual exceptional gainers, eventual gainers that were missed, early high-ranking candidates that faded, and ordinary or volatile controls where appropriate.

## Performance measures

- Recall and precision.
- Detection lead time.
- Gain already completed at detection.
- Remaining move after detection.
- Candidate-set size and alert burden.
- False positives and reasons for failure.
- Missed runners and reasons for exclusion.
- API calls, cache hits and processing cost per run.

The exact outcome definition and acceptable performance thresholds remain open.
