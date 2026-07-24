# Project Brief

## Objective

Build a cost-efficient Python research scanner that identifies US stocks with a realistic possibility of becoming exceptional intraday gainers while meaningful upside may still remain.

The scanner is not intended to predict a precise percentage gain. Research may analyse outcome bands such as +30%, +50%, +80% and +100%, but those bands are labels for evaluating results, not preset alert thresholds.

The central distinction is between:

1. a stock that has already made a conspicuous move; and
2. a stock transitioning from quiet or ordinary behaviour into accelerating price and volume activity.

The second case is especially important. The intended behavioural hypothesis is:

`quiet → unusual activity → accelerating volume → accelerating price → possible exceptional momentum`

This is a hypothesis to test, not an approved scoring formula.

## Scope

### Initial scope

- US-listed equities;
- premarket discovery;
- broad quantitative candidate detection;
- historical reconstruction and backtesting;
- false-positive and missed-runner analysis;
- API-efficient data collection and caching;
- observation-mode forward testing;
- research and paper workflows only.

### Outside the initial scope

- live trading or order execution;
- modification of `battersea-dynamics/trading-agent`;
- direct integration with `trading-agent`;
- long-term investment selection;
- an LLM performing numerical screening;
- treating every detected stock as suitable to trade.

## Discovery is not trading eligibility

The discovery universe should be broad enough to observe unusual behaviour that conservative trading filters might exclude. Detection does not imply adequate liquidity, acceptable spread, safe execution or suitability for a trade.

Trading and execution constraints, if investigated later, must be applied as a separate assessment.

## Conceptual pipeline

`US equity universe → early detection → candidate union → deeper analysis → catalyst enrichment → evidence-based ranking → continuous re-evaluation`

Several discovery channels should be investigated instead of relying on a single formula:

- positive movement from the previous close;
- absolute premarket volume;
- time-normalised premarket relative volume;
- volume velocity and acceleration;
- price velocity and acceleration;
- dormant-to-active transitions;
- proximity to premarket high;
- premarket structure and volatility expansion;
- VWAP position and behaviour.

Deeper analysis may investigate float rotation, spread, liquidity, pullbacks, new-high frequency and catalyst timing where reliable data is available.

None of these features, weights or thresholds is approved merely by appearing in this list.

## Data-source direction

- Alpaca is the primary quantitative source for the initial research.
- Fifteen-minute-delayed consolidated SIP data is acceptable initially, provided the delay is represented honestly in every simulated decision.
- Finnhub may be used selectively for catalyst or company enrichment after the quantitative candidate set has been reduced.
- An LLM may eventually interpret a very small final set, but should not replace deterministic calculations.
- Reddit and screenshots are not authoritative numerical market-data sources.

## Development phases

1. Architecture and historical research.
2. Live premarket observation without trading.
3. Forward validation of recall, precision, lead time and false positives.
4. Paper-trading research only if evidence justifies it.
5. Possible future `trading-agent` integration after explicit approval.

Implementation should remain incremental. Major architectural choices should be reviewed before substantial code is built.

## Success question

Can the system identify a practical subset of eventual exceptional gainers early enough that substantial movement remains, while controlling false positives, data limitations and operating cost?
