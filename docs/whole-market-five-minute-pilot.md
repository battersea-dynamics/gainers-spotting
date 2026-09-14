# Whole-market five-minute pilot

**Status:** Implemented; authenticated collection not yet run

**Pilot version:** `whole-market-five-minute-pilot-v1`

**Default research session:** 2026-09-11

## Purpose

This pilot is the first test of independent market-wide discovery. It does not
use Revolut membership, screenshot ranks, displayed gains, or a fixed ticker
list. Revolut remains historical evidence used to form hypotheses; candidate
discovery starts from a newly captured Alpaca universe of active, tradable US
equities on supported exchanges.

The pilot answers a deliberately narrow first question: can the broad universe
and five-minute data pass complete within a practical API, runtime, and storage
budget while retaining enough information to measure candidate burden, false
positives, missed runners, and subsequent opportunity?

## Reproducible flow

1. Capture a dated Alpaca asset snapshot without a price or historical-volume
   floor and store its deterministic content hash.
2. Collect 60 calendar days of raw-adjusted daily history ending before the
   research date.
3. Resolve the actual previous US trading session from returned daily data.
4. Collect raw-adjusted five-minute bars across the full universe from the
   previous session at 16:00 ET through the research session at 16:00 ET.
5. Calculate point-in-time features at 09:30, 09:45, and 10:00 ET. A
   five-minute bar is available only when its start plus five minutes is no
   later than the decision timestamp.
6. Rank independent discovery channels and report per-channel union budgets of
   20, 50, and 100. These are burden/recall curves, not approved limits.
7. Write future outcomes separately and evaluate whole-universe recall and
   precision after the session.

The workflow spaces Alpaca requests by 0.5 seconds by default, corresponding
to a maximum starting rate of approximately 120 requests per minute before
retries. Actual request counts and safe rate-limit headers remain in metadata.

## Pilot channels

The enabled candidate-union channels are:

- `absolute_activity`: dollar volume, trades, and active five-minute bars;
- `daily_volume_activation`: current premarket activity compared with the
  symbol's own preceding 20-session daily-volume baseline;
- `dormant_activation`: current activation combined transparently with lower
  preceding 20-session close volatility and absence of large daily jumps;
- `emerging_structure`: late premarket price change, acceleration, range
  position, proximity to the premarket high, and VWAP position;
- `opening_confirmation`: additional completed regular-session evidence for
  the 09:45 and 10:00 decisions only.

The raw positive-gap rank is retained as a descriptive baseline but is disabled
from candidate selection. Corporate actions are not yet available, so a raw
gap must not be treated as a verified true gap.

Channel component scores are within-date percentiles and use a transparent
equal mean with missing components omitted. This is an exploratory pilot
baseline, not an approved model or trading threshold. Deterministic symbol
ordering breaks score ties so a top-k channel cannot accidentally retain the
entire universe.

## Outputs

The artifact contains the captured universe, raw compressed API pages, clean
daily and five-minute bars, collection metadata, and:

- `analysis/run-manifest.json`;
- `analysis/universe.csv.gz`;
- `analysis/broad-features.csv.gz`;
- `analysis/channel-rankings.csv.gz`;
- `analysis/candidate-unions.csv.gz`;
- separate `analysis/rankings-*.csv.gz` files;
- `analysis/ranking-explanations.json`;
- `analysis/retrospective-outcomes.csv.gz`;
- `analysis/pilot-evaluation.csv`;
- `analysis/api-cache-usage.json`;
- `analysis/data-quality.json`.

Ranking files contain no future return, MFE, MAE, regular-session high, or
eventual-gainer outcome fields. The workflow verifies that separation before
uploading the artifact.

## Limitations

- The default 2026-09-11 pilot uses an asset snapshot captured after that
  session. It is suitable for API and pipeline validation but carries explicit
  survivorship and symbol-change risk. Later validation requires universes
  captured before their sessions.
- Historical premarket time-of-day baselines are not collected in this first
  volume pilot. The daily activity ratio is not labelled as premarket RVOL.
- Five-minute bars are the broad discovery layer. One-minute candidate detail
  is intentionally deferred until broad coverage and burden are measured.
- Spread, quote depth, auction data, and corporate actions remain unavailable.
- Raw previous-close-to-high bands are unverified sensitivity labels. MFE from
  the fixed decision benchmark is evaluated separately.
- The candidate budgets, equal component means, and score directions are
  research baselines. Nothing in the pilot submits or recommends an order.

## Running the pilot

From GitHub, open **Actions → Whole-market five-minute pilot → Run workflow**.
Use a completed US session. The default is `2026-09-11`. The workflow uses the
repository's existing Alpaca secrets and uploads one downloadable artifact.

To reproduce locally with configured environment credentials:

```bash
python scripts/build_alpaca_universe.py \
  --date 2026-09-11 \
  --output data/research/universes/2026-09-11.json

python scripts/collect_whole_market_pilot.py \
  --date 2026-09-11 \
  --universe-file data/research/universes/2026-09-11.json

python scripts/analyze_whole_market_pilot.py \
  --pilot-dir data/research/whole-market-pilot/2026-09-11
```

Generated data remain excluded from Git.
