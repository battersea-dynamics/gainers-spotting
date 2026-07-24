# Data and API Constraints

## Alpaca

Alpaca is the preferred initial quantitative market-data source.

As verified on 24 July 2026, the individual Trading API plans advertise:

| Capability | Basic | Algo Trader Plus |
|---|---:|---:|
| Historical data requests | 200/minute | 10,000/minute |
| Real-time US equity coverage | IEX | All US exchanges |
| Historical consolidated SIP recency | Available after a 15-minute delay | No 15-minute restriction |

Limits and product terms can change. The implementation should record relevant rate-limit response headers rather than relying only on this document.

### Initial operating policy

- Use delayed consolidated SIP for reproducible research.
- Batch symbols where supported.
- Pace research traffic to leave headroom for other Alpaca processes.
- Cache the active asset universe and reusable historical data.
- Retry rate-limit responses conservatively.
- Record endpoint-level request counts, pages, failures and cache use.

A provisional shared limit of 100–120 research requests per minute is sensible until the existing market-hours scanner's usage is measured.

### Delayed-SIP research requirement

Every historical experiment must distinguish the underlying market-event timestamp from the timestamp at which delayed SIP would have made that information available to the scanner.

For the current research assumption:

`market event time + approximately 15 minutes = earliest assumed information time`

A signal, ranking or hypothetical entry must not use bars that would still have been unavailable at the simulated decision time. The research must measure whether this latency still leaves enough useful premarket movement for the approach to remain viable.

### Premarket discovery limitation

Alpaca's built-in top-movers endpoint is not a premarket discovery solution. Its stock results reset at market open and show the previous market day's movers until then. Premarket rankings therefore need to be calculated from market data.

### Efficient research collection

1. Cache the eligible U.S. equity universe daily.
2. Request delayed SIP bars in bounded symbol batches at the research checkpoints.
3. Calculate quantitative rankings locally.
4. Retain the union of candidates appearing across checkpoints.
5. Identify eventual significant gainers and selected controls for comparison.
6. After the session, download complete one-minute histories only for retained candidates, eventual winners and selected controls.
7. For detailed candidate reconstruction, retain approximately 04:00 ET through 16:00 ET where available.

This avoids continuous full-universe polling while preserving the information needed to reconstruct premarket candle sequences and evaluate post-open outcomes.

The exact batching size, safety budget and storage format remain unresolved.

## Finnhub

Finnhub is a possible selective news and catalyst source. Its exact plan and limits must be verified before implementation. It should generally be queried only after quantitative filtering has reduced the universe.

The authoritative catalyst source and exact endpoints remain open architecture questions.

## LLM usage

An LLM is optional and should be limited to qualitative interpretation where it adds value. It must not calculate basic indicators or replace reproducible Python logic.

The model used by the existing day scanner must not automatically be selected for Gainers Spotting. Model selection remains open and should be evaluated during architecture planning based on:

- model-specific call allowance;
- cost;
- latency;
- reasoning or classification quality for the intended qualitative task;
- expected number of candidate calls;
- whether quotas are sufficiently independent to avoid unnecessary competition with other systems.

Quantitative filtering should reduce the candidate population substantially before any model call. Where practical, multiple candidates should be evaluated efficiently rather than creating unnecessary per-symbol model traffic.

No LLM model has been approved for this project.

## Website screenshots

Automated scraping of third-party movers websites is not the selected approach. TradingView and Nasdaq impose restrictions that make automated capture unsuitable, and ProRealTime is better suited to interactive validation than unattended browser collection.

Manual movers screenshots may be retained as exploratory observational evidence, but they are not authoritative numerical market data and should not replace Alpaca historical reconstruction where that data is available.

If visual records are useful, the project should generate its own movers report from licensed API data and screenshot that local report. The underlying machine-readable data must be saved alongside the image.

## Credentials and generated data

- Credentials must be supplied through environment or secure credential storage.
- Secrets must never be committed.
- Raw market data, caches and generated screenshots should be excluded from Git unless a small, licensed test fixture is intentionally approved.
- Every dataset should record feed, request time, effective data cutoff and timezone-aware observation time.
- Historical entry experiments should additionally record the assumed information latency and the fill model used.