#!/usr/bin/env python3
"""Live SHADOW-MODE premarket scanner (market data only).

Reuses the Engine v2 research code path unchanged:
  build_alpaca_universe  -> broad asset snapshot (paper-api /v2/assets, read-only)
  build_stock_security_master + analyze_engine_v2_phase1.classify_universe
  collect_prior_session_context._collect_dataset  -> SIP bars (data.alpaca.markets)
  analyze_whole_market_pilot._daily_context / _after_hours_context /
      _decision_features / _outcomes
  analyze_engine_v2_phase1.build_stock_features + PROFILE_CONFIG

This module NEVER talks to Alpaca orders, positions or account endpoints: every
outbound URL goes through ``guarded_urlopen`` which only allows the prefixes in
ALLOWED_URL_PREFIXES. Credentials are read from the environment and never
written to logs.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import urllib.request
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import analyze_engine_v2_phase1 as aev2  # noqa: E402
import analyze_whole_market_pilot as awmp  # noqa: E402
import build_alpaca_universe as bau  # noqa: E402
import build_stock_security_master as bssm  # noqa: E402
import collect_alpaca_bars as cab  # noqa: E402
import collect_prior_session_context as cpsc  # noqa: E402

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
SHADOW_VERSION = "shadow-live-v1"
ENGINE_VERSION = "|".join([
    SHADOW_VERSION, aev2.EXPERIMENT_VERSION, aev2.RANKING_VERSION,
    awmp.FEATURE_VERSION, awmp.OUTCOME_VERSION, bssm.MASTER_VERSION,
    bssm.CLASSIFIER_VERSION, bau.RULE_VERSION, "controls:shadow-controls-v1",
])
SIP_DELAY_MINUTES = 16  # Alpaca free plan: SIP queryable only >15 min after the fact
FEED = "sip"

# ------------------------------------------------------------------ safety
ALLOWED_URL_PREFIXES = (
    "https://data.alpaca.markets/v2/stocks/bars?",
    "https://paper-api.alpaca.markets/v2/assets?",
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt",
)
_real_urlopen = urllib.request.urlopen


class BlockedUrl(RuntimeError):
    pass


def assert_allowed(url: str) -> None:
    if not any(url.startswith(prefix) for prefix in ALLOWED_URL_PREFIXES):
        raise BlockedUrl(f"Blocked non-market-data URL: {url.split('?')[0]}")


def guarded_urlopen(request: Any, *args: Any, **kwargs: Any):
    url = request.full_url if hasattr(request, "full_url") else str(request)
    method = request.get_method() if hasattr(request, "get_method") else "GET"
    if method != "GET":
        raise BlockedUrl(f"Blocked non-GET request: {method}")
    assert_allowed(url)
    return _real_urlopen(request, *args, **kwargs)


for _module in (cab, bau, bssm):
    _module.urlopen = guarded_urlopen  # type: ignore[attr-defined]

# ------------------------------------------------------------------ calendar
# NYSE full-day holidays and 13:00 ET early closes (mirror of the trigger Worker).
HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
    "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
    "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}
EARLY_CLOSES = {"2026-11-27": "13:00", "2026-12-24": "13:00", "2027-11-26": "13:00"}
CALENDAR_COVERS = ("2026-01-01", "2027-12-31")


def is_trading_day(day: str) -> bool:
    if not CALENDAR_COVERS[0] <= day <= CALENDAR_COVERS[1]:
        raise ValueError(f"Holiday calendar does not cover {day}")
    return date.fromisoformat(day).weekday() < 5 and day not in HOLIDAYS


def close_time(day: str) -> str:
    return EARLY_CLOSES.get(day, "16:00")


def previous_trading_day(day: str) -> str:
    current = date.fromisoformat(day)
    while True:
        current -= timedelta(days=1)
        if is_trading_day(current.isoformat()):
            return current.isoformat()


def et(day: str, hhmm: str) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime.combine(date.fromisoformat(day), dtime(hour, minute), tzinfo=ET)


# ------------------------------------------------------------------ decisions
SNAPSHOT_DECISIONS = {"07:00": "snap-0700", "08:00": "snap-0800", "09:00": "snap-0900", "09:15": "snap-0915"}
RANK_DECISIONS = {"09:30": "open", "09:45": "open+15", "10:00": "open+30"}
JOBS = ("universe", "snapshot", "rank", "outcomes", "summary")


def decision_for(job: str, cutoff: str) -> str:
    table = SNAPSHOT_DECISIONS if job == "snapshot" else RANK_DECISIONS
    if cutoff not in table:
        raise ValueError(f"Unsupported cutoff {cutoff!r} for job {job}; allowed: {sorted(table)}")
    name = table[cutoff]
    awmp.DECISIONS.setdefault(name, cutoff)  # register snapshot cutoffs with the shared feature code
    return name


def safe_name(decision: str) -> str:
    return decision.replace("+", "-plus-")


# ------------------------------------------------------------------ config
DEFAULTS = {"top_n": 20, "random_n": 20, "liquid_min_dv20": 1_000_000.0, "batch_size": 200,
            "request_interval_seconds": 0.35, "timeout": 60, "max_attempts": 5}


def seed_for(day: str, decision: str) -> int:
    digest = hashlib.sha256(f"{day}|{decision}|{SHADOW_VERSION}".encode()).hexdigest()
    return int(digest[:8], 16)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(json_safe(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def utc_now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------ append-only store
class Store:
    """Append-only file store rooted at <data_root>/shadow/<date>/.

    A file is written once. A forced re-run writes a new ``.rerun-<run_id>``
    sibling instead of overwriting, so committed history is never rewritten and
    concurrent runs (which always write different file names) never conflict.
    """

    def __init__(self, data_root: Path, day: str, run_id: str):
        self.root = data_root / "shadow" / day
        self.run_id = run_id

    def path(self, rel: str) -> Path:
        return self.root / rel

    def exists(self, rel: str) -> bool:
        return self.path(rel).exists()

    def _target(self, rel: str, force: bool) -> Path | None:
        target = self.path(rel)
        if target.exists():
            if not force:
                return None
            stem, dot, ext = target.name.partition(".")
            target = target.with_name(f"{stem}.rerun-{self.run_id}{dot}{ext}")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def write_json(self, rel: str, payload: Any, force: bool = False) -> Path | None:
        target = self._target(rel, force)
        if target is None:
            return None
        text = json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n"
        if target.suffix == ".gz":
            with gzip.open(target, "wt", encoding="utf-8") as handle:
                handle.write(text)
        else:
            target.write_text(text, encoding="utf-8")
        return target

    def write_csv(self, rel: str, frame: pd.DataFrame, force: bool = False) -> Path | None:
        target = self._target(rel, force)
        if target is None:
            return None
        frame.to_csv(target, index=False, compression="gzip" if target.suffix == ".gz" else None)
        return target

    def read_json(self, rel: str) -> Any:
        path = self.path(rel)
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return json.load(handle)
        return json.loads(path.read_text(encoding="utf-8"))

    def read_csv(self, rel: str) -> pd.DataFrame:
        return pd.read_csv(self.path(rel), low_memory=False)


# ------------------------------------------------------------------ data access
class Bars:
    """Thin wrapper around the repo's SIP bar collector (keeps raw pages in a temp dir)."""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.key, self.secret = cab.get_credentials()
        self.raw_dir = Path(tempfile.mkdtemp(prefix="shadow-raw-"))
        self.stats: list[dict[str, Any]] = []

    def fetch(self, dataset: str, symbols: list[str], start: datetime, end: datetime, timeframe: str) -> pd.DataFrame:
        if not symbols:
            return _bars_frame([])
        latest_allowed = utc_now() - timedelta(minutes=SIP_DELAY_MINUTES - 1)
        if end.astimezone(UTC) > latest_allowed:
            raise RuntimeError(f"{dataset}: request end {end.isoformat()} is inside the SIP delay window")
        rows, summary = cpsc._collect_dataset(
            dataset=dataset, symbols=symbols, group_by_symbol={s: "shadow" for s in symbols},
            start_et=start, end_et=end, timeframe=timeframe, raw_dir=self.raw_dir,
            key=self.key, secret=self.secret, batch_size=self.cfg["batch_size"], limit=10_000,
            timeout=self.cfg["timeout"], max_attempts=self.cfg["max_attempts"],
            request_interval_seconds=self.cfg["request_interval_seconds"],
        )
        failures = summary.get("failures", {})
        self.stats.append({
            "dataset": dataset, "timeframe": timeframe, "start_utc": summary["start_utc"],
            "end_utc": summary["end_utc"], "pages": summary["pages"],
            "batches": summary["attempted_batches"], "split_batches": summary["split_batches"],
            "symbols_requested": len(symbols), "symbols_with_bars": len(summary["successful_symbols"]),
            "rejected_symbols": sorted(s for s, r in failures.items() if r != "No bars returned for the requested window")[:50],
            "total_bars": summary["total_bars"],
        })
        return _bars_frame(rows)


def _bars_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    columns = ["symbol", "session_date", "timestamp_et", "open", "high", "low", "close", "volume", "trade_count", "vwap"]
    frame = pd.DataFrame(rows, columns=[*columns, "timestamp_utc"]) if rows else pd.DataFrame(columns=columns)
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["session_date"] = frame["session_date"].astype(str)
    frame["timestamp_et"] = pd.to_datetime(frame["timestamp_et"], errors="coerce", utc=True).dt.tz_convert(ET)
    for field in ("open", "high", "low", "close", "volume", "trade_count", "vwap"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    return frame.dropna(subset=["symbol", "timestamp_et"]).sort_values(["symbol", "timestamp_et"])


# ------------------------------------------------------------------ jobs
def job_universe(ctx: "RunContext") -> dict[str, Any]:
    store, day = ctx.store, ctx.day
    if store.exists("universe/context.csv.gz") and not ctx.force:
        return {"skipped": "universe already frozen for this date (append-only)"}
    key, secret = bau.get_credentials()
    assets = bau.fetch_assets(key, secret, ctx.cfg["timeout"])
    accepted, rejected = bau.eligible_assets(assets)
    universe = bau.build_payload(day, accepted, rejected)
    master_bytes = bssm._download(bssm.SOURCE_URL, ctx.cfg["timeout"])
    master = bssm.build_payload(master_bytes, bssm.SOURCE_URL)
    classes = aev2.classify_universe(universe, master)
    primary = sorted(classes.loc[classes.primary_stock_eligible.eq(True), "symbol"].astype(str))
    if ctx.limit:
        primary = primary[: ctx.limit]

    bars = ctx.bars()
    research_day = date.fromisoformat(day)
    daily = bars.fetch("daily", primary, datetime.combine(research_day - timedelta(days=60), dtime(0, 0), tzinfo=ET),
                       datetime.combine(research_day, dtime(0, 0), tzinfo=ET), "1Day")
    observed_prev = max((d for d in daily.session_date.unique() if d < day), default=None)
    prev = previous_trading_day(day)
    after_hours = bars.fetch("after-hours", primary, et(prev, "16:00"), et(prev, "20:00"), "5Min")
    daily_groups = dict(tuple(daily.groupby("symbol", sort=False)))
    ah_groups = dict(tuple(after_hours.groupby("symbol", sort=False)))
    rows = []
    for symbol in primary:
        d = awmp._daily_context(daily_groups.get(symbol, daily.iloc[0:0]), prev)
        a = awmp._after_hours_context(ah_groups.get(symbol, after_hours.iloc[0:0]), awmp._finite(d["previous_close_raw"]))
        rows.append({"symbol": symbol, "previous_session": prev, **d, **a})
    context = pd.DataFrame(rows)
    store.write_json("universe/universe.json.gz", universe, ctx.force)
    store.write_csv("universe/classification.csv.gz", classes, ctx.force)
    store.write_csv("universe/context.csv.gz", context, ctx.force)
    meta = {
        "universe_content_sha256": universe["universe_content_sha256"], "asset_count": universe["asset_count"],
        "master_source_sha256": master["source_sha256"], "master_record_count": master["record_count"],
        "primary_stock_symbols": len(primary), "instrument_type_counts": classes.instrument_type.value_counts().to_dict(),
        "possible_spac_common": int(classes.possible_spac_common.sum()),
        "previous_session_calendar": prev, "previous_session_observed": observed_prev,
        "previous_session_match": prev == observed_prev,
        "survivorship_note": "Asset/master snapshot is CURRENT metadata; for a past date this is a backfill with survivorship bias." if ctx.backfill else None,
    }
    store.write_json("universe/meta.json", meta, ctx.force)
    return meta


def _load_frozen(ctx: "RunContext") -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    if not ctx.store.exists("universe/context.csv.gz"):
        ctx.flags.append("UNIVERSE_BUILT_LATE")
        job_universe(ctx)
    classes = ctx.store.read_csv("universe/classification.csv.gz")
    context = ctx.store.read_csv("universe/context.csv.gz")
    for column in ("primary_stock_eligible", "possible_spac_common"):
        classes[column] = classes[column].astype(str).str.lower().eq("true")
    symbols = sorted(context.symbol.astype(str))
    if ctx.limit:
        symbols = symbols[: ctx.limit]
    return classes, context, symbols


def compute_features(day: str, decision: str, bars: pd.DataFrame, context: pd.DataFrame,
                     classes: pd.DataFrame, symbols: list[str], failed: set[str]) -> pd.DataFrame:
    """Point-in-time Engine v2 stock features from bars strictly before the cutoff."""
    cutoff = et(day, awmp.DECISIONS[decision])
    bars = bars.loc[(bars.session_date == day) & (bars.timestamp_et + pd.Timedelta(minutes=5) <= cutoff)]
    groups = dict(tuple(bars.groupby("symbol", sort=False)))
    ctx_lookup = context.set_index("symbol").to_dict("index")
    daily_keys = list(awmp._daily_context(bars.iloc[0:0], day).keys())
    ah_keys = list(awmp._after_hours_context(bars.iloc[0:0], math.nan).keys())
    rows = []
    for symbol in symbols:
        record = ctx_lookup.get(symbol, {})
        daily = {k: record.get(k, math.nan) for k in daily_keys}
        daily["dormancy_sessions_available_20"] = int(awmp._finite(daily["dormancy_sessions_available_20"]) or 0) if math.isfinite(awmp._finite(daily["dormancy_sessions_available_20"])) else 0
        after_hours = {k: record.get(k, math.nan) for k in ah_keys}
        row = awmp._decision_features(session_date=day, decision=decision, current_bars=groups.get(symbol, bars.iloc[0:0]),
                                      daily=daily, after_hours=after_hours, collection_failed=symbol in failed)
        row.update({"session_date": day, "symbol": symbol, "research_only": True, "orders_supported": False,
                    "feed": FEED, "feature_set_version": awmp.FEATURE_VERSION})
        rows.append(row)
    features = pd.DataFrame(rows)
    leaked = aev2.FUTURE_COLUMNS & set(features.columns)
    if leaked:
        raise AssertionError(f"future columns in features: {sorted(leaked)}")
    return aev2.build_stock_features(features, classes[[
        "symbol", "instrument_type", "primary_stock_eligible", "possible_spac_common",
        "classification_reason", "master_match_status"]])


def build_lists(day: str, decision: str, stock: pd.DataFrame, cfg: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Engine v2 profile lists plus controls (gap top-N, rel-vol top-N, seeded random liquid N)."""
    top_n, random_n = int(cfg["top_n"]), int(cfg["random_n"])
    eligible = stock.loc[stock.v2_primary_eligible.eq(True)].copy()
    configs = dict(aev2.PROFILE_CONFIG)
    if decision in ("open+15", "open+30"):
        configs["v2_opening_confirmation"] = "opening_confirmation_v2_score"
    lists: dict[str, list[tuple[str, float]]] = {}

    def top_by(column: str) -> list[tuple[str, float]]:
        frame = eligible.assign(_s=pd.to_numeric(eligible[column], errors="coerce")).dropna(subset=["_s"])
        frame = frame.sort_values(["_s", "symbol"], ascending=[False, True]).head(top_n)
        return list(zip(frame.symbol.astype(str), frame._s.astype(float)))

    for model, column in configs.items():
        lists[f"engine:{model}"] = top_by(column)
    lists["control:gap_top"] = top_by("decision_vs_previous_close_raw")
    lists["control:rel_vol_top"] = top_by("pm_volume_to_median_daily_volume_20")
    seed = seed_for(day, decision)
    dv20 = pd.to_numeric(stock.dormancy_median_daily_dollar_volume_20, errors="coerce")
    pool = sorted(stock.loc[stock.primary_stock_eligible.eq(True) & (dv20 >= cfg["liquid_min_dv20"])
                            & pd.to_numeric(stock.decision_price, errors="coerce").notna(), "symbol"].astype(str))
    rng = np.random.default_rng(seed)
    picks = sorted(rng.choice(pool, size=min(random_n, len(pool)), replace=False).tolist()) if pool else []
    lists["control:random_liquid"] = [(s, math.nan) for s in picks]

    rows, hashes = [], {}
    for list_type, items in lists.items():
        hashes[list_type] = sha256_json({"day": day, "decision": decision, "list_type": list_type,
                                         "engine_version": ENGINE_VERSION, "items": items})
        for rank, (symbol, score) in enumerate(items, start=1):
            rows.append({"session_date": day, "decision": decision, "list_type": list_type, "rank": rank,
                         "symbol": symbol, "score": score, "list_sha256": hashes[list_type]})
    meta = {"random_seed": seed, "random_liquid_pool": len(pool),
            "liquid_rule": f"primary stock, dormancy_median_daily_dollar_volume_20 >= {cfg['liquid_min_dv20']:.0f}, has a price before cutoff",
            "top_n": top_n, "random_n": random_n, "eligible_ranked": int(len(eligible)), "list_sha256": hashes}
    return pd.DataFrame(rows, columns=["session_date", "decision", "list_type", "rank", "symbol", "score", "list_sha256"]), meta


def job_features(ctx: "RunContext") -> dict[str, Any]:
    decision = decision_for(ctx.job, ctx.cutoff)
    name = safe_name(decision)
    if ctx.store.exists(f"rankings/{name}.csv") and not ctx.force:
        return {"skipped": f"rankings for {decision} already written (append-only)"}
    cutoff = et(ctx.day, ctx.cutoff)
    ctx.wait_until(cutoff + timedelta(minutes=SIP_DELAY_MINUTES))
    classes, context, symbols = _load_frozen(ctx)
    bars = ctx.bars()
    t0 = time.monotonic()
    raw = bars.fetch(f"pm-{name}", symbols, et(ctx.day, "04:00"), cutoff, "5Min")
    fetch_seconds = round(time.monotonic() - t0, 1)
    failed = set(bars.stats[-1]["rejected_symbols"])
    stock = compute_features(ctx.day, decision, raw, context, classes, symbols, failed)
    lists, list_meta = build_lists(ctx.day, decision, stock, ctx.cfg)
    keep = stock.loc[stock.v2_primary_eligible.eq(True)]
    # Git keeps only the features of logged (listed) symbols; the full eligible table goes to the
    # run artifact directory (uploaded as a GitHub Actions artifact) to keep shadow-data small.
    listed = keep.loc[keep.symbol.isin(set(lists.symbol))]
    ctx.store.write_csv(f"features/{name}.csv.gz", listed, ctx.force)
    full = ctx.artifact_dir / ctx.day / f"features-full-{name}.csv.gz"
    full.parent.mkdir(parents=True, exist_ok=True)
    keep.to_csv(full, index=False, compression="gzip")
    ctx.store.write_csv(f"rankings/{name}.csv", lists, ctx.force)
    manifest = {"decision": decision, "cutoff_et": cutoff.isoformat(), "bar_request_end_utc": cutoff.astimezone(UTC).isoformat(),
                "bar_policy": "5-minute SIP bars with bar_start + 5m <= cutoff", "computed_at_utc": utc_now().isoformat(),
                "latency_minutes_after_cutoff": round((utc_now() - cutoff).total_seconds() / 60, 1),
                "universe_symbols": len(symbols), "feature_rows_primary_active": int(len(keep)),
                "fetch_seconds": fetch_seconds, **list_meta}
    ctx.store.write_json(f"rankings/{name}.manifest.json", {**manifest, **ctx.stamp()}, ctx.force)
    return manifest


def _first_touch(future: pd.DataFrame, entry: float, up: float, down: float) -> float:
    for _, bar in future.iterrows():
        hit_down = bar.low <= entry * (1 - down)
        hit_up = bar.high >= entry * (1 + up)
        if hit_down:
            return 0.0  # conservative: a bar touching both counts as stop first
        if hit_up:
            return 1.0
    return 0.0  # neither level touched before the close


def compute_outcomes(day: str, decisions: list[str], symbols: list[str], regular: pd.DataFrame,
                     context: pd.DataFrame) -> pd.DataFrame:
    close = et(day, close_time(day))
    regular = regular.loc[(regular.session_date == day) & (regular.timestamp_et >= et(day, "09:30")) & (regular.timestamp_et < close)]
    groups = dict(tuple(regular.groupby("symbol", sort=False)))
    prev_close = context.set_index("symbol")["previous_close_raw"].to_dict()
    rows = []
    for decision in decisions:
        cutoff = et(day, awmp.DECISIONS[decision])
        for symbol in symbols:
            frame = groups.get(symbol, regular.iloc[0:0])
            out = awmp._outcomes(day, decision, frame, awmp._finite(prev_close.get(symbol, math.nan)))
            future = frame.loc[frame.timestamp_et >= cutoff].sort_values("timestamp_et")
            entry = awmp._finite(out.get("entry_price", math.nan))
            for up in (0.05, 0.10):
                out[f"hit_up{int(up*100)}_before_dn5"] = _first_touch(future, entry, up, 0.05) if math.isfinite(entry) else math.nan
            out.update({"session_date": day, "decision": decision, "symbol": symbol,
                        "outcome_set_version": awmp.OUTCOME_VERSION + "+first-touch-v1", "close_et": close.isoformat()})
            rows.append(out)
    return pd.DataFrame(rows)


def job_outcomes(ctx: "RunContext") -> dict[str, Any]:
    if ctx.store.exists("outcomes/outcomes.csv.gz") and not ctx.force:
        return {"skipped": "outcomes already written (append-only)"}
    close = et(ctx.day, close_time(ctx.day))
    ctx.wait_until(close + timedelta(minutes=SIP_DELAY_MINUTES))
    # Only the SET of logged symbols is read from the rankings; scores are never used here.
    decisions, symbols = [], set()
    for path in sorted((ctx.store.root / "rankings").glob("*.csv")):
        if ".rerun-" in path.name:
            continue
        frame = pd.read_csv(path, usecols=["decision", "symbol"])
        decisions.extend(frame.decision.astype(str).unique().tolist())
        symbols.update(frame.symbol.astype(str))
    decisions = sorted(set(decisions))
    for decision in decisions:
        awmp.DECISIONS.setdefault(decision, {v: k for k, v in {**SNAPSHOT_DECISIONS, **RANK_DECISIONS}.items()}[decision])
    classes, context, universe_symbols = _load_frozen(ctx)
    # Universe-median control: regular-session bars for every primary stock, aggregated only.
    bars = ctx.bars()
    regular = bars.fetch("regular", universe_symbols, et(ctx.day, "09:30"), close, "5Min")
    logged = compute_outcomes(ctx.day, decisions, sorted(symbols), regular, context)
    rank_decisions = [d for d in decisions if d in RANK_DECISIONS.values()]
    universe_out = compute_outcomes(ctx.day, rank_decisions, universe_symbols, regular, context) if rank_decisions else pd.DataFrame()
    universe_stats = {}
    for decision in rank_decisions:
        sub = universe_out.loc[universe_out.decision == decision]
        universe_stats[decision] = {m: {"median": float(pd.to_numeric(sub[m], errors="coerce").median()),
                                        "mean": float(pd.to_numeric(sub[m], errors="coerce").mean()),
                                        "n": int(pd.to_numeric(sub[m], errors="coerce").notna().sum())}
                                    for m in ("ret_30m", "ret_60m", "ret_close", "mfe", "mae")}
    ctx.store.write_csv("outcomes/outcomes.csv.gz", logged, ctx.force)
    meta = {"decisions": decisions, "logged_symbols": len(symbols), "close_et": close.isoformat(),
            "universe_median_control": universe_stats, "early_close": ctx.day in EARLY_CLOSES}
    ctx.store.write_json("outcomes/outcomes.manifest.json", {**meta, **ctx.stamp()}, ctx.force)
    return {k: v for k, v in meta.items() if k != "universe_median_control"}


def summarise(rankings: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    merged = rankings.merge(outcomes, on=["session_date", "decision", "symbol"], how="left")
    rows = []
    for (decision, list_type), group in merged.groupby(["decision", "list_type"], sort=True):
        num = lambda c: pd.to_numeric(group[c], errors="coerce")  # noqa: E731
        rows.append({
            "decision": decision, "list_type": list_type, "n": int(len(group)),
            "n_with_outcome": int(num("ret_close").notna().sum()),
            "mean_ret_30m": num("ret_30m").mean(), "mean_ret_60m": num("ret_60m").mean(),
            "mean_ret_close": num("ret_close").mean(), "median_ret_close": num("ret_close").median(),
            "mean_mfe": num("mfe").mean(), "median_mae": num("mae").median(),
            "share_abs_close_ge_10pct": (num("ret_close").abs() >= 0.10).mean(),
            "share_positive_close": (num("ret_close") > 0).mean(),
            "hit_up5_before_dn5": num("hit_up5_before_dn5").mean(),
            "hit_up10_before_dn5": num("hit_up10_before_dn5").mean(),
        })
    return pd.DataFrame(rows)


def job_summary(ctx: "RunContext") -> dict[str, Any]:
    if ctx.store.exists("summary.csv") and not ctx.force:
        return {"skipped": "summary already written"}
    if not ctx.store.exists("outcomes/outcomes.csv.gz"):
        ctx.flags.append("OUTCOMES_RUN_FROM_SUMMARY")
        job_outcomes(ctx)
    rankings = pd.concat([pd.read_csv(p) for p in sorted((ctx.store.root / "rankings").glob("*.csv")) if ".rerun-" not in p.name],
                         ignore_index=True)
    outcomes = ctx.store.read_csv("outcomes/outcomes.csv.gz")
    summary = summarise(rankings, outcomes)
    ctx.store.write_csv("summary.csv", summary, ctx.force)
    runs = sorted(p.name for p in (ctx.store.root / "runs").glob("*.json")) if (ctx.store.root / "runs").exists() else []
    primary = summary.loc[summary.decision.eq("open+30")].set_index("list_type")
    payload = {"day": ctx.day, "run_logs": runs, "rows": len(summary),
               "open_plus_30_mean_ret_close": primary["mean_ret_close"].to_dict() if not primary.empty else {}}
    ctx.store.write_json("summary.json", {**payload, **ctx.stamp()}, ctx.force)
    return payload


# ------------------------------------------------------------------ orchestration
class RunContext:
    def __init__(self, job: str, day: str, cutoff: str | None, data_root: Path, *, force: bool = False,
                 limit: int | None = None, no_wait: bool = False, cfg: dict[str, Any] | None = None,
                 sleeper: Callable[[float], None] = time.sleep):
        if job not in JOBS:
            raise ValueError(f"unknown job {job}")
        self.job, self.day, self.cutoff = job, day, (cutoff or "")
        self.force, self.limit, self.no_wait, self.sleeper = force, limit, no_wait, sleeper
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.run_id = os.getenv("GITHUB_RUN_ID", "local") + "-" + os.getenv("GITHUB_RUN_ATTEMPT", "1") + "-" + utc_now().strftime("%H%M%S")
        self.store = Store(data_root, day, self.run_id)
        self.flags: list[str] = []
        self.started = utc_now()
        self.backfill = day < datetime.now(ET).date().isoformat()
        self._bars: Bars | None = None
        self.artifact_dir = Path(os.getenv("SHADOW_ARTIFACT_DIR", "shadow-artifacts"))

    def bars(self) -> Bars:
        if self._bars is None:
            self._bars = Bars(self.cfg)
        return self._bars

    def wait_until(self, moment: datetime, max_wait_minutes: float = 25) -> None:
        delta = (moment - utc_now()).total_seconds()
        if delta <= 0:
            return
        if self.no_wait or delta > max_wait_minutes * 60:
            raise RuntimeError(f"SIP data for {moment.isoformat()} not yet queryable (wait {delta/60:.1f} min)")
        self.flags.append(f"WAITED_{int(delta)}S_FOR_SIP_DELAY")
        self.sleeper(delta + 5)

    def stamp(self) -> dict[str, Any]:
        return {"engine_version": ENGINE_VERSION, "git_sha": os.getenv("GITHUB_SHA", "local"), "run_id": self.run_id,
                "feed": FEED, "mode": "backfill" if self.backfill else "live", "limit": self.limit,
                "research_only": True, "orders_supported": False}


def run(ctx: RunContext) -> dict[str, Any]:
    if not is_trading_day(ctx.day):
        result: dict[str, Any] = {"status": "skipped", "reason": "not an NYSE trading day"}
    else:
        handler = {"universe": job_universe, "snapshot": job_features, "rank": job_features,
                   "outcomes": job_outcomes, "summary": job_summary}[ctx.job]
        try:
            details = handler(ctx)
            result = {"status": "skipped" if "skipped" in details else "ok", "details": details}
        except Exception as exc:  # logged, then re-raised so the workflow run is red
            result = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:500]}
    log = {"job": ctx.job, "day": ctx.day, "cutoff": ctx.cutoff or None, "started_utc": ctx.started.isoformat(),
           "finished_utc": utc_now().isoformat(), "flags": ctx.flags,
           "api": ctx._bars.stats if ctx._bars else [], **result, **ctx.stamp()}
    tag = f"{ctx.job}-{ctx.cutoff.replace(':', '') or 'na'}-{ctx.run_id}"
    ctx.store.root.mkdir(parents=True, exist_ok=True)
    ctx.store.write_json(f"runs/{tag}.json", log)
    return log
