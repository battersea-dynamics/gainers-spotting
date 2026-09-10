#!/usr/bin/env python3
"""Compare recovered screenshot labels with point-in-time bar outcomes.

This is a retrospective, research-only case-study tool. Revolut observations
label historical examples; they never construct or rank the future scanner
universe. Actual UK phone times are converted to America/New_York before a
checkpoint is assigned to a market phase.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


LONDON = ZoneInfo("Europe/London")
EASTERN = ZoneInfo("America/New_York")


def checkpoint_datetime_et(research_date: str, uk_time: str) -> datetime:
    local = datetime.combine(
        date.fromisoformat(research_date),
        time.fromisoformat(uk_time),
        tzinfo=LONDON,
    )
    return local.astimezone(EASTERN)


def classify_checkpoint(research_date: str, uk_time: str) -> str:
    timestamp_et = checkpoint_datetime_et(research_date, uk_time)
    session_date = date.fromisoformat(research_date)
    minute = timestamp_et.hour * 60 + timestamp_et.minute
    if timestamp_et.date() == session_date:
        if 4 * 60 <= minute < 9 * 60 + 30:
            return "same_session_premarket"
        if 9 * 60 + 30 <= minute < 16 * 60:
            return "same_session_regular"
        if minute >= 16 * 60:
            return "same_session_afterhours"
    if timestamp_et.date() < session_date and minute >= 16 * 60:
        return "previous_session_afterhours"
    return "other"


def load_checkpoint_labels(
    observation_root: Path, dates: Iterable[str]
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day in dates:
        path = observation_root / f"{day}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("research_date") != day:
            raise ValueError(f"Observation date mismatch in {path}")
        if payload.get("screenshots_are_scanner_inputs") is not False:
            raise ValueError(f"Scanner-input boundary is not explicit in {path}")
        for checkpoint in payload.get("checkpoints", []):
            uk_time = checkpoint["actual_uk_time_start"]
            timestamp_et = checkpoint_datetime_et(day, uk_time)
            phase = classify_checkpoint(day, uk_time)
            for symbol in checkpoint.get("symbols", []):
                percentage = symbol.get("resolved_percentage_points")
                rows.append(
                    {
                        "date": day,
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "ticker": symbol.get("ticker"),
                        "actual_uk_time": uk_time,
                        "timestamp_et": timestamp_et.isoformat(),
                        "source_market_phase": checkpoint.get("market_phase"),
                        "corrected_market_phase": phase,
                        "displayed_percentage_points": percentage,
                        "suspicious_percentage": (
                            percentage is not None
                            and abs(float(percentage)) >= 100.0
                        ),
                    }
                )
    labels = pd.DataFrame(rows)
    return labels.drop_duplicates(
        ["date", "checkpoint_id", "ticker"]
    ).sort_values(["date", "timestamp_et", "ticker"])


def _emergence_bucket(hour: float) -> str:
    if hour < 6:
        return "04:00-05:59"
    if hour < 8:
        return "06:00-07:59"
    if hour < 8.5:
        return "08:00-08:29"
    return "08:30-09:29"


def aggregate_premarket_labels(labels: pd.DataFrame) -> pd.DataFrame:
    premarket = labels[
        labels.corrected_market_phase == "same_session_premarket"
    ].copy()
    checkpoint_counts = (
        premarket.groupby("date").checkpoint_id.nunique().to_dict()
    )
    records: list[dict[str, object]] = []
    for (day, ticker), rows in premarket.groupby(["date", "ticker"]):
        rows = rows.sort_values("timestamp_et")
        valid_percentage = rows[
            rows.displayed_percentage_points.notna()
            & ~rows.suspicious_percentage
        ]
        first_et = datetime.fromisoformat(str(rows.iloc[0].timestamp_et))
        appearances = int(rows.checkpoint_id.nunique())
        available = int(checkpoint_counts[day])
        records.append(
            {
                "date": day,
                "ticker": ticker,
                "first_timestamp_et": rows.iloc[0].timestamp_et,
                "last_timestamp_et": rows.iloc[-1].timestamp_et,
                "first_hour_et": first_et.hour + first_et.minute / 60.0,
                "emergence_bucket": _emergence_bucket(
                    first_et.hour + first_et.minute / 60.0
                ),
                "premarket_checkpoint_appearances": appearances,
                "available_premarket_checkpoints": available,
                "persistence_share": appearances / available,
                "persistence_bucket": (
                    "1 checkpoint"
                    if appearances == 1
                    else "2 checkpoints"
                    if appearances == 2
                    else "3+ checkpoints"
                ),
                "first_valid_displayed_percentage_points": (
                    valid_percentage.iloc[0].displayed_percentage_points
                    if not valid_percentage.empty
                    else math.nan
                ),
                "last_valid_displayed_percentage_points": (
                    valid_percentage.iloc[-1].displayed_percentage_points
                    if not valid_percentage.empty
                    else math.nan
                ),
                "had_suspicious_percentage": bool(
                    rows.suspicious_percentage.any()
                ),
            }
        )
    return pd.DataFrame(records).sort_values(["date", "ticker"])


def join_bar_outcomes(
    label_rows: pd.DataFrame, features_outcomes: Path
) -> pd.DataFrame:
    bars = pd.read_csv(features_outcomes)
    cohort = bars[
        (bars.decision_et == "09:30")
        & (bars.group == "premarket_observed")
        & bars.pm_observable.eq(True)
    ]
    return label_rows.merge(
        cohort,
        left_on=["date", "ticker"],
        right_on=["date", "symbol"],
        how="inner",
        validate="one_to_one",
    )


def summarize_buckets(joined: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for dimension in ("persistence_bucket", "emergence_bucket"):
        for bucket, rows in joined.groupby(dimension, sort=False):
            records.append(
                {
                    "dimension": dimension,
                    "bucket": bucket,
                    "symbol_dates": len(rows),
                    "median_mfe": rows.mfe.median(),
                    "median_mae": rows.mae.median(),
                    "median_ret_30m": rows.ret_30m.median(),
                    "median_ret_close": rows.ret_close.median(),
                    "share_mfe_ge_10pct": float((rows.mfe >= 0.10).mean()),
                    "share_mfe_ge_20pct": float((rows.mfe >= 0.20).mean()),
                }
            )
    return pd.DataFrame(records)


def label_correlations(joined: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    features = (
        "premarket_checkpoint_appearances",
        "persistence_share",
        "first_hour_et",
    )
    outcomes = ("mfe", "mae", "ret_30m", "ret_close")
    for feature in features:
        for outcome in outcomes:
            valid = joined[["date", feature, outcome]].dropna()
            pooled = (
                float(spearmanr(valid[feature], valid[outcome]).statistic)
                if valid[feature].nunique() > 1
                else math.nan
            )
            per_date: list[float] = []
            for _, date_rows in valid.groupby("date"):
                if (
                    len(date_rows) >= 5
                    and date_rows[feature].nunique() > 1
                    and date_rows[outcome].nunique() > 1
                ):
                    per_date.append(
                        float(
                            spearmanr(
                                date_rows[feature], date_rows[outcome]
                            ).statistic
                        )
                    )
            records.append(
                {
                    "feature": feature,
                    "outcome": outcome,
                    "n": len(valid),
                    "pooled_spearman_rho": pooled,
                    "dates_with_estimate": len(per_date),
                    "median_per_date_rho": (
                        float(np.median(per_date))
                        if per_date
                        else math.nan
                    ),
                    "dates_positive": sum(value > 0 for value in per_date),
                    "dates_negative": sum(value < 0 for value in per_date),
                }
            )
    return pd.DataFrame(records)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--observation-root",
        type=Path,
        default=Path("config/research-observations"),
    )
    parser.add_argument("--features-outcomes", type=Path, required=True)
    parser.add_argument("--dates", nargs="+", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    dates = sorted(dict.fromkeys(args.dates))
    checkpoints = load_checkpoint_labels(args.observation_root, dates)
    label_rows = aggregate_premarket_labels(checkpoints)
    joined = join_bar_outcomes(label_rows, args.features_outcomes)
    summary = summarize_buckets(joined)
    correlations = label_correlations(joined)

    checkpoints.to_csv(
        args.output_dir / "screenshot-checkpoint-labels.csv", index=False
    )
    joined.to_csv(
        args.output_dir / "screenshot-symbol-behavior.csv", index=False
    )
    summary.to_csv(
        args.output_dir / "screenshot-behavior-summary.csv", index=False
    )
    correlations.to_csv(
        args.output_dir / "screenshot-label-correlations.csv", index=False
    )
    print(
        json.dumps(
            {
                "dates": len(dates),
                "checkpoint_rows": len(checkpoints),
                "premarket_label_symbol_dates": len(label_rows),
                "joined_symbol_dates": len(joined),
                "output_dir": str(args.output_dir),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
