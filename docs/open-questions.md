# Open Questions

These items require evidence or an explicit decision. They must not be silently converted into implementation assumptions.

## Outcome definition

- What constitutes a top or significant gainer?
- Should outcomes use previous-close-to-intraday-high, close-to-close, previous-close-to-close or multiple labels?
- How many daily winners form the positive set?
- Are +30%, +50%, +80% and +100% useful research bands?
- How much remaining move is required for detection to count as useful?
- How should a useful/profitable opportunity be labelled without prematurely imposing an arbitrary return threshold?
- Which post-open windows should be used when evaluating continuation or failure?

## Entry timing and fill modelling

- Should a future system favour premarket entry, opening entry, or choose dynamically based on evidence?
- What evidence is sufficient to justify an actionable entry?
- How should extended-hours limit-order fills be modelled historically?
- Which opening-order mechanism or opening-entry assumption should be researched?
- How should achievable fill prices be estimated when displayed/last premarket prices may not be executable?
- How should the official opening print be used without assuming it was necessarily achievable?
- Which liquidity, spread or quote information is required for credible entry modelling?
- How should the trade-off between earlier detection and stronger confirmation be quantified?

## Research dataset

- Which historical dates and market regimes should be included?
- How large must the positive, false-positive and control sets be?
- Which post-open checkpoints should be evaluated?
- What recall, precision and alert burden justify forward testing?
- How should the 24 July 2026 observation names be incorporated into the first historical reconstruction sample without treating that day as representative?

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
- Does persistence of a premarket gain add predictive value?
- How should deterioration, pullback and recovery patterns be represented?
- How should VWAP, pullback, new-high and volatility features be defined?
- Is reliable float and market-cap data available at an acceptable cost?
- Does float rotation add predictive value?
- Which liquidity measures belong in discovery versus entry/execution assessment?
- Should the final output be a score, probability, ranked evidence profile or classification?
- Do progressive conceptual stages such as WATCH, EMERGING CANDIDATE, HIGH-CONFIDENCE CANDIDATE and FINAL PRE-OPEN SELECTION improve decisions, or add unnecessary complexity?
- What weights and thresholds are justified?

## Data and infrastructure

- What Alpaca request load does the existing market-hours scanner consume?
- What safety budget should this project reserve?
- What batching size is reliable for the active universe?
- How materially does delayed SIP affect early detection and remaining opportunity?
- Which Finnhub plan and endpoints are available?
- Which source should be authoritative for catalysts?
- Should local storage use Parquet files, a database or a hybrid?
- What retention and cache invalidation policies are appropriate?
- What schema should represent observations, candidates, features, entry assumptions and outcomes?
- What quote or spread history is available and affordable for realistic premarket/opening fill research?

## AI model architecture

- Does Gainers Spotting need an LLM at all for the first research architecture?
- If qualitative analysis adds value, which model is appropriate?
- What are the candidate models' call allowances, costs and latency?
- What reasoning/classification quality is required for the intended qualitative task?
- How many model calls would a typical premarket session require after quantitative filtering?
- Are model quotas sufficiently independent from the existing day scanner to avoid unnecessary competition?
- Should several finalists be analysed in one structured model call or individually?

## Operations

- Is the four-checkpoint observation schedule sufficient?
- How frequently should a future production scanner run?
- Should UK checkpoints remain fixed or should scheduling follow Eastern market time through daylight-saving transition weeks?
- When, if ever, would real-time consolidated SIP justify its cost?

## Future integration

- What structured output would a later consumer need?
- What evidence must be met before paper-trading research?
- What evidence and review are required before any `trading-agent` integration?