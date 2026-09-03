# Premarket ranking engine

`scripts/rank_premarket_candidates.py` is a research-only, point-in-time
candidate ranker. It does not connect to a broker and cannot submit orders.

## What it produces

For each historical date it creates three rankings:

- `open`: uses only 04:00–09:29 ET bars;
- `open+15`: adds completed 09:30–09:44 ET bars;
- `open+30`: adds completed 09:30–09:59 ET bars.

The ranking features measure premarket return, dollar volume, active minutes,
late-volume acceleration, VWAP location, proximity to the premarket high, and
green-bar persistence. The +15 and +30 rankings also measure opening-session
confirmation. The score is an exploratory equal-weight average of within-day
percentile ranks. It is deliberately transparent and has no fitted thresholds.

There is no minimum share-price filter. Low-priced shares remain in the research
universe; liquidity, activity and price behaviour are measured rather than
replaced by a price cutoff.

Retrospective outcomes include 5-, 15-, 30-, 60- and 120-minute returns,
noon/close returns, maximum favourable/adverse excursion, time to each
extreme, high-to-close giveback, and threshold-free failure flags. They are
never included in `research_score` and are written to separate outcome files.

Every ranking records `feature_set_version`, `outcome_set_version`,
`score_version`, and per-row feature coverage. The pooled analysis additionally
uses `config/research-protocol-v1.json` to freeze score inputs, continuous
outcomes, evaluation-only MFE sensitivity labels, top-k alert budgets, and the
minimum chronological training window.

## Run it

From the repository root, after downloading the Alpaca artifact for a date:

```bash
python scripts/rank_premarket_candidates.py --date 2026-07-27
```

The script discovers the clean bar CSV below `data/research/2026-07-27/` and
writes to:

```text
data/research/2026-07-27/analysis/premarket_ranker/
```

To select a file explicitly:

```bash
python scripts/rank_premarket_candidates.py \
  --date 2026-07-27 \
  --input data/research/2026-07-27/clean/bars_1min.csv
```

Generated research data remains local/ignored. Commit the script, tests and
documentation, not the generated rankings.

For pooled top-k and walk-forward evaluation, run the multi-date command in the
README. It writes:

- `candidate-rankings.csv`;
- `candidate-ranking-outcomes.csv` (retrospective labels kept separate);
- `top-k-evaluation.csv`;
- `alert-burden.csv`;
- `chronological-walk-forward.csv`;
- the exact `research-protocol.json` snapshot used for the run.

## Interpretation limits

- The collector starts at 04:00 ET, so the true gap from the previous regular
  close cannot be computed from that file alone. `premarket_return_pct` is the
  return from the first observed premarket bar to the last premarket bar and is
  intentionally not called a gap.
- Revolut screenshots are external labels used to check coverage and evolution;
  they are not inputs to the score.
- The engine ranks the point-in-time-eligible symbols in its input file; it
  does not turn a screenshot-derived file into a whole-market scanner. Symbols
  labelled `post_open_only_observed` or `missed_runner_control` remain in source
  data for evaluation but are excluded from rankings because their inclusion
  depends on future information.
- A broad future-session universe can be generated with
  `scripts/build_alpaca_universe.py`. Its timestamped asset snapshot is
  reproducible, but using a current snapshot for an earlier historical date may
  introduce survivorship bias.
- Bid/ask spread, corporate actions, official previous close, historical RVOL,
  float rotation, and catalyst tags remain unavailable until their source data
  is collected. The engine does not infer them from one-minute candle ranges.
- Execution/slippage modelling is deliberately deferred.
- A high historical score is not a recommendation. Thresholds and entry rules
  require out-of-sample evaluation across more dates before any paper-trading
  trial.
