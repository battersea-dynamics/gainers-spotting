#!/usr/bin/env python3
"""Analyse a whole-US-market five-minute discovery pilot.

The script creates point-in-time channel rankings and candidate unions at
09:30, 09:45 and 10:00 America/New_York time. Future outcomes are written to a
separate file and never appear in ranking artifacts. The pilot is descriptive
research only and contains no order functionality.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


EASTERN = ZoneInfo("America/New_York")
PILOT_VERSION = "whole-market-five-minute-pilot-v1"
FEATURE_VERSION = "broad-five-minute-features-v1"
CHANNEL_VERSION = "independent-channel-ranks-v1"
OUTCOME_VERSION = "whole-market-five-minute-outcomes-v1"
DECISIONS = {"open": "09:30", "open+15": "09:45", "open+30": "10:00"}
CHANNEL_BUDGETS = (20, 50, 100)
MFE_THRESHOLDS = (0.10, 0.20, 0.30)
RAW_EXTREME_THRESHOLDS = (0.30, 0.50, 0.80, 1.00)
CHANNEL_REASON_CODES = {
    "absolute_activity": "ABNORMAL_DOLLAR_ACTIVITY",
    "daily_volume_activation": "UNUSUAL_ACTIVITY_VS_DAILY_BASELINE",
    "dormant_activation": "DORMANT_TO_ACTIVE",
    "emerging_structure": "EMERGING_PRICE_STRUCTURE",
    "opening_confirmation": "OPENING_CONFIRMATION",
}
FUTURE_COLUMNS = {
    "entry_price", "ret_5m", "ret_15m", "ret_30m", "ret_60m",
    "ret_120m", "ret_close", "mfe", "mae", "regular_high",
    "raw_previous_close_to_regular_high", "true_previous_close_to_regular_high",
}


def _clock(session_date: str, value: str) -> pd.Timestamp:
    return pd.Timestamp(f"{session_date} {value}", tz=EASTERN)


def _ret(numerator: float, denominator: float) -> float:
    return numerator / denominator - 1.0 if denominator and denominator > 0 else math.nan


def _finite(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def _weighted_vwap(frame: pd.DataFrame) -> tuple[float, bool]:
    if frame.empty:
        return math.nan, False
    volume = pd.to_numeric(frame["volume"], errors="coerce").clip(lower=0)
    vwap = pd.to_numeric(frame.get("vwap"), errors="coerce")
    fallback = vwap.isna()
    prices = vwap.fillna(pd.to_numeric(frame["close"], errors="coerce"))
    valid = prices.notna() & volume.notna()
    denominator = float(volume.loc[valid].sum())
    if denominator <= 0:
        return math.nan, bool(fallback.any())
    return float((prices.loc[valid] * volume.loc[valid]).sum() / denominator), bool(fallback.any())


def _dollar_volume(frame: pd.DataFrame) -> tuple[float, bool]:
    if frame.empty:
        return 0.0, False
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0).clip(lower=0)
    vwap = pd.to_numeric(frame.get("vwap"), errors="coerce")
    fallback = vwap.isna()
    prices = vwap.fillna(pd.to_numeric(frame["close"], errors="coerce"))
    return float((prices.fillna(0) * volume).sum()), bool(fallback.any())


def _window_return(frame: pd.DataFrame) -> float:
    if frame.empty:
        return math.nan
    ordered = frame.sort_values("timestamp_et")
    return _ret(_finite(ordered.iloc[-1].close), _finite(ordered.iloc[0].open))


def _load_bars(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"symbol", "session_date", "timestamp_et", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{path.name} is missing fields: {', '.join(missing)}")
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["timestamp_et"] = pd.to_datetime(frame["timestamp_et"], errors="coerce", utc=True).dt.tz_convert(EASTERN)
    for field in ("open", "high", "low", "close", "volume", "trade_count", "vwap"):
        if field in frame:
            frame[field] = pd.to_numeric(frame[field], errors="coerce")
    return frame.dropna(subset=["symbol", "timestamp_et"]).sort_values(["symbol", "timestamp_et"])


def _read_inputs(pilot_dir: Path) -> tuple[dict, dict, pd.DataFrame, pd.DataFrame]:
    metadata = json.loads((pilot_dir / "collection-metadata.json").read_text(encoding="utf-8"))
    universe_path = pilot_dir / "universe.json"
    if not universe_path.exists():
        universe_path = Path(str(metadata["universe_source"]))
        if not universe_path.is_absolute():
            candidates = [universe_path, Path.cwd() / universe_path]
            universe_path = next((path for path in candidates if path.exists()), universe_path)
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    if metadata.get("pilot_version") != PILOT_VERSION:
        raise ValueError("Unexpected or missing pilot_version")
    if metadata.get("error"):
        raise ValueError(f"Collection metadata contains an error: {metadata['error']}")
    if metadata.get("universe_content_sha256") != universe.get("universe_content_sha256"):
        raise ValueError("Universe hash does not match collection metadata")
    for section in ("daily_history", "broad_five_minute"):
        if metadata.get(section, {}).get("completed") is not True:
            raise ValueError(f"Collection section did not complete: {section}")
    daily = _load_bars(pilot_dir / "daily-bars.csv.gz")
    broad = _load_bars(pilot_dir / "broad-five-minute-bars.csv.gz")
    return metadata, universe, daily, broad


def _daily_context(history: pd.DataFrame, previous_session: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "previous_close_raw": math.nan,
        "previous_daily_volume": math.nan,
        "dormancy_sessions_available_20": 0,
        "dormancy_median_daily_volume_20": math.nan,
        "dormancy_median_daily_dollar_volume_20": math.nan,
        "dormancy_median_daily_range_20": math.nan,
        "dormancy_close_return_volatility_20": math.nan,
        "dormancy_max_abs_close_return_20": math.nan,
    }
    if history.empty:
        return result
    ordered = history.sort_values("timestamp_et")
    previous = ordered.loc[ordered["session_date"].astype(str) == previous_session]
    if not previous.empty:
        result["previous_close_raw"] = _finite(previous.iloc[-1].close)
        result["previous_daily_volume"] = _finite(previous.iloc[-1].volume)
    result["dormancy_sessions_available_20"] = min(len(ordered), 20)
    if len(ordered) < 20:
        return result
    baseline = ordered.tail(20).copy()
    daily_volume = pd.to_numeric(baseline.volume, errors="coerce")
    price = pd.to_numeric(baseline.vwap, errors="coerce").fillna(pd.to_numeric(baseline.close, errors="coerce"))
    daily_range = pd.to_numeric(baseline.high, errors="coerce") / pd.to_numeric(baseline.low, errors="coerce") - 1.0
    close_returns = pd.to_numeric(baseline.close, errors="coerce").pct_change(fill_method=None).dropna()
    result.update({
        "dormancy_median_daily_volume_20": float(daily_volume.median()),
        "dormancy_median_daily_dollar_volume_20": float((price * daily_volume).median()),
        "dormancy_median_daily_range_20": float(daily_range.median()),
        "dormancy_close_return_volatility_20": float(close_returns.std(ddof=0)) if len(close_returns) else math.nan,
        "dormancy_max_abs_close_return_20": float(close_returns.abs().max()) if len(close_returns) else math.nan,
    })
    return result


def _after_hours_context(frame: pd.DataFrame, previous_close: float) -> dict[str, Any]:
    result = {
        "after_hours_active_bars": 0,
        "after_hours_volume": 0.0,
        "after_hours_dollar_volume": 0.0,
        "after_hours_return": math.nan,
        "after_hours_range": math.nan,
        "after_hours_fade_from_high": math.nan,
        "after_hours_last_vs_previous_close_raw": math.nan,
        "after_hours_last": math.nan,
        "after_hours_high": math.nan,
    }
    if frame.empty:
        return result
    ordered = frame.sort_values("timestamp_et")
    first = _finite(ordered.iloc[0].open)
    last = _finite(ordered.iloc[-1].close)
    high = _finite(ordered.high.max())
    low = _finite(ordered.low.min())
    dollar, _ = _dollar_volume(ordered)
    result.update({
        "after_hours_active_bars": int(len(ordered)),
        "after_hours_volume": float(ordered.volume.sum()),
        "after_hours_dollar_volume": dollar,
        "after_hours_return": _ret(last, first),
        "after_hours_range": _ret(high, low),
        "after_hours_fade_from_high": _ret(last, high),
        "after_hours_last_vs_previous_close_raw": _ret(last, previous_close),
        "after_hours_last": last,
        "after_hours_high": high,
    })
    return result


def _eligible_completed(frame: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    return frame.loc[frame.timestamp_et + pd.Timedelta(minutes=5) <= cutoff]


def _decision_features(
    *,
    session_date: str,
    decision: str,
    current_bars: pd.DataFrame,
    daily: dict[str, Any],
    after_hours: dict[str, Any],
    collection_failed: bool,
) -> dict[str, Any]:
    cutoff = _clock(session_date, DECISIONS[decision])
    open_time = _clock(session_date, "09:30")
    completed = _eligible_completed(current_bars, cutoff)
    pm = completed.loc[(completed.timestamp_et >= _clock(session_date, "04:00")) & (completed.timestamp_et < open_time)]
    opening = completed.loc[(completed.timestamp_et >= open_time) & (completed.timestamp_et < cutoff)]
    latest_15 = pm.loc[pm.timestamp_et >= _clock(session_date, "09:15")]
    previous_15 = pm.loc[(pm.timestamp_et >= _clock(session_date, "09:00")) & (pm.timestamp_et < _clock(session_date, "09:15"))]

    row: dict[str, Any] = {**daily, **after_hours}
    if collection_failed:
        zero_or_missing = math.nan
        collection_status = "failed"
    else:
        zero_or_missing = 0.0
        collection_status = "completed"
    row.update({
        "decision": decision,
        "decision_timestamp_et": cutoff.isoformat(),
        "market_event_cutoff_et": (cutoff - pd.Timedelta(minutes=5)).isoformat(),
        "information_available_at_et": cutoff.isoformat(),
        "data_mode": "historical_sip_zero_delay_assumption",
        "broad_collection_status": collection_status,
        "pm_bar_count": int(len(pm)) if not collection_failed else math.nan,
        "pm_active_bars": int((pm.volume > 0).sum()) if not collection_failed else math.nan,
        "pm_volume": float(pm.volume.sum()) if not collection_failed else zero_or_missing,
        "pm_trade_count": float(pm.trade_count.sum()) if "trade_count" in pm and not collection_failed else zero_or_missing,
        "pm_first": math.nan,
        "pm_last": math.nan,
        "pm_return": math.nan,
        "pm_range": math.nan,
        "pm_range_position": math.nan,
        "pm_drawdown_from_high": math.nan,
        "pm_last_vs_vwap": math.nan,
        "pm_return_latest_15m": _window_return(latest_15),
        "pm_price_acceleration_15m": (
            _window_return(latest_15) - _window_return(previous_15)
            if math.isfinite(_window_return(latest_15)) and math.isfinite(_window_return(previous_15))
            else math.nan
        ),
        "pm_volume_acceleration_15m": (
            math.log1p(float(latest_15.volume.sum())) - math.log1p(float(previous_15.volume.sum()))
            if not collection_failed else math.nan
        ),
        "pm_staleness_minutes": math.nan,
        "opening_bar_count": int(len(opening)) if not collection_failed else math.nan,
        "opening_return": _window_return(opening),
        "opening_volume": float(opening.volume.sum()) if not collection_failed else zero_or_missing,
        "opening_range_position": math.nan,
        "opening_drawdown_from_high": math.nan,
        "decision_price": math.nan,
        "decision_vs_previous_close_raw": math.nan,
        "decision_vs_after_hours_last": math.nan,
        "decision_vs_after_hours_high": math.nan,
        "true_gap": math.nan,
        "true_gap_verified": False,
        "spread_available": False,
    })
    pm_dollar, pm_fallback = _dollar_volume(pm) if not collection_failed else (math.nan, False)
    opening_dollar, opening_fallback = _dollar_volume(opening) if not collection_failed else (math.nan, False)
    row["pm_dollar_volume"] = pm_dollar
    row["opening_dollar_volume"] = opening_dollar
    row["dollar_volume_price_fallback"] = pm_fallback or opening_fallback

    if not pm.empty:
        ordered = pm.sort_values("timestamp_et")
        first = _finite(ordered.iloc[0].open)
        last = _finite(ordered.iloc[-1].close)
        high = _finite(ordered.high.max())
        low = _finite(ordered.low.min())
        vwap, fallback = _weighted_vwap(ordered)
        row.update({
            "pm_first": first,
            "pm_last": last,
            "pm_return": _ret(last, first),
            "pm_range": _ret(high, low),
            "pm_range_position": (last - low) / (high - low) if high > low else 0.5,
            "pm_drawdown_from_high": _ret(last, high),
            "pm_last_vs_vwap": _ret(last, vwap),
            "pm_staleness_minutes": float((cutoff - (ordered.iloc[-1].timestamp_et + pd.Timedelta(minutes=5))).total_seconds() / 60.0),
            "dollar_volume_price_fallback": row["dollar_volume_price_fallback"] or fallback,
        })
    if not opening.empty:
        last = _finite(opening.iloc[-1].close)
        high = _finite(opening.high.max())
        low = _finite(opening.low.min())
        row["opening_range_position"] = (last - low) / (high - low) if high > low else 0.5
        row["opening_drawdown_from_high"] = _ret(last, high)
    if not completed.empty:
        decision_price = _finite(completed.iloc[-1].close)
        row["decision_price"] = decision_price
        row["decision_vs_previous_close_raw"] = _ret(decision_price, _finite(daily["previous_close_raw"]))
        row["decision_vs_after_hours_last"] = _ret(decision_price, _finite(after_hours["after_hours_last"]))
        row["decision_vs_after_hours_high"] = _ret(decision_price, _finite(after_hours["after_hours_high"]))

    median_daily = _finite(daily["dormancy_median_daily_volume_20"])
    row["pm_volume_to_median_daily_volume_20"] = (
        float(row["pm_volume"]) / median_daily
        if math.isfinite(_finite(row["pm_volume"])) and math.isfinite(median_daily) and median_daily > 0
        else math.nan
    )
    row["pm_log_volume_surprise_vs_daily_20"] = (
        math.log1p(float(row["pm_volume"])) - math.log1p(median_daily)
        if math.isfinite(_finite(row["pm_volume"])) and math.isfinite(median_daily) and median_daily >= 0
        else math.nan
    )
    core = [
        "pm_dollar_volume", "pm_active_bars", "pm_return_latest_15m",
        "pm_range_position", "pm_last_vs_vwap",
        "pm_log_volume_surprise_vs_daily_20",
        "dormancy_close_return_volatility_20",
        "dormancy_max_abs_close_return_20",
    ]
    row["feature_coverage"] = float(pd.Series([row[name] for name in core]).notna().mean())
    flags = ["CORPORATE_ACTIONS_UNAVAILABLE", "SPREAD_UNAVAILABLE"]
    if collection_failed:
        flags.append("COLLECTION_FAILED")
    elif len(pm) == 0:
        flags.append("NO_PREMARKET_TRADES")
    if daily["dormancy_sessions_available_20"] < 20:
        flags.append("INSUFFICIENT_20_SESSION_HISTORY")
    if math.isfinite(_finite(row["pm_staleness_minutes"])) and row["pm_staleness_minutes"] > 15:
        flags.append("STALE_LAST_PRINT_OVER_15M")
    row["data_quality_and_risk_flags"] = "|".join(flags)
    return row


def _outcomes(session_date: str, decision: str, regular: pd.DataFrame, previous_close: float) -> dict[str, Any]:
    result = {name: math.nan for name in FUTURE_COLUMNS}
    cutoff = _clock(session_date, DECISIONS[decision])
    future = regular.loc[regular.timestamp_et >= cutoff].sort_values("timestamp_et")
    if regular.empty:
        return result
    regular_high = _finite(regular.high.max())
    result["regular_high"] = regular_high
    result["raw_previous_close_to_regular_high"] = _ret(regular_high, previous_close)
    result["true_previous_close_to_regular_high"] = math.nan
    if future.empty:
        return result
    entry = _finite(future.iloc[0].open)
    result["entry_price"] = entry
    for minutes in (5, 15, 30, 60, 120):
        eligible = future.loc[future.timestamp_et + pd.Timedelta(minutes=5) <= cutoff + pd.Timedelta(minutes=minutes)]
        result[f"ret_{minutes}m"] = _ret(_finite(eligible.iloc[-1].close), entry) if not eligible.empty else math.nan
    result["ret_close"] = _ret(_finite(future.iloc[-1].close), entry)
    result["mfe"] = _ret(_finite(future.high.max()), entry)
    result["mae"] = _ret(_finite(future.low.min()), entry)
    return result


def build_feature_and_outcome_frames(
    metadata: dict,
    universe: dict,
    daily_bars: pd.DataFrame,
    broad_bars: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    session_date = str(metadata["research_date"])
    previous_session = str(metadata["previous_session_date"])
    symbols = [str(item["symbol"]).upper() for item in universe.get("assets", [])]
    daily_groups = {symbol: frame for symbol, frame in daily_bars.groupby("symbol", sort=False)}
    broad_groups = {symbol: frame for symbol, frame in broad_bars.groupby("symbol", sort=False)}
    broad_failures = metadata.get("broad_five_minute", {}).get("failures", {})
    failed = {
        symbol for symbol, reason in broad_failures.items()
        if reason != "No bars returned for the requested window"
    }
    feature_rows: list[dict[str, Any]] = []
    outcome_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        daily = _daily_context(daily_groups.get(symbol, daily_bars.iloc[0:0]), previous_session)
        all_bars = broad_groups.get(symbol, broad_bars.iloc[0:0])
        after_hours_bars = all_bars.loc[
            (all_bars.session_date.astype(str) == previous_session)
            & (all_bars.timestamp_et.dt.time >= datetime.strptime("16:00", "%H:%M").time())
            & (all_bars.timestamp_et.dt.time < datetime.strptime("20:00", "%H:%M").time())
        ]
        current = all_bars.loc[all_bars.session_date.astype(str) == session_date]
        regular = current.loc[
            (current.timestamp_et >= _clock(session_date, "09:30"))
            & (current.timestamp_et < _clock(session_date, "16:00"))
        ]
        after_hours = _after_hours_context(after_hours_bars, _finite(daily["previous_close_raw"]))
        for decision in DECISIONS:
            features = _decision_features(
                session_date=session_date,
                decision=decision,
                current_bars=current,
                daily=daily,
                after_hours=after_hours,
                collection_failed=symbol in failed,
            )
            features.update({
                "session_date": session_date,
                "symbol": symbol,
                "research_only": True,
                "orders_supported": False,
                "feed": metadata.get("feed", "sip"),
                "feature_set_version": FEATURE_VERSION,
                "universe_rule_version": metadata.get("universe_rule_version"),
                "universe_content_sha256": metadata.get("universe_content_sha256"),
            })
            feature_rows.append(features)
            outcomes = _outcomes(session_date, decision, regular, _finite(daily["previous_close_raw"]))
            outcomes.update({
                "session_date": session_date,
                "symbol": symbol,
                "decision": decision,
                "outcome_set_version": OUTCOME_VERSION,
                "corporate_action_verified": False,
            })
            outcome_rows.append(outcomes)
    return pd.DataFrame(feature_rows), pd.DataFrame(outcome_rows)


def _percentile(series: pd.Series, *, higher_is_better: bool = True) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.rank(method="average", pct=True, ascending=higher_is_better)


def _mean_with_coverage(frame: pd.DataFrame, components: list[pd.Series]) -> tuple[pd.Series, pd.Series]:
    values = pd.concat(components, axis=1)
    return values.mean(axis=1, skipna=True), values.notna().mean(axis=1)


def channel_scores(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    scored_frames: list[pd.DataFrame] = []
    channel_rows: list[pd.DataFrame] = []
    for decision, frame in features.groupby("decision", sort=False):
        scored = frame.copy()
        scored["raw_positive_gap_descriptive_score"] = _percentile(scored["decision_vs_previous_close_raw"])
        scored["raw_positive_gap_descriptive_coverage"] = scored["decision_vs_previous_close_raw"].notna().astype(float)
        scored["absolute_activity_score"], scored["absolute_activity_coverage"] = _mean_with_coverage(scored, [
            _percentile(scored["pm_dollar_volume"]),
            _percentile(scored["pm_trade_count"]),
            _percentile(scored["pm_active_bars"]),
        ])
        scored["daily_volume_activation_score"], scored["daily_volume_activation_coverage"] = _mean_with_coverage(scored, [
            _percentile(scored["pm_log_volume_surprise_vs_daily_20"]),
            _percentile(scored["pm_dollar_volume"]),
            _percentile(scored["pm_active_bars"]),
        ])
        scored["dormant_activation_score"], scored["dormant_activation_coverage"] = _mean_with_coverage(scored, [
            _percentile(scored["pm_log_volume_surprise_vs_daily_20"]),
            _percentile(scored["dormancy_max_abs_close_return_20"], higher_is_better=False),
            _percentile(scored["dormancy_close_return_volatility_20"], higher_is_better=False),
        ])
        scored["emerging_structure_score"], scored["emerging_structure_coverage"] = _mean_with_coverage(scored, [
            _percentile(scored["pm_return_latest_15m"]),
            _percentile(scored["pm_price_acceleration_15m"]),
            _percentile(scored["pm_range_position"]),
            _percentile(scored["pm_drawdown_from_high"]),
            _percentile(scored["pm_last_vs_vwap"]),
        ])
        scored["opening_confirmation_score"], scored["opening_confirmation_coverage"] = _mean_with_coverage(scored, [
            _percentile(scored["opening_return"]),
            _percentile(scored["opening_range_position"]),
            _percentile(scored["opening_drawdown_from_high"]),
            _percentile(scored["opening_dollar_volume"]),
        ])
        scored_frames.append(scored)

        configs = [
            ("raw_positive_gap_descriptive", False),
            ("absolute_activity", True),
            ("daily_volume_activation", True),
            ("dormant_activation", True),
            ("emerging_structure", True),
            ("opening_confirmation", decision != "open"),
        ]
        for channel, enabled in configs:
            values = scored[["session_date", "symbol", "decision"]].copy()
            values["channel"] = channel
            values["channel_score"] = scored[f"{channel}_score"]
            values["channel_feature_coverage"] = scored[f"{channel}_coverage"]
            values["enabled_for_candidate_union"] = enabled
            eligible = values.channel_score.notna() & (scored.broad_collection_status != "failed")
            values["channel_rank"] = math.nan
            ordered = values.loc[eligible].sort_values(
                ["channel_score", "symbol"], ascending=[False, True]
            )
            values.loc[ordered.index, "channel_rank"] = np.arange(1, len(ordered) + 1)
            values["channel_version"] = CHANNEL_VERSION
            channel_rows.append(values)
    return pd.concat(scored_frames, ignore_index=True), pd.concat(channel_rows, ignore_index=True)


def candidate_unions(scored: pd.DataFrame, channels: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[dict[str, Any]]]]:
    output: list[dict[str, Any]] = []
    explanations: dict[str, list[dict[str, Any]]] = {}
    for decision, feature_rows in scored.groupby("decision", sort=False):
        decision_channels = channels.loc[
            (channels.decision == decision) & channels.enabled_for_candidate_union
        ]
        score_lookup = feature_rows.set_index("symbol")
        explanations[decision] = []
        for budget in CHANNEL_BUDGETS:
            hits = decision_channels.loc[decision_channels.channel_rank <= budget]
            for symbol, symbol_hits in hits.groupby("symbol", sort=True):
                channel_names = sorted(symbol_hits.channel.astype(str).unique())
                all_channel_values = decision_channels.loc[
                    decision_channels.symbol == symbol, "channel_score"
                ]
                consensus = float(all_channel_values.mean())
                reasons = [CHANNEL_REASON_CODES[name] for name in channel_names]
                row = score_lookup.loc[symbol]
                output.append({
                    "session_date": row.session_date,
                    "symbol": symbol,
                    "decision": decision,
                    "channel_budget": budget,
                    "channels_hit": "|".join(channel_names),
                    "channel_hit_count": len(channel_names),
                    "reason_codes": "|".join(reasons),
                    "pilot_consensus_score": consensus,
                    "feature_coverage": row.feature_coverage,
                    "data_quality_and_risk_flags": row.data_quality_and_risk_flags,
                    "research_only": True,
                    "orders_supported": False,
                    "channel_version": CHANNEL_VERSION,
                    "universe_content_sha256": row.universe_content_sha256,
                })
        max_budget_rows = [row for row in output if row["decision"] == decision and row["channel_budget"] == max(CHANNEL_BUDGETS)]
        max_budget_rows.sort(key=lambda row: (-row["pilot_consensus_score"], row["symbol"]))
        for rank, row in enumerate(max_budget_rows, start=1):
            row["pilot_consensus_rank"] = rank
            explanations[decision].append({
                "symbol": row["symbol"],
                "rank": rank,
                "channels_hit": row["channels_hit"].split("|"),
                "reason_codes": row["reason_codes"].split("|"),
                "risk_and_data_quality_flags": row["data_quality_and_risk_flags"].split("|"),
            })
    unions = pd.DataFrame(output)
    if not unions.empty:
        unions["pilot_consensus_rank"] = unions.groupby(["decision", "channel_budget"])["pilot_consensus_score"].rank(method="min", ascending=False)
    return unions, explanations


def evaluate(unions: pd.DataFrame, outcomes: pd.DataFrame, universe_size: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    label_configs = [
        ("remaining_mfe", "mfe", MFE_THRESHOLDS, True),
        ("raw_extreme_gainer_unverified", "raw_previous_close_to_regular_high", RAW_EXTREME_THRESHOLDS, False),
    ]
    for decision in DECISIONS:
        decision_outcomes = outcomes.loc[outcomes.decision == decision]
        for budget in CHANNEL_BUDGETS:
            candidates = set(unions.loc[
                (unions.decision == decision) & (unions.channel_budget == budget), "symbol"
            ])
            for label_name, field, thresholds, verified in label_configs:
                eligible = decision_outcomes.dropna(subset=[field])
                evaluated_candidates = eligible.loc[eligible.symbol.isin(candidates)]
                for threshold in thresholds:
                    positives = set(eligible.loc[eligible[field] >= threshold, "symbol"])
                    detected = candidates & positives
                    candidate_positives = int((evaluated_candidates[field] >= threshold).sum())
                    rows.append({
                        "session_date": decision_outcomes.session_date.iloc[0],
                        "decision": decision,
                        "channel_budget": budget,
                        "label": label_name,
                        "threshold": threshold,
                        "label_verified": verified,
                        "universe_size": universe_size,
                        "label_eligible_symbols": int(len(eligible)),
                        "candidate_union_size": len(candidates),
                        "evaluated_candidates": int(len(evaluated_candidates)),
                        "whole_universe_positives": len(positives),
                        "detected_positives": len(detected),
                        "false_positives": int(len(evaluated_candidates) - candidate_positives),
                        "recall": len(detected) / len(positives) if positives else math.nan,
                        "precision": candidate_positives / len(evaluated_candidates) if len(evaluated_candidates) else math.nan,
                    })
    return pd.DataFrame(rows)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def run(pilot_dir: Path) -> Path:
    metadata, universe, daily, broad = _read_inputs(pilot_dir)
    analysis_dir = pilot_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    features, outcomes = build_feature_and_outcome_frames(metadata, universe, daily, broad)
    scored, channels = channel_scores(features)
    unions, explanations = candidate_unions(scored, channels)
    evaluation = evaluate(unions, outcomes, len(universe.get("assets", [])))

    assets = pd.DataFrame(universe.get("assets", []))
    assets.to_csv(analysis_dir / "universe.csv.gz", index=False, compression="gzip")
    scored.to_csv(analysis_dir / "broad-features.csv.gz", index=False, compression="gzip")
    channels.to_csv(analysis_dir / "channel-rankings.csv.gz", index=False, compression="gzip")
    unions.to_csv(analysis_dir / "candidate-unions.csv.gz", index=False, compression="gzip")
    outcomes.to_csv(analysis_dir / "retrospective-outcomes.csv.gz", index=False, compression="gzip")
    evaluation.to_csv(analysis_dir / "pilot-evaluation.csv", index=False)

    max_budget = max(CHANNEL_BUDGETS)
    ranking_columns = [column for column in scored.columns if column not in FUTURE_COLUMNS]
    for decision in DECISIONS:
        selected = unions.loc[
            (unions.decision == decision) & (unions.channel_budget == max_budget)
        ].merge(scored[ranking_columns], on=["session_date", "symbol", "decision"], how="left", suffixes=("", "_feature"))
        if any(column in selected for column in FUTURE_COLUMNS):
            raise AssertionError("Point-in-time ranking contains future outcomes")
        selected.sort_values(["pilot_consensus_rank", "symbol"]).to_csv(
            analysis_dir / f"rankings-{decision.replace('+', '-plus-')}.csv.gz",
            index=False,
            compression="gzip",
        )

    (analysis_dir / "ranking-explanations.json").write_text(
        json.dumps(_json_safe(explanations), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    api_usage = {
        "alpaca_requests": sum(
            len(metadata.get(section, {}).get("page_requests", []))
            for section in ("daily_history", "broad_five_minute")
        ),
        "alpaca_pages": sum(
            int(metadata.get(section, {}).get("pages", 0))
            for section in ("daily_history", "broad_five_minute")
        ),
        "finnhub_calls": 0,
        "llm_calls": 0,
        "cache_hits": 0,
        "cache_misses": 2,
        "request_interval_seconds": metadata.get("request_interval_seconds"),
    }
    (analysis_dir / "api-cache-usage.json").write_text(
        json.dumps(api_usage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    premarket_open = scored.loc[scored.decision == "open"]
    snapshot_time = pd.Timestamp(universe["universe_snapshot_at_utc"])
    session_close = _clock(str(metadata["research_date"]), "16:00").tz_convert("UTC")
    snapshot_status = (
        "captured_on_or_before_session_close"
        if snapshot_time <= session_close
        else "post_session_snapshot_survivorship_risk"
    )
    broad_failures = metadata.get("broad_five_minute", {}).get("failures", {})
    no_bar_symbols = [
        symbol for symbol, reason in broad_failures.items()
        if reason == "No bars returned for the requested window"
    ]
    rejected_symbols = sorted(set(broad_failures) - set(no_bar_symbols))
    quality = {
        "research_date": metadata["research_date"],
        "universe_assets": len(universe.get("assets", [])),
        "universe_snapshot_status": snapshot_status,
        "daily_symbols_with_bars": len(metadata.get("daily_history", {}).get("successful_symbols", [])),
        "broad_symbols_with_bars": len(metadata.get("broad_five_minute", {}).get("successful_symbols", [])),
        "broad_symbols_with_no_bars": len(no_bar_symbols),
        "broad_rejected_or_failed_symbols": len(rejected_symbols),
        "symbols_with_premarket_bars": int((premarket_open.pm_bar_count.fillna(0) > 0).sum()),
        "symbols_with_20_session_history": int((premarket_open.dormancy_sessions_available_20 >= 20).sum()),
        "corporate_action_status": metadata.get("corporate_actions", {}).get("status"),
        "verified_true_gap_count": int(premarket_open.true_gap.notna().sum()),
        "spread_status": "unavailable_not_collected",
        "historical_premarket_baseline_status": "not_collected_in_five_minute_volume_pilot",
        "five_minute_detail_limitation": (
            "This pilot measures broad coverage and discovery burden. Candidate-detail "
            "one-minute collection is a later stage."
        ),
    }
    (analysis_dir / "data-quality.json").write_text(
        json.dumps(quality, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "pilot_version": PILOT_VERSION,
        "feature_set_version": FEATURE_VERSION,
        "channel_version": CHANNEL_VERSION,
        "outcome_set_version": OUTCOME_VERSION,
        "research_only": True,
        "orders_supported": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "session_date": metadata["research_date"],
        "decisions": DECISIONS,
        "channel_budgets": list(CHANNEL_BUDGETS),
        "enabled_channels": sorted(CHANNEL_REASON_CODES),
        "disabled_channels": {
            "raw_positive_gap_descriptive": "Corporate actions are unavailable; raw gap cannot select candidates."
        },
        "universe_content_sha256": metadata["universe_content_sha256"],
        "universe_snapshot_status": snapshot_status,
        "completed_bar_rule": "five-minute bar start + 5 minutes <= decision timestamp",
        "ranking_outcome_separation": True,
        "candidate_budget_policy": "Report 20/50/100 per-channel union curves; no operational budget is approved.",
        "ranking_policy": "Transparent equal mean of enabled channel percentile scores; exploratory pilot baseline only.",
        "files": sorted(path.name for path in analysis_dir.iterdir() if path.is_file()),
    }
    (analysis_dir / "run-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    digest = hashlib.sha256(
        (analysis_dir / "run-manifest.json").read_bytes()
    ).hexdigest()
    print(json.dumps({
        "analysis_dir": str(analysis_dir),
        "universe_assets": len(universe.get("assets", [])),
        "feature_rows": len(scored),
        "channel_rows": len(channels),
        "candidate_union_rows": len(unions),
        "manifest_sha256": digest,
    }, sort_keys=True))
    return analysis_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-dir", required=True, type=Path)
    args = parser.parse_args()
    run(args.pilot_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
