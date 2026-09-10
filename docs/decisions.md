# Decision Log

This document records agreed project direction. Candidate features and ideas are not decisions unless stated here.

## 24 July 2026

### Project boundary

- Use the standalone public repository `battersea-dynamics/gainers-spotting`.
- Keep `battersea-dynamics/trading-agent` untouched.
- Keep the premarket Gainers Spotting system separate from the existing day-session system during development.
- Consider integration only in a later phase after independent validation and explicit approval.
- Do not implement selling or exit logic in the current Gainers Spotting phase. Post-open data is used for evaluation, not for development of the selling system.

### Objective and scope

- Focus on early identification of U.S.-traded stocks during premarket that may become significant gainers during the upcoming regular session.
- The practical objective is to identify useful candidates early enough that a future actionable purchase could potentially occur before the major regular-session move, not merely to predict final top gainers.
- Begin with U.S. equities and premarket research.
- Treat the project as research/observation software; do not place live orders.
- Separate broad discovery from later trading or execution eligibility.
- Prefer evidence of emerging acceleration over merely sorting stocks by gains already completed.
- Include monitoring of candidate evolution and final pre-open candidate selection within the research scope.
- Research the appropriate entry mechanism without assuming one in advance.

### Entry research

- Compare premarket-entry and opening-entry approaches historically before choosing an entry approach.
- Do not assume displayed or last premarket prices are achievable fills.
- Do not automatically treat the official opening print as an achievable trading fill.
- Evaluate both candidate quality and the point at which evidence becomes actionable while meaningful upside may remain.

### Research

- Derive thresholds, weights and ranking logic from multi-day evidence.
- Include false positives, missed runners and controls alongside winners.
- Treat stocks that become major regular-session gainers but were not selected premarket as a required missed-runner comparison group.
- Avoid look-ahead bias and represent data latency at the actionable timestamp.
- Evaluate detection lead time and remaining move, not only final classification.
- Use post-open data to evaluate whether premarket selections created useful opportunities, without turning that analysis into exit-system development.
- Reconstruct retained candidates, eventual winners and selected controls with one-minute data where available, including relevant premarket and regular-session behaviour.
- Treat the 24 July 2026 manual movers screenshots as exploratory observational evidence only, not authoritative quantitative market data or proof of predictive features.

### Data and cost

- Use Alpaca as the initial quantitative source.
- Accept 15-minute-delayed SIP initially and test its practical effect.
- Batch requests, cache reusable data and measure API consumption.
- Use Finnhub selectively after candidate reduction if its limits are suitable.
- Do deterministic calculations locally in Python.
- Do not automatically reuse the existing day scanner's Gemini model; Gainers Spotting model selection remains an independent architecture decision.
- Do not use Reddit as authoritative market data.
- Do not base the collector on automated third-party website scraping.

### Development

- Implement incrementally after architecture and data requirements are approved.
- Begin with historical research, then observation-mode forward testing.
- Consider paper-trading research only if results justify it.
- Do not begin substantial scanner implementation until the proposed research architecture, API-budget strategy and historical entry-comparison methodology have been presented and approved.

## Background requiring independent verification

A supplied project draft describes the existing `trading-agent` scanner and its filters. Those descriptions may inform future comparison but are not treated as verified facts in this repository unless its code is separately inspected with permission.

## 9 September 2026

### Engine specification v1

- Approve `docs/engine-spec-v1.md` as the implementation blueprint for the next research phase.
- Preserve the original Revolut screenshot study as a primary historical pattern-discovery track.
- Use Alpaca one-minute bars, rather than screenshot percentages, to reconstruct the authoritative behaviour of screenshot-observed top gainers, controls, fades and missed runners.
- Include previous official close and previous-session 16:00-20:00 ET after-hours context for retained symbols where reliable data are available.
- Use patterns observed in screenshot-labelled cases as hypotheses, then test them against independent failures, controls and whole-market outcomes.
- Keep Revolut membership, rank and displayed percentage outside the future engine's candidate and ranking inputs.
- Limit v1 entry research to the fixed 09:30, 09:45 and 10:00 ET benchmarks; premarket order entry is outside the current engine phase.
- Use a two-stage, API-efficient market-wide discovery funnel with multiple candidate channels rather than one `gap x volume` gateway.
- Record explicit feed, delay, completed-bar boundaries and information cutoffs for every historical or observation-mode ranking.
- Keep emergence evidence, momentum quality and execution risk separately observable.
- Do not choose final channel budgets, feature weights or trading thresholds until later-date evidence supports them.

## 10 September 2026

### Prior-session context implementation

- Collect raw-adjusted daily history ending before each research date and the
  immediately preceding US session's 16:00-20:00 ET one-minute bars.
- Derive the previous session from returned daily market data instead of
  guessing around weekends and exchange holidays.
- Preserve descriptive raw gaps but leave verified true-gap fields missing
  while corporate-action information is unavailable or a symbol is affected.
- Add exact 20-, 60- and 120-session dormancy windows. Do not silently shorten
  a window when history is insufficient.
- Keep all new context features outside ranking weights until the authenticated
  collection has completed and later-date validation supports their use.
