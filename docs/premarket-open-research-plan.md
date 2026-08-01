# Premarket selection and opening-entry research plan

## Scope

`gainers-spotting` has one purpose: identify U.S.-traded stocks before the
regular-session open that may offer a useful long entry at one of three fixed
decision times:

- 09:30 ET — market open;
- 09:45 ET — 15 minutes after open;
- 10:00 ET — 30 minutes after open.

The project does not develop intraday exits, position management, later
day-trading decisions or order submission. Those responsibilities belong to a
separate project. Post-entry data is used here only to label whether a selected
stock subsequently offered favourable or adverse movement.

No scanner cutoff, buy rule or profitability claim may be derived from one
session or selected after inspecting the final outcomes. The first multi-date
study is exploratory and must freeze feature definitions before comparing
dates.

## What the current data can establish

### Authoritative quantitative data

The 24 July dataset contains 15,090 Alpaca SIP one-minute bars for 44 supplied
symbols from 04:00 through 16:00 ET. It supports exact candle, price, volume,
trade-count and VWAP calculations for that supplied universe.

### Structured observational data

The 27–31 July checkpoint files preserve the manually observed Revolut Top
Movers lists, timestamps, ranks, displayed prices, displayed changes and list
membership. They can support analysis of:

- when a symbol first appeared;
- persistence across premarket checkpoints;
- rank and displayed-change development within premarket;
- whether a symbol was still present in later Top Movers observations;
- candidates seen before the open versus movers first seen after the open.

Screenshots cannot provide authoritative candles, consolidated volume,
previous official close, bid/ask spread, achievable fills or exact returns from
09:30, 09:45 or 10:00 ET. Those measurements require historical market data.

### Sampling limitation

Revolut Top Movers is a selected list, not a documented market-wide eligible
universe. The week can compare observed premarket candidates with observed
later movers and candidate fades. It cannot yet estimate true market-wide
precision, false-positive rate or recall against every U.S. stock.

## Evidence informing the design

1. Pre-open trading can contribute to a more efficient opening price, but the
   effect depends strongly on the amount of pre-open trading. Barclay and
   Hendershott found price discovery shifted into the Nasdaq pre-open mainly
   for the highest-volume stocks. Therefore volume must be paired with price
   response, dollar activity and continuity; raw volume alone is not treated
   as a sufficient signal.
   <https://doi.org/10.1016/j.jempfin.2008.03.001>

2. The pre-open contains genuine price-discovery information, but market
   mechanisms and quotes matter. Cao, Ghysels and Hatheway documented Nasdaq
   preopening price discovery even before continuous trading. This supports
   measuring the timing and evolution of the premarket path rather than using
   only one final gap percentage.
   <https://doi.org/10.1111/0022-1082.00249>

3. Opening prices are formed through concentrated liquidity and auction/order
   imbalance processes. NYSE begins opening-imbalance publication before the
   auction and describes paired quantity, imbalance quantity and clearing
   price as price-discovery information. These fields would be valuable future
   inputs, but they are not present in Alpaca minute bars and must not be
   inferred from candles.
   <https://www.nyse.com/data-insights/nyse-introduces-the-enhanced-nyse-auction-tool-with-opening-imbalance-history>

4. Transitory volatility is typically greatest near the open and declines
   through the day. This makes separate 09:30, 09:45 and 10:00 ET experiments
   preferable to assuming the opening print is always the best entry.
   <https://doi.org/10.1093/rfs/7.3.609>

5. Extended-hours markets have lower liquidity, wider spreads, higher
   volatility and prices that may not carry into the regular-session open.
   Consequently, a premarket last trade is not treated as an achievable
   opening fill, and minute-bar entry prices remain research benchmarks rather
   than execution claims.
   <https://www.finra.org/rules-guidance/rulebooks/finra-rules/2265>

6. Overnight and intraday return signals are not interchangeable. Recent
   long-horizon evidence finds momentum in past intraday-return components but
   not in past overnight-return components. The study will therefore keep
   previous-close gap, premarket path and post-open confirmation as separate
   features rather than collapsing them into one momentum number.
   <https://doi.org/10.1093/rfs/hhag036>

## Candidate population and labels

For each date, construct non-overlapping groups using timestamped information:

1. `premarket_observed` — U.S.-research symbols present in at least one
   checkpoint before 09:30 ET;
2. `post_open_only_observed` — symbols absent before 09:30 ET but present in a
   later same-date Top Movers checkpoint;
3. `premarket_fade` — a premarket-observed symbol whose authoritative
   post-open path weakens;
4. `premarket_continuation` — a premarket-observed symbol whose authoritative
   post-open path continues;
5. `not_observable_premarket` — a later mover with no meaningful premarket
   trades or information in the collected SIP data.

`premarket_fade` and `premarket_continuation` remain descriptive families until
continuous outcome measurements have been inspected across dates. Numerical
boundaries must not be invented in advance merely to force binary labels.

## Features available at 09:30 ET

All calculations must stop before the decision timestamp.

### Price and gap

- official previous close to first, last and high premarket price;
- first-to-last premarket return;
- premarket high and low excursion;
- last price's location within the premarket range;
- drawdown from premarket high;
- last premarket price to regular-session opening benchmark.

The true gap requires the previous official close, which is not yet part of the
current minute-bar files and must be collected separately.

### Timing and path

- returns over 04:00–06:00, 06:00–08:00, 08:00–09:00 and 09:00–09:30 ET;
- rolling 5-, 15- and 30-minute price change;
- price velocity and acceleration;
- time of premarket high and low;
- number and timing of new highs;
- higher-high/higher-low counts;
- pullback depth, recovery amount and time since recovery;
- consolidation duration and range compression after an impulse.

### Activity and liquidity proxies

- active one-minute bars;
- shares, trades and dollar volume by premarket segment;
- late-premarket share of total volume;
- rolling volume and dollar-volume acceleration;
- price movement per dollar volume as an illiquidity warning;
- VWAP distance and VWAP recovery/retention.

Raw bars do not provide bid/ask spread, depth or guaranteed fill quality.

### Cross-sectional and observational features

- rank within the date-specific research universe;
- first Revolut appearance time and rank;
- number of premarket checkpoint appearances;
- rank improvement or deterioration;
- displayed-change development within premarket;
- price as a continuous feature.

Very low-priced stocks are retained. Price may help describe behaviour and
execution risk, but it is not an automatic exclusion; LVWR is the frozen
counterexample.

## Additional features at 09:45 and 10:00 ET

The later decisions may use only regular-session bars already completed by the
decision time:

- open-to-decision return;
- opening range high, low and location;
- retention of the premarket high/low/VWAP structure;
- first-15-minute or first-30-minute volume and dollar volume;
- volume continuation versus immediate collapse;
- maximum pullback from the opening high;
- recovery after the opening pullback;
- higher-high/higher-low structure since the open;
- new-high count and time since latest high.

These features test whether waiting supplies useful confirmation. Results must
also record the upside already lost by waiting.

## Entry benchmarks and outcomes

Use three separate benchmark entries, never one retrospectively selected
entry:

- first eligible regular-session bar at or after 09:30 ET;
- first eligible bar at or after 09:45 ET;
- first eligible bar at or after 10:00 ET.

For every entry benchmark, retain continuous outcomes rather than an invented
success threshold:

- forward return after 5, 15, 30, 60 and 120 minutes;
- return to noon and close;
- maximum favourable excursion after entry;
- maximum adverse excursion after entry;
- time to subsequent high and low;
- subsequent high relative to premarket high;
- high-to-close giveback.

The minute-bar open is a reproducible benchmark, not a claim that a market
order would have filled at that price. Quote/spread data and a documented
slippage model are required before execution-level conclusions.

## Pattern-search sequence

1. Reproduce the 24 July calculations under the three-entry framework.
2. Build each 27–31 July universe from timestamped checkpoint files.
3. Collect SIP minute bars for the union of premarket-observed and
   post-open-only symbols on each date.
4. Add official previous close for each symbol/date.
5. Validate missing minutes without fabricating zero-volume candles.
6. Calculate the frozen features and continuous outcomes.
7. Compare distributions, rank correlations and effect sizes by date.
8. Use leave-one-date-out checks: discover on four dates and inspect the held
   out date, rotating through all dates.
9. Report patterns that recur, patterns driven by one outlier and patterns that
   fail on later dates.
10. Only after more sessions, test candidate cutoffs on dates not used to
    choose them.

With five screenshot dates plus 24 July, the first result is hypothesis
generation and pipeline validation. It is not a production stock picker.
