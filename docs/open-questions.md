# Open Questions

These items require evidence or an explicit decision. They must not be silently converted into implementation assumptions.

## Outcome definition

- What constitutes a top or exceptional gainer?
- Should outcomes use previous-close-to-intraday-high, close-to-close, previous-close-to-close or multiple labels?
- How many daily winners form the positive set?
- Are +30%, +50%, +80% and +100% useful bands?
- How much remaining move is required for detection to count as useful?

## Research dataset

- Which historical dates and market regimes should be included?
- How large must the positive, false-positive and control sets be?
- Which post-open checkpoints should be evaluated?
- What recall, precision and alert burden justify forward testing?

## Discovery universe

- Minimum price, if any.
- Minimum historical or current liquidity, if any.
- Exchange coverage.
- Treatment of ETFs, ADRs, warrants, units, preferred shares and OTC securities.
- Whether historically dormant stocks require special handling.

## Features and ranking

- Which price and volume windows are predictive?
- How should time-normalised premarket volume baselines be defined?
- Which acceleration measures are robust to very small denominators?
- How should VWAP, pullback, new-high and volatility features be defined?
- Is reliable float data available at an acceptable cost?
- Does float rotation add predictive value?
- Which liquidity measures belong in discovery versus execution assessment?
- Should the final output be a score, probability, ranked evidence profile or classification?
- What weights and thresholds are justified?

## Data and infrastructure

- What Alpaca request load does the existing market-hours scanner consume?
- What safety budget should this project reserve?
- What batching size is reliable for the active universe?
- How materially does delayed SIP affect early detection?
- Which Finnhub plan and endpoints are available?
- Which source should be authoritative for catalysts?
- Should local storage use Parquet files, a database or a hybrid?
- What retention and cache invalidation policies are appropriate?
- What schema should represent observations, candidates, features and outcomes?

## Operations

- Is the four-checkpoint observation schedule sufficient?
- How frequently should a future production scanner run?
- Should UK checkpoints remain fixed or should scheduling follow Eastern market time through daylight-saving transition weeks?
- When, if ever, would real-time consolidated SIP justify its cost?

## Future integration

- What structured output would a later consumer need?
- What evidence must be met before paper-trading research?
- What evidence and review are required before any `trading-agent` integration?
