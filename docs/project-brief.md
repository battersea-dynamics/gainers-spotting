# Project Brief

## Objective

Build a cost-efficient Python research scanner that identifies U.S.-traded stocks during premarket with a realistic possibility of becoming significant gainers during the upcoming regular session while meaningful upside may still remain.

The scanner is not intended to predict a precise percentage gain. Research may analyse outcome bands such as +30%, +50%, +80% and +100%, but those bands are labels for evaluating results, not preset alert thresholds.

The practical objective is not merely to identify which stocks ultimately finish as top gainers. The system must identify useful candidates early enough that a future actionable purchase could potentially be made before the major regular-session move.

The central distinction is between:

1. a stock that has already made a conspicuous move; and
2. a stock transitioning from quiet or ordinary behaviour into accelerating price and volume activity.

The second case is especially important. The intended behavioural hypothesis is:

`quiet → unusual activity → accelerating volume → accelerating price → possible exceptional momentum`

This is a hypothesis to test, not an approved scoring formula.

## Intended future workflow

`PREMARKET DATA → GAINERS SPOTTING SCANNER → SMALL CANDIDATE SET → PRE-OPEN FINAL DECISION → ENTRY BEFORE/AT REGULAR-SESSION OPEN → DAY-SESSION MANAGEMENT → existing day scanner / trading-agent`

The premarket system and day-session system remain separate during development. Only after Gainers Spotting has been independently researched, tested and validated should integration with the existing day-session system be considered.

No integration is part of the current phase.

## Scope

### Gainers Spotting owns during research

- premarket universe scanning;
- early identification of unusual movers;
- monitoring candidate evolution during premarket;
- quantitative candidate ranking/filtering;
- optional qualitative/catalyst analysis;
- final candidate selection before the regular session;
- research into the appropriate entry mechanism;
- historical post-open evaluation of whether premarket selections created useful opportunities.

### Initial scope

- U.S.-traded equities;
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
- selling or exit-system development;
- long-term investment selection;
- an LLM performing numerical screening;
- treating every detected stock as suitable to trade.

The existing day scanner/trading-agent may eventually own regular-session position management. Selling/exit logic is therefore not part of the current Gainers Spotting implementation, although post-open data is required for research evaluation.

## Discovery is not trading eligibility

The discovery universe should be broad enough to observe unusual behaviour that conservative trading filters might exclude. Detection does not imply adequate liquidity, acceptable spread, safe execution or suitability for a trade.

Trading and execution constraints, if investigated later, must be applied as a separate assessment.

## Conceptual pipeline

`US equity universe → early detection → candidate union → deeper analysis → catalyst enrichment → evidence-based ranking → continuous re-evaluation → pre-open decision research`

Several discovery channels should be investigated instead of relying on a single formula:

- positive movement from the previous close;
- absolute premarket volume;
- time-normalised premarket relative volume;
- volume velocity and acceleration;
- price velocity and acceleration;
- dormant-to-active transitions;
- persistence of gains;
- pullback magnitude and recovery;
- proximity to premarket high;
- premarket structure and volatility expansion;
- VWAP position and behaviour.

Deeper analysis may investigate float rotation, market-cap characteristics, spread, liquidity, pullbacks, new-high frequency and catalyst timing where reliable data is available.

None of these features, weights, stages or thresholds is approved merely by appearing in this list.

Conceptual candidate stages such as `WATCH → EMERGING CANDIDATE → HIGH-CONFIDENCE CANDIDATE → FINAL PRE-OPEN SELECTION` may be investigated as a research framework, but they are not approved scanner states or production logic.

## Entry-timing research

The system ultimately needs to answer both:

1. Which stocks are developing into likely significant gainers?
2. At what point is there enough evidence to justify an actionable entry while meaningful upside may remain?

Two broad approaches must be compared historically without choosing between them in advance:

- premarket entry using an extended-hours mechanism; and
- entry at or around the regular-session opening using an appropriate opening mechanism.

Research must recognise that earlier detection may leave more upside but provide less confirmation, while later detection may provide more confirmation but less remaining move. Premarket liquidity and achievable fills may differ materially from displayed or last prices, and the official opening print must not automatically be treated as an achievable trading fill.

## Data-source direction

- Alpaca is the primary quantitative source for the initial research.
- Fifteen-minute-delayed consolidated SIP data is acceptable initially, provided the delay is represented honestly in every simulated decision.
- Finnhub may be used selectively for catalyst or company enrichment after the quantitative candidate set has been reduced.
- An LLM may eventually interpret a very small final set, but should not replace deterministic calculations.
- The model used by the existing day scanner must not be assumed to be the correct model for this project; model selection remains open.
- Reddit and screenshots are not authoritative numerical market-data sources.
- Manual screenshots may be retained as exploratory observational evidence where useful, but quantitative reconstruction should use Alpaca historical data when available.

## Development phases

1. Architecture and historical research.
2. Live premarket observation without trading.
3. Forward validation of recall, precision, lead time and false positives.
4. Paper-trading research only if evidence justifies it.
5. Possible future `trading-agent` integration after explicit approval.

Implementation should remain incremental. Major architectural choices should be reviewed before substantial code is built.

## Success question

Can the system identify a practical subset of eventual significant gainers early enough that an actionable entry could potentially be made while substantial movement remains, while controlling false positives, data limitations, fill realism and operating cost?