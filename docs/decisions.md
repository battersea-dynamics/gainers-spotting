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