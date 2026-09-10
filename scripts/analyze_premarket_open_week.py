#!/usr/bin/env python3
"""Leakage-safe, research-only analysis of premarket selection and opening entries.

The script consumes historical Alpaca SIP one-minute bars already collected by
``collect_alpaca_bars.py``.  It never connects to a broker and contains no order
code.  Every feature is cut off at its stated decision time (09:30, 09:45 or
10:00 ET); later bars are used only as outcomes.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu, spearmanr


DECISIONS = ("09:30", "09:45", "10:00")
OUTCOMES = (
    "ret_5m", "ret_15m", "ret_30m", "ret_60m", "ret_120m",
    "ret_noon", "ret_close", "mfe", "mae", "high_to_close_giveback",
)
BAR_FEATURES = (
    "price_at_decision", "pm_bar_count", "pm_return", "pm_range_pct",
    "pm_close_location", "pm_drawdown_from_high", "pm_volume", "pm_trades",
    "pm_dollar_volume", "pm_late_return_0800", "pm_late_return_0900",
    "pm_late_volume_share", "pm_last_vs_vwap", "pm_new_high_count",
    "pm_minutes_since_high", "pm_active_bars_last_60m", "open_return",
    "open_range_pct", "open_close_location", "open_volume", "open_trades",
    "open_dollar_volume", "open_last_vs_vwap", "open_drawdown_from_high",
    "open_recovery_from_low", "open_new_high_count", "decision_vs_pm_high",
)
CONTEXT_FEATURES = (
    "previous_close_raw",
    "true_overnight_gap_raw",
    "true_overnight_gap",
    "decision_vs_previous_close_raw",
    "decision_vs_previous_close",
    "previous_close_to_pm_high_raw",
    "after_hours_active_bars",
    "after_hours_return",
    "after_hours_range_pct",
    "after_hours_volume",
    "after_hours_trades",
    "after_hours_dollar_volume",
    "after_hours_close_location",
    "after_hours_fade_from_high",
    "after_hours_first_vs_previous_close_raw",
    "after_hours_last_vs_previous_close_raw",
    "premarket_first_vs_after_hours_last",
    "decision_vs_after_hours_last",
    "decision_vs_after_hours_high",
    "after_hours_move_retention_at_decision",
    "pm_return_latest_30m",
    "pm_return_previous_30m",
    "premarket_reacceleration_30m",
    *(
        feature
        for window in (20, 60, 120)
        for feature in (
            f"dormancy_median_daily_volume_{window}",
            f"dormancy_median_daily_dollar_volume_{window}",
            f"dormancy_median_daily_range_pct_{window}",
            f"dormancy_close_return_volatility_{window}",
            f"dormancy_max_abs_close_return_{window}",
            f"pm_volume_to_median_daily_volume_{window}",
        )
    ),
)
FEATURES = (*BAR_FEATURES, *CONTEXT_FEATURES)


def _premarket_selection(rows: pd.DataFrame) -> pd.DataFrame:
    """Return symbols available to the premarket selection process."""
    return rows[rows.group.isin(["premarket_candidate", "premarket_observed"])]


def _finite(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def _ret(end: float, start: float) -> float:
    return end / start - 1.0 if start and math.isfinite(start) and math.isfinite(end) else math.nan


def load_protocol(path: Path) -> dict[str, object]:
    protocol = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "protocol_version", "feature_set_version", "outcome_set_version",
        "ranking_models", "continuous_primary_outcomes",
        "mfe_sensitivity_thresholds", "top_k", "minimum_training_dates",
    }
    missing = sorted(required - set(protocol))
    if missing:
        raise ValueError(f"Research protocol is missing: {', '.join(missing)}")
    if not protocol["ranking_models"]:
        raise ValueError("Research protocol must define at least one ranking model")
    return protocol


def load_bars(date_dir: Path) -> tuple[pd.DataFrame, str]:
    """Load clean bars, falling back to the JSONL copy if CSV gzip is damaged."""
    csv_path = date_dir / "bars.csv.gz"
    try:
        bars = pd.read_csv(csv_path, compression="gzip")
        source = "bars.csv.gz"
    except (EOFError, OSError):
        rows = []
        with gzip.open(date_dir / "bars.jsonl.gz", "rt", encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
        bars = pd.DataFrame(rows)
        source = "bars.jsonl.gz (CSV integrity fallback)"
    bars["timestamp_et"] = pd.to_datetime(bars["timestamp_et"], utc=True).dt.tz_convert("America/New_York")
    for col in ("open", "high", "low", "close", "volume", "trade_count", "vwap"):
        bars[col] = pd.to_numeric(bars[col], errors="coerce")
    return bars.sort_values(["symbol", "timestamp_et"]).reset_index(drop=True), source


def load_context(
    date_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object], str]:
    """Load optional prior-session context without weakening old datasets."""
    context_dir = date_dir / "context"
    metadata_path = context_dir / "context-metadata.json"
    daily_path = context_dir / "daily-bars.csv.gz"
    after_hours_path = context_dir / "after-hours-bars.csv.gz"
    if not (metadata_path.exists() and daily_path.exists() and after_hours_path.exists()):
        return pd.DataFrame(), pd.DataFrame(), {}, "absent"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("research_date") != date_dir.name:
        raise ValueError(f"Context research_date mismatch in {metadata_path}")
    if metadata.get("context_version") != "prior-session-context-v1":
        raise ValueError(f"Unsupported context version in {metadata_path}")

    def read(path: Path) -> pd.DataFrame:
        frame = pd.read_csv(path, compression="gzip")
        if frame.empty:
            return frame
        frame["timestamp_et"] = pd.to_datetime(
            frame["timestamp_et"], utc=True
        ).dt.tz_convert("America/New_York")
        for column in (
            "open", "high", "low", "close", "volume", "trade_count", "vwap"
        ):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.sort_values(["symbol", "timestamp_et"]).reset_index(drop=True)

    daily = read(daily_path)
    after_hours = read(after_hours_path)
    previous_session = str(metadata.get("previous_session_date") or "")
    if previous_session and not daily.empty:
        if previous_session not in set(daily.session_date.astype(str)):
            raise ValueError(f"Previous session missing from {daily_path}")
    if not after_hours.empty:
        observed_sessions = set(after_hours.session_date.astype(str))
        if observed_sessions != {previous_session}:
            raise ValueError(f"After-hours session mismatch in {after_hours_path}")
    return daily, after_hours, metadata, "context-v1"


def _gzip_ok(path: Path) -> bool:
    try:
        with gzip.open(path, "rb") as handle:
            while handle.read(1024 * 1024):
                pass
        return True
    except (EOFError, OSError):
        return False


def _weighted_vwap(frame: pd.DataFrame) -> float:
    good = frame.dropna(subset=["vwap", "volume"])
    weight = good["volume"].sum()
    return float((good["vwap"] * good["volume"]).sum() / weight) if weight > 0 else math.nan


def _new_high_count(frame: pd.DataFrame) -> float:
    if frame.empty:
        return math.nan
    highs = frame["high"].to_numpy(float)
    prior = np.maximum.accumulate(np.r_[-np.inf, highs[:-1]])
    return float(np.sum(highs > prior))


def _window_return(frame: pd.DataFrame, start: pd.Timestamp) -> float:
    part = frame[frame["timestamp_et"] >= start]
    return _ret(float(part.iloc[-1]["close"]), float(part.iloc[0]["open"])) if not part.empty else math.nan


def _context_feature_values(
    day: str,
    pm: pd.DataFrame,
    known: pd.DataFrame,
    daily_history: pd.DataFrame,
    after_hours: pd.DataFrame,
    metadata: dict[str, object],
) -> dict[str, object]:
    values: dict[str, object] = {name: math.nan for name in CONTEXT_FEATURES}
    corporate = metadata.get("corporate_actions", {})
    adjustment = metadata.get("price_adjustment", {})
    if not isinstance(corporate, dict):
        corporate = {}
    if not isinstance(adjustment, dict):
        adjustment = {}
    status = str(corporate.get("status") or "unavailable")
    affected = {
        str(symbol) for symbol in (corporate.get("affected_symbols") or [])
    }
    symbol = str(known.symbol.iloc[0]) if not known.empty and "symbol" in known else None
    corporate_safe = (
        status in {"checked_no_actions", "verified"}
        and symbol not in affected
        and adjustment.get("comparable_basis") is True
    )
    values["corporate_action_status"] = status
    values["true_gap_verified"] = corporate_safe
    values["context_available"] = bool(metadata)

    history = daily_history.copy()
    if not history.empty:
        history = history[history["session_date"].astype(str) < day]
        history = (
            history.sort_values("session_date")
            .drop_duplicates("session_date", keep="last")
        )
    previous_close = (
        _finite(history.iloc[-1]["close"]) if not history.empty else math.nan
    )
    values["previous_close_raw"] = previous_close
    pm_first = _finite(pm.iloc[0]["open"]) if not pm.empty else math.nan
    pm_high = _finite(pm["high"].max()) if not pm.empty else math.nan
    decision_price = _finite(known.iloc[-1]["close"]) if not known.empty else math.nan
    raw_overnight_gap = _ret(pm_first, previous_close)
    raw_decision_gap = _ret(decision_price, previous_close)
    values["true_overnight_gap_raw"] = raw_overnight_gap
    values["decision_vs_previous_close_raw"] = raw_decision_gap
    values["previous_close_to_pm_high_raw"] = _ret(pm_high, previous_close)
    values["true_overnight_gap"] = raw_overnight_gap if corporate_safe else math.nan
    values["decision_vs_previous_close"] = raw_decision_gap if corporate_safe else math.nan

    after_hours_summary = metadata.get("after_hours", {})
    after_hours_failures = (
        after_hours_summary.get("failures", {})
        if isinstance(after_hours_summary, dict) else {}
    )
    if (
        after_hours.empty
        and isinstance(after_hours_summary, dict)
        and after_hours_summary.get("completed") is True
        and symbol not in after_hours_failures
    ):
        values.update({
            "after_hours_active_bars": 0,
            "after_hours_volume": 0.0,
            "after_hours_trades": 0.0,
            "after_hours_dollar_volume": 0.0,
        })
    if not after_hours.empty:
        ah = after_hours.sort_values("timestamp_et")
        first, last = ah.iloc[0], ah.iloc[-1]
        high = _finite(ah.high.max())
        low = _finite(ah.low.min())
        volume = float(ah.volume.sum())
        dollar_volume = float((ah.vwap.fillna(ah.close) * ah.volume).sum())
        first_price = _finite(first.open)
        last_price = _finite(last.close)
        values.update({
            "after_hours_active_bars": int(len(ah)),
            "after_hours_return": _ret(last_price, first_price),
            "after_hours_range_pct": _ret(high, low),
            "after_hours_volume": volume,
            "after_hours_trades": float(ah.trade_count.sum()),
            "after_hours_dollar_volume": dollar_volume,
            "after_hours_close_location": (
                (last_price - low) / (high - low) if high > low else 0.5
            ),
            "after_hours_fade_from_high": _ret(last_price, high),
            "after_hours_first_vs_previous_close_raw": _ret(
                first_price, previous_close
            ),
            "after_hours_last_vs_previous_close_raw": _ret(
                last_price, previous_close
            ),
            "premarket_first_vs_after_hours_last": _ret(pm_first, last_price),
            "decision_vs_after_hours_last": _ret(decision_price, last_price),
            "decision_vs_after_hours_high": _ret(decision_price, high),
        })
        high_move = _ret(high, previous_close)
        decision_move = _ret(decision_price, previous_close)
        values["after_hours_move_retention_at_decision"] = (
            decision_move / high_move
            if math.isfinite(high_move) and high_move > 0 and math.isfinite(decision_move)
            else math.nan
        )

    if not pm.empty:
        d = pd.Timestamp(day, tz="America/New_York")
        latest = pm[pm.timestamp_et >= d + pd.Timedelta(hours=9)]
        previous = pm[
            (pm.timestamp_et >= d + pd.Timedelta(hours=8, minutes=30))
            & (pm.timestamp_et < d + pd.Timedelta(hours=9))
        ]
        latest_return = (
            _ret(_finite(latest.iloc[-1].close), _finite(latest.iloc[0].open))
            if not latest.empty else math.nan
        )
        previous_return = (
            _ret(_finite(previous.iloc[-1].close), _finite(previous.iloc[0].open))
            if not previous.empty else math.nan
        )
        values["pm_return_latest_30m"] = latest_return
        values["pm_return_previous_30m"] = previous_return
        values["premarket_reacceleration_30m"] = (
            latest_return - previous_return
            if math.isfinite(latest_return) and math.isfinite(previous_return)
            else math.nan
        )

    for window in (20, 60, 120):
        values[f"dormancy_sessions_available_{window}"] = min(len(history), window)
        if len(history) < window:
            continue
        baseline = history.tail(window).copy()
        daily_volume = pd.to_numeric(baseline.volume, errors="coerce")
        daily_dollar = baseline.vwap.fillna(baseline.close) * daily_volume
        daily_range = baseline.high / baseline.low - 1.0
        close_returns = baseline.close.pct_change(fill_method=None).dropna()
        median_volume = float(daily_volume.median())
        values[f"dormancy_median_daily_volume_{window}"] = median_volume
        values[f"dormancy_median_daily_dollar_volume_{window}"] = float(
            daily_dollar.median()
        )
        values[f"dormancy_median_daily_range_pct_{window}"] = float(
            daily_range.median()
        )
        values[f"dormancy_close_return_volatility_{window}"] = (
            float(close_returns.std(ddof=0)) if not close_returns.empty else math.nan
        )
        values[f"dormancy_max_abs_close_return_{window}"] = (
            float(close_returns.abs().max()) if not close_returns.empty else math.nan
        )
        pm_volume = float(pm.volume.sum()) if not pm.empty else math.nan
        values[f"pm_volume_to_median_daily_volume_{window}"] = (
            pm_volume / median_volume
            if math.isfinite(pm_volume) and median_volume > 0 else math.nan
        )
    return values


def _base_features(
    day: str,
    symbol: str,
    group: str,
    bars: pd.DataFrame,
    decision: str,
    daily_history: pd.DataFrame | None = None,
    after_hours: pd.DataFrame | None = None,
    context_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    tz = "America/New_York"
    d = pd.Timestamp(day, tz=tz)
    dec = pd.Timestamp(f"{day} {decision}", tz=tz)
    pm = bars[(bars.timestamp_et >= d + pd.Timedelta(hours=4)) & (bars.timestamp_et < d + pd.Timedelta(hours=9, minutes=30))]
    known = bars[(bars.timestamp_et >= d + pd.Timedelta(hours=4)) & (bars.timestamp_et < dec)]
    opening = bars[(bars.timestamp_et >= d + pd.Timedelta(hours=9, minutes=30)) & (bars.timestamp_et < dec)]
    row: dict[str, object] = {"date": day, "symbol": symbol, "group": group, "decision_et": decision}

    if pm.empty:
        row.update({name: math.nan for name in BAR_FEATURES})
        row["pm_bar_count"] = 0
        row["pm_observable"] = False
    else:
        first, last = pm.iloc[0], pm.iloc[-1]
        high, low = float(pm.high.max()), float(pm.low.min())
        high_at = pm.loc[pm.high.idxmax(), "timestamp_et"]
        total_volume = float(pm.volume.sum())
        pm_vwap = _weighted_vwap(pm)
        last60 = pm[pm.timestamp_et >= d + pd.Timedelta(hours=8, minutes=30)]
        row.update({
            "pm_observable": True,
            "pm_bar_count": int(len(pm)),
            "pm_first": float(first.open), "pm_last": float(last.close),
            "pm_high": high, "pm_low": low,
            "pm_return": _ret(float(last.close), float(first.open)),
            "pm_range_pct": _ret(high, low),
            "pm_close_location": (float(last.close) - low) / (high - low) if high > low else 0.5,
            "pm_drawdown_from_high": _ret(float(last.close), high),
            "pm_volume": total_volume, "pm_trades": float(pm.trade_count.sum()),
            "pm_dollar_volume": float((pm.vwap.fillna(pm.close) * pm.volume).sum()),
            "pm_late_return_0800": _window_return(pm, d + pd.Timedelta(hours=8)),
            "pm_late_return_0900": _window_return(pm, d + pd.Timedelta(hours=9)),
            "pm_late_volume_share": float(pm[pm.timestamp_et >= d + pd.Timedelta(hours=8)].volume.sum() / total_volume) if total_volume else math.nan,
            "pm_last_vs_vwap": _ret(float(last.close), pm_vwap),
            "pm_new_high_count": _new_high_count(pm),
            "pm_minutes_since_high": float((d + pd.Timedelta(hours=9, minutes=30) - high_at).total_seconds() / 60),
            "pm_active_bars_last_60m": int(len(last60)),
        })

    if opening.empty:
        row.update({name: math.nan for name in BAR_FEATURES if name.startswith("open_") or name == "decision_vs_pm_high"})
    else:
        first, last = opening.iloc[0], opening.iloc[-1]
        high, low = float(opening.high.max()), float(opening.low.min())
        ovwap = _weighted_vwap(opening)
        row.update({
            "open_return": _ret(float(last.close), float(first.open)),
            "open_high": high,
            "open_low": low,
            "open_range_pct": _ret(high, low),
            "open_close_location": (float(last.close) - low) / (high - low) if high > low else 0.5,
            "open_volume": float(opening.volume.sum()), "open_trades": float(opening.trade_count.sum()),
            "open_dollar_volume": float((opening.vwap.fillna(opening.close) * opening.volume).sum()),
            "open_last_vs_vwap": _ret(float(last.close), ovwap),
            "open_drawdown_from_high": _ret(float(last.close), high),
            "open_recovery_from_low": _ret(float(last.close), low),
            "open_new_high_count": _new_high_count(opening),
            "decision_vs_pm_high": _ret(float(last.close), _finite(row.get("pm_high"))),
        })
    row["price_at_decision"] = float(known.iloc[-1].close) if not known.empty else math.nan
    row.update(_context_feature_values(
        day,
        pm,
        known,
        daily_history if daily_history is not None else pd.DataFrame(),
        after_hours if after_hours is not None else pd.DataFrame(),
        context_metadata or {},
    ))
    return row


def _outcomes(day: str, bars: pd.DataFrame, decision: str) -> dict[str, object]:
    d = pd.Timestamp(day, tz="America/New_York")
    entry_at = pd.Timestamp(f"{day} {decision}", tz="America/New_York")
    regular = bars[(bars.timestamp_et >= d + pd.Timedelta(hours=9, minutes=30)) & (bars.timestamp_et < d + pd.Timedelta(hours=16))]
    future = regular[regular.timestamp_et >= entry_at]
    if future.empty:
        return {
            "entry_price": math.nan,
            "entry_timestamp_et": None,
            "future_high": math.nan,
            "future_low": math.nan,
            "time_to_high_min": math.nan,
            "time_to_low_min": math.nan,
            **{name: math.nan for name in OUTCOMES},
        }
    entry = future.iloc[0]
    price = float(entry.open)
    result: dict[str, object] = {"entry_price": price, "entry_timestamp_et": entry.timestamp_et.isoformat()}
    for minutes in (5, 15, 30, 60, 120):
        end = entry_at + pd.Timedelta(minutes=minutes)
        completed = future[(future.timestamp_et >= entry_at) & (future.timestamp_et < end)]
        result[f"ret_{minutes}m"] = _ret(float(completed.iloc[-1].close), price) if not completed.empty else math.nan
    noon = future[future.timestamp_et < d + pd.Timedelta(hours=12)]
    result["ret_noon"] = _ret(float(noon.iloc[-1].close), price) if not noon.empty else math.nan
    close_price = float(future.iloc[-1].close)
    future_high = float(future.high.max())
    future_low = float(future.low.min())
    result["ret_close"] = _ret(close_price, price)
    result["mfe"] = _ret(future_high, price)
    result["mae"] = _ret(float(future.low.min()), price)
    favourable_dollars = future_high - price
    result["high_to_close_giveback"] = (
        (future_high - close_price) / favourable_dollars
        if favourable_dollars > 0 else math.nan
    )
    result["future_high"] = future_high
    result["future_low"] = future_low
    result["time_to_high_min"] = float((future.loc[future.high.idxmax(), "timestamp_et"] - entry_at).total_seconds() / 60)
    result["time_to_low_min"] = float((future.loc[future.low.idxmin(), "timestamp_et"] - entry_at).total_seconds() / 60)
    return result


def build_dataset(root: Path, dates: Iterable[str]) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    all_rows, quality = [], []
    for day in dates:
        date_dir = root / day
        metadata = json.loads((date_dir / "metadata.json").read_text(encoding="utf-8"))
        bars, source = load_bars(date_dir)
        daily_context, after_hours_context, context_metadata, context_source = (
            load_context(date_dir)
        )
        requested = list(metadata.get("requested_symbols", []))
        failures = metadata.get("failures", {})
        actual_symbols = sorted(bars.symbol.unique())
        raw_files = sorted((date_dir / "raw").glob("page-*.json.gz"))
        quality.append({
            "date": day, "feed": metadata.get("feed"), "requested_symbols": len(requested),
            "successful_symbols": len(metadata.get("successful_symbols", [])), "failures": len(failures),
            "pages": metadata.get("pagination", {}).get("pages"), "bars": len(bars), "clean_source": source,
            "metadata_total_bars": metadata.get("total_bars"),
            "bar_count_matches_metadata": len(bars) == metadata.get("total_bars"),
            "actual_symbols": len(actual_symbols),
            "symbol_set_matches_successful": set(actual_symbols) == set(metadata.get("successful_symbols", [])),
            "duplicate_symbol_timestamps": int(bars.duplicated(["symbol", "timestamp_et"]).sum()),
            "csv_gzip_integrity": _gzip_ok(date_dir / "bars.csv.gz"),
            "jsonl_gzip_integrity": _gzip_ok(date_dir / "bars.jsonl.gz"),
            "raw_pages_integrity": all(_gzip_ok(path) for path in raw_files),
            "window_start_utc": metadata.get("request", {}).get("start_utc") or metadata.get("requested_time_window", {}).get("start_utc"),
            "window_end_utc": metadata.get("request", {}).get("end_utc") or metadata.get("requested_time_window", {}).get("end_utc"),
            "context_source": context_source,
            "context_daily_bars": len(daily_context),
            "context_after_hours_bars": len(after_hours_context),
            "context_previous_session_date": context_metadata.get("previous_session_date"),
            "context_daily_gzip_integrity": (
                _gzip_ok(date_dir / "context" / "daily-bars.csv.gz")
                if context_source != "absent" else None
            ),
            "context_after_hours_gzip_integrity": (
                _gzip_ok(date_dir / "context" / "after-hours-bars.csv.gz")
                if context_source != "absent" else None
            ),
            "corporate_action_status": (
                context_metadata.get("corporate_actions", {}).get("status")
                if isinstance(context_metadata.get("corporate_actions"), dict)
                else None
            ),
        })
        for symbol, sbars in bars.groupby("symbol", sort=True):
            group = str(sbars.group.iloc[0])
            symbol_daily = (
                daily_context[daily_context.symbol == symbol]
                if not daily_context.empty else pd.DataFrame()
            )
            symbol_after_hours = (
                after_hours_context[after_hours_context.symbol == symbol]
                if not after_hours_context.empty else pd.DataFrame()
            )
            for decision in DECISIONS:
                row = _base_features(
                    day,
                    symbol,
                    group,
                    sbars,
                    decision,
                    daily_history=symbol_daily,
                    after_hours=symbol_after_hours,
                    context_metadata=context_metadata,
                )
                row.update(_outcomes(day, sbars, decision))
                known_high = _finite(row.get("pm_high"))
                if decision != "09:30":
                    opening_high = _finite(row.get("open_high"))
                    if math.isfinite(opening_high):
                        known_high = max(known_high, opening_high) if math.isfinite(known_high) else opening_high
                row["faded_by_30m"] = bool(row["ret_30m"] < 0) if math.isfinite(_finite(row["ret_30m"])) else None
                row["closed_below_entry"] = bool(row["ret_close"] < 0) if math.isfinite(_finite(row["ret_close"])) else None
                row["never_above_entry"] = bool(row["mfe"] <= 0) if math.isfinite(_finite(row["mfe"])) else None
                row["no_new_high_after_decision"] = (
                    bool(row["future_high"] <= known_high)
                    if math.isfinite(_finite(row.get("future_high"))) and math.isfinite(known_high)
                    else None
                )
                all_rows.append(row)
    return pd.DataFrame(all_rows), quality


def _bh_adjust(pvalues: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=pvalues.index, dtype=float)
    valid = pvalues.dropna().sort_values()
    if valid.empty:
        return result
    n = len(valid)
    adjusted = (valid * n / np.arange(1, n + 1)).clip(upper=1.0)
    adjusted = adjusted.iloc[::-1].cummin().iloc[::-1]
    result.loc[adjusted.index] = adjusted
    return result


def correlation_table(rows: pd.DataFrame) -> pd.DataFrame:
    records = []
    for decision in DECISIONS:
        # Later-only movers and retrospective controls were selected with future
        # information. Including them here would leak outcomes into the universe.
        part = _premarket_selection(rows[rows.decision_et == decision])
        for feature in FEATURES:
            if feature.startswith("open_") and decision == "09:30":
                continue
            for outcome in OUTCOMES:
                valid = part[[feature, outcome]].replace([np.inf, -np.inf], np.nan).dropna()
                if len(valid) < 8 or valid[feature].nunique() < 2 or valid[outcome].nunique() < 2:
                    continue
                rho, p = spearmanr(valid[feature], valid[outcome])
                per_date = []
                for day, dpart in valid.join(part[["date"]], how="left").groupby("date"):
                    if len(dpart) >= 5 and dpart[feature].nunique() > 1 and dpart[outcome].nunique() > 1:
                        per_date.append(float(spearmanr(dpart[feature], dpart[outcome]).statistic))
                lodo = []
                for held_out in sorted(part.date.unique()):
                    train = part[part.date != held_out][[feature, outcome]].dropna()
                    if len(train) >= 8 and train[feature].nunique() > 1 and train[outcome].nunique() > 1:
                        lodo.append(float(spearmanr(train[feature], train[outcome]).statistic))
                records.append({"decision_et": decision, "feature": feature, "outcome": outcome,
                                "n": len(valid), "spearman_rho": float(rho), "p_value": float(p),
                                "dates_with_estimate": len(per_date),
                                "dates_same_sign": sum(np.sign(x) == np.sign(rho) for x in per_date),
                                "median_per_date_rho": float(np.median(per_date)) if per_date else math.nan,
                                "lodo_folds": len(lodo),
                                "lodo_same_sign": sum(np.sign(x) == np.sign(rho) for x in lodo),
                                "lodo_min_abs_rho": min((abs(x) for x in lodo), default=math.nan)})
    out = pd.DataFrame(records)
    if not out.empty:
        out["q_value_bh"] = _bh_adjust(out.p_value)
        out["abs_rho"] = out.spearman_rho.abs()
        out = out.sort_values(["decision_et", "outcome", "abs_rho"], ascending=[True, True, False])
    return out


def entry_summary(rows: pd.DataFrame) -> pd.DataFrame:
    return (_premarket_selection(rows).groupby("decision_et", sort=False)
            .agg(symbol_dates=("symbol", "size"), median_entry_price=("entry_price", "median"),
                 median_ret_15m=("ret_15m", "median"), median_ret_30m=("ret_30m", "median"),
                 median_ret_60m=("ret_60m", "median"), median_ret_close=("ret_close", "median"),
                 median_mfe=("mfe", "median"), median_mae=("mae", "median"))
            .reset_index())


def paired_entry_differences(rows: pd.DataFrame) -> pd.DataFrame:
    """Later-entry outcome minus the same symbol/date's 09:30 outcome."""
    primary = _premarket_selection(rows)
    records = []
    for metric in ("ret_15m", "ret_30m", "ret_60m", "ret_close", "mfe", "mae"):
        pivot = primary.pivot_table(index=["date", "symbol"], columns="decision_et", values=metric)
        if "09:30" not in pivot:
            continue
        for later in ("09:45", "10:00"):
            if later not in pivot:
                continue
            diff = (pivot[later] - pivot["09:30"]).dropna()
            records.append({"later_decision_et": later, "metric": metric, "paired_n": len(diff),
                            "median_later_minus_0930": diff.median(),
                            "mean_later_minus_0930": diff.mean(),
                            "share_later_higher": float((diff > 0).mean())})
    return pd.DataFrame(records)


def per_date_summary(rows: pd.DataFrame) -> pd.DataFrame:
    return (rows.groupby(["date", "decision_et", "group"], dropna=False)
            .agg(symbols=("symbol", "size"), pm_observable=("pm_observable", "sum"),
                 median_pm_return=("pm_return", "median"), median_ret_30m=("ret_30m", "median"),
                 median_ret_60m=("ret_60m", "median"), median_ret_close=("ret_close", "median"),
                 median_mfe=("mfe", "median"), median_mae=("mae", "median"))
            .reset_index())


def group_comparison(rows: pd.DataFrame) -> pd.DataFrame:
    records = []
    week = rows[rows.group.isin(["premarket_observed", "post_open_only_observed"])]
    for decision in DECISIONS:
        part = week[week.decision_et == decision]
        for metric in ("ret_30m", "ret_60m", "ret_close", "mfe", "mae"):
            a = part[part.group == "premarket_observed"][metric].dropna()
            b = part[part.group == "post_open_only_observed"][metric].dropna()
            if len(a) and len(b):
                stat = mannwhitneyu(a, b, alternative="two-sided")
                records.append({"decision_et": decision, "metric": metric, "premarket_n": len(a),
                                "post_open_n": len(b), "premarket_median": a.median(),
                                "post_open_median": b.median(), "median_difference": a.median() - b.median(),
                                "mann_whitney_p": stat.pvalue})
    out = pd.DataFrame(records)
    if not out.empty:
        out["q_value_bh"] = _bh_adjust(out.mann_whitney_p)
    return out


def build_rankings(rows: pd.DataFrame, protocol: dict[str, object]) -> pd.DataFrame:
    """Build long-form, within-date rankings without using outcome columns."""
    records: list[dict[str, object]] = []
    candidates = _premarket_selection(rows).copy()
    models = protocol["ranking_models"]
    assert isinstance(models, dict)
    for (day, decision), part in candidates.groupby(["date", "decision_et"], sort=True):
        for model_name, definition in models.items():
            assert isinstance(definition, dict)
            features = list(definition.get("open_features", []))
            if decision != "09:30":
                features.extend(definition.get("delayed_features", []))
            missing = [feature for feature in features if feature not in part.columns]
            if missing:
                raise ValueError(f"Ranking model {model_name} references missing features: {missing}")
            components = pd.DataFrame(index=part.index)
            for feature in features:
                values = pd.to_numeric(part[feature], errors="coerce")
                components[feature] = values.rank(method="average", pct=True)
            scores = components.mean(axis=1, skipna=True)
            coverage = components.notna().mean(axis=1)
            ranks = scores.rank(method="min", ascending=False)
            for index in part.index:
                row = part.loc[index]
                record = {
                    "protocol_version": protocol["protocol_version"],
                    "feature_set_version": protocol["feature_set_version"],
                    "outcome_set_version": protocol["outcome_set_version"],
                    "date": day,
                    "decision_et": decision,
                    "symbol": row["symbol"],
                    "group": row["group"],
                    "model": model_name,
                    "score": float(scores.loc[index]) if pd.notna(scores.loc[index]) else math.nan,
                    "rank": int(ranks.loc[index]) if pd.notna(ranks.loc[index]) else None,
                    "feature_coverage": float(coverage.loc[index]),
                    "features": ",".join(features),
                }
                for outcome in (*OUTCOMES, "time_to_high_min", "time_to_low_min"):
                    record[outcome] = row.get(outcome, math.nan)
                for failure in protocol.get("failure_modes", {}):
                    record[failure] = row.get(failure)
                records.append(record)
    return pd.DataFrame(records).sort_values(
        ["date", "decision_et", "model", "rank", "symbol"], na_position="last"
    ).reset_index(drop=True)


def alert_burden(rankings: pd.DataFrame) -> pd.DataFrame:
    if rankings.empty:
        return pd.DataFrame()
    first_model = str(rankings.model.iloc[0])
    unique_candidates = rankings[rankings.model == first_model]
    return (
        unique_candidates.groupby(["date", "decision_et"], sort=True)
        .agg(candidate_count=("symbol", "nunique"), median_feature_coverage=("feature_coverage", "median"))
        .reset_index()
    )


def top_k_metrics(rankings: pd.DataFrame, protocol: dict[str, object]) -> pd.DataFrame:
    """Evaluate alert budgets inside the observed research universe only."""
    records: list[dict[str, object]] = []
    thresholds = [float(value) for value in protocol["mfe_sensitivity_thresholds"]]
    for (day, decision, model), part in rankings.groupby(["date", "decision_et", "model"], sort=True):
        part = part.dropna(subset=["rank"]).sort_values(["rank", "symbol"])
        for requested_k in protocol["top_k"]:
            selected = part.head(int(requested_k))
            base = {
                "protocol_version": protocol["protocol_version"],
                "date": day,
                "decision_et": decision,
                "model": model,
                "requested_k": int(requested_k),
                "selected_count": int(len(selected)),
                "candidate_count": int(len(part)),
                "median_mfe": selected.mfe.median(),
                "median_mae": selected.mae.median(),
                "median_ret_30m": selected.ret_30m.median(),
                "median_ret_close": selected.ret_close.median(),
            }
            for threshold in thresholds:
                label = f"mfe_ge_{int(round(threshold * 100))}pct"
                total_positive = int((part.mfe >= threshold).sum())
                captured = int((selected.mfe >= threshold).sum())
                base[f"precision_{label}"] = captured / len(selected) if len(selected) else math.nan
                base[f"recall_{label}_within_observed_universe"] = (
                    captured / total_positive if total_positive else math.nan
                )
                base[f"missed_{label}_within_observed_universe"] = total_positive - captured
            records.append(base)
    return pd.DataFrame(records)


def chronological_walk_forward(rankings: pd.DataFrame, protocol: dict[str, object]) -> pd.DataFrame:
    """Choose a model on earlier dates and evaluate it on the next date."""
    records: list[dict[str, object]] = []
    minimum = int(protocol["minimum_training_dates"])
    dates = sorted(rankings.date.unique())
    first_k = int(protocol["top_k"][0])
    first_threshold = float(protocol["mfe_sensitivity_thresholds"][0])
    for decision in DECISIONS:
        decision_rows = rankings[rankings.decision_et == decision]
        for offset in range(minimum, len(dates)):
            train_dates = dates[:offset]
            test_date = dates[offset]
            model_scores: list[tuple[float, str]] = []
            for model, model_rows in decision_rows[decision_rows.date.isin(train_dates)].groupby("model"):
                per_date_rho = []
                for _, date_rows in model_rows.groupby("date"):
                    valid = date_rows[["score", "mfe"]].dropna()
                    if len(valid) >= 3 and valid.score.nunique() > 1 and valid.mfe.nunique() > 1:
                        per_date_rho.append(float(spearmanr(valid.score, valid.mfe).statistic))
                if per_date_rho:
                    model_scores.append((float(np.mean(per_date_rho)), str(model)))
            if not model_scores:
                continue
            train_rho, selected_model = max(model_scores, key=lambda value: (value[0], value[1]))
            test = decision_rows[
                (decision_rows.date == test_date) & (decision_rows.model == selected_model)
            ].sort_values(["rank", "symbol"])
            valid = test[["score", "mfe"]].dropna()
            test_rho = (
                float(spearmanr(valid.score, valid.mfe).statistic)
                if len(valid) >= 3 and valid.score.nunique() > 1 and valid.mfe.nunique() > 1
                else math.nan
            )
            selected = test.head(first_k)
            records.append({
                "protocol_version": protocol["protocol_version"],
                "decision_et": decision,
                "train_dates": ",".join(train_dates),
                "test_date": test_date,
                "selected_model": selected_model,
                "train_mean_per_date_spearman_mfe": train_rho,
                "test_spearman_mfe": test_rho,
                "alert_budget_k": first_k,
                "selected_count": len(selected),
                "test_top_k_median_mfe": selected.mfe.median(),
                f"test_top_k_precision_mfe_ge_{int(round(first_threshold * 100))}pct": (
                    float((selected.mfe >= first_threshold).mean()) if len(selected) else math.nan
                ),
            })
    return pd.DataFrame(records)


def write_findings(out_dir: Path, rows: pd.DataFrame, corr: pd.DataFrame, entry: pd.DataFrame,
                   paired: pd.DataFrame, quality: list[dict[str, object]],
                   protocol: dict[str, object], burden: pd.DataFrame,
                   walk_forward: pd.DataFrame) -> None:
    primary = corr[(corr.outcome == "mfe") & (corr.decision_et == "09:30")].sort_values("abs_rho", ascending=False).head(8)
    fallback_dates = [
        str(item["date"])
        for item in quality
        if item["clean_source"] != "bars.csv.gz"
    ]
    integrity_ok = all(
        item["csv_gzip_integrity"]
        and item["jsonl_gzip_integrity"]
        and item["raw_pages_integrity"]
        for item in quality
    )
    context_dates = [
        str(item["date"]) for item in quality if item.get("context_source") != "absent"
    ]
    corporate_statuses = sorted({
        str(item.get("corporate_action_status"))
        for item in quality
        if item.get("corporate_action_status")
    })
    verified_gaps = int(
        _premarket_selection(rows[rows.decision_et == "09:30"])
        .get("true_gap_verified", pd.Series(dtype=bool))
        .fillna(False)
        .sum()
    )
    lines = [
        "# Collective premarket/open research findings", "",
        "Research-only descriptive analysis. This report does not define a buy rule or an order instruction.",
        f"Protocol: `{protocol['protocol_version']}`. MFE thresholds are sensitivity labels only; continuous outcomes are primary.", "",
        "## Coverage", "",
        f"- Sessions: {', '.join(q['date'] for q in quality)}.",
        f"- Collected symbol-date observations: {len(rows) // len(DECISIONS)}; premarket-selection cohort: {len(_premarket_selection(rows)) // len(DECISIONS)}; fixed entry benchmarks: {', '.join(DECISIONS)} ET.",
        f"- Alpaca feed: SIP; one-minute bars; 04:00–16:00 ET.",
        (
            "- CSV fallback dates: " + ", ".join(fallback_dates) + "."
            if fallback_dates
            else "- All sessions loaded from bars.csv.gz without fallback."
        ),
        (
            "- CSV, JSONL and raw-page gzip integrity checks passed for every session."
            if integrity_ok
            else "- At least one gzip integrity check failed; inspect data-quality.json."
        ),
        (
            f"- Prior-session context loaded for {len(context_dates)}/{len(quality)} "
            f"sessions; corporate-action status: {', '.join(corporate_statuses) or 'unavailable'}; "
            f"corporate-action-safe true gaps: {verified_gaps}."
            if context_dates
            else "- Previous official close and after-hours context are absent. Exact gap features cannot be measured."
        ),
        "- Quote spread, auction imbalance and market-wide non-candidates remain absent. Execution cost, whole-market precision and recall cannot yet be measured.", "",
        "## Closure-to-premarket context", "",
        "Raw daily and after-hours prices are retained on the same adjustment basis. Raw gaps remain descriptive until corporate-action reconciliation marks a symbol safe.",
        "Dormancy windows require 20, 60 or 120 prior sessions respectively; insufficient histories remain missing instead of being filled or shortened.", "",
        "## Entry benchmark comparison", "",
        "| Decision ET | Median 30m return | Median 60m return | Median MFE | Median MAE | Median close return |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in entry.itertuples():
        lines.append(f"| {row.decision_et} | {row.median_ret_30m:.2%} | {row.median_ret_60m:.2%} | {row.median_mfe:.2%} | {row.median_mae:.2%} | {row.median_ret_close:.2%} |")
    lines += ["", "These are unweighted medians for symbols available to the premarket-selection process, not simulated portfolio returns.", "",
              "## Paired timing trade-off", "",
              "| Later decision | Outcome | Median later minus 09:30 | Share later higher |",
              "|---|---|---:|---:|"]
    for row in paired.itertuples():
        lines.append(f"| {row.later_decision_et} | {row.metric} | {row.median_later_minus_0930:.2%} | {row.share_later_higher:.1%} |")
    lines += ["", "A positive difference favours waiting for that metric. For MAE, a less-negative value means reduced adverse excursion.", "",
              "## Strongest 09:30 premarket associations with subsequent MFE", "",
              "| Feature | N | Spearman rho | Dates same direction | LODO same direction | BH q-value |", "|---|---:|---:|---:|---:|---:|"]
    for row in primary.itertuples():
        q = "n/a" if pd.isna(row.q_value_bh) else f"{row.q_value_bh:.3f}"
        lines.append(f"| {row.feature} | {row.n} | {row.spearman_rho:.3f} | {row.dates_same_sign}/{row.dates_with_estimate} | {row.lodo_same_sign}/{row.lodo_folds} | {q} |")
    lines += ["", f"Interpret recurrent direction and effect size before significance. These {len(quality)} selected sessions are hypothesis generation only.", "",
              "## Leakage controls", "",
              "- 09:30 features use bars strictly before 09:30 ET.",
              "- 09:45 and 10:00 features add only completed bars strictly before their decision time.",
              "- Each decision is evaluated separately; the best entry is never chosen after viewing the outcome.",
              "- Post-open bars are labels only and are not used to construct premarket features.", "",
              "## Alert burden", "",
              "Candidate counts below describe only the supplied research universe; they are not whole-market alert counts.", "",
              "| Date | Decision ET | Candidates | Median feature coverage |", "|---|---|---:|---:|"]
    for row in burden.itertuples():
        lines.append(f"| {row.date} | {row.decision_et} | {row.candidate_count} | {row.median_feature_coverage:.1%} |")
    lines += ["", "## Chronological walk-forward", "",
              f"At each fold, model choice uses earlier dates only and is evaluated on the next date. The present {len(quality)}-session, screenshot-selected sample is pipeline validation, not predictive proof.", "",
              "| Decision ET | Test date | Earlier dates | Selected model | Train rho | Test rho | Top-k median MFE |",
              "|---|---|---:|---|---:|---:|---:|"]
    for row in walk_forward.itertuples():
        test_rho = "n/a" if pd.isna(row.test_spearman_mfe) else f"{row.test_spearman_mfe:.3f}"
        lines.append(f"| {row.decision_et} | {row.test_date} | {len(row.train_dates.split(','))} | {row.selected_model} | {row.train_mean_per_date_spearman_mfe:.3f} | {test_rho} | {row.test_top_k_median_mfe:.2%} |")
    lines += ["", "## Selection-bias warning", "",
              "The post-open-only cohort was defined by later Top Movers appearances. Its superior realized outcomes are therefore expected by construction and cannot be used as a predictive benchmark. Main feature correlations and entry summaries exclude that cohort and any retrospective controls.", "",
              "## Next research step", "",
              "Repeat the same frozen calculations on additional dates and validate any candidate feature or cutoff on dates not used to choose it. Add verified corporate-action reconciliation and quote/auction data before treating gap or execution quality as reliable."]
    (out_dir / "research-findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-root", type=Path, default=Path("data/research"))
    parser.add_argument("--dates", nargs="+", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=Path("config/research-protocol-v1.json"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    dates = sorted(dict.fromkeys(args.dates))
    protocol = load_protocol(args.protocol)
    rows, quality = build_dataset(args.research_root, dates)
    corr = correlation_table(rows)
    entry = entry_summary(rows)
    per_date = per_date_summary(rows)
    groups = group_comparison(rows)
    paired = paired_entry_differences(rows)
    rankings = build_rankings(rows, protocol)
    burden = alert_burden(rankings)
    top_k = top_k_metrics(rankings, protocol)
    walk_forward = chronological_walk_forward(rankings, protocol)
    rows.to_csv(args.output_dir / "features-outcomes.csv", index=False)
    corr.to_csv(args.output_dir / "feature-correlations.csv", index=False)
    entry.to_csv(args.output_dir / "entry-comparison.csv", index=False)
    per_date.to_csv(args.output_dir / "per-date-summary.csv", index=False)
    groups.to_csv(args.output_dir / "group-comparison.csv", index=False)
    paired.to_csv(args.output_dir / "paired-entry-differences.csv", index=False)
    ranking_label_columns = [
        *OUTCOMES, "time_to_high_min", "time_to_low_min",
        *protocol.get("failure_modes", {}).keys(),
    ]
    rankings.drop(columns=ranking_label_columns, errors="ignore").to_csv(
        args.output_dir / "candidate-rankings.csv", index=False
    )
    ranking_label_keys = [
        "protocol_version", "outcome_set_version", "date", "decision_et",
        "symbol", "group", "model", "rank",
    ]
    rankings[[*ranking_label_keys, *ranking_label_columns]].to_csv(
        args.output_dir / "candidate-ranking-outcomes.csv", index=False
    )
    burden.to_csv(args.output_dir / "alert-burden.csv", index=False)
    top_k.to_csv(args.output_dir / "top-k-evaluation.csv", index=False)
    walk_forward.to_csv(args.output_dir / "chronological-walk-forward.csv", index=False)
    (args.output_dir / "research-protocol.json").write_text(
        json.dumps(protocol, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "data-quality.json").write_text(json.dumps(quality, indent=2) + "\n", encoding="utf-8")
    write_findings(args.output_dir, rows, corr, entry, paired, quality, protocol, burden, walk_forward)
    print(json.dumps({
        "protocol_version": protocol["protocol_version"],
        "rows": len(rows),
        "symbol_dates": len(rows) // 3,
        "ranking_rows": len(rankings),
        "walk_forward_folds": len(walk_forward),
        "output_dir": str(args.output_dir),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
