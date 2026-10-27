# Shadow mode v1: Cloudflare cron trigger -> GitHub Actions (market data only)

**No orders. No account, positions or orders endpoints.** `scripts/shadow_live.py` patches every
collector's `urlopen` with an allow-list (`data.alpaca.markets/v2/stocks/bars`, `paper-api.alpaca.markets/v2/assets`,
Nasdaq Trader symbol directory; GET only) and tests enforce it.

## Architecture
1. `gainers-shadow-trigger` (Cloudflare Worker, Free plan, 1 cron `*/15 8-21 * * MON-FRI`, no D1, ~0 CPU)
   converts each tick to America/New_York, skips weekends/NYSE holidays, picks the due slot and POSTs
   `workflow_dispatch` for `.github/workflows/shadow-scan.yml` with inputs `{job, date, cutoff}`.
2. `shadow-scan.yml` runs `scripts/shadow_run.py`, which reuses the Engine v2 code path
   (`build_alpaca_universe`, `build_stock_security_master`, `analyze_engine_v2_phase1.classify_universe/build_stock_features/PROFILE_CONFIG`,
   `collect_prior_session_context._collect_dataset`, `analyze_whole_market_pilot._daily_context/_after_hours_context/_decision_features/_outcomes`).
3. Logs are committed to the orphan branch `shadow-data` under `shadow/<date>/`.

## Slot table (15-minute grid; ET is authoritative)
Alpaca's free plan only serves SIP bars older than 15 minutes, so each data job's tick is >= cutoff + 15 min,
and the runner sleeps until cutoff + 16 min before querying. Only 5-minute bars with `start + 5m <= cutoff` are used.

| Tick ET | UTC (EDT, to 30 Oct 2026) | UTC (EST, from 2 Nov 2026) | job | cutoff (data up to) |
|---|---|---|---|---|
| 04:00 | 08:00 | 09:00 | universe + prior-session context (freeze) | – |
| 07:15 | 11:15 | 12:15 | snapshot | 07:00 |
| 08:15 | 12:15 | 13:15 | snapshot | 08:00 |
| 09:15 | 13:15 | 14:15 | snapshot | 09:00 |
| 09:30 | 13:30 | 14:30 | snapshot (last pre-open data queryable by the open) | 09:15 |
| 09:45 | 13:45 | 14:45 | rank R0 | 09:30 |
| 10:00 | 14:00 | 15:00 | rank R1 | 09:45 |
| 10:15 | 14:15 | 15:15 | rank R2 | 10:00 |
| 16:30 | 20:30 | 21:30 | outcomes (to 16:00 close) | – |
| 16:45 | 20:45 | 21:45 | daily summary | – |

Early-close days (13:00 ET: 2026-11-27, 2026-12-24, 2027-11-26): morning slots unchanged; outcomes 13:30 ET, summary 13:45 ET; no 16:30/16:45.
Holidays 2026-27 are hard-coded in both the Worker and `shadow_live.py` (fail-closed outside 2026-01-01..2027-12-31).

## Logs (`shadow-data` branch, `shadow/<date>/`, append-only)
- `universe/universe.json.gz, classification.csv.gz, context.csv.gz, meta.json` (frozen at 04:00; built late and flagged `UNIVERSE_BUILT_LATE` if missing)
- `rankings/<decision>.csv` (list_type `engine:v2_activation|v2_momentum_quality|v2_absolute_activity_baseline|v2_opening_confirmation`,
  `control:gap_top|rel_vol_top|random_liquid`; rank, symbol, score, per-list sha256) + `<decision>.manifest.json` (seed, pool, git SHA, engine version, latency)
- `features/<decision>.csv.gz` features of listed symbols (full eligible table only in the 90-day Actions artifact)
- `outcomes/outcomes.csv.gz` (+ manifest with universe-median control) — reads only the *set* of logged symbols, never scores
- `summary.csv/json`, `runs/<job>-<cutoff>-<run_id>.json` (status, flags, API page stats; never credentials)

Controls: top-N by raw gap, top-N by premarket rel-vol, N random liquid primary stocks (20-session median $ volume >= $1M,
seed = sha256(date|decision|shadow-live-v1)), universe median. Defaults N = 20.

Concurrency: files are written once (a forced re-run writes `*.rerun-<run_id>.*`), every job writes different paths, so
overlapping runs never conflict; the push step does fetch + rebase + retry (8 attempts with jitter). No workflow
`concurrency:` group, because GitHub would cancel queued runs.

## Secrets
`SHADOW_ALPACA_KEY_ID`, `SHADOW_ALPACA_SECRET_KEY` (dedicated data-only paper account; separate from the
`ALPACA_API_KEY`/`ALPACA_SECRET_KEY` used by the research workflows). The Worker needs `GITHUB_TOKEN`
(fine-grained PAT: this repo only, Actions read/write).
