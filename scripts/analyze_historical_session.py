#!/usr/bin/env python3
"""Analyse one historical Gainers Spotting session.

The analysis is descriptive and research-only. It measures behaviour, compares
the supplied cohorts and groups similar trajectories. It does not create
scanner thresholds, trading rules, entry signals or orders.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/gainers-spotting-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.patches import Rectangle
from scipy.stats import mannwhitneyu, spearmanr
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


EASTERN = "America/New_York"
SESSION_START = "04:00"
REGULAR_OPEN = "09:30"
SESSION_END = "16:00"

SEGMENTS = (
    ("early_premarket", "04:00", "06:00"),
    ("middle_premarket", "06:00", "08:00"),
    ("late_premarket", "08:00", "09:30"),
    ("opening_30m", "09:30", "10:00"),
    ("morning", "10:00", "12:00"),
    ("afternoon", "12:00", "16:00"),
)

CLUSTER_FEATURES = (
    "premarket_return_pct",
    "premarket_high_return_pct",
    "premarket_drawdown_from_high_pct",
    "premarket_range_pct",
    "premarket_close_location_pct",
    "premarket_active_minutes",
    "premarket_log_dollar_volume",
    "late_premarket_volume_share_pct",
    "late_premarket_return_pct",
    "open_vs_last_premarket_pct",
    "regular_high_from_open_pct",
    "regular_low_from_open_pct",
    "regular_close_from_open_pct",
    "regular_high_vs_premarket_high_pct",
    "minutes_to_regular_high",
)

COMPARISON_FEATURES = (
    "premarket_return_pct",
    "premarket_high_return_pct",
    "premarket_drawdown_from_high_pct",
    "premarket_range_pct",
    "premarket_close_location_pct",
    "premarket_active_minutes",
    "premarket_volume",
    "premarket_trade_count",
    "premarket_dollar_volume",
    "late_premarket_volume_share_pct",
    "early_premarket_return_pct",
    "middle_premarket_return_pct",
    "late_premarket_return_pct",
    "open_vs_last_premarket_pct",
    "regular_high_from_open_pct",
    "regular_low_from_open_pct",
    "regular_close_from_open_pct",
    "regular_high_vs_premarket_high_pct",
    "minutes_to_regular_high",
)

FEATURE_LABELS = {
    "premarket_return_pct": "Premarket first-to-last return",
    "premarket_high_return_pct": "Premarket first-to-high return",
    "premarket_drawdown_from_high_pct": "Last premarket price vs high",
    "premarket_range_pct": "Premarket high-low range",
    "premarket_close_location_pct": "Last premarket location in range",
    "premarket_active_minutes": "Premarket active minutes",
    "premarket_volume": "Premarket volume",
    "premarket_trade_count": "Premarket trades",
    "premarket_dollar_volume": "Premarket dollar volume",
    "premarket_log_dollar_volume": "Log premarket dollar volume",
    "late_premarket_volume_share_pct": "Late premarket share of volume",
    "early_premarket_return_pct": "04:00–06:00 return",
    "middle_premarket_return_pct": "06:00–08:00 return",
    "late_premarket_return_pct": "08:00–09:30 return",
    "open_vs_last_premarket_pct": "Open vs last premarket price",
    "regular_high_from_open_pct": "Regular-session high from open",
    "regular_low_from_open_pct": "Regular-session low from open",
    "regular_close_from_open_pct": "Close from open",
    "regular_high_vs_premarket_high_pct": "Regular high vs premarket high",
    "minutes_to_regular_high": "Minutes from open to session high",
}


@dataclass(frozen=True)
class AnalysisPaths:
    input_dir: Path
    output_dir: Path
    charts_dir: Path


def safe_return_pct(start: float, end: float) -> float:
    if not np.isfinite(start) or not np.isfinite(end) or start <= 0:
        return np.nan
    return (end / start - 1.0) * 100.0


def safe_divide(numerator: float, denominator: float) -> float:
    if not np.isfinite(numerator) or not np.isfinite(denominator):
        return np.nan
    if denominator == 0:
        return np.nan
    return numerator / denominator


def market_timestamp(session_date: str, clock: str) -> pd.Timestamp:
    return pd.Timestamp(f"{session_date} {clock}", tz=EASTERN)


def load_inputs(input_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    bars_path = input_dir / "bars.jsonl.gz"
    metadata_path = input_dir / "metadata.json"
    if not bars_path.exists() or not metadata_path.exists():
        raise FileNotFoundError(
            f"Expected bars.jsonl.gz and metadata.json under {input_dir}"
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    bars = pd.read_json(bars_path, lines=True, compression="gzip")
    bars["timestamp_utc"] = pd.to_datetime(
        bars["timestamp_utc"], utc=True
    )
    bars["timestamp_et"] = bars["timestamp_utc"].dt.tz_convert(EASTERN)
    bars["symbol"] = bars["symbol"].astype(str)
    bars["group"] = bars["group"].astype(str)
    bars = bars.sort_values(["symbol", "timestamp_et"]).reset_index(drop=True)
    return bars, metadata


def validate_data(
    bars: pd.DataFrame, metadata: dict[str, Any]
) -> dict[str, Any]:
    session_date = metadata["requested_time_window"]["date"]
    start = market_timestamp(session_date, SESSION_START)
    end = market_timestamp(session_date, SESSION_END)
    requested = list(metadata["requested_symbols"])
    present = sorted(bars["symbol"].unique().tolist())
    duplicate_mask = bars.duplicated(["symbol", "timestamp_utc"], keep=False)
    invalid_ohlc = (
        (bars["high"] < bars[["open", "close"]].max(axis=1))
        | (bars["low"] > bars[["open", "close"]].min(axis=1))
        | (bars["high"] < bars["low"])
        | (bars[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    outside = (bars["timestamp_et"] < start) | (bars["timestamp_et"] > end)
    at_exact_end = bars["timestamp_et"] == end
    negative_activity = (bars["volume"] < 0) | (bars["trade_count"] < 0)
    counts = bars.groupby("symbol").size()
    return {
        "session_date": session_date,
        "feed": metadata.get("feed"),
        "requested_symbol_count": len(requested),
        "present_symbol_count": len(present),
        "requested_symbols_missing": sorted(set(requested) - set(present)),
        "unexpected_symbols": sorted(set(present) - set(requested)),
        "total_rows": int(len(bars)),
        "duplicate_symbol_timestamps": int(duplicate_mask.sum()),
        "invalid_ohlc_rows": int(invalid_ohlc.sum()),
        "rows_outside_window": int(outside.sum()),
        "rows_at_exact_end_timestamp": int(at_exact_end.sum()),
        "negative_activity_rows": int(negative_activity.sum()),
        "minimum_bars_per_symbol": int(counts.min()),
        "maximum_bars_per_symbol": int(counts.max()),
        "important_note": (
            "Alpaca omits one-minute bars when no eligible trades occur. "
            "Missing minutes are not zero-volume candles. Bars timestamped "
            "exactly 16:00 ET are preserved in raw data but excluded from "
            "regular-session metrics, whose final interval starts at 15:59."
        ),
    }


def subset_between(
    frame: pd.DataFrame, session_date: str, start: str, end: str
) -> pd.DataFrame:
    start_ts = market_timestamp(session_date, start)
    end_ts = market_timestamp(session_date, end)
    return frame[
        (frame["timestamp_et"] >= start_ts)
        & (frame["timestamp_et"] < end_ts)
    ]


def segment_metrics(
    frame: pd.DataFrame,
    session_date: str,
    segment_name: str,
    start: str,
    end: str,
) -> dict[str, float]:
    segment = subset_between(frame, session_date, start, end)
    if segment.empty:
        return {
            f"{segment_name}_active_minutes": 0,
            f"{segment_name}_volume": 0,
            f"{segment_name}_trade_count": 0,
            f"{segment_name}_return_pct": np.nan,
        }
    return {
        f"{segment_name}_active_minutes": int(len(segment)),
        f"{segment_name}_volume": float(segment["volume"].sum()),
        f"{segment_name}_trade_count": float(segment["trade_count"].sum()),
        f"{segment_name}_return_pct": safe_return_pct(
            float(segment.iloc[0]["open"]),
            float(segment.iloc[-1]["close"]),
        ),
    }


def close_at_or_before(
    frame: pd.DataFrame, timestamp: pd.Timestamp
) -> float:
    eligible = frame[frame["timestamp_et"] <= timestamp]
    return float(eligible.iloc[-1]["close"]) if not eligible.empty else np.nan


def calculate_symbol_features(
    symbol_frame: pd.DataFrame, session_date: str
) -> dict[str, Any]:
    symbol_frame = symbol_frame.sort_values("timestamp_et")
    symbol = str(symbol_frame.iloc[0]["symbol"])
    group = str(symbol_frame.iloc[0]["group"])
    premarket = subset_between(
        symbol_frame, session_date, SESSION_START, REGULAR_OPEN
    )
    regular = subset_between(
        symbol_frame, session_date, REGULAR_OPEN, SESSION_END
    )
    row: dict[str, Any] = {"symbol": symbol, "group": group}

    for segment_name, start, end in SEGMENTS:
        row.update(
            segment_metrics(
                symbol_frame, session_date, segment_name, start, end
            )
        )

    if not premarket.empty:
        pm_first = float(premarket.iloc[0]["open"])
        pm_last = float(premarket.iloc[-1]["close"])
        pm_high = float(premarket["high"].max())
        pm_low = float(premarket["low"].min())
        pm_high_row = premarket.loc[premarket["high"].idxmax()]
        pm_low_row = premarket.loc[premarket["low"].idxmin()]
        pm_volume = float(premarket["volume"].sum())
        pm_dollar_volume = float(
            (premarket["vwap"] * premarket["volume"]).sum()
        )
        late = subset_between(
            symbol_frame, session_date, "08:00", REGULAR_OPEN
        )
        row.update(
            {
                "first_premarket_time_et": premarket.iloc[0][
                    "timestamp_et"
                ].isoformat(),
                "last_premarket_time_et": premarket.iloc[-1][
                    "timestamp_et"
                ].isoformat(),
                "first_premarket_price": pm_first,
                "last_premarket_price": pm_last,
                "premarket_high": pm_high,
                "premarket_high_time_et": pm_high_row[
                    "timestamp_et"
                ].isoformat(),
                "premarket_low": pm_low,
                "premarket_low_time_et": pm_low_row[
                    "timestamp_et"
                ].isoformat(),
                "premarket_return_pct": safe_return_pct(pm_first, pm_last),
                "premarket_high_return_pct": safe_return_pct(
                    pm_first, pm_high
                ),
                "premarket_low_return_pct": safe_return_pct(pm_first, pm_low),
                "premarket_drawdown_from_high_pct": safe_return_pct(
                    pm_high, pm_last
                ),
                "premarket_range_pct": safe_return_pct(pm_low, pm_high),
                "premarket_close_location_pct": (
                    safe_divide(pm_last - pm_low, pm_high - pm_low) * 100
                ),
                "premarket_active_minutes": int(len(premarket)),
                "premarket_volume": pm_volume,
                "premarket_trade_count": float(
                    premarket["trade_count"].sum()
                ),
                "premarket_dollar_volume": pm_dollar_volume,
                "premarket_log_dollar_volume": math.log10(
                    max(pm_dollar_volume, 1.0)
                ),
                "late_premarket_volume_share_pct": (
                    safe_divide(float(late["volume"].sum()), pm_volume) * 100
                ),
            }
        )
    else:
        for field in (
            "first_premarket_price",
            "last_premarket_price",
            "premarket_high",
            "premarket_low",
            "premarket_return_pct",
            "premarket_high_return_pct",
            "premarket_low_return_pct",
            "premarket_drawdown_from_high_pct",
            "premarket_range_pct",
            "premarket_close_location_pct",
            "premarket_volume",
            "premarket_trade_count",
            "premarket_dollar_volume",
            "premarket_log_dollar_volume",
            "late_premarket_volume_share_pct",
        ):
            row[field] = np.nan
        row["premarket_active_minutes"] = 0

    if not regular.empty:
        reg_open = float(regular.iloc[0]["open"])
        reg_close = float(regular.iloc[-1]["close"])
        reg_high = float(regular["high"].max())
        reg_low = float(regular["low"].min())
        reg_high_row = regular.loc[regular["high"].idxmax()]
        reg_low_row = regular.loc[regular["low"].idxmin()]
        open_time = market_timestamp(session_date, REGULAR_OPEN)
        row.update(
            {
                "regular_open": reg_open,
                "regular_open_first_bar_time_et": regular.iloc[0][
                    "timestamp_et"
                ].isoformat(),
                "regular_high": reg_high,
                "regular_high_time_et": reg_high_row[
                    "timestamp_et"
                ].isoformat(),
                "regular_low": reg_low,
                "regular_low_time_et": reg_low_row[
                    "timestamp_et"
                ].isoformat(),
                "regular_close": reg_close,
                "regular_volume": float(regular["volume"].sum()),
                "regular_trade_count": float(
                    regular["trade_count"].sum()
                ),
                "regular_high_from_open_pct": safe_return_pct(
                    reg_open, reg_high
                ),
                "regular_low_from_open_pct": safe_return_pct(
                    reg_open, reg_low
                ),
                "regular_close_from_open_pct": safe_return_pct(
                    reg_open, reg_close
                ),
                "regular_close_from_high_pct": safe_return_pct(
                    reg_high, reg_close
                ),
                "regular_high_vs_premarket_high_pct": safe_return_pct(
                    float(row.get("premarket_high", np.nan)), reg_high
                ),
                "open_vs_last_premarket_pct": safe_return_pct(
                    float(row.get("last_premarket_price", np.nan)), reg_open
                ),
                "minutes_to_regular_high": (
                    reg_high_row["timestamp_et"] - open_time
                ).total_seconds()
                / 60.0,
                "minutes_to_regular_low": (
                    reg_low_row["timestamp_et"] - open_time
                ).total_seconds()
                / 60.0,
            }
        )
        for minutes in (5, 15, 30, 60, 150, 390):
            checkpoint = open_time + pd.Timedelta(minutes=minutes)
            checkpoint_price = close_at_or_before(regular, checkpoint)
            row[f"open_to_{minutes}m_pct"] = safe_return_pct(
                reg_open, checkpoint_price
            )
    else:
        for field in (
            "regular_open",
            "regular_high",
            "regular_low",
            "regular_close",
            "regular_volume",
            "regular_trade_count",
            "regular_high_from_open_pct",
            "regular_low_from_open_pct",
            "regular_close_from_open_pct",
            "regular_close_from_high_pct",
            "regular_high_vs_premarket_high_pct",
            "open_vs_last_premarket_pct",
            "minutes_to_regular_high",
            "minutes_to_regular_low",
        ):
            row[field] = np.nan
        for minutes in (5, 15, 30, 60, 150, 390):
            row[f"open_to_{minutes}m_pct"] = np.nan
    return row


def calculate_features(
    bars: pd.DataFrame, session_date: str
) -> pd.DataFrame:
    rows = [
        calculate_symbol_features(frame, session_date)
        for _, frame in bars.groupby("symbol", sort=True)
    ]
    features = pd.DataFrame(rows)
    features["regular_high_rank"] = features[
        "regular_high_from_open_pct"
    ].rank(method="min", ascending=False)
    features["premarket_return_rank"] = features[
        "premarket_return_pct"
    ].rank(method="min", ascending=False)
    return features.sort_values("symbol").reset_index(drop=True)


def cliffs_delta(left: np.ndarray, right: np.ndarray) -> float:
    left = left[np.isfinite(left)]
    right = right[np.isfinite(right)]
    if len(left) == 0 or len(right) == 0:
        return np.nan
    comparisons = np.subtract.outer(left, right)
    return float(
        (np.count_nonzero(comparisons > 0)
         - np.count_nonzero(comparisons < 0))
        / comparisons.size
    )


def benjamini_hochberg(p_values: Iterable[float]) -> np.ndarray:
    p_values = np.asarray(list(p_values), dtype=float)
    order = np.argsort(p_values)
    ranked = p_values[order]
    adjusted = np.empty(len(ranked), dtype=float)
    running = 1.0
    for idx in range(len(ranked) - 1, -1, -1):
        rank = idx + 1
        running = min(running, ranked[idx] * len(ranked) / rank)
        adjusted[idx] = running
    result = np.empty(len(ranked), dtype=float)
    result[order] = np.clip(adjusted, 0, 1)
    return result


def compare_cohorts(features: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    candidates = features[features["group"] == "premarket_candidate"]
    controls = features[features["group"] == "missed_runner_control"]
    for feature in COMPARISON_FEATURES:
        left = pd.to_numeric(candidates[feature], errors="coerce").dropna()
        right = pd.to_numeric(controls[feature], errors="coerce").dropna()
        if left.empty or right.empty:
            continue
        statistic, p_value = mannwhitneyu(
            left, right, alternative="two-sided"
        )
        rows.append(
            {
                "feature": feature,
                "feature_label": FEATURE_LABELS.get(feature, feature),
                "candidate_median": float(left.median()),
                "control_median": float(right.median()),
                "median_difference": float(left.median() - right.median()),
                "cliffs_delta": cliffs_delta(
                    left.to_numpy(), right.to_numpy()
                ),
                "mann_whitney_u": float(statistic),
                "p_value": float(p_value),
                "candidate_n": int(len(left)),
                "control_n": int(len(right)),
            }
        )
    comparison = pd.DataFrame(rows)
    comparison["fdr_q_value"] = benjamini_hochberg(
        comparison["p_value"]
    )
    return comparison.sort_values(
        "cliffs_delta", key=lambda series: series.abs(), ascending=False
    ).reset_index(drop=True)


def feature_outcome_correlations(features: pd.DataFrame) -> pd.DataFrame:
    predictors = (
        "premarket_return_pct",
        "premarket_high_return_pct",
        "premarket_drawdown_from_high_pct",
        "premarket_close_location_pct",
        "premarket_active_minutes",
        "premarket_volume",
        "premarket_trade_count",
        "premarket_dollar_volume",
        "late_premarket_volume_share_pct",
        "early_premarket_return_pct",
        "middle_premarket_return_pct",
        "late_premarket_return_pct",
    )
    outcomes = (
        "regular_high_from_open_pct",
        "regular_close_from_open_pct",
    )
    cohorts = (
        ("all_symbols", features),
        (
            "premarket_candidate",
            features[features["group"] == "premarket_candidate"],
        ),
        (
            "missed_runner_control",
            features[features["group"] == "missed_runner_control"],
        ),
    )
    rows: list[dict[str, Any]] = []
    for cohort, frame in cohorts:
        for predictor in predictors:
            for outcome in outcomes:
                pair = frame[[predictor, outcome]].dropna()
                if len(pair) < 4:
                    continue
                rho, p_value = spearmanr(pair[predictor], pair[outcome])
                rows.append(
                    {
                        "cohort": cohort,
                        "predictor": predictor,
                        "predictor_label": FEATURE_LABELS.get(
                            predictor, predictor
                        ),
                        "outcome": outcome,
                        "outcome_label": FEATURE_LABELS.get(outcome, outcome),
                        "spearman_rho": float(rho),
                        "p_value": float(p_value),
                        "n": int(len(pair)),
                    }
                )
    return pd.DataFrame(rows).sort_values(
        "spearman_rho", key=lambda series: series.abs(), ascending=False
    ).reset_index(drop=True)


def checkpoint_summary(features: pd.DataFrame) -> pd.DataFrame:
    checkpoints = (
        (5, "open_to_5m_pct"),
        (15, "open_to_15m_pct"),
        (30, "open_to_30m_pct"),
        (60, "open_to_60m_pct"),
        (150, "open_to_150m_pct"),
        (390, "open_to_390m_pct"),
    )
    rows = []
    for group, frame in features.groupby("group"):
        for minute, column in checkpoints:
            rows.append(
                {
                    "group": group,
                    "minutes_after_open": minute,
                    "median_return_pct": float(frame[column].median()),
                    "lower_quartile_pct": float(frame[column].quantile(0.25)),
                    "upper_quartile_pct": float(frame[column].quantile(0.75)),
                    "symbol_count": int(frame[column].notna().sum()),
                }
            )
    return pd.DataFrame(rows)


def cluster_symbols(
    features: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    matrix = features.loc[:, CLUSTER_FEATURES].replace([np.inf, -np.inf], np.nan)
    preprocessing = make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler()
    )
    scaled = preprocessing.fit_transform(matrix)
    max_k = min(8, len(features) - 1)
    scores: dict[int, float] = {}
    fitted: dict[int, KMeans] = {}
    for k in range(2, max_k + 1):
        model = KMeans(n_clusters=k, random_state=20260724, n_init=30)
        labels = model.fit_predict(scaled)
        scores[k] = float(silhouette_score(scaled, labels))
        fitted[k] = model
    best_k = max(scores, key=scores.get)
    labels = fitted[best_k].labels_
    assignments = features[
        [
            "symbol",
            "group",
            "premarket_return_pct",
            "regular_high_from_open_pct",
            "regular_close_from_open_pct",
        ]
    ].copy()
    assignments["cluster"] = [f"Cluster {label + 1}" for label in labels]

    scaled_frame = pd.DataFrame(
        scaled, columns=CLUSTER_FEATURES, index=features.index
    )
    scaled_frame["cluster"] = assignments["cluster"].to_numpy()
    profile = scaled_frame.groupby("cluster").median()
    profile.insert(
        0,
        "symbol_count",
        assignments.groupby("cluster").size().reindex(profile.index),
    )
    profile = profile.reset_index()
    diagnostics = {
        "method": "KMeans after median imputation and standardisation",
        "selected_cluster_count": int(best_k),
        "selection_method": (
            "Highest silhouette score among candidate counts 2 through "
            f"{max_k}"
        ),
        "silhouette_scores": {
            str(key): value for key, value in scores.items()
        },
        "features": list(CLUSTER_FEATURES),
        "interpretation_warning": (
            "Clusters are exploratory descriptions of this one session, not "
            "scanner states or trading rules."
        ),
    }
    return assignments, profile, diagnostics


def save_chart(fig: plt.Figure, path: Path) -> str:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    content = buffer.getvalue()
    path.write_bytes(content)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(content).decode("ascii")


def five_minute_candles(frame: pd.DataFrame) -> pd.DataFrame:
    indexed = frame.set_index("timestamp_et").sort_index()
    candles = indexed.resample("5min").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    candles.loc[candles["open"].isna(), "volume"] = np.nan
    return candles.dropna(subset=["open"])


def make_symbol_chart(
    frame: pd.DataFrame,
    feature: pd.Series,
    session_date: str,
    path: Path,
) -> str:
    candles = five_minute_candles(frame)
    fig, (ax_price, ax_volume) = plt.subplots(
        2,
        1,
        figsize=(12, 6.3),
        sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1], "hspace": 0.05},
    )
    width = 3.5 / (24 * 60)
    for timestamp, candle in candles.iterrows():
        x = mdates.date2num(timestamp.to_pydatetime())
        up = candle["close"] >= candle["open"]
        color = "#168a62" if up else "#c44949"
        ax_price.vlines(
            x, candle["low"], candle["high"], color=color, linewidth=0.75
        )
        body_low = min(candle["open"], candle["close"])
        body_height = abs(candle["close"] - candle["open"])
        if body_height == 0:
            body_height = max(candle["open"] * 0.0002, 0.0001)
        ax_price.add_patch(
            Rectangle(
                (x - width / 2, body_low),
                width,
                body_height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.5,
            )
        )
        ax_volume.bar(
            x,
            candle["volume"],
            width=width,
            color=color,
            alpha=0.72,
            align="center",
        )

    session_start = market_timestamp(session_date, SESSION_START)
    regular_open = market_timestamp(session_date, REGULAR_OPEN)
    session_end = market_timestamp(session_date, SESSION_END)
    for axis in (ax_price, ax_volume):
        axis.axvspan(
            session_start,
            regular_open,
            color="#dbeafe",
            alpha=0.32,
            zorder=0,
        )
        axis.axvline(
            regular_open, color="#334155", linestyle="--", linewidth=1
        )
        axis.grid(axis="y", color="#e5e7eb", linewidth=0.6)
        axis.set_xlim(session_start, session_end)
    if np.isfinite(feature.get("premarket_high", np.nan)):
        ax_price.axhline(
            feature["premarket_high"],
            color="#7c3aed",
            linestyle=":",
            linewidth=1,
            label="Premarket high",
        )
        ax_price.legend(loc="upper left", frameon=False, fontsize=8)
    ax_price.set_ylabel("Price")
    ax_volume.set_ylabel("Volume")
    ax_volume.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    ax_volume.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=EASTERN))
    ax_volume.set_xlabel("Eastern time")
    title = (
        f"{feature['symbol']} — 5-minute candles | "
        f"PM {feature['premarket_return_pct']:+.1f}% | "
        f"Open→high {feature['regular_high_from_open_pct']:+.1f}% | "
        f"Open→close {feature['regular_close_from_open_pct']:+.1f}%"
    )
    fig.suptitle(title, fontsize=12, fontweight="bold")
    fig.text(
        0.5,
        0.01,
        "Blue shading: premarket. Missing bars mean no eligible trades were "
        "reported; candles are not fabricated.",
        ha="center",
        fontsize=8,
        color="#475569",
    )
    fig.subplots_adjust(bottom=0.13, top=0.91)
    return save_chart(fig, path)


def normalized_paths(
    bars: pd.DataFrame, session_date: str
) -> pd.DataFrame:
    grid = pd.date_range(
        market_timestamp(session_date, SESSION_START),
        market_timestamp(session_date, SESSION_END),
        freq="5min",
        inclusive="left",
    )
    rows: list[pd.DataFrame] = []
    for symbol, frame in bars.groupby("symbol"):
        series = (
            frame.set_index("timestamp_et")["close"]
            .resample("5min")
            .last()
            .reindex(grid)
        )
        first_valid = series.first_valid_index()
        if first_valid is None:
            continue
        series.loc[first_valid:] = series.loc[first_valid:].ffill()
        base = float(series.loc[first_valid])
        normalized = (series / base - 1) * 100
        item = pd.DataFrame(
            {
                "timestamp_et": grid,
                "normalized_return_pct": normalized.to_numpy(),
                "symbol": symbol,
                "group": frame.iloc[0]["group"],
            }
        )
        rows.append(item)
    return pd.concat(rows, ignore_index=True)


def make_group_path_chart(
    paths: pd.DataFrame, session_date: str, path: Path
) -> str:
    fig, ax = plt.subplots(figsize=(12, 5.5))
    colours = {
        "premarket_candidate": "#2563eb",
        "missed_runner_control": "#d97706",
    }
    labels = {
        "premarket_candidate": "Premarket candidates",
        "missed_runner_control": "Missed runners / controls",
    }
    for group, frame in paths.groupby("group"):
        pivot = frame.pivot(
            index="timestamp_et",
            columns="symbol",
            values="normalized_return_pct",
        )
        median = pivot.median(axis=1)
        lower = pivot.quantile(0.25, axis=1)
        upper = pivot.quantile(0.75, axis=1)
        ax.plot(
            median.index,
            median,
            label=labels[group],
            color=colours[group],
            linewidth=2,
        )
        ax.fill_between(
            median.index,
            lower,
            upper,
            color=colours[group],
            alpha=0.16,
        )
    regular_open = market_timestamp(session_date, REGULAR_OPEN)
    ax.axvline(
        regular_open,
        color="#334155",
        linestyle="--",
        linewidth=1,
        label="Regular open",
    )
    ax.axhline(0, color="#94a3b8", linewidth=0.8)
    ax.set_title(
        "Median normalized price paths with interquartile ranges",
        fontweight="bold",
    )
    ax.set_ylabel("Return from each symbol’s first observed price (%)")
    ax.set_xlabel("Eastern time")
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=EASTERN))
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.6)
    ax.legend(frameon=False)
    fig.autofmt_xdate(rotation=0)
    return save_chart(fig, path)


def make_scatter_chart(features: pd.DataFrame, path: Path) -> str:
    fig, ax = plt.subplots(figsize=(8, 6))
    colours = {
        "premarket_candidate": "#2563eb",
        "missed_runner_control": "#d97706",
    }
    labels = {
        "premarket_candidate": "Premarket candidates",
        "missed_runner_control": "Missed runners / controls",
    }
    for group, frame in features.groupby("group"):
        ax.scatter(
            frame["premarket_return_pct"],
            frame["regular_high_from_open_pct"],
            s=48,
            alpha=0.78,
            color=colours[group],
            label=labels[group],
        )
        for _, row in frame.iterrows():
            if (
                row["regular_high_rank"] <= 8
                or row["premarket_return_rank"] <= 8
            ):
                ax.annotate(
                    row["symbol"],
                    (
                        row["premarket_return_pct"],
                        row["regular_high_from_open_pct"],
                    ),
                    xytext=(4, 3),
                    textcoords="offset points",
                    fontsize=7,
                )
    ax.axhline(0, color="#94a3b8", linewidth=0.8)
    ax.axvline(0, color="#94a3b8", linewidth=0.8)
    ax.set_title(
        "Premarket movement versus regular-session opportunity",
        fontweight="bold",
    )
    ax.set_xlabel("First-to-last premarket return (%)")
    ax.set_ylabel("Regular-session high from opening price (%)")
    ax.grid(color="#e5e7eb", linewidth=0.6)
    ax.legend(frameon=False)
    return save_chart(fig, path)


def make_checkpoint_chart(summary: pd.DataFrame, path: Path) -> str:
    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    colours = {
        "premarket_candidate": "#2563eb",
        "missed_runner_control": "#d97706",
    }
    labels = {
        "premarket_candidate": "Premarket candidates",
        "missed_runner_control": "Missed runners / controls",
    }
    for group, frame in summary.groupby("group"):
        frame = frame.sort_values("minutes_after_open")
        ax.plot(
            frame["minutes_after_open"],
            frame["median_return_pct"],
            marker="o",
            linewidth=2.2,
            color=colours[group],
            label=labels[group],
        )
        ax.fill_between(
            frame["minutes_after_open"],
            frame["lower_quartile_pct"],
            frame["upper_quartile_pct"],
            color=colours[group],
            alpha=0.13,
        )
    ax.axhline(0, color="#94a3b8", linewidth=0.8)
    ax.set_xscale("symlog", linthresh=15)
    ax.set_xticks([5, 15, 30, 60, 150, 390])
    ax.set_xticklabels(["5m", "15m", "30m", "60m", "150m", "Close"])
    ax.set_title(
        "Median return development after the regular-session open",
        fontweight="bold",
    )
    ax.set_xlabel("Checkpoint after 09:30 ET")
    ax.set_ylabel("Return from opening price (%)")
    ax.grid(color="#e5e7eb", linewidth=0.6)
    ax.legend(frameon=False)
    return save_chart(fig, path)


def make_cluster_heatmap(profile: pd.DataFrame, path: Path) -> str:
    heatmap = profile.set_index("cluster").drop(columns=["symbol_count"])
    fig_width = max(11, len(heatmap.columns) * 0.72)
    fig, ax = plt.subplots(figsize=(fig_width, 4.8))
    sns.heatmap(
        heatmap,
        cmap="vlag",
        center=0,
        linewidths=0.5,
        cbar_kws={"label": "Median standardized feature"},
        ax=ax,
    )
    ax.set_title(
        "Exploratory cluster profiles", fontweight="bold"
    )
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_xticklabels(
        [FEATURE_LABELS.get(name, name) for name in heatmap.columns],
        rotation=50,
        ha="right",
        fontsize=8,
    )
    return save_chart(fig, path)


def fmt(value: Any, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "N/A"
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):,.{digits}f}"
    return str(value)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    return value


def dataframe_html(
    frame: pd.DataFrame,
    columns: list[str],
    headings: list[str],
    percent_columns: set[str] | None = None,
    max_rows: int | None = None,
) -> str:
    percent_columns = percent_columns or set()
    display = frame.head(max_rows) if max_rows else frame
    head = "".join(f"<th>{html.escape(label)}</th>" for label in headings)
    body_rows = []
    for _, row in display.iterrows():
        cells = []
        for column in columns:
            value = row[column]
            rendered = fmt(value)
            if column in percent_columns and rendered != "N/A":
                rendered += "%"
            cells.append(f"<td>{html.escape(rendered)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div>"
    )


def cluster_descriptions(
    assignments: pd.DataFrame,
    profile: pd.DataFrame,
    features: pd.DataFrame,
) -> list[dict[str, Any]]:
    output = []
    profile_indexed = profile.set_index("cluster")
    for cluster in sorted(assignments["cluster"].unique()):
        members = assignments[assignments["cluster"] == cluster]
        values = profile_indexed.loc[cluster].drop("symbol_count")
        strongest = values.reindex(
            values.abs().sort_values(ascending=False).index
        ).head(4)
        descriptors = []
        for feature, value in strongest.items():
            direction = "above" if value > 0 else "below"
            descriptors.append(
                f"{FEATURE_LABELS.get(feature, feature)} {direction} the "
                "session-wide median"
            )
        member_features = features[
            features["symbol"].isin(members["symbol"])
        ]
        output.append(
            {
                "cluster": cluster,
                "symbols": members["symbol"].tolist(),
                "candidate_count": int(
                    (members["group"] == "premarket_candidate").sum()
                ),
                "control_count": int(
                    (members["group"] == "missed_runner_control").sum()
                ),
                "median_regular_high_from_open_pct": float(
                    member_features["regular_high_from_open_pct"].median()
                ),
                "median_regular_close_from_open_pct": float(
                    member_features["regular_close_from_open_pct"].median()
                ),
                "descriptors": descriptors,
            }
        )
    return output


def build_report(
    session_date: str,
    quality: dict[str, Any],
    features: pd.DataFrame,
    comparison: pd.DataFrame,
    correlations: pd.DataFrame,
    checkpoints: pd.DataFrame,
    assignments: pd.DataFrame,
    cluster_profile: pd.DataFrame,
    cluster_diagnostics: dict[str, Any],
    cluster_notes: list[dict[str, Any]],
    overview_images: dict[str, str],
    symbol_images: dict[str, str],
) -> str:
    ranked_high = features.sort_values(
        "regular_high_from_open_pct", ascending=False
    )
    ranked_pm = features.sort_values(
        "premarket_return_pct", ascending=False
    )
    top_effects = comparison.sort_values(
        "cliffs_delta", key=lambda series: series.abs(), ascending=False
    )
    correlation_display = correlations[
        correlations["cohort"] == "all_symbols"
    ].copy()
    cluster_lookup = assignments.set_index("symbol")["cluster"].to_dict()

    top_high_table = dataframe_html(
        ranked_high,
        [
            "symbol",
            "group",
            "premarket_return_pct",
            "regular_high_from_open_pct",
            "regular_close_from_open_pct",
            "minutes_to_regular_high",
        ],
        [
            "Symbol",
            "Research group",
            "Premarket return",
            "Open→high",
            "Open→close",
            "Minutes to high",
        ],
        {
            "premarket_return_pct",
            "regular_high_from_open_pct",
            "regular_close_from_open_pct",
        },
        max_rows=15,
    )
    top_pm_table = dataframe_html(
        ranked_pm,
        [
            "symbol",
            "group",
            "premarket_return_pct",
            "premarket_high_return_pct",
            "premarket_drawdown_from_high_pct",
            "regular_high_from_open_pct",
        ],
        [
            "Symbol",
            "Research group",
            "Premarket return",
            "Premarket maximum",
            "Last PM vs PM high",
            "Open→high",
        ],
        {
            "premarket_return_pct",
            "premarket_high_return_pct",
            "premarket_drawdown_from_high_pct",
            "regular_high_from_open_pct",
        },
        max_rows=15,
    )
    comparison_table = dataframe_html(
        top_effects,
        [
            "feature_label",
            "candidate_median",
            "control_median",
            "cliffs_delta",
            "p_value",
            "fdr_q_value",
        ],
        [
            "Feature",
            "Candidate median",
            "Control median",
            "Cliff’s delta",
            "Exploratory p",
            "FDR q",
        ],
        max_rows=12,
    )
    correlation_table = dataframe_html(
        correlation_display,
        [
            "predictor_label",
            "outcome_label",
            "spearman_rho",
            "p_value",
            "n",
        ],
        ["Premarket feature", "Outcome", "Spearman ρ", "Exploratory p", "N"],
        max_rows=10,
    )

    cluster_sections = []
    for note in cluster_notes:
        cluster_sections.append(
            f"""
            <article class="cluster-card">
              <h3>{html.escape(note['cluster'])}
                <span class="muted">({len(note['symbols'])} symbols)</span>
              </h3>
              <p><strong>Members:</strong>
                {html.escape(', '.join(note['symbols']))}</p>
              <p><strong>Cohort mix:</strong> {note['candidate_count']}
                candidates; {note['control_count']} missed/control.</p>
              <p><strong>Median regular open→high:</strong>
                {fmt(note['median_regular_high_from_open_pct'])}%.
                <strong>Median open→close:</strong>
                {fmt(note['median_regular_close_from_open_pct'])}%.</p>
              <ul>{''.join(
                  f"<li>{html.escape(item)}</li>"
                  for item in note['descriptors']
              )}</ul>
            </article>
            """
        )

    gallery = []
    for _, row in ranked_high.iterrows():
        symbol = row["symbol"]
        gallery.append(
            f"""
            <article class="symbol-card">
              <h3>{html.escape(symbol)}
                <span class="pill">{html.escape(cluster_lookup[symbol])}</span>
              </h3>
              <img src="{symbol_images[symbol]}"
                   alt="{html.escape(symbol)} candlestick chart">
            </article>
            """
        )

    strongest = top_effects.iloc[0]
    largest_runner = ranked_high.iloc[0]
    largest_pm = ranked_pm.iloc[0]
    generated_at = datetime.now().astimezone().isoformat()
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gainers Spotting research — {html.escape(session_date)}</title>
<style>
  :root {{ --ink:#172033; --muted:#5b6577; --line:#dce2ea;
    --blue:#2457d6; --paper:#fff; --wash:#f4f7fb; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--wash); color:var(--ink);
    font:15px/1.55 Inter,Segoe UI,Arial,sans-serif; }}
  main {{ max-width:1200px; margin:auto; padding:32px 24px 64px; }}
  header, section {{ background:var(--paper); border:1px solid var(--line);
    border-radius:14px; padding:24px; margin-bottom:18px; }}
  h1 {{ font-size:30px; margin:0 0 6px; }}
  h2 {{ font-size:21px; margin:0 0 14px; }}
  h3 {{ font-size:16px; margin:0 0 8px; }}
  p {{ margin:8px 0; }}
  .muted {{ color:var(--muted); font-weight:normal; }}
  .warning {{ border-left:4px solid #d97706; background:#fff8e8;
    padding:12px 14px; margin:14px 0; }}
  .facts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
    gap:10px; margin-top:18px; }}
  .fact {{ background:#f7f9fc; border-radius:10px; padding:12px; }}
  .fact b {{ display:block; font-size:20px; }}
  .chart {{ width:100%; height:auto; display:block; margin:12px 0 4px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
    gap:14px; }}
  .cluster-card,.symbol-card {{ border:1px solid var(--line);
    border-radius:10px; padding:14px; background:#fff; }}
  .symbol-card img {{ width:100%; height:auto; }}
  .pill {{ display:inline-block; background:#e8efff; color:#244b9b;
    border-radius:999px; padding:2px 8px; font-size:11px; margin-left:6px; }}
  .table-wrap {{ overflow-x:auto; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th,td {{ border-bottom:1px solid var(--line); padding:8px 9px;
    text-align:right; white-space:nowrap; }}
  th:first-child,td:first-child,th:nth-child(2),td:nth-child(2) {{
    text-align:left; }}
  th {{ background:#f7f9fc; }}
  code {{ background:#eef2f7; padding:2px 5px; border-radius:4px; }}
  @media print {{ body {{ background:#fff; }} main {{ max-width:none; }}
    header,section {{ break-inside:avoid; box-shadow:none; }} }}
</style>
</head>
<body><main>
<header>
  <h1>Gainers Spotting historical research</h1>
  <p class="muted">{html.escape(session_date)} · SIP one-minute data ·
    04:00–16:00 ET</p>
  <div class="warning"><strong>Research status:</strong> one-session discovery
    analysis. Observed relationships are hypotheses for later dates, not
    scanner thresholds, entry rules or evidence of future profitability.</div>
  <div class="facts">
    <div class="fact"><b>{quality['present_symbol_count']}</b>symbols</div>
    <div class="fact"><b>{quality['total_rows']:,}</b>one-minute bars</div>
    <div class="fact"><b>{cluster_diagnostics['selected_cluster_count']}</b>
      exploratory clusters</div>
    <div class="fact"><b>{html.escape(str(largest_runner['symbol']))}</b>
      largest open→high move ({fmt(largest_runner['regular_high_from_open_pct'])}%)</div>
  </div>
</header>

<section>
  <h2>Executive reading of this session</h2>
  <ul>
    <li>The largest first-to-last premarket increase was
      <strong>{html.escape(str(largest_pm['symbol']))}</strong>
      at {fmt(largest_pm['premarket_return_pct'])}%.</li>
    <li>The largest regular-session opening-to-high opportunity was
      <strong>{html.escape(str(largest_runner['symbol']))}</strong>
      at {fmt(largest_runner['regular_high_from_open_pct'])}%.</li>
    <li>The strongest measured separation between the supplied cohorts was
      <strong>{html.escape(str(strongest['feature_label']))}</strong>
      (Cliff’s delta {fmt(strongest['cliffs_delta'])}). This is descriptive
      because the cohorts were selected, not randomly sampled.</li>
    <li>Missing minutes represent an absence of reported eligible trades; the
      analysis never creates synthetic one-minute candles. Five-minute candles
      are used only for readable charts.</li>
  </ul>
</section>

<section>
  <h2>Data quality</h2>
  <div class="facts">
    <div class="fact"><b>{quality['duplicate_symbol_timestamps']}</b>
      duplicate timestamps</div>
    <div class="fact"><b>{quality['invalid_ohlc_rows']}</b>invalid OHLC rows</div>
    <div class="fact"><b>{quality['rows_outside_window']}</b>
      rows outside window</div>
    <div class="fact"><b>{quality['requested_symbol_count']
      - quality['present_symbol_count']}</b>missing symbols</div>
  </div>
</section>

<section>
  <h2>Group trajectories</h2>
  <p>Each symbol is rebased to its first observed price. Lines show cohort
    medians; shading shows the middle 50% of symbols. Forward filling is used
    only for this trajectory visualization and represents the last observed
    traded price, not a fabricated candle.</p>
  <img class="chart" src="{overview_images['paths']}"
       alt="Normalized cohort paths">
</section>

<section>
  <h2>Premarket movement versus daytime opportunity</h2>
  <p>The scatter plot checks whether a larger premarket first-to-last move
    corresponded to a larger opening-to-intraday-high move. It is not an entry
    simulation and does not assume the high was achievable.</p>
  <img class="chart" src="{overview_images['scatter']}"
       alt="Premarket versus regular-session scatter chart">
</section>

<section>
  <h2>How the two cohorts developed after the open</h2>
  <p>Lines show the median return from each symbol’s opening price; shading
    shows the middle 50%. The supplied candidates tended to peak quickly and
    fade, while the missed/control cohort developed more gradually during this
    particular session.</p>
  <img class="chart" src="{overview_images['checkpoints']}"
       alt="Median returns after the market open">
</section>

<section>
  <h2>Largest regular-session moves</h2>
  {top_high_table}
</section>

<section>
  <h2>Largest premarket first-to-last moves</h2>
  {top_pm_table}
</section>

<section>
  <h2>Candidate versus missed/control comparison</h2>
  <p>Cliff’s delta is positive when candidate values tended to be larger.
    Values near ±1 indicate stronger separation; values near zero indicate
    overlap. P and FDR values are exploratory and must not be treated as
    validation from a single selected session.</p>
  {comparison_table}
</section>

<section>
  <h2>Premarket feature correlations with daytime outcomes</h2>
  <p>Spearman correlations measure monotonic association, not causation.
    The full-universe values can be confounded by the way the two cohorts were
    selected, so the accompanying CSV also provides correlations within each
    cohort. No relationship from one date should be converted into a scanner
    weight.</p>
  {correlation_table}
</section>

<section>
  <h2>Exploratory behavioural clusters</h2>
  <p>The number of clusters was selected by the highest silhouette score
    across 2–8 clusters. The inputs are continuous behaviour measurements.
    Clusters describe this date; they are not named scanner states.</p>
  <img class="chart" src="{overview_images['clusters']}"
       alt="Cluster profile heatmap">
  <div class="grid">{''.join(cluster_sections)}</div>
</section>

<section>
  <h2>Interpretation boundaries and next validation</h2>
  <ul>
    <li>The dataset contains only the supplied symbols, so it cannot estimate
      market-wide precision, recall or false-alert burden.</li>
    <li>The 04:00 start means the official previous close is absent. Current
      “premarket return” means first observed premarket price to last observed
      premarket price, not the official overnight gap.</li>
    <li>Bars alone do not establish achievable fills, bid-ask spreads, float,
      news timing or catalyst quality.</li>
    <li>Patterns found here should be frozen as hypotheses and checked on later
      dates before any threshold or production logic is considered.</li>
  </ul>
</section>

<section>
  <h2>All symbol charts</h2>
  <p>Five-minute aggregation is used for legibility; every calculated feature
    and ranking comes from the collected one-minute bars.</p>
  <div class="grid">{''.join(gallery)}</div>
</section>

<footer class="muted">Generated {html.escape(generated_at)} by
  <code>scripts/analyze_historical_session.py</code>.</footer>
</main></body></html>"""


def run_analysis(paths: AnalysisPaths) -> dict[str, Any]:
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    paths.charts_dir.mkdir(parents=True, exist_ok=True)
    bars, metadata = load_inputs(paths.input_dir)
    session_date = metadata["requested_time_window"]["date"]
    quality = validate_data(bars, metadata)
    (paths.output_dir / "data-quality.json").write_text(
        json.dumps(quality, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fatal_quality_fields = (
        "requested_symbols_missing",
        "unexpected_symbols",
        "duplicate_symbol_timestamps",
        "invalid_ohlc_rows",
        "rows_outside_window",
        "negative_activity_rows",
    )
    if any(quality[field] for field in fatal_quality_fields):
        raise ValueError(
            "Data validation failed; inspect data-quality.json before analysis"
        )
    features = calculate_features(bars, session_date)
    comparison = compare_cohorts(features)
    correlations = feature_outcome_correlations(features)
    checkpoints = checkpoint_summary(features)
    assignments, cluster_profile, cluster_diagnostics = cluster_symbols(
        features
    )
    cluster_notes = cluster_descriptions(
        assignments, cluster_profile, features
    )

    features.to_csv(paths.output_dir / "features-by-symbol.csv", index=False)
    comparison.to_csv(
        paths.output_dir / "cohort-comparison.csv", index=False
    )
    correlations.to_csv(
        paths.output_dir / "feature-outcome-correlations.csv", index=False
    )
    checkpoints.to_csv(
        paths.output_dir / "checkpoint-summary.csv", index=False
    )
    assignments.to_csv(
        paths.output_dir / "cluster-assignments.csv", index=False
    )
    cluster_profile.to_csv(
        paths.output_dir / "cluster-profiles.csv", index=False
    )
    (paths.output_dir / "cluster-diagnostics.json").write_text(
        json.dumps(cluster_diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    sns.set_theme(style="whitegrid", context="notebook")
    path_data = normalized_paths(bars, session_date)
    overview_images = {
        "paths": make_group_path_chart(
            path_data,
            session_date,
            paths.charts_dir / "group-normalized-paths.png",
        ),
        "scatter": make_scatter_chart(
            features,
            paths.charts_dir / "premarket-vs-regular-high.png",
        ),
        "checkpoints": make_checkpoint_chart(
            checkpoints,
            paths.charts_dir / "post-open-checkpoints.png",
        ),
        "clusters": make_cluster_heatmap(
            cluster_profile,
            paths.charts_dir / "cluster-profiles.png",
        ),
    }
    symbol_images: dict[str, str] = {}
    feature_lookup = features.set_index("symbol")
    for symbol, frame in bars.groupby("symbol", sort=True):
        symbol_feature = feature_lookup.loc[symbol].copy()
        symbol_feature["symbol"] = symbol
        symbol_images[symbol] = make_symbol_chart(
            frame,
            symbol_feature,
            session_date,
            paths.charts_dir / f"{symbol}.png",
        )

    report = build_report(
        session_date=session_date,
        quality=quality,
        features=features,
        comparison=comparison,
        correlations=correlations,
        checkpoints=checkpoints,
        assignments=assignments,
        cluster_profile=cluster_profile,
        cluster_diagnostics=cluster_diagnostics,
        cluster_notes=cluster_notes,
        overview_images=overview_images,
        symbol_images=symbol_images,
    )
    report_path = paths.output_dir / "research-report.html"
    report_path.write_text(report, encoding="utf-8")

    summary = {
        "research_only": True,
        "trading_rules_created": False,
        "session_date": session_date,
        "symbols_analysed": int(len(features)),
        "one_minute_bars": int(len(bars)),
        "selected_cluster_count": int(
            cluster_diagnostics["selected_cluster_count"]
        ),
        "largest_premarket_moves": features.nlargest(
            10, "premarket_return_pct"
        )[
            [
                "symbol",
                "group",
                "premarket_return_pct",
                "regular_high_from_open_pct",
                "regular_close_from_open_pct",
            ]
        ].to_dict("records"),
        "largest_regular_open_to_high_moves": features.nlargest(
            10, "regular_high_from_open_pct"
        )[
            [
                "symbol",
                "group",
                "premarket_return_pct",
                "regular_high_from_open_pct",
                "regular_close_from_open_pct",
                "minutes_to_regular_high",
            ]
        ].to_dict("records"),
        "strongest_cohort_differences": comparison.head(10)[
            [
                "feature",
                "feature_label",
                "candidate_median",
                "control_median",
                "cliffs_delta",
                "p_value",
                "fdr_q_value",
            ]
        ].to_dict("records"),
        "post_open_checkpoint_medians": checkpoints.to_dict("records"),
        "strongest_full_universe_correlations": correlations[
            correlations["cohort"] == "all_symbols"
        ].head(10)[
            [
                "predictor",
                "predictor_label",
                "outcome",
                "outcome_label",
                "spearman_rho",
                "p_value",
                "n",
            ]
        ].to_dict("records"),
        "clusters": cluster_notes,
        "limitations": [
            "One selected session is a discovery sample, not validation.",
            "The supplied universe cannot estimate market-wide recall or precision.",
            "Previous official close, quotes, spreads, news and float are absent.",
            "Intraday highs are descriptive and not assumed achievable fills.",
        ],
        "output_files": [
            "research-report.html",
            "features-by-symbol.csv",
            "cohort-comparison.csv",
            "feature-outcome-correlations.csv",
            "checkpoint-summary.csv",
            "cluster-assignments.csv",
            "cluster-profiles.csv",
            "data-quality.json",
            "cluster-diagnostics.json",
            "charts/",
        ],
    }
    (paths.output_dir / "analysis-summary.json").write_text(
        json.dumps(json_safe(summary), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyse one collected Gainers Spotting session without creating "
            "trading rules."
        )
    )
    parser.add_argument(
        "--date", required=True, help="Research date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--research-root",
        type=Path,
        default=Path("data/research"),
        help="Research data root (default: data/research)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_dir = args.research_root / args.date
    output_dir = input_dir / "analysis"
    paths = AnalysisPaths(
        input_dir=input_dir,
        output_dir=output_dir,
        charts_dir=output_dir / "charts",
    )
    try:
        summary = run_analysis(paths)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "status": "completed",
                "session_date": summary["session_date"],
                "symbols_analysed": summary["symbols_analysed"],
                "one_minute_bars": summary["one_minute_bars"],
                "output_dir": str(output_dir),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
