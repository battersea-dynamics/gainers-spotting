# Engine v2 Phase 1 pilot results

**Status:** exploratory single-session evidence

**Engine version:** `engine-v2-phase1-v1`

**Pilot session:** 2026-09-11

**Analysis date:** 2026-09-15

## Purpose

Phase 1 corrects the first whole-market pilot without changing its raw inputs.
It tests whether stock classification, a current-premarket-activity requirement,
removal of dormancy selection, and separate activation and momentum profiles
produce more useful discovery results than the v1 equal-channel consensus.

This is retrospective research. It does not support orders and is not an entry
strategy.

## Input and population

- 13,131 active Alpaca `us_equity` assets in the dated pilot snapshot.
- 5,382 assets classified as common shares, ordinary shares, or operating-company
  ADRs/ADSs by the dated Nasdaq Trader security master.
- 3,072 classified stocks with at least one completed premarket bar and non-zero
  premarket volume.
- 5,228 classified stocks with a valid 09:30 retrospective outcome.
- 309 unresolved assets excluded from the primary ranking rather than guessed.
- 215 possible SPAC common shares retained as stocks and separately flagged.

The security master used for this replay was captured on 2026-09-15, after the
2026-09-11 session. The comparison therefore retains survivorship, delisting,
and symbol-change risk. A production-quality historical test needs a security
master captured for each session.

## Stock classification result

| Instrument type | Assets | Primary ranking |
|---|---:|---|
| Common stock | 3,974 | Included |
| Ordinary shares | 881 | Included |
| Common shares | 245 | Included |
| ADR/ADS | 282 | Included |
| Pooled products | 5,978 | Excluded |
| Preferred shares | 456 | Excluded |
| Warrants | 427 | Excluded |
| Units | 299 | Excluded |
| Debt | 158 | Excluded |
| Rights | 122 | Excluded |
| Unknown | 309 | Excluded/control |

## Discovery comparison

The table uses maximum favourable excursion after each decision. A `20% hit`
means that the stock traded at least 20% above the decision entry price later
in the session. The rankings never contain that outcome field.

| Decision | Model | Top K | 20% hits | Precision | Recall | Non-stock/unknown selections | Median MFE | Median MAE | Median close return |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 09:30 | v1 consensus | 20 | 0 | 0% | 0% | 15 | 2.7% | -0.4% | 1.4% |
| 09:30 | v1 consensus, stock-filtered | 20 | 0 | 0% | 0% | 0 | 2.5% | -1.4% | 0.5% |
| 09:30 | v2 activation | 20 | 6 | 30% | 15.0% | 0 | 4.5% | -7.2% | -4.8% |
| 09:30 | v2 momentum quality | 20 | 0 | 0% | 0% | 0 | 4.1% | -2.4% | -1.3% |
| 09:45 | v2 activation | 20 | 4 | 20% | 14.3% | 0 | 4.5% | -5.3% | -3.3% |
| 10:00 | v2 activation | 20 | 3 | 15% | 13.6% | 0 | 4.2% | -6.0% | -2.1% |

The v2 activation score is recalculated within the eligible stock population
from:

- premarket log-volume surprise relative to the available 20-session daily
  volume proxy;
- cumulative premarket dollar volume;
- number of active completed premarket bars.

The momentum-quality profile remains separate and uses late return,
acceleration, range position, drawdown from high, and VWAP position. Dormancy is
not a candidate channel.

## Interpretation

The stock classifier materially fixes the v1 contamination problem. The
activation profile also found far more large remaining moves than the old
consensus on this one session. That supports carrying activation forward as a
broad-discovery route.

It does **not** support buying the top activation names at the open. The same
top-20 set had a -7.2% median maximum adverse excursion and a -4.8% median close
return. Several candidates spiked and then fell sharply; others were already
in unstable price discovery. Five-minute bars cannot establish executable
ordering inside a bar, and the replay includes no spread, slippage, halt, or
fill model.

The momentum-quality profile did not identify 20% open-decision runners in its
top 20 on this session. It should remain a separately measured experimental
profile until multi-session evidence determines whether it helps with smaller
moves, timing, or risk. It should not be averaged into activation merely to
produce one score.

## Safeguards verified

- Fresh whole-market snapshot; no fixed ticker list.
- Stocks only in primary v2 rankings.
- Current premarket activity required.
- Revolut membership and ranks absent from inputs.
- Dormancy absent from eligibility and primary scores.
- Rankings and retrospective outcomes stored separately.
- No outcome fields in candidate or ranking files.
- Research-only outputs; no account, position, or order access.

## Run locally

After a completed whole-market pilot exists:

```bash
python scripts/build_stock_security_master.py \
  --output data/research/whole-market-pilot/2026-09-11/security-master.json

python scripts/analyze_engine_v2_phase1.py \
  --pilot-dir data/research/whole-market-pilot/2026-09-11 \
  --security-master data/research/whole-market-pilot/2026-09-11/security-master.json
```

Outputs are written below
`data/research/whole-market-pilot/2026-09-11/analysis-v2-phase1/`.

## Decision and next evidence gate

Phase 1 is successful as a pipeline correction and hypothesis screen. It is not
approved for paper or live trading. Phase 2 should:

1. repeat the same frozen Phase 1 comparison over multiple independent dates;
2. collect one-minute bars for the broad candidate union;
3. replace the daily-volume proxy with same-cutoff historical premarket
   baselines;
4. add detailed acceleration, persistence, pullback/recovery, and near-high
   structure features;
5. add quote/spread and corporate-action-verified gap data where available;
6. evaluate spike capture and adverse excursion separately before defining an
   entry rule.
