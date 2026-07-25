# Gainers Spotting

Research software for identifying U.S.-traded stocks during premarket that may be developing into significant gainers during the upcoming regular session.

The project focuses on detecting abnormal behaviour early enough that meaningful upside may still remain, rather than reproducing a list of stocks that have already completed most of their move. Historical research also compares when a candidate becomes actionable, including premarket-entry versus opening-entry approaches, without assuming an entry method in advance.

## Status

The project is in its research and architecture phase. It does not place live orders and is not integrated with `battersea-dynamics/trading-agent`.

Initial work will:

- collect reproducible premarket observations;
- reconstruct historical one-minute premarket and post-open behaviour;
- compare eventual significant gainers, missed runners and candidates that faded;
- investigate price, volume, acceleration, structure, liquidity and catalysts;
- compare plausible premarket and opening entry assumptions without look-ahead bias;
- measure detection time, remaining move, recall, precision, post-entry opportunity and API usage;
- derive scanner and entry rules from evidence rather than preset weights or thresholds.

## Principles

- U.S. equities and premarket discovery are the initial focus.
- Discovery eligibility is separate from trading eligibility.
- Historical evaluation must avoid look-ahead bias.
- Market-data delays must be represented at the simulated decision time.
- Post-open data is used to evaluate premarket selections, not to build selling logic in this phase.
- Alpaca requests should be batched and reusable data cached locally.
- Deterministic calculations belong in Python, not an LLM.
- News enrichment should occur only after quantitative candidate reduction.
- `trading-agent` must remain untouched unless future integration is explicitly approved.

## Documentation

- [Project brief](docs/project-brief.md)
- [Research methodology](docs/research-methodology.md)
- [Data and API constraints](docs/data-and-api-constraints.md)
- [Decision log](docs/decisions.md)
- [Open questions](docs/open-questions.md)

## Repository

This is a standalone project. Generated datasets, screenshots, API credentials and caches should not be committed to Git.

## Historical Alpaca collector

The research-only collector downloads paginated one-minute SIP bars for the
documented candidate and control universes. It reads credentials only from
`APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` or the compatible
`ALPACA_API_KEY` / `ALPACA_SECRET_KEY` environment variables.

```bash
python scripts/collect_alpaca_bars.py --date 2026-07-24
```

Generated raw pages, clean gzip-compressed CSV/JSONL files, and metadata are
written under `data/research/YYYY-MM-DD/`, which is excluded from Git.

## Historical session analysis

Run the reproducible research analysis after placing a collected dataset under
its date directory:

```bash
python scripts/analyze_historical_session.py --date 2026-07-24
```

The analysis validates the bars, calculates continuous premarket and
regular-session behaviour measurements, compares the documented cohorts,
performs exploratory clustering, and generates a self-contained HTML report
with candlestick and volume charts. Generated outputs are written under
`data/research/YYYY-MM-DD/analysis/` and remain excluded from Git.

The analysis is descriptive. It does not create scanner thresholds, trading
rules, entries, exits or orders.
