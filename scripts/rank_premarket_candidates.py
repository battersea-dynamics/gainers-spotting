#!/usr/bin/env python3
"""Research-only, point-in-time premarket candidate ranking.

This module never connects to a broker and contains no order functionality.  It
reads historical one-minute bars produced by collect_alpaca_bars.py, calculates
features available at a stated decision time, and stores subsequent outcomes
only for retrospective evaluation.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date as date_type
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd


NEW_YORK = ZoneInfo("America/New_York")
DECISIONS = {"open": "09:30", "open+15": "09:45", "open+30": "10:00"}
FEATURE_SET_VERSION = "point-in-time-ranker-v1"
OUTCOME_SET_VERSION = "continuous-outcomes-v1"
SCORE_VERSION = "equal-weight-percentile-v1"
RETROSPECTIVE_ONLY_GROUPS = {"post_open_only_observed", "missed_runner_control"}
REQUIRED_FIELDS = ("symbol", "open", "high", "low", "close", "volume")
ALIASES = {
    "symbol": ("symbol", "s"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c"),
    "volume": ("volume", "v"),
    "vwap": ("vwap", "vw"),
    "trade_count": ("trade_count", "n"),
}
TIMESTAMP_COLUMNS = ("timestamp_utc", "timestamp_et", "timestamp", "t")
OUTCOME_COLUMNS = (
    "entry_price", "return_5m_pct", "return_15m_pct", "return_30m_pct",
    "return_60m_pct", "return_120m_pct", "return_to_noon_pct",
    "return_to_close_pct", "mfe_to_close_pct", "mae_to_close_pct",
    "time_to_mfe_minutes", "time_to_mae_minutes",
    "high_to_close_giveback_fraction", "faded_by_30m", "closed_below_entry",
    "never_above_entry",
)


def _column(columns: Iterable[str], names: Iterable[str]) -> str | None:
    lookup = {str(value).lower(): str(value) for value in columns}
    return next((lookup[name.lower()] for name in names if name.lower() in lookup), None)


def _parse_timestamp(frame: pd.DataFrame) -> pd.Series:
    source = _column(frame.columns, TIMESTAMP_COLUMNS)
    if source is None:
        raise ValueError(f"No timestamp column found; expected one of {TIMESTAMP_COLUMNS}")
    values = frame[source]
    if source.lower() == "timestamp_et":
        parsed = pd.to_datetime(values, errors="coerce")
        if getattr(parsed.dt, "tz", None) is None:
            return parsed.dt.tz_localize(NEW_YORK, ambiguous="NaT", nonexistent="shift_forward")
        return parsed.dt.tz_convert(NEW_YORK)
    return pd.to_datetime(values, errors="coerce", utc=True).dt.tz_convert(NEW_YORK)


def load_bars(path: Path, session_date: str) -> pd.DataFrame:
    raw = pd.read_csv(path)
    rename: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        found = _column(raw.columns, aliases)
        if found is not None:
            rename[found] = canonical
    frame = raw.rename(columns=rename).copy()
    missing = [field for field in REQUIRED_FIELDS if field not in frame.columns]
    if missing:
        raise ValueError(f"Missing required bar columns: {', '.join(missing)}")
    frame["timestamp_et"] = _parse_timestamp(raw)
    for field in ("open", "high", "low", "close", "volume", "vwap", "trade_count"):
        if field in frame:
            frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    wanted = date_type.fromisoformat(session_date)
    frame = frame.loc[frame["timestamp_et"].dt.date == wanted]
    frame = frame.dropna(subset=["timestamp_et", *REQUIRED_FIELDS])
    frame = frame.loc[
        (frame["symbol"] != "")
        & (frame[["open", "high", "low", "close"]] > 0).all(axis=1)
        & (frame["volume"] >= 0)
    ]
    return frame.sort_values(["symbol", "timestamp_et"]).drop_duplicates(
        ["symbol", "timestamp_et"], keep="last"
    )


def discover_input(data_root: Path, session_date: str) -> Path:
    directory = data_root / session_date
    candidates: list[tuple[int, int, Path]] = []
    paths = [*directory.rglob("*.csv"), *directory.rglob("*.csv.gz")]
    for path in paths:
        lowered = path.name.lower()
        if any(token in lowered for token in ("ranking", "outcome", "feature", "summary")):
            continue
        try:
            header = pd.read_csv(path, nrows=0)
        except Exception:
            continue
        fields = {str(column).lower() for column in header.columns}
        required_score = sum(any(alias in fields for alias in ALIASES[field]) for field in REQUIRED_FIELDS)
        timestamp_score = int(any(column in fields for column in TIMESTAMP_COLUMNS))
        if required_score == len(REQUIRED_FIELDS) and timestamp_score:
            clean_score = 1 if "clean" in str(path).lower() else 0
            candidates.append((clean_score, path.stat().st_size, path))
    if not candidates:
        raise FileNotFoundError(f"No clean one-minute bar CSV found below {directory}")
    return max(candidates, key=lambda value: (value[0], value[1]))[2]


def _clock(session_date: str, value: str) -> pd.Timestamp:
    return pd.Timestamp(f"{session_date} {value}", tz=NEW_YORK)


def _weighted_vwap(frame: pd.DataFrame) -> float:
    volume = frame["volume"].clip(lower=0)
    if volume.sum() <= 0:
        return float("nan")
    prices = frame["vwap"] if "vwap" in frame and frame["vwap"].notna().any() else frame["close"]
    valid = prices.notna() & volume.notna()
    denominator = volume.loc[valid].sum()
    return float((prices.loc[valid] * volume.loc[valid]).sum() / denominator) if denominator else float("nan")


def _safe_return(numerator: float, denominator: float) -> float:
    return 100.0 * (numerator / denominator - 1.0) if denominator and denominator > 0 else float("nan")


def _dollar_volume(frame: pd.DataFrame) -> float:
    return float((frame["close"] * frame["volume"]).sum())


def _window_return(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    window = frame.loc[(frame["timestamp_et"] >= start) & (frame["timestamp_et"] < end)]
    if window.empty:
        return float("nan")
    return _safe_return(float(window.iloc[-1]["close"]), float(window.iloc[0]["open"]))


def _premarket_features(symbol: str, bars: pd.DataFrame, session_date: str) -> dict[str, float | str | int]:
    start = _clock(session_date, "04:00")
    open_time = _clock(session_date, "09:30")
    pm = bars.loc[(bars["timestamp_et"] >= start) & (bars["timestamp_et"] < open_time)]
    if pm.empty:
        return {}
    first, last = pm.iloc[0], pm.iloc[-1]
    pm_high, pm_low = float(pm["high"].max()), float(pm["low"].min())
    vwap = _weighted_vwap(pm)
    prior = pm.loc[(pm["timestamp_et"] >= _clock(session_date, "08:30")) & (pm["timestamp_et"] < _clock(session_date, "09:00"))]
    late = pm.loc[(pm["timestamp_et"] >= _clock(session_date, "09:00")) & (pm["timestamp_et"] < open_time)]
    prior_dv, late_dv = _dollar_volume(prior), _dollar_volume(late)
    acceleration = (late_dv + 1.0) / (prior_dv + 1.0)
    last_5 = pm.loc[pm["timestamp_et"] >= _clock(session_date, "09:25")]
    previous_5 = pm.loc[
        (pm["timestamp_et"] >= _clock(session_date, "09:20"))
        & (pm["timestamp_et"] < _clock(session_date, "09:25"))
    ]
    last_15 = pm.loc[pm["timestamp_et"] >= _clock(session_date, "09:15")]
    previous_15 = pm.loc[
        (pm["timestamp_et"] >= _clock(session_date, "09:00"))
        & (pm["timestamp_et"] < _clock(session_date, "09:15"))
    ]
    return_5 = _window_return(pm, _clock(session_date, "09:25"), open_time)
    previous_return_5 = _window_return(
        pm, _clock(session_date, "09:20"), _clock(session_date, "09:25")
    )
    return {
        "symbol": symbol,
        "premarket_first_price": float(first["open"]),
        "premarket_last_price": float(last["close"]),
        "premarket_high": pm_high,
        "premarket_low": pm_low,
        "premarket_return_pct": _safe_return(float(last["close"]), float(first["open"])),
        "premarket_dollar_volume": _dollar_volume(pm),
        "premarket_volume": float(pm["volume"].sum()),
        "premarket_active_minutes": int((pm["volume"] > 0).sum()),
        "premarket_bar_count": int(len(pm)),
        "premarket_trade_count": (
            float(pm["trade_count"].sum()) if "trade_count" in pm else float("nan")
        ),
        "premarket_last_bar_staleness_minutes": float(
            (open_time - last["timestamp_et"]).total_seconds() / 60.0
        ),
        "premarket_range_pct": _safe_return(pm_high, pm_low),
        "premarket_vwap": vwap,
        "premarket_vwap_location_pct": _safe_return(float(last["close"]), vwap),
        "premarket_proximity_to_high_pct": _safe_return(float(last["close"]), pm_high),
        "premarket_green_bar_fraction": float((pm["close"] >= pm["open"]).mean()),
        "premarket_late_dollar_volume": late_dv,
        "premarket_volume_acceleration": acceleration,
        "premarket_log_volume_acceleration": math.log(acceleration),
        "premarket_return_last_5m_pct": return_5,
        "premarket_return_last_15m_pct": _window_return(
            pm, _clock(session_date, "09:15"), open_time
        ),
        "premarket_return_last_30m_pct": _window_return(
            pm, _clock(session_date, "09:00"), open_time
        ),
        "premarket_price_acceleration_5m_pct": (
            return_5 - previous_return_5
            if math.isfinite(return_5) and math.isfinite(previous_return_5)
            else float("nan")
        ),
        "premarket_volume_velocity_last_5m": float(last_5["volume"].sum()) / 5.0,
        "premarket_volume_velocity_last_15m": float(last_15["volume"].sum()) / 15.0,
        "premarket_volume_acceleration_5m": (
            (float(last_5["volume"].sum()) + 1.0)
            / (float(previous_5["volume"].sum()) + 1.0)
        ),
        "premarket_volume_acceleration_15m": (
            (float(last_15["volume"].sum()) + 1.0)
            / (float(previous_15["volume"].sum()) + 1.0)
        ),
    }


def _opening_features(bars: pd.DataFrame, session_date: str, cutoff: pd.Timestamp) -> dict[str, float | int]:
    open_time = _clock(session_date, "09:30")
    opening = bars.loc[(bars["timestamp_et"] >= open_time) & (bars["timestamp_et"] < cutoff)]
    if opening.empty:
        return {
            "opening_return_pct": float("nan"),
            "opening_dollar_volume": 0.0,
            "opening_active_minutes": 0,
            "opening_vwap_location_pct": float("nan"),
            "opening_proximity_to_high_pct": float("nan"),
        }
    first, last = opening.iloc[0], opening.iloc[-1]
    vwap = _weighted_vwap(opening)
    return {
        "opening_return_pct": _safe_return(float(last["close"]), float(first["open"])),
        "opening_dollar_volume": _dollar_volume(opening),
        "opening_active_minutes": int((opening["volume"] > 0).sum()),
        "opening_vwap_location_pct": _safe_return(float(last["close"]), vwap),
        "opening_proximity_to_high_pct": _safe_return(float(last["close"]), float(opening["high"].max())),
    }


def _close_before(frame: pd.DataFrame, timestamp: pd.Timestamp) -> float:
    eligible = frame.loc[frame["timestamp_et"] < timestamp]
    return float(eligible.iloc[-1]["close"]) if not eligible.empty else float("nan")


def _outcomes(bars: pd.DataFrame, session_date: str, cutoff: pd.Timestamp) -> dict[str, float]:
    close_time = _clock(session_date, "16:00")
    future = bars.loc[(bars["timestamp_et"] >= cutoff) & (bars["timestamp_et"] < close_time)]
    if future.empty:
        return {key: float("nan") for key in OUTCOME_COLUMNS}
    entry = float(future.iloc[0]["open"])
    result: dict[str, float] = {"entry_price": entry}
    for minutes in (5, 15, 30, 60, 120):
        price = _close_before(future, cutoff + pd.Timedelta(minutes=minutes))
        result[f"return_{minutes}m_pct"] = _safe_return(price, entry)
    noon = future.loc[future["timestamp_et"] < _clock(session_date, "12:00")]
    close_price = float(future.iloc[-1]["close"])
    high_index = future["high"].idxmax()
    low_index = future["low"].idxmin()
    high_price = float(future.loc[high_index, "high"])
    low_price = float(future.loc[low_index, "low"])
    result["return_to_noon_pct"] = (
        _safe_return(float(noon.iloc[-1]["close"]), entry) if not noon.empty else float("nan")
    )
    result["return_to_close_pct"] = _safe_return(close_price, entry)
    result["mfe_to_close_pct"] = _safe_return(high_price, entry)
    result["mae_to_close_pct"] = _safe_return(low_price, entry)
    result["time_to_mfe_minutes"] = float(
        (future.loc[high_index, "timestamp_et"] - cutoff).total_seconds() / 60.0
    )
    result["time_to_mae_minutes"] = float(
        (future.loc[low_index, "timestamp_et"] - cutoff).total_seconds() / 60.0
    )
    favourable_dollars = high_price - entry
    result["high_to_close_giveback_fraction"] = (
        (high_price - close_price) / favourable_dollars
        if favourable_dollars > 0 else float("nan")
    )
    result["faded_by_30m"] = result["return_30m_pct"] < 0
    result["closed_below_entry"] = result["return_to_close_pct"] < 0
    result["never_above_entry"] = result["mfe_to_close_pct"] <= 0
    return result


def _score(frame: pd.DataFrame, include_opening: bool) -> tuple[pd.DataFrame, list[str]]:
    score_fields = [
        "premarket_return_pct",
        "premarket_dollar_volume",
        "premarket_active_minutes",
        "premarket_log_volume_acceleration",
        "premarket_return_last_15m_pct",
        "premarket_price_acceleration_5m_pct",
        "premarket_volume_velocity_last_15m",
        "premarket_volume_acceleration_15m",
        "premarket_vwap_location_pct",
        "premarket_proximity_to_high_pct",
        "premarket_green_bar_fraction",
    ]
    if include_opening:
        score_fields += [
            "opening_return_pct",
            "opening_dollar_volume",
            "opening_vwap_location_pct",
            "opening_proximity_to_high_pct",
        ]
    components = []
    for field in score_fields:
        name = f"score_component_{field}"
        frame[name] = frame[field].rank(method="average", pct=True).fillna(0.5)
        components.append(name)
    frame["score_feature_coverage"] = frame[score_fields].notna().mean(axis=1)
    frame["research_score"] = frame[components].mean(axis=1) * 100.0
    frame["research_rank"] = frame["research_score"].rank(method="min", ascending=False).astype(int)
    return frame.sort_values(["research_rank", "symbol"]), score_fields


def rank_decision(bars: pd.DataFrame, session_date: str, decision_name: str) -> tuple[pd.DataFrame, list[str]]:
    cutoff = _clock(session_date, DECISIONS[decision_name])
    rows = []
    for symbol, symbol_bars in bars.groupby("symbol", sort=True):
        groups = set(symbol_bars["group"].dropna().astype(str)) if "group" in symbol_bars else set()
        if groups and groups.issubset(RETROSPECTIVE_ONLY_GROUPS):
            continue
        features = _premarket_features(symbol, symbol_bars, session_date)
        if not features:
            continue
        features.update(_opening_features(symbol_bars, session_date, cutoff))
        features.update(_outcomes(symbol_bars, session_date, cutoff))
        features["session_date"] = session_date
        features["decision"] = decision_name
        features["decision_time_et"] = cutoff.isoformat()
        features["universe_group"] = sorted(groups)[0] if len(groups) == 1 else "supplied_unlabeled"
        features["feature_set_version"] = FEATURE_SET_VERSION
        features["outcome_set_version"] = OUTCOME_SET_VERSION
        features["score_version"] = SCORE_VERSION
        rows.append(features)
    if not rows:
        raise ValueError(f"No symbols had premarket bars on {session_date}")
    return _score(pd.DataFrame(rows), include_opening=decision_name != "open")


def run(session_date: str, input_path: Path, output_root: Path, decisions: list[str]) -> list[Path]:
    bars = load_bars(input_path, session_date)
    target = output_root / session_date / "analysis" / "premarket_ranker"
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    summaries = []
    key_columns = [
        "session_date", "symbol", "decision", "decision_time_et",
        "outcome_set_version",
    ]
    for name in decisions:
        ranking, score_fields = rank_decision(bars, session_date, name)
        output = target / f"rankings_{name.replace('+', '_plus_')}.csv"
        ranking.drop(columns=list(OUTCOME_COLUMNS), errors="ignore").to_csv(output, index=False)
        written.append(output)
        outcomes_output = target / f"outcomes_{name.replace('+', '_plus_')}.csv"
        ranking[[*key_columns, *OUTCOME_COLUMNS]].to_csv(outcomes_output, index=False)
        written.append(outcomes_output)
        summaries.append({
            "decision": name,
            "decision_time_et": DECISIONS[name],
            "symbol_count": int(len(ranking)),
            "score_features": score_fields,
            "output": str(output),
            "outcomes_output": str(outcomes_output),
        })
    metadata = {
        "research_only": True,
        "orders_supported": False,
        "session_date": session_date,
        "input_file": str(input_path),
        "timezone": "America/New_York",
        "premarket_window": "04:00-09:30 ET",
        "point_in_time_policy": "ranking features use bars strictly before each decision time",
        "outcomes_policy": "outcome columns are retrospective labels and are excluded from research_score",
        "output_separation": "ranking files contain point-in-time features only; retrospective labels are written to separate outcome files",
        "feature_set_version": FEATURE_SET_VERSION,
        "outcome_set_version": OUTCOME_SET_VERSION,
        "score_version": SCORE_VERSION,
        "universe_scope": "Ranks point-in-time-eligible symbols in the supplied bar file; it does not claim whole-market discovery or recall.",
        "retrospective_group_policy": (
            "post_open_only_observed and missed_runner_control remain in source data for evaluation "
            "but are excluded from point-in-time rankings"
        ),
        "price_floor": None,
        "thresholds": None,
        "warning": "Exploratory equal-weight percentile score; not validated for live trading.",
        "decisions": summaries,
    }
    metadata_path = target / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    written.append(metadata_path)
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Historical session date (YYYY-MM-DD)")
    parser.add_argument("--data-root", type=Path, default=Path("data/research"))
    parser.add_argument("--input", type=Path, help="Clean one-minute bar CSV; auto-discovered if omitted")
    parser.add_argument("--output-root", type=Path, default=Path("data/research"))
    parser.add_argument("--decision", choices=[*DECISIONS, "all"], default="all")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    date_type.fromisoformat(args.date)
    input_path = args.input or discover_input(args.data_root, args.date)
    decisions = list(DECISIONS) if args.decision == "all" else [args.decision]
    for path in run(args.date, input_path, args.output_root, decisions):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
