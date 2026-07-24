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

### Premarket discovery limitation

Alpaca's built-in top-movers endpoint is not a premarket discovery solution. Its stock results reset at market open and show the previous market day's movers until then. Premarket rankings therefore need to be calculated from market data.

### Efficient research collection

1. Cache the eligible US equity universe daily.
2. Request delayed SIP bars in bounded symbol batches at four checkpoints.
3. Calculate rankings locally.
4. Retain the union of candidates appearing across checkpoints.
5. After the session, download complete minute bars only for retained candidates, eventual winners and selected controls.

This avoids full-universe polling every minute while preserving the information needed to reconstruct candle sequences.

## Finnhub

Finnhub is a possible selective news and catalyst source. Its exact plan and limits must be verified before implementation. It should generally be queried only after quantitative filtering has reduced the universe.

## LLM usage

An LLM is optional and should be limited to qualitative interpretation where it adds value. It must not calculate basic indicators or replace reproducible Python logic.

## Website screenshots

Automated scraping of third-party movers websites is not the selected approach. TradingView and Nasdaq impose restrictions that make automated capture unsuitable, and ProRealTime is better suited to interactive validation than unattended browser collection.

If visual records are useful, the project should generate its own movers report from licensed API data and screenshot that local report. The underlying machine-readable data must be saved alongside the image.

## Credentials and generated data

- Credentials must be supplied through environment or secure credential storage.
- Secrets must never be committed.
- Raw market data, caches and generated screenshots should be excluded from Git unless a small, licensed test fixture is intentionally approved.
- Every dataset should record feed, request time, effective data cutoff and timezone-aware observation time.
