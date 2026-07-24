# Decision Log

This document records agreed project direction. Candidate features and ideas are not decisions unless stated here.

## 24 July 2026

### Project boundary

- Use the standalone public repository `battersea-dynamics/gainers-spotting`.
- Keep `battersea-dynamics/trading-agent` untouched.
- Consider integration only in a later phase after independent validation and explicit approval.

### Objective and scope

- Focus on early identification of potential exceptional daily gainers.
- Begin with US equities and premarket research.
- Treat the project as research/observation software; do not place live orders.
- Separate broad discovery from later trading or execution eligibility.
- Prefer evidence of emerging acceleration over merely sorting stocks by gains already completed.

### Research

- Derive thresholds, weights and ranking logic from multi-day evidence.
- Include false positives, missed runners and controls alongside winners.
- Avoid look-ahead bias and represent data latency at the actionable timestamp.
- Evaluate detection lead time and remaining move, not only final classification.

### Data and cost

- Use Alpaca as the initial quantitative source.
- Accept 15-minute-delayed SIP initially and test its practical effect.
- Batch requests, cache reusable data and measure API consumption.
- Use Finnhub selectively after candidate reduction if its limits are suitable.
- Do deterministic calculations locally in Python.
- Do not use Reddit as authoritative market data.
- Do not base the collector on automated third-party website scraping.

### Development

- Implement incrementally after architecture and data requirements are approved.
- Begin with historical research, then observation-mode forward testing.
- Consider paper-trading research only if results justify it.

## Background requiring independent verification

A supplied project draft describes the existing `trading-agent` scanner and its filters. Those descriptions may inform future comparison but are not treated as verified facts in this repository unless its code is separately inspected with permission.
