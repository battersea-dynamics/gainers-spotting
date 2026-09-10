# Gainers Spotting

> **Continuing this project in a new chat?** Start with
> [`docs/research-handoff.md`](docs/research-handoff.md) for the current scope,
> constraints, data status, methodology, next actions, and bootstrap prompt.

Research software for identifying U.S.-traded stocks during premarket that may
offer a useful long entry at the regular-session open, 15 minutes after open or
30 minutes after open.

The project focuses on detecting abnormal behaviour early enough that
meaningful upside may still remain, rather than reproducing a list of stocks
that have already completed most of their move. It compares fixed 09:30, 09:45
and 10:00 ET entry benchmarks. It does not develop later day-trading decisions,
exits, position management or order submission.

## Status

The project now has a reproducible historical collector, point-in-time ranking
engine, multi-date evaluation, and a broad Alpaca asset-universe builder. It is
still a research system: no live scanner is scheduled, it does not place
orders, and it is not integrated with `battersea-dynamics/trading-agent`.

Initial work will:

- collect reproducible premarket observations;
- reconstruct screenshot-labelled top gainers and controls from the previous
  close, after-hours, premarket and post-open one-minute behaviour;
- compare eventual significant gainers, missed runners and candidates that faded;
- investigate price, volume, acceleration, structure, liquidity and catalysts;
- compare fixed 09:30, 09:45 and 10:00 ET benchmarks without look-ahead bias;
- measure detection time, remaining move, recall, precision, post-entry opportunity and API usage;
- derive scanner and entry rules from evidence rather than preset weights or thresholds.

## Principles

- U.S. equities and premarket discovery are the initial focus.
- Discovery eligibility is separate from trading eligibility.
- Historical evaluation must avoid look-ahead bias.
- Market-data delays must be represented at the simulated decision time.
- Post-open data is used to evaluate premarket selections, not to build selling logic in this phase.
- Alpaca requests should be batched and reusable data cached locally.
- Deterministic calculations belong in Python, not an LLM.
- News enrichment should occur only after quantitative candidate reduction.
- `trading-agent` must remain untouched unless future integration is explicitly approved.

## Documentation

- [Project brief](docs/project-brief.md)
- [Research methodology](docs/research-methodology.md)
- [Data and API constraints](docs/data-and-api-constraints.md)
- [Decision log](docs/decisions.md)
- [Open questions](docs/open-questions.md)
- [Premarket and opening-entry research plan](docs/premarket-open-research-plan.md)
- [Premarket ranking engine](docs/premarket-ranking-engine.md)
- [Approved engine specification v1](docs/engine-spec-v1.md)
- [Frozen research protocol v1](config/research-protocol-v1.json)
- [Evidence-based improvements (external review)](docs/evidence-based-improvements.md)

## Repository

This is a standalone project. Raw market datasets, screenshot images, recovery
archives, API credentials and caches should not be committed to Git. Small,
reviewable derived observations and dated research-universe manifests may be
committed when their provenance and limitations are explicit.

## Recovered screenshot observations

The repository contains normalized, date-level observations derived from the
recovered Revolut OCR archive under `config/research-observations/`. The source
ZIP and original screenshots remain outside Git. The records retain actual UK
capture times, per-image visible positions, OCR confidence and conflicting or
missing values; they never infer a global rank across scrolling captures.

To reproduce the normalization from a local copy of the recovery ZIP:

```bash
python scripts/normalize_screenshot_recovery.py \
  --input /path/to/gainers-screenshot-recovery.zip \
  --write-universes
```

Existing reviewed universe files are preserved. Missing dated universes are
created as collection manifests: a symbol shown with a dollar price is marked
`provisional_usd_displayed`, not verified as an eligible US equity. Pass a
dated Alpaca asset snapshot with `--asset-file` when one is available, and use
historical bar success/failure metadata to finish eligibility review before
analysis.

## Historical Alpaca collector

The research-only collector downloads paginated one-minute SIP bars for the
documented candidate and control universes. It reads credentials only from
`APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` or the compatible
`ALPACA_API_KEY` / `ALPACA_SECRET_KEY` environment variables.

```bash
python scripts/collect_alpaca_bars.py --date 2026-07-24
```

For an observed date, pass its tracked, timestamp-derived research universe:

```bash
python scripts/collect_alpaca_bars.py \
  --date 2026-07-27 \
  --universe-file config/research-universes/2026-07-27.json
```

The manual GitHub Actions workflow `Collect observed research week` collects
27–31 July in parallel using the repository's existing Alpaca secrets. It does
not submit orders and does not expose secret values.

The manual `Collect recovered August observations` workflow collects the nine
recovered screenshot dates from 3–14 August in batches of three parallel jobs.
Each job checks that pagination completed and at least one requested symbol
returned usable bars before uploading its dated artifact.

Generated raw pages, clean gzip-compressed CSV/JSONL files, and metadata are
written under `data/research/YYYY-MM-DD/`, which is excluded from Git.

For a broad discovery universe captured before a future research session, run:

```bash
python scripts/build_alpaca_universe.py --date 2026-09-03
```

This queries Alpaca's active, tradable US-equity assets without a price or
historical-volume floor and writes a dated, versioned snapshot under
`data/research/universes/`. It records that the snapshot is not a historically
complete universe for earlier dates. Use the generated JSON with the collector;
the collector batches large symbol lists so it does not create one oversized
request URL.

## Historical session analysis

Run the reproducible research analysis after placing a collected dataset under
its date directory:

```bash
python scripts/analyze_historical_session.py --date 2026-07-24
```

The analysis validates the bars, calculates continuous premarket and
regular-session behaviour measurements, compares the documented cohorts,
performs exploratory clustering, and generates a self-contained HTML report
with candlestick and volume charts. Generated outputs are written under
`data/research/YYYY-MM-DD/analysis/` and remain excluded from Git.

The analysis is descriptive. It does not create scanner thresholds, trading
rules, entries, exits or orders.

## Multi-date premarket and opening-entry analysis

After collecting each date, run the leakage-controlled pooled analysis with
the dates to compare. Features use only bars completed before the 09:30, 09:45
or 10:00 ET decision, while later bars are reserved for outcomes.

```bash
python scripts/analyze_premarket_open_week.py \
  --dates 2026-07-24 2026-07-27 2026-07-28 2026-07-29 2026-07-30 2026-07-31 \
  --output-dir data/research/collective-2026-07-24_to_2026-07-31/analysis
```

The command validates all sessions, falls back to intact JSONL if a clean CSV
gzip is damaged, builds symbol-date feature/outcome data, compares fixed entry
times and reports rank associations with per-date and leave-one-date-out sign
checks. Its generated research tables and report remain excluded from Git.

This remains hypothesis-generation research: it does not select production
thresholds, claim executable fills or submit orders.

The multi-date command also writes versioned candidate rankings, simple
baselines, top-5/10/20 evaluation, candidate burden, failure labels, and
chronological walk-forward folds. The MFE thresholds in
`config/research-protocol-v1.json` are evaluation-only sensitivity labels;
continuous outcomes remain primary and the thresholds are not buy rules.

## Point-in-time candidate rankings

To rank every symbol present in one collected session at the open, +15 minutes,
and +30 minutes:

```bash
python scripts/rank_premarket_candidates.py --date 2026-07-27
```

The ranker accepts compressed `bars.csv.gz` input, retains low-priced stocks,
and uses only completed bars available at each decision time. Point-in-time
ranking files and retrospective outcome files are written separately under
`data/research/YYYY-MM-DD/analysis/premarket_ranker/`.

This command ranks the supplied bar universe. Market-wide recall and precision
become measurable only after the independently generated broad universe has
been collected; screenshot-derived universes cannot support those claims.

## What is not running

The GitHub workflows are manual historical collectors. There is currently no
scheduled or continuously running live scanner, no paper-trading workflow, and
no order capability in this repository.
