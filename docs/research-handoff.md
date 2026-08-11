# Research handoff and continuity

Read this document first when resuming the project in a new chat. It is the durable source of truth for the research scope, decisions, data status, and next actions. Update it whenever the methodology or project state materially changes.

Last updated: 2026-08-11

## Mission

Build and validate a research-only premarket stock-selection process that produces a short, ranked list of US stocks for possible entry at the regular-market open, 15 minutes after the open, or 30 minutes after the open.

This repository covers candidate discovery and the premarket-to-open research only. Intraday trade management belongs to the separate trading-agent project.

## Non-negotiable boundaries

- Work only in `battersea-dynamics/gainers-spotting`.
- Do not modify `battersea-dynamics/trading-agent`.
- Do not implement, simulate through a broker, or submit orders.
- Read Alpaca credentials only from existing environment variables or GitHub secrets.
- Never print, expose, save, or commit credentials.
- Historical collection uses paginated 1-minute SIP bars for 04:00–16:00 America/New_York time.
- Preserve raw responses, cleaned machine-readable data, and collection metadata.
- Do not invent scanner thresholds or trading rules. Treat all proposed signals as hypotheses to test.
- Do not automatically exclude very low-priced stocks. Price and liquidity may be features or risk flags, but a hard price floor would have hidden cases such as LVWR.
- Revolut screenshots are observational labels and discovery evidence, not an input required by the eventual scanner.

## What is already implemented

The repository contains a reusable historical Alpaca collector and analysis pipeline, including:

- `.github/workflows/collect-historical-alpaca.yml`
- `.github/workflows/collect-observed-week.yml`
- `scripts/collect_alpaca_bars.py`
- `scripts/analyze_historical_session.py`
- `tests/test_collect_alpaca_bars.py`
- `tests/test_analyze_historical_session.py`
- `docs/premarket-open-research-plan.md`
- `docs/preliminary-week-findings.md`
- date-specific universes under `config/research-universes/`

The multi-date research pipeline was committed as `2cded70` (`Add multi-date premarket research pipeline`). GitHub Actions run `30696226390` completed successfully for 2026-07-27 through 2026-07-31.

## Data status and source quality

### Alpaca market data

- 2026-07-24 was the original historical collection date.
- The observed-week workflow collected 2026-07-27, 2026-07-28, 2026-07-29, 2026-07-30, and 2026-07-31.
- The user downloaded those artifacts into `data/research/YYYY-MM-DD/` in the local Windows clone.
- Alpaca bars are the authoritative source for timestamps, OHLC, volume, trade count, and VWAP for the requested feed and window.
- Each date must be checked through its metadata for requested symbols, successful symbols, failures, pages, feed, time window, and request timestamps.
- Generated market data should remain excluded from Git unless a small derived research artifact is intentionally committed.

### Screenshot observations

- Revolut Top Movers screenshots provide approximate observed rankings, displayed prices, and displayed percentage gains at specific checkpoints.
- The screenshots include non-US securities and leveraged ETPs. Retain these in raw transcription, but mark them separately and exclude them from US-Alpaca evaluation when appropriate.
- Always record the actual phone timestamp, intended checkpoint, and delay. Never silently relabel a delayed screenshot as on-time.
- Missing checkpoints remain missing; do not interpolate their rankings.
- Screenshot percentages may use a reference price that differs from the research definition. They are useful labels, not exact market bars.

Latest visible checkpoint at this handoff: Tuesday 2026-08-11 at 09:49 UK, intended for 09:15 UK and therefore 34 minutes late. Its transcription is expected under `data/research/observations/2026-08-11/09-49-uk.json`.

## Research question

Using only information available before each decision time, which premarket characteristics help identify stocks likely to offer favorable returns from:

- the 09:30 ET regular-market open;
- 09:45 ET, after the first 15 minutes; or
- 10:00 ET, after the first 30 minutes?

The target is not simply the largest end-of-day gainer. For every candidate and entry time, measure forward return as well as maximum favorable excursion and maximum adverse excursion over clearly defined horizons.

## Candidate features to evaluate

These are hypotheses, not fixed filters:

- percentage gap from the prior regular-session close;
- premarket share volume and dollar volume;
- volume relative to comparable historical premarket windows;
- premarket high-low range and realized volatility;
- position within the premarket range;
- price relative to premarket VWAP and VWAP slope;
- early-versus-late premarket momentum;
- persistence or acceleration across premarket sub-windows;
- distance from the premarket high immediately before the open;
- liquidity indicators, price, trade count, and bar completeness;
- opening confirmation during the first 15 or 30 minutes for delayed-entry variants.

Low price alone is not a rejection rule. Any liquidity or price constraint must be evaluated for both recall lost and execution risk reduced.

## Evaluation rules

- Pool all eligible dates for descriptive analysis; do not treat 2026-07-24 as the permanent comparison baseline.
- Keep dates separated for validation so the same day cannot appear in both training and testing.
- Compute every feature using only bars available at the relevant decision timestamp.
- Use prior-session data only when it would genuinely have been available then.
- Compare proposed scores with simple baselines such as ranking by premarket gap or dollar volume.
- Report top-k recall, precision, rank quality, entry returns, maximum favorable excursion, maximum adverse excursion, and failure cases.
- Show results separately for entry at the open, +15 minutes, and +30 minutes.
- Keep controls and non-winners. A winners-only dataset cannot estimate false-positive rates.
- Freeze candidate logic before evaluating it on later, unseen dates.
- Treat findings from the small current sample as provisional rather than predictive proof.

## Screenshot protocol (UK time)

| Intended time | Research role |
|---|---|
| 09:15 | Early premarket discovery |
| 11:00 | Mid-premarket persistence |
| 13:00 | Late premarket development |
| 14:00 | Approximately 30 minutes before the US open |
| 14:30–14:35 | Open / immediate post-open observation |
| 15:00 | Approximately 30 minutes after the open |
| 17:00 | Intraday outcome checkpoint |
| 23:00 | End-of-day / after-hours reference |

Phone timestamps are authoritative. If the screenshot is late, store the real time and intended checkpoint separately.

## Known limitations

- Revolut's displayed universe and ranking methodology create selection bias and are not the future scanner universe.
- Some days have incomplete or delayed screenshots.
- A screenshot-derived symbol union is useful for case study analysis but is not a complete negative sample.
- A production-quality study needs a broader eligible US-stock universe or a reproducible daily candidate universe created without looking at later winners.
- Corporate actions, symbol changes, news catalysts, halts, and adjusted historical prices can distort naive comparisons and should be flagged where possible.
- SIP bars describe trades but do not guarantee executable fills at the displayed OHLC prices.

## Next actions

1. Finish transcribing each screenshot checkpoint into dated machine-readable observation files.
2. Build the per-date US symbol universe from observed names plus controls, while preserving non-US observations separately.
3. Collect and validate Alpaca SIP bars for every observed date, not only 2026-07-24.
4. Inspect every metadata file and resolve or document symbol failures.
5. Generate one time-safe feature-and-outcome table with rows keyed by date, symbol, and decision time.
6. Run collective descriptive analysis across dates and compare winners with controls/non-winners.
7. Propose a small number of candidate ranking models, freeze them, and test on later unseen dates.
8. Only after validation, design the stock-picker output. Keep it research-only and order-free.

## New-chat bootstrap prompt

Copy this into a fresh chat:

> Work only in `battersea-dynamics/gainers-spotting`. First read `docs/research-handoff.md`, `docs/premarket-open-research-plan.md`, `docs/preliminary-week-findings.md`, and inspect Git status before acting. Continue the research-only premarket/open pipeline from the documented state. Do not modify `trading-agent`, place or implement orders, expose credentials, invent thresholds, or use future data in features. Use Revolut screenshots only as observational labels; use Alpaca SIP bars as the authoritative market data. Analyze all dates collectively with date-separated validation. Tell me the verified current status and the next safe action before making material changes.

## Maintenance rule

After any meaningful collection, analysis, methodology decision, or pipeline change, update this document's date, data status, verified findings, and next actions in the same commit. Keep detailed outputs in dated research files and keep this document concise enough to read at the start of every new chat.
