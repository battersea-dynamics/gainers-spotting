# Research handoff and continuity

Read this document first when resuming the project in a new chat. It is the durable source of truth for the research scope, decisions, data status, and next actions. Update it whenever the methodology or project state materially changes.

Last updated: 2026-09-09

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
- `scripts/analyze_premarket_open_week.py`
- `scripts/rank_premarket_candidates.py`
- `scripts/build_alpaca_universe.py`
- `scripts/normalize_screenshot_recovery.py`
- `tests/test_collect_alpaca_bars.py`
- `tests/test_analyze_historical_session.py`
- `tests/test_analyze_premarket_open_week.py`
- `tests/test_rank_premarket_candidates.py`
- `tests/test_build_alpaca_universe.py`
- `tests/test_normalize_screenshot_recovery.py`
- `docs/premarket-open-research-plan.md`
- `docs/engine-spec-v1.md`
- `docs/preliminary-week-findings.md`
- date-specific universes under `config/research-universes/`
- normalized Revolut observations under `config/research-observations/`
- frozen evaluation definitions under `config/research-protocol-v1.json`

The multi-date research pipeline was committed as `2cded70` (`Add multi-date premarket research pipeline`). GitHub Actions run `30696226390` completed successfully for 2026-07-27 through 2026-07-31.

The recovered engine implementation adds three strictly point-in-time ranking
decisions, separates ranking features from future outcome files, preserves
version identifiers, compares the composite score with simple baselines,
reports top-5/10/20 utility inside the supplied universe, and performs
chronological expanding-window model checks. The broad-universe builder uses
current Alpaca asset metadata without a price or historical-volume floor and
records the snapshot time and survivorship limitation.

No live scanner is scheduled or running. Existing GitHub workflows are manual
historical data collectors only.

The approved `engine-spec-v1.md` preserves the user's original screenshot-led
research strategy as a primary historical track: use Revolut observations to
identify important top-gainer cases, reconstruct them with authoritative
Alpaca one-minute bars, compare their patterns with failures and missed
runners, and then test those hypotheses through an independent market-wide
discovery engine. The future scanner does not use Revolut as an input.

The specification also adds previous-session after-hours context for retained
symbols, explicit market-data latency and bar-boundary rules, a two-stage
market-wide discovery funnel, historical time-normalised baselines, separate
emergence/momentum/risk profiles, and unambiguous numeric units.

## Data status and source quality

### Alpaca market data

- 2026-07-24 was the original historical collection date.
- The observed-week workflow collected 2026-07-27, 2026-07-28, 2026-07-29, 2026-07-30, and 2026-07-31.
- The user downloaded those artifacts into `data/research/YYYY-MM-DD/` in the local Windows clone.
- Alpaca bars are the authoritative source for timestamps, OHLC, volume, trade count, and VWAP for the requested feed and window.
- Each date must be checked through its metadata for requested symbols, successful symbols, failures, pages, feed, time window, and request timestamps.
- Generated market data should remain excluded from Git unless a small derived research artifact is intentionally committed.

### Screenshot observations

- The recovered archive inventory covers 249 captures, 2,314 visible rows, 89
  grouped checkpoints and 14 dates from 2026-07-27 through 2026-08-14. The
  committed date-level files preserve 585 readable ticker strings and 552
  unreadable-field records.
- The archive contains OCR-derived JSON and inventories, not the original image
  pixels. The source ZIP remains outside Git.
- Revolut Top Movers observations provide per-capture visible positions,
  displayed prices, and displayed percentage gains at specific actual times.
  Numeric global ranks cannot be reconstructed safely from overlapping
  scrolling captures and are not inferred.
- The screenshots include non-US securities and leveraged ETPs. Retain these in raw transcription, but mark them separately and exclude them from US-Alpaca evaluation when appropriate.
- Actual UK phone timestamps are preserved. Intended checkpoint times were not
  recoverable from the archive, so they remain null rather than being inferred;
  consequently, capture delay cannot yet be calculated.
- Missing checkpoints remain missing; do not interpolate their rankings.
- Screenshot percentages may use a reference price that differs from the research definition. They are useful labels, not exact market bars.
- Existing reviewed universes for 2026-07-27 through 2026-07-31 were preserved.
  New August universe manifests are provisional collection inputs. Dollar-price
  display is not proof of Alpaca eligibility; validate against dated assets and
  the collector's successful-symbol/failure metadata before analysis.

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

1. Validate the provisional August symbols with a dated Alpaca asset snapshot
   where available and historical one-minute bar success/failure metadata.
2. Collect the missing Alpaca one-minute datasets for 2026-08-03 through
   2026-08-14 and retain their metadata locally.
3. Run the approved screenshot-labelled behavioural reconstruction across all
   dates with usable bars, preserving controls and missing observations.
4. Add previous official close, corporate-action checks and previous-session 16:00-20:00 ET after-hours context for retained symbols.
5. Verify current Alpaca feed entitlements and run a one-session broad-universe five-minute data-volume pilot.
6. Consolidate the duplicated feature calculations before extending the ranking models.
7. Build historical, time-normalised activity baselines using only earlier sessions.
8. Implement the independent multi-channel discovery funnel and retain whole-market controls.
9. Expand historical validation beyond the selected screenshot sessions before choosing thresholds or weights.
10. Add quote-derived spread, catalyst tagging, float data and regime analysis only when reliable data justify them; keep the project order-free.

## New-chat bootstrap prompt

Copy this into a fresh chat:

> Work only in `battersea-dynamics/gainers-spotting`. First read `docs/research-handoff.md`, `docs/engine-spec-v1.md`, `docs/premarket-open-research-plan.md`, `docs/preliminary-week-findings.md`, and inspect Git status before acting. Continue the research-only premarket/open pipeline from the documented state. Do not modify `trading-agent`, place or implement orders, expose credentials, invent thresholds, or use future data in features. Preserve the Revolut screenshot-led behavioural study as the initial historical pattern-discovery track, while keeping Revolut outside the future scanner's inputs. Use Alpaca SIP bars as the authoritative market data. Analyze all dates collectively with date-separated validation. Tell me the verified current status and the next safe action before making material changes.

## Maintenance rule

After any meaningful collection, analysis, methodology decision, or pipeline change, update this document's date, data status, verified findings, and next actions in the same commit. Keep detailed outputs in dated research files and keep this document concise enough to read at the start of every new chat.
