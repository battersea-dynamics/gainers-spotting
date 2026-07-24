# Gainers Spotting

Research software for identifying US stocks that may be developing into the
day's exceptional gainers.

The project focuses on detecting abnormal behaviour early—particularly during
premarket—rather than reproducing a list of stocks that have already completed
most of their move.

## Status

The project is in its research and architecture phase. It does not place live
orders and is not integrated with `battersea-dynamics/trading-agent`.

Initial work will:

- collect reproducible premarket observations;
- reconstruct historical one-minute market behaviour;
- compare eventual top gainers with candidates that faded;
- investigate price, volume, acceleration, structure, liquidity and catalysts;
- measure detection time, remaining move, recall, precision and API usage;
- derive scanner rules from evidence rather than preset weights.

## Principles

- US equities and premarket discovery are the initial focus.
- Discovery eligibility is separate from trading eligibility.
- Historical evaluation must avoid look-ahead bias.
- Market-data delays must be represented at the simulated decision time.
- Alpaca requests should be batched and reusable data cached locally.
- Deterministic calculations belong in Python, not an LLM.
- News enrichment should occur only after quantitative candidate reduction.
- `trading-agent` must remain untouched unless future integration is explicitly
  approved.

## Documentation

- [Project brief](docs/project-brief.md)
- [Research methodology](docs/research-methodology.md)
- [Data and API constraints](docs/data-and-api-constraints.md)
- [Decision log](docs/decisions.md)
- [Open questions](docs/open-questions.md)

## Repository

This is a standalone project. Generated datasets, screenshots, API credentials
and caches should not be committed to Git.
