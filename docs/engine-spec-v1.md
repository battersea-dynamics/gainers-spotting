# Gainers Spotting engine specification v1

**Status:** Approved for phased research implementation  
**Specification version:** `engine-spec-v1`  
**Date:** 2026-09-09  
**Repository:** `battersea-dynamics/gainers-spotting`

## 1. Purpose

This document specifies the next research architecture for Gainers Spotting.
The engine is intended to discover unusual premarket behaviour across a broad
US-equity universe and produce point-in-time candidate rankings for possible
entry research at:

- 09:30 America/New_York time (regular-session open);
- 09:45 America/New_York time (open +15 minutes);
- 10:00 America/New_York time (open +30 minutes).

The research objective is not to predict an exact final percentage gain. It is
to identify stocks transitioning from ordinary or dormant behaviour into an
extreme positive-momentum regime while meaningful movement may still remain.

The intended behavioural sequence is:

`quiet -> unusual activity -> accelerating volume -> accelerating price -> potential extreme momentum`

This specification builds on the current historical collector, point-in-time
ranker and multi-date evaluator. It does not replace working components unless
the replacement removes duplicated logic or is required for market-wide
discovery.

## 2. Boundaries and confirmed scope

The following requirements are binding for v1:

1. Work only in `battersea-dynamics/gainers-spotting`.
2. Do not modify or couple directly to `battersea-dynamics/trading-agent`.
3. Do not implement or submit broker orders.
4. Do not access account, position or order endpoints.
5. Do not implement selling, exit selection or position management.
6. Treat 09:30, 09:45 and 10:00 ET as separate research decisions.
7. The 09:30 ranking may use premarket information only.
8. The 09:45 and 10:00 rankings may add regular-session information available
   before their respective decision times.
9. Use later data only for retrospective outcomes, never as ranking inputs.
10. Keep broad discovery separate from later execution or tradability review.
11. Do not impose an automatic minimum price on the discovery universe.
12. Treat Revolut screenshots as independent observational labels only.
13. Use deterministic Python for market-data calculations.
14. Keep news and any LLM interpretation outside the initial quantitative
    discovery path.

Older documentation that proposes a premarket entry experiment is superseded
for this engine phase. Premarket activity is used to select candidates for the
three stated regular-session decision times; premarket order entry is not part
of v1.

## 3. Terminology

### Discovery universe

The broad set of US-traded instruments eligible to be examined for abnormal
behaviour. Inclusion does not imply that the instrument is suitable to trade.

### Candidate

A symbol retained by at least one quantitative discovery channel using only
information available at that point in time.

### Execution-risk profile

Separate measurements describing staleness, liquidity, spread, volatility and
other possible implementation risks. These measurements must not silently
remove a symbol from discovery.

### Market-event timestamp

The timestamp associated with an exchange event or market-data bar.

### Information-available timestamp

The earliest time at which the configured data feed is assumed to make an
event available to the scanner.

### Decision timestamp

The time at which a historical replay or observation-mode run produces a
ranking.

### Entry benchmark timestamp

The fixed timestamp used to measure subsequent opportunity. A benchmark price
is reproducible research data, not a claim that an order could have achieved
that fill.

### Numeric conventions

Canonical calculations shall use decimal returns internally: `0.10` means a
10% return. Fields whose names end in `_pct` must contain percentage points:
`10.0` means 10%. The two representations must never share an ambiguous field
name.

Other canonical units are:

- price and dollar volume: US dollars;
- share volume: shares;
- elapsed time: minutes;
- rank percentiles and range positions: dimensionless values from 0 to 1;
- timestamps: timezone-aware ISO 8601 values.

Rounding occurs only for human-facing reports. Machine-readable calculations
retain full available precision. JSON uses `null`, never non-standard `NaN` or
infinity, for missing numeric values.

Canonical per-bar dollar volume is:

`bar_dollar_volume = volume * bar_vwap`

If a valid bar VWAP is unavailable, `close * volume` may be used with an
explicit `dollar_volume_price_fallback` flag. Cumulative VWAP uses the same
volume-weighted bar-price basis. This policy replaces the current inconsistent
use of close in one analysis path and bar VWAP in another.

## 4. Architectural overview

The engine shall use a two-stage discovery funnel:

1. Create and preserve a dated broad universe.
2. Load previous-close, corporate-action and historical-baseline reference
   data.
3. Collect a cost-efficient broad premarket market-data pass.
4. Calculate independent discovery-channel measurements locally.
5. Retain the union of symbols surfaced by those channels.
6. Calculate deeper one-minute features for the retained candidates.
7. Produce separate 09:30, 09:45 and 10:00 ET rankings.
8. Store future outcomes separately after the session.
9. Evaluate rankings using date-separated historical validation.

Historical replay and live observation must use the same feature and ranking
interfaces. Differences in data feed, delay or coverage must be explicit run
configuration, not hidden branching.

## 5. Time, bar boundaries and data latency

### 5.1 Canonical timezone

All internal market decisions and stored market timestamps shall use
`America/New_York`. Human-facing reports may also show UK time using
`Europe/London`. Code and scheduling must not assume that the UK-US difference
is permanently five hours.

### 5.2 Completed-bar rule

If a one-minute bar timestamp represents the beginning of its interval, its
bar-end time is:

`bar_end = bar_timestamp + 1 minute`

A bar is eligible for a decision only if:

`bar_end + configured_feed_delay <= decision_timestamp`

The equivalent rule must be used for five-minute bars.

Examples under an assumed zero-delay feed:

- 09:30 ranking: latest eligible one-minute bar begins at 09:29.
- 09:45 ranking: latest eligible one-minute bar begins at 09:44.
- 10:00 ranking: latest eligible one-minute bar begins at 09:59.

Under a configured 15-minute delay, the available market-event cutoff will be
approximately 15 minutes earlier. Exact Alpaca publication timing and boundary
semantics must be tested and recorded before delayed-feed results are treated
as operationally representative.

### 5.3 Required data modes

Every run shall declare one of the following or an equivalent versioned mode:

- `historical_sip_zero_delay_assumption`;
- `historical_sip_configured_delay`;
- `iex_realtime_experiment`;
- `sip_realtime_experiment`.

The engine must never imply that consolidated SIP-trained feature values are
identical to live IEX feature values. Feed comparisons must be treated as
separate experiments.

### 5.4 Required timestamps in every run

Every feature snapshot and ranking shall retain:

- `session_date`;
- `decision_timestamp_et`;
- `market_event_cutoff_et`;
- `information_available_at_et` or the delay assumption used to derive it;
- `entry_benchmark_timestamp_et`;
- `generated_at_utc`;
- `feed` and `data_mode`.

### 5.5 Discovery observations versus entry decisions

Premarket discovery observations and entry-decision rankings are different
objects.

Historical replay should calculate broad discovery snapshots every five
minutes from 04:15 ET through the final eligible premarket cutoff when the
underlying data support it. This local replay cadence is used to measure first
detection, persistence and deterioration; it does not create additional entry
times.

The only v1 entry-decision rankings remain 09:30, 09:45 and 10:00 ET. A future
live observation cadence may be less frequent and shall be selected after API
and runtime measurements.

## 6. Universe construction

### 6.1 Initial eligibility

The broad universe shall initially require:

- US equity asset class;
- active status at the captured snapshot;
- tradable status in Alpaca asset metadata;
- a supported US exchange;
- a non-blank unique symbol.

The discovery universe shall not initially require:

- a minimum share price;
- a minimum historical daily volume;
- a positive premarket gap;
- previous premarket activity;
- execution-quality approval.

### 6.2 Instrument annotation

Where reliable metadata permits, the universe should annotate common stock,
ADR, ETF/ETP, warrant, unit, preferred share and other security types. Unknown
types remain marked unknown; they must not be guessed from the security name.

Instrument-type exclusions, if later proposed, must report both the reduction
in alert burden and any loss of extreme-gainer recall.

### 6.3 Point-in-time preservation

Each universe snapshot shall include:

- capture timestamp;
- research session date;
- universe-rule version;
- included assets and relevant metadata;
- exclusion counts by explicit reason;
- a deterministic content hash.

A current asset snapshot may support a future observation session. It must not
be described as a complete historical universe for an earlier date. Historical
tests using present-day asset lists must disclose survivorship and symbol-change
risk.

## 7. Required market and reference data

### 7.1 Broad premarket data

The preferred initial experiment is five-minute bars across the dated broad
universe from 04:00 ET to each information cutoff. This interval is a proposed
cost optimisation and must first pass a one-session coverage and API-volume
pilot.

If five-minute bars materially harm early detection, the design may use
one-minute bars or another measured approach without changing downstream
interfaces.

### 7.2 Candidate detail data

For the union of candidates, retain one-minute bars containing, where
available:

- OHLC;
- share volume;
- dollar-volume inputs;
- trade count;
- bar VWAP;
- feed and timestamps.

Detailed outcome collection may extend through 16:00 ET after the selection
set has been frozen.

For screenshot-labelled case studies and retained candidates, the detail layer
shall also collect the previous session's available after-hours bars from
16:00-20:00 ET. This permits the research to distinguish:

- a reaction that began immediately after the previous regular close;
- continuation or deterioration of that reaction during the next premarket;
- genuinely new activity that first appeared during the morning premarket.

There is normally no continuous US equity session between the end of
after-hours trading and the 04:00 ET premarket start. The price discontinuity
between the last after-hours observation and first premarket observation may be
measured, but missing overnight trades must not be fabricated.

### 7.3 Daily reference data

For each symbol-date, collect or derive without future leakage:

- previous official regular-session close;
- previous regular-session volume;
- split and other relevant corporate-action flags;
- the source and adjustment mode.

The engine must not call a first-to-last premarket return a gap. A true gap is
computed from the previous official regular-session close.

Previous close and current bars must be on a comparable corporate-action basis.
If they cannot be reconciled safely, true-gap features are missing and a
corporate-action warning is recorded. The symbol remains eligible for
non-gap discovery channels.

### 7.4 Quotes and auction data

Historical bid/ask spread, depth and opening-auction imbalance are not required
for the first discovery implementation. If unavailable, the engine must report
them as unavailable and must not infer bid/ask spread from candle high-low
range.

### 7.5 Missing bars

No-trade periods and missing data are different states. The engine shall not
fabricate zero-volume candles. It shall retain:

- first and last observed bar times;
- observed bar count;
- active-minute count;
- staleness at decision;
- expected-versus-observed coverage where an expectation is justified;
- explicit data-quality flags.

## 8. Historical baseline store

Historical baselines must use only sessions before the research date.

The initial configuration shall expose, rather than hard-code invisibly:

- `baseline_window_sessions`, initially tested with 20 prior eligible sessions;
- `minimum_baseline_sessions`, initially tested with 5;
- time buckets and cumulative cutoff definitions;
- feed and adjustment mode.

For every symbol and comparable premarket cutoff, retain historical
distributions for:

- cumulative share volume;
- cumulative dollar volume;
- trade count;
- active bars;
- five-, 15- and 30-minute activity;
- premarket return and range where observable.

Initial robust features shall include:

`share_rvol = (today_cumulative_volume + 1) / (historical_median_cumulative_volume + 1)`

`dollar_rvol = (today_cumulative_dollar_volume + 1) / (historical_median_cumulative_dollar_volume + 1)`

`log_volume_surprise = log1p(today_cumulative_volume) - median(log1p(historical_cumulative_volume))`

`log_dollar_surprise = log1p(today_cumulative_dollar_volume) - median(log1p(historical_cumulative_dollar_volume))`

`historical_zero_activity_fraction = zero_activity_sessions / eligible_baseline_sessions`

The `+1` stabilisers are units of one share or one dollar and must be versioned
with the feature definition. Median-based baselines are preferred initially to
reduce sensitivity to isolated extreme historical sessions.

If insufficient baseline history exists, baseline-dependent features shall be
missing and `baseline_status` shall explain why. The symbol remains eligible
for channels that do not require a baseline.

## 9. Parallel candidate-discovery channels

Candidate generation must not depend on a single formula. Each channel shall
produce a channel score, a within-date channel rank and deterministic reason
codes.

### 9.1 Positive gap activity

Uses the previous official close and the latest eligible price. Negative-gap
reversal research is not part of this positive-runner pathway.

### 9.2 Absolute market activity

Uses cumulative share volume, dollar volume, trade count and active bars. Raw
share volume alone must not be treated as sufficient evidence.

### 9.3 Time-normalised abnormal activity

Uses share RVOL, dollar RVOL and log-surprise measurements against historical
activity observed up to the same market-event cutoff.

### 9.4 Volume acceleration

Measures whether recent volume arrival is increasing. Initial one-minute
candidate-detail features include:

`volume_velocity_5m = sum(volume in latest eligible 5 minutes) / 5`

`volume_velocity_previous_5m = sum(volume in the preceding 5 minutes) / 5`

`log_volume_acceleration_5m = log1p(latest_5m_volume) - log1p(previous_5m_volume)`

Equivalent 15-minute measurements shall also be retained. Missing no-trade
intervals are not silently filled with market-data candles; window sums and
observed-bar counts are stored together.

### 9.5 Positive price acceleration

Initial features include:

`return_latest_5m = last_close_latest_window / first_open_latest_window - 1`

`return_previous_5m = last_close_previous_window / first_open_previous_window - 1`

`price_acceleration_5m = return_latest_5m - return_previous_5m`

Equivalent 15-minute and 30-minute returns may be retained. Windows without
enough observations are marked missing rather than assigned zero return.

### 9.6 Dormant-to-active transition

Combines current activity with:

- historical zero-activity fraction;
- current log-volume and log-dollar surprise;
- time of first premarket activity;
- current active-minute and trade-count evidence.

A historically dormant symbol shall not be excluded merely because its RVOL
denominator is small or missing.

### 9.7 Emerging price structure

Uses positive late-premarket return, new-high frequency, position in the
premarket range, VWAP relationship, pullback and recovery. A single isolated
high on a stale or thin print shall be distinguishable from persistent
strength.

### 9.8 Candidate union and alert budget

The retained set is the union of symbols selected by all enabled channels.
Per-channel top-k budgets and any absolute anomaly cutoffs shall live in a
versioned research protocol.

No candidate budget is approved in this draft. Historical replay shall first
generate burden-versus-recall curves for alternative budgets such as top 20,
50 and 100 per channel. The chosen budget is an operational capacity decision
that must be frozen before later-date evaluation.

## 10. Candidate-detail features

### 10.1 Price and gap

- previous-close-to-latest-price gap;
- previous-close-to-premarket-high excursion;
- first-observed-to-latest premarket return;
- five-, 15- and 30-minute returns;
- early-, middle- and late-premarket returns;
- continuous price as a descriptive and risk feature;
- a versioned descriptive price band where useful for stratified evaluation.

Price bands must never replace the continuous price field and shall not create
an automatic discovery exclusion.

### 10.2 Previous-close and after-hours context

For symbols with suitable prior-session data, retain:

- previous official regular-session close;
- previous after-hours first, last, high and low prices;
- previous after-hours return, range, volume, dollar volume and trades;
- time of first abnormal after-hours activity;
- current premarket price relative to the previous close, after-hours close and
  after-hours high;
- whether after-hours strength persisted, faded or reaccelerated in premarket.

These are point-in-time context features. They must use the previous session's
data and may not incorporate any future portion of the research date.

### 10.3 Activity

- cumulative volume, dollar volume and trades;
- active bars and staleness;
- last-five- and last-15-minute activity;
- late-premarket share of total activity;
- own-history volume and dollar-volume surprise;
- volume velocity and acceleration.

### 10.4 Premarket structure

- premarket high and low;
- range percentage;
- latest-price position within the range;
- drawdown from the premarket high;
- time since the premarket high;
- new-high count and frequency;
- higher-high and higher-low evidence;
- maximum pullback and subsequent recovery;
- VWAP distance and retention;
- volatility expansion and possible consolidation near highs.

For a non-zero range:

`range_position = (latest_price - premarket_low) / (premarket_high - premarket_low)`

For a zero range, `range_position = 0.5` and a zero-range flag is set.

`drawdown_from_high = latest_price / premarket_high - 1`

`latest_vs_vwap = latest_price / cumulative_vwap - 1`

### 10.5 Opening confirmation at 09:45 and 10:00 ET

Only eligible completed regular-session bars may contribute:

- open-to-decision return;
- opening range and range position;
- opening volume, dollar volume and trades;
- opening VWAP relationship;
- drawdown from opening high;
- recovery from opening low;
- opening new-high count;
- price relative to the known premarket high;
- retention or loss of premarket VWAP/high structure;
- change in rank and evidence profile from the previous decision.

### 10.6 Feature direction and versioning

Every scored feature shall define whether higher or lower values represent the
positive direction. Feature definitions, units, windows, missing-data policy
and code version shall be frozen together.

## 11. Ranking and explanations

### 11.1 Evidence profiles

The engine shall keep three concepts separate:

1. `emergence_profile`: own-history surprise and acceleration;
2. `momentum_quality_profile`: positive path, persistence and structure;
3. `execution_risk_profile`: liquidity, staleness, spread and volatility risk.

An execution-risk flag must not rewrite the discovery evidence or erase the
candidate from retrospective recall analysis.

### 11.2 Research rankings

The engine may output several versioned rankings in parallel:

- simple gap baseline;
- dollar-volume baseline;
- abnormal-activity baseline;
- emergence profile rank;
- momentum-quality profile rank;
- transparent composite research rank.

The current equal-weight percentile composite remains a research baseline, not
an approved production formula. New weights must not be selected from the same
dates used to report final performance.

Within-date percentile components may be used for transparent comparison, but
the engine must also preserve raw values and own-history anomalies. This avoids
making the result depend exclusively on cross-sectional extremes.

### 11.3 Missing score components

Missing components shall be excluded from the arithmetic mean and shall lower
`feature_coverage`. They must not be silently replaced by a neutral percentile.
If all required components for a model are missing, its score and rank are
missing for that symbol.

### 11.4 Deterministic explanations

Every ranked row shall include:

- discovery channels hit;
- the strongest positive measurements;
- deterioration or risk flags;
- missing-data and baseline warnings;
- feature coverage;
- current and previous-decision ranks where available.

Initial reason codes may include:

- `POSITIVE_GAP`;
- `ABNORMAL_DOLLAR_ACTIVITY`;
- `DORMANT_TO_ACTIVE`;
- `LATE_VOLUME_SURGE`;
- `POSITIVE_PRICE_ACCELERATION`;
- `NEAR_PREMARKET_HIGH`;
- `ABOVE_PREMARKET_VWAP`;
- `OPENING_CONFIRMATION`;
- `OPENING_FAILURE`;
- `STALE_LAST_PRINT`;
- `THIN_ACTIVITY`;
- `INSUFFICIENT_BASELINE`.

These explanations are deterministic descriptions, not LLM-generated advice.

## 12. Output contracts

Each run shall write immutable or reproducibly replaceable versioned outputs.
Preferred tabular storage is compressed Parquet, with JSON for manifests and
small downstream interfaces.

Minimum artifacts are:

- `run-manifest.json`;
- `universe.parquet`;
- `broad-features.parquet`;
- `channel-hits.parquet`;
- `candidate-features.parquet`;
- separate rankings for 09:30, 09:45 and 10:00 ET;
- `ranking-explanations.json`;
- separately generated retrospective outcomes;
- API and cache-usage summary;
- data-quality report.

Every ranking row shall contain at minimum:

- session, symbol and decision identifiers;
- rank and score-model version;
- raw feature references or values;
- feature coverage;
- channel membership;
- deterministic reason codes;
- data-quality and execution-risk flags;
- universe version and content hash;
- feed, delay and information cutoff;
- `research_only: true` and `orders_supported: false`.

Future outcomes must not be present in the point-in-time ranking artifact.

## 13. Truth sets and retrospective outcomes

The research must distinguish two outcome families.

### 13.1 Eventual extreme-gainer outcome

Using whole-market daily/reference data, measure:

`previous_close_to_regular_high = regular_session_high / previous_official_close - 1`

Report continuous values and sensitivity bands at +30%, +50%, +80% and +100%.
These bands are evaluation labels, not candidate filters.

### 13.2 Remaining-opportunity outcome

For each fixed decision benchmark, retain:

- returns after 5, 15, 30, 60 and 120 minutes;
- return to noon and close;
- maximum favourable excursion (MFE);
- maximum adverse excursion (MAE);
- time to MFE and MAE;
- whether a new high occurred after the decision;
- high-to-close giveback;
- documented failure modes.

A stock can be an eventual extreme gainer while offering little remaining
movement at a later decision. Conversely, a useful post-decision move does not
require the stock to finish in an extreme full-day band.

### 13.3 Benchmark-price limitation

The first bar at or after a decision may remain a reproducible optimistic
benchmark. It must not be described as an achievable fill. Quote, spread,
auction and documented slippage inputs are required before execution-level or
profitability conclusions.

## 14. Evaluation methodology

### 14.1 Population

Market-wide recall and precision require:

- a universe captured independently of future winners;
- broad discovery inputs for that universe;
- whole-market eventual-gainer labels;
- ordinary candidates and failures, not winners alone.

Screenshot-derived symbol lists can support case studies but cannot estimate
market-wide performance.

### 14.2 Primary metrics

For each decision and ranking model, report:

- recall of eventual extreme gainers;
- precision at fixed k;
- candidate and alert burden;
- detection lead time;
- gain already completed at first detection;
- remaining move after detection;
- rank association with continuous outcomes;
- MFE, MAE and forward-return distributions;
- false-positive and missed-runner reasons;
- data-quality and baseline coverage.

### 14.3 Baseline comparisons

Every composite or learned model shall be compared with at least:

- positive-gap rank;
- absolute-volume rank;
- dollar-volume rank;
- premarket-high-proximity rank;
- own-history abnormal-activity rank.

Complexity is justified only if it improves held-out performance or materially
reduces alert burden without unacceptable recall loss.

### 14.4 Date separation

Validation shall use chronological expanding-window tests:

1. choose features, models or budgets using earlier dates;
2. freeze them;
3. evaluate on the next unseen date or block of dates;
4. record the result before making revisions.

Leave-one-date-out analysis may describe stability but must not replace
chronological validation. Symbols from one date must not be split between
training and validation as if they were independent future sessions.

### 14.5 Sample size and regimes

The six currently selected sessions are pipeline-validation and hypothesis-
generation data. They are insufficient for production thresholds or claims.
The next research collection should expand toward at least 40-60 additional
sessions covering different volatility, catalyst and market-breadth regimes.

## 15. Screenshot-labelled behavioural reconstruction

The user's original Revolut screenshot study is a primary historical-research
track and the starting point for candidate-pattern hypotheses. It is not
replaced by market-wide discovery.

For every available screenshot date, the research shall:

1. preserve the actual screenshot timestamp and intended checkpoint;
2. transcribe the complete displayed list while separately identifying
   US-traded research symbols and excluded instruments;
3. record rank, displayed price/change and first/last observed membership;
4. construct the union of premarket-observed, post-open-only and selected
   control symbols without relabelling missing checkpoints;
5. collect authoritative Alpaca one-minute bars for the previous close,
   previous after-hours session, current premarket and current regular session
   where available;
6. reconstruct each symbol's point-in-time price, activity and structure path;
7. assign descriptive pattern families without treating them as buy rules;
8. compare recurring patterns with similar premarket cases that failed;
9. use those comparisons to propose features for later market-wide validation.

Initial descriptive pattern families include:

- late premarket accelerator;
- persistent premarket leader;
- dormant-to-active transition;
- early spike and deep fade;
- pullback and recovery;
- opening continuation;
- opening failure;
- opening reversal;
- no observable premarket signal.

Pattern assignment must retain the underlying continuous features and reason
codes. It must not substitute subjective labels for quantitative analysis.

### 15.1 Relationship to the future scanner

Revolut screenshots identify important historical cases to study. Alpaca bars
provide the authoritative quantitative reconstruction. The resulting
hypotheses are then tested against independently constructed candidates and
whole-market outcomes.

The future engine must discover candidates without using Revolut membership,
rank or displayed percentage as an input. Otherwise it could reproduce a
third-party top-gainers list but could not demonstrate independent early
detection.

### 15.2 Independent comparison

After an engine ranking has been frozen, Revolut observations may also assess:

- whether an engine candidate appeared in the independently observed list;
- timing and persistence of appearance;
- selected case-study misses;
- qualitative agreement or disagreement.

Screenshot-derived lists must not be presented as a complete market-wide
universe or used alone to estimate market-wide precision and recall.

## 16. Storage, caching and API accounting

### 16.1 Proposed storage

The initial preferred design is:

- compressed Parquet for bars, baselines, features and outcomes;
- DuckDB for cross-date local research queries;
- JSON manifests for provenance, versions and API usage.

This choice shall be confirmed after the broad-universe pilot measures data
volume and query patterns.

### 16.2 Cache identity

Cache keys shall include, where relevant:

- source and endpoint;
- feed;
- symbols or universe hash;
- time window;
- timeframe;
- adjustment mode;
- request parameters;
- collector/schema version.

Incomplete or failed downloads must never be marked as valid cache hits.

### 16.3 API summary

Every run shall report:

- calls and pages by endpoint;
- attempts, retries and failures;
- rate-limit headers where safely available;
- symbols requested and returned;
- bars requested or returned where measurable;
- bytes and runtime where practical;
- cache hits and misses;
- candidate counts at each funnel stage.

Credentials must never appear in requests saved to disk, logs, exceptions,
metadata or committed files.

## 17. Failure behaviour

The engine shall fail closed for invalid research state. It must not publish a
normal-looking ranking when:

- the universe snapshot is absent or mismatched;
- timestamps cannot be interpreted safely;
- the requested feed or delay mode is unknown;
- required reference data are stale or inconsistent;
- collection is incomplete beyond an approved tolerance;
- feature or protocol versions are incompatible;
- future outcome columns are detected in ranking inputs.

Partial but usable runs may be emitted only with explicit completeness and
quality warnings at both run and symbol level.

## 18. Testing requirements

The shared engine shall include tests for:

1. post-decision mutation invariance: changing future bars cannot change an
   earlier feature or rank;
2. exact completed-bar and configured-delay boundaries;
3. 09:30 exclusion of all regular-session bars;
4. 09:45 and 10:00 inclusion of only eligible completed opening bars;
5. New York and London daylight-saving transition weeks;
6. duplicate bars and out-of-order pagination;
7. no-trade periods versus genuinely missing data;
8. corporate actions and false-gap prevention;
9. insufficient historical baseline handling;
10. zero-denominator and extreme low-volume robustness;
11. low-priced symbols remaining in discovery;
12. candidate union deduplication and channel attribution;
13. output separation between rankings and outcomes;
14. deterministic results from identical inputs and protocol versions;
15. absence of broker-order capabilities and credential leakage.

A small synthetic golden dataset should exercise a dormant-to-active runner,
an already-extended mover, a stale thin print, a premarket fade, an opening
reversal and a symbol with no premarket activity.

## 19. Implementation sequence

Implementation shall proceed incrementally:

### Phase A - Specification and broad-data pilot

- approve this specification;
- resolve stale documentation references to premarket entry;
- inventory every available Revolut screenshot date and checkpoint;
- identify which screenshot dates already have complete one-minute Alpaca data
  and which still require transcription or collection;
- run and preserve the screenshot-labelled behavioural reconstruction before
  treating its observed patterns as reusable hypotheses;
- verify current Alpaca feed entitlements and timing behaviour;
- collect one broad-universe five-minute pilot session;
- report pages, data volume, runtime, failures and coverage;
- confirm or revise the broad-pass interval and storage choice.

### Phase B - Shared deterministic core

- extract shared time, loading, feature and outcome logic from the two current
  ranking/analysis scripts;
- preserve current output behaviour through regression tests;
- remove inconsistent duplicate missing-data and scoring policies.

### Phase C - Reference and baseline data

- add previous official close and corporate-action handling;
- build point-in-time historical time-bucket baselines;
- version baseline inputs and completeness.

### Phase D - Market-wide discovery replay

- implement broad features and parallel discovery channels;
- persist the candidate union and reason codes;
- calculate one-minute candidate-detail features;
- produce the three fixed rankings and separate outcomes.

### Phase E - Expanded historical validation

- collect a larger date-separated sample;
- freeze protocols before later-date evaluation;
- compare discovery budgets and simple baselines;
- analyse misses, false positives, latency and feed sensitivity.

### Phase F - Live observation

- run the frozen engine without orders;
- preserve every point-in-time input and alert;
- evaluate at least 20-30 additional forward sessions before considering any
  paper-trading research.

## 20. Explicitly deferred work

The following are not part of the initial implementation:

- live or paper order submission;
- exits and trade management;
- direct `trading-agent` integration;
- profitability claims;
- LLM-based numerical ranking;
- market-wide news polling;
- catalyst-based ranking weights;
- float rotation without a reliable historical source;
- short-interest features;
- inferred spread from candle range;
- opening-auction or slippage models without suitable data;
- a dashboard or user interface before the research pipeline is stable.

## 21. Decisions still requiring approval or evidence

The following are deliberately unresolved:

1. Final broad-pass timeframe after the one-session pilot.
2. Exact per-channel candidate budgets.
3. Final historical baseline window and minimum coverage.
4. Security-type exclusions, if any.
5. Final feature membership, weights and thresholds.
6. Whether the final user-facing result should emphasize one composite rank or
   multiple evidence-profile ranks.
7. Acceptable recall, precision and alert burden for live observation.
8. Exact live data mode and whether real-time consolidated SIP is required.
9. Authoritative quote, float and catalyst sources for later phases.
10. Conservative fill and slippage modelling after discovery validation.

## 22. Approval gates

No stage implies approval of the next stage.

- Approving this specification permits the broad-data pilot and incremental
  research-engine implementation only.
- Historical results must be reviewed before live observation.
- Live observation results must be reviewed before paper-trading research.
- Paper research must be reviewed before any integration proposal.
- Integration with `trading-agent` or order capability always requires
  separate explicit approval.
