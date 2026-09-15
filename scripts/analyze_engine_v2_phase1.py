#!/usr/bin/env python3
"""Run the stock-only Engine v2 Phase 1 experiment on a v1 pilot artifact.

This analysis leaves the v1 artifact unchanged. It applies a dated security
master, requires current premarket activity, removes dormant selection, keeps
activation and momentum profiles separate, and writes direct v1/v2 evaluation
tables. It is retrospective research and contains no order functionality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


EXPERIMENT_VERSION = "engine-v2-phase1-v1"
RANKING_VERSION = "stock-only-separate-profiles-v1"
CHANNEL_BUDGETS = (20, 50, 100)
EVALUATION_K = (5, 10, 20, 50, 100)
MFE_THRESHOLDS = (0.10, 0.20, 0.30)
DECISIONS = ("open", "open+15", "open+30")
FUTURE_COLUMNS = {
    "entry_price", "ret_5m", "ret_15m", "ret_30m", "ret_60m",
    "ret_120m", "ret_close", "mfe", "mae", "regular_high",
    "raw_previous_close_to_regular_high", "true_previous_close_to_regular_high",
}
PROFILE_CONFIG = {
    "v2_activation": "activation_score",
    "v2_momentum_quality": "momentum_quality_score",
    "v2_absolute_activity_baseline": "absolute_activity_v2_score",
}
CHANNEL_CONFIG = {
    "absolute_activity": "absolute_activity_v2_score",
    "daily_volume_activation": "activation_score",
    "emerging_structure": "momentum_quality_score",
}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ValueError(f"Required pilot file is missing: {path}")
    return pd.read_csv(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}") from exc


def _master_lookup(master: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in master.get("securities", []):
        for alias in record.get("aliases", []):
            alias = str(alias).strip().upper()
            if alias:
                lookup[alias].append(record)
    return lookup


def classify_universe(universe: dict[str, Any], master: dict[str, Any]) -> pd.DataFrame:
    lookup = _master_lookup(master)
    rows: list[dict[str, Any]] = []
    for asset in universe.get("assets", []):
        symbol = str(asset.get("symbol") or "").strip().upper()
        matches = lookup.get(symbol, [])
        exact = [row for row in matches if row.get("source_symbol") == symbol]
        if len(exact) == 1:
            selected = exact[0]
            match_status = "exact_source_symbol"
        elif len(matches) == 1:
            selected = matches[0]
            match_status = "unique_alias"
        elif matches and len({row.get("instrument_type") for row in matches}) == 1:
            selected = sorted(matches, key=lambda row: str(row.get("source_symbol")))[0]
            match_status = "alias_collision_same_type"
        else:
            selected = None
            match_status = "ambiguous_alias" if matches else "unmatched"
        if selected is None:
            instrument_type = "unknown"
            eligible = False
            reason = "AMBIGUOUS_SECURITY_MASTER_ALIAS" if matches else "NO_SECURITY_MASTER_MATCH"
            security_name = None
            source_symbol = None
            possible_spac = False
        else:
            instrument_type = str(selected.get("instrument_type") or "unknown")
            eligible = bool(selected.get("primary_stock_eligible"))
            reason = str(selected.get("classification_reason") or "UNKNOWN_REASON")
            security_name = selected.get("security_name")
            source_symbol = selected.get("source_symbol")
            possible_spac = bool(selected.get("possible_spac_common"))
        rows.append({
            "symbol": symbol,
            "alpaca_name": asset.get("name"),
            "alpaca_exchange": asset.get("exchange"),
            "instrument_type": instrument_type,
            "primary_stock_eligible": eligible,
            "possible_spac_common": possible_spac,
            "classification_reason": reason,
            "master_match_status": match_status,
            "master_source_symbol": source_symbol,
            "master_security_name": security_name,
        })
    return pd.DataFrame(rows).sort_values("symbol").reset_index(drop=True)


def _rank(frame: pd.DataFrame, score_column: str) -> pd.Series:
    ranks = pd.Series(math.nan, index=frame.index, dtype=float)
    eligible = pd.to_numeric(frame[score_column], errors="coerce").notna()
    ordered = frame.loc[eligible].sort_values(
        [score_column, "symbol"], ascending=[False, True]
    )
    ranks.loc[ordered.index] = np.arange(1, len(ordered) + 1)
    return ranks


def _percentile(series: pd.Series, *, higher_is_better: bool = True) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.rank(method="average", pct=True, ascending=higher_is_better)


def _profile_score(
    frame: pd.DataFrame,
    components: list[tuple[str, bool]],
) -> tuple[pd.Series, pd.Series]:
    values = pd.concat(
        [
            _percentile(frame[column], higher_is_better=higher_is_better)
            for column, higher_is_better in components
        ],
        axis=1,
    )
    return values.mean(axis=1, skipna=True), values.notna().mean(axis=1)


def build_stock_features(
    features: pd.DataFrame, classifications: pd.DataFrame
) -> pd.DataFrame:
    merged = features.merge(classifications, on="symbol", how="left", validate="many_to_one")
    merged["primary_stock_eligible"] = merged["primary_stock_eligible"].eq(True)
    merged["current_premarket_activity"] = (
        pd.to_numeric(merged["pm_volume"], errors="coerce").fillna(0) > 0
    ) & (pd.to_numeric(merged["pm_bar_count"], errors="coerce").fillna(0) > 0)
    merged["v2_primary_eligible"] = (
        merged["primary_stock_eligible"]
        & merged["current_premarket_activity"]
        & merged["broad_collection_status"].ne("failed")
    )
    for column in (
        "activation_score", "activation_coverage", "momentum_quality_score",
        "momentum_quality_coverage", "absolute_activity_v2_score",
        "absolute_activity_v2_coverage", "opening_confirmation_v2_score",
        "opening_confirmation_v2_coverage", "activation_rank",
        "momentum_quality_rank", "absolute_activity_rank",
        "opening_confirmation_rank",
    ):
        merged[column] = math.nan
    for decision, indexes in merged.groupby("decision", sort=False).groups.items():
        eligible_indexes = [index for index in indexes if merged.at[index, "v2_primary_eligible"]]
        subset = merged.loc[eligible_indexes]
        activation_score, activation_coverage = _profile_score(subset, [
            ("pm_log_volume_surprise_vs_daily_20", True),
            ("pm_dollar_volume", True),
            ("pm_active_bars", True),
        ])
        momentum_score, momentum_coverage = _profile_score(subset, [
            ("pm_return_latest_15m", True),
            ("pm_price_acceleration_15m", True),
            ("pm_range_position", True),
            ("pm_drawdown_from_high", True),
            ("pm_last_vs_vwap", True),
        ])
        absolute_score, absolute_coverage = _profile_score(subset, [
            ("pm_dollar_volume", True),
            ("pm_trade_count", True),
            ("pm_active_bars", True),
        ])
        merged.loc[eligible_indexes, "activation_score"] = activation_score
        merged.loc[eligible_indexes, "activation_coverage"] = activation_coverage
        merged.loc[eligible_indexes, "momentum_quality_score"] = momentum_score
        merged.loc[eligible_indexes, "momentum_quality_coverage"] = momentum_coverage
        merged.loc[eligible_indexes, "absolute_activity_v2_score"] = absolute_score
        merged.loc[eligible_indexes, "absolute_activity_v2_coverage"] = absolute_coverage
        merged.loc[eligible_indexes, "activation_rank"] = _rank(
            merged.loc[eligible_indexes], "activation_score"
        ).values
        merged.loc[eligible_indexes, "momentum_quality_rank"] = _rank(
            merged.loc[eligible_indexes], "momentum_quality_score"
        ).values
        merged.loc[eligible_indexes, "absolute_activity_rank"] = _rank(
            merged.loc[eligible_indexes], "absolute_activity_v2_score"
        ).values
        if decision != "open":
            opening_score, opening_coverage = _profile_score(subset, [
                ("opening_return", True),
                ("opening_range_position", True),
                ("opening_drawdown_from_high", True),
                ("opening_dollar_volume", True),
            ])
            merged.loc[eligible_indexes, "opening_confirmation_v2_score"] = opening_score
            merged.loc[eligible_indexes, "opening_confirmation_v2_coverage"] = opening_coverage
            merged.loc[eligible_indexes, "opening_confirmation_rank"] = _rank(
                merged.loc[eligible_indexes], "opening_confirmation_v2_score"
            ).values
    return merged


def build_channel_rows(stock_features: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for decision, frame in stock_features.groupby("decision", sort=False):
        eligible = frame.loc[frame.v2_primary_eligible].copy()
        configs = dict(CHANNEL_CONFIG)
        if decision != "open":
            configs["opening_confirmation"] = "opening_confirmation_v2_score"
        for channel, score_column in configs.items():
            values = eligible[["session_date", "symbol", "decision"]].copy()
            values["channel"] = channel
            values["channel_score"] = pd.to_numeric(eligible[score_column], errors="coerce")
            values["channel_rank"] = _rank(
                eligible.assign(_channel_score=values["channel_score"]), "_channel_score"
            ).values
            values["enabled_for_candidate_union"] = True
            values["ranking_version"] = RANKING_VERSION
            rows.append(values)
    if not rows:
        return pd.DataFrame(columns=[
            "session_date", "symbol", "decision", "channel", "channel_score",
            "channel_rank", "enabled_for_candidate_union", "ranking_version",
        ])
    return pd.concat(rows, ignore_index=True)


def build_candidate_unions(
    stock_features: pd.DataFrame, channels: pd.DataFrame
) -> pd.DataFrame:
    output: list[dict[str, Any]] = []
    feature_lookup = stock_features.set_index(["decision", "symbol"])
    for decision in DECISIONS:
        decision_channels = channels.loc[channels.decision == decision]
        for budget in CHANNEL_BUDGETS:
            hits = decision_channels.loc[decision_channels.channel_rank <= budget]
            for symbol, symbol_hits in hits.groupby("symbol", sort=True):
                feature = feature_lookup.loc[(decision, symbol)]
                names = sorted(symbol_hits.channel.astype(str).unique())
                output.append({
                    "session_date": feature.session_date,
                    "symbol": symbol,
                    "decision": decision,
                    "channel_budget": budget,
                    "channels_hit": "|".join(names),
                    "channel_hit_count": len(names),
                    "best_channel_rank": float(symbol_hits.channel_rank.min()),
                    "activation_score": feature.activation_score,
                    "activation_rank": feature.activation_rank,
                    "momentum_quality_score": feature.momentum_quality_score,
                    "momentum_quality_rank": feature.momentum_quality_rank,
                    "opening_confirmation_score": feature.opening_confirmation_v2_score,
                    "opening_confirmation_rank": feature.get("opening_confirmation_rank", math.nan),
                    "possible_spac_common": bool(feature.possible_spac_common),
                    "data_quality_and_risk_flags": feature.data_quality_and_risk_flags,
                    "research_only": True,
                    "orders_supported": False,
                    "ranking_version": RANKING_VERSION,
                })
    return pd.DataFrame(output)


def build_model_rankings(
    stock_features: pd.DataFrame, v1_unions: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    max_budget = int(pd.to_numeric(v1_unions.channel_budget, errors="coerce").max())
    classification = stock_features.loc[
        stock_features.decision == "open",
        ["symbol", "instrument_type", "primary_stock_eligible"],
    ].drop_duplicates("symbol")

    for decision, frame in stock_features.groupby("decision", sort=False):
        eligible = frame.loc[frame.v2_primary_eligible].copy()
        configs = dict(PROFILE_CONFIG)
        if decision != "open":
            configs["v2_opening_confirmation"] = "opening_confirmation_v2_score"
        for model, score_column in configs.items():
            ranked = eligible.dropna(subset=[score_column]).sort_values(
                [score_column, "symbol"], ascending=[False, True]
            )
            for rank, (_, row) in enumerate(ranked.iterrows(), start=1):
                rows.append({
                    "session_date": row.session_date,
                    "decision": decision,
                    "model": model,
                    "model_rank": rank,
                    "model_score": row[score_column],
                    "symbol": row.symbol,
                    "instrument_type": row.instrument_type,
                    "primary_stock_eligible": True,
                    "current_premarket_activity": True,
                    "research_only": True,
                    "orders_supported": False,
                    "ranking_version": RANKING_VERSION,
                })

        original = v1_unions.loc[
            (v1_unions.decision == decision)
            & (pd.to_numeric(v1_unions.channel_budget, errors="coerce") == max_budget)
        ].merge(classification, on="symbol", how="left")
        original = original.sort_values(
            ["pilot_consensus_rank", "symbol"], ascending=[True, True]
        )
        activity = frame.set_index("symbol")["current_premarket_activity"]
        for rank, (_, row) in enumerate(original.iterrows(), start=1):
            rows.append({
                "session_date": row.session_date,
                "decision": decision,
                "model": "v1_consensus_original",
                "model_rank": rank,
                "model_score": row.pilot_consensus_score,
                "symbol": row.symbol,
                "instrument_type": row.get("instrument_type", "unknown"),
                "primary_stock_eligible": row.get("primary_stock_eligible") is True,
                "current_premarket_activity": bool(activity.get(row.symbol, False)),
                "research_only": True,
                "orders_supported": False,
                "ranking_version": "v1-original-pilot-consensus",
            })
        stock_only = original.loc[
            original.primary_stock_eligible.fillna(False)
            & original.symbol.map(activity).fillna(False)
        ].sort_values(["pilot_consensus_score", "symbol"], ascending=[False, True])
        for rank, (_, row) in enumerate(stock_only.iterrows(), start=1):
            rows.append({
                "session_date": row.session_date,
                "decision": decision,
                "model": "v1_consensus_stock_only",
                "model_rank": rank,
                "model_score": row.pilot_consensus_score,
                "symbol": row.symbol,
                "instrument_type": row.instrument_type,
                "primary_stock_eligible": True,
                "current_premarket_activity": True,
                "research_only": True,
                "orders_supported": False,
                "ranking_version": "v1-consensus-filtered-stock-only",
            })
    return pd.DataFrame(rows)


def evaluate_models(
    rankings: pd.DataFrame,
    outcomes: pd.DataFrame,
    classifications: pd.DataFrame,
) -> pd.DataFrame:
    stock_symbols = set(
        classifications.loc[classifications.primary_stock_eligible, "symbol"]
    )
    rows: list[dict[str, Any]] = []
    for decision in DECISIONS:
        decision_outcomes = outcomes.loc[
            (outcomes.decision == decision) & outcomes.symbol.isin(stock_symbols)
        ].copy()
        eligible_outcomes = decision_outcomes.dropna(subset=["mfe"])
        outcome_lookup = eligible_outcomes.set_index("symbol")
        for model, model_rows in rankings.loc[
            rankings.decision == decision
        ].groupby("model", sort=True):
            ordered = model_rows.sort_values("model_rank")
            for k in EVALUATION_K:
                selected = ordered.head(k)
                selected_symbols = set(selected.symbol)
                selected_outcomes = outcome_lookup.loc[
                    outcome_lookup.index.intersection(selected_symbols)
                ]
                for threshold in MFE_THRESHOLDS:
                    positives = set(eligible_outcomes.loc[
                        eligible_outcomes.mfe >= threshold, "symbol"
                    ])
                    hits = selected_symbols & positives
                    rows.append({
                        "session_date": decision_outcomes.session_date.iloc[0],
                        "decision": decision,
                        "model": model,
                        "top_k": k,
                        "threshold": threshold,
                        "stock_population_with_outcomes": len(eligible_outcomes),
                        "stock_population_positives": len(positives),
                        "selected": len(selected),
                        "selected_primary_stocks": int(selected.primary_stock_eligible.sum()),
                        "selected_nonstock_or_unknown": int((~selected.primary_stock_eligible).sum()),
                        "selected_with_stock_outcomes": len(selected_outcomes),
                        "hits": len(hits),
                        "precision": len(hits) / len(selected) if len(selected) else math.nan,
                        "recall": len(hits) / len(positives) if positives else math.nan,
                        "median_mfe": pd.to_numeric(selected_outcomes.mfe, errors="coerce").median(),
                        "median_mae": pd.to_numeric(selected_outcomes.mae, errors="coerce").median(),
                        "median_ret_close": pd.to_numeric(
                            selected_outcomes.ret_close, errors="coerce"
                        ).median(),
                    })
    return pd.DataFrame(rows)


def comparison_table(evaluation: pd.DataFrame) -> pd.DataFrame:
    baseline = evaluation.loc[evaluation.model == "v1_consensus_original"].set_index(
        ["session_date", "decision", "top_k", "threshold"]
    )
    rows: list[dict[str, Any]] = []
    for _, row in evaluation.loc[evaluation.model != "v1_consensus_original"].iterrows():
        key = (row.session_date, row.decision, row.top_k, row.threshold)
        if key not in baseline.index:
            continue
        base = baseline.loc[key]
        rows.append({
            **row.to_dict(),
            "baseline_model": "v1_consensus_original",
            "baseline_precision": base.precision,
            "baseline_recall": base.recall,
            "precision_delta": row.precision - base.precision,
            "recall_delta": row.recall - base.recall,
            "nonstock_selection_delta": (
                row.selected_nonstock_or_unknown - base.selected_nonstock_or_unknown
            ),
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


def run(pilot_dir: Path, security_master_path: Path) -> Path:
    v1_dir = pilot_dir / "analysis"
    output_dir = pilot_dir / "analysis-v2-phase1"
    universe = _read_json(pilot_dir / "universe.json")
    master = _read_json(security_master_path)
    features = _read_csv(v1_dir / "broad-features.csv.gz")
    v1_unions = _read_csv(v1_dir / "candidate-unions.csv.gz")
    outcomes = _read_csv(v1_dir / "retrospective-outcomes.csv.gz")
    if FUTURE_COLUMNS & set(features.columns):
        raise ValueError("Future outcome fields were found in v1 broad features")
    classifications = classify_universe(universe, master)
    stock_features = build_stock_features(features, classifications)
    channels = build_channel_rows(stock_features)
    unions = build_candidate_unions(stock_features, channels)
    rankings = build_model_rankings(stock_features, v1_unions)
    evaluation = evaluate_models(rankings, outcomes, classifications)
    comparison = comparison_table(evaluation)

    output_dir.mkdir(parents=True, exist_ok=True)
    classifications.to_csv(
        output_dir / "security-classification.csv.gz", index=False, compression="gzip"
    )
    stock_features.to_csv(
        output_dir / "stock-broad-features.csv.gz", index=False, compression="gzip"
    )
    channels.to_csv(
        output_dir / "v2-channel-rankings.csv.gz", index=False, compression="gzip"
    )
    unions.to_csv(
        output_dir / "candidate-unions.csv.gz", index=False, compression="gzip"
    )
    rankings.to_csv(
        output_dir / "model-rankings.csv.gz", index=False, compression="gzip"
    )
    evaluation.to_csv(output_dir / "model-evaluation.csv", index=False)
    comparison.to_csv(output_dir / "v1-v2-comparison.csv", index=False)
    ranking_columns = [column for column in rankings.columns if column not in FUTURE_COLUMNS]
    for decision in DECISIONS:
        for model in ("v2_activation", "v2_momentum_quality"):
            selected = rankings.loc[
                (rankings.decision == decision) & (rankings.model == model),
                ranking_columns,
            ].head(100)
            selected.to_csv(
                output_dir / f"rankings-{decision.replace('+', '-plus-')}-{model}.csv",
                index=False,
            )

    instrument_counts = Counter(classifications.instrument_type.astype(str))
    open_features = stock_features.loc[stock_features.decision == "open"]
    quality = {
        "universe_assets": len(classifications),
        "primary_stock_assets": int(classifications.primary_stock_eligible.sum()),
        "primary_stocks_with_premarket_activity": int(open_features.v2_primary_eligible.sum()),
        "unresolved_assets": int((classifications.instrument_type == "unknown").sum()),
        "possible_spac_common_assets": int(classifications.possible_spac_common.sum()),
        "instrument_type_counts": dict(sorted(instrument_counts.items())),
        "security_master_version": master.get("security_master_version"),
        "security_master_source": master.get("source_url"),
        "security_master_source_sha256": master.get("source_sha256"),
        "security_master_captured_at_utc": master.get("captured_at_utc"),
        "historical_classification_warning": (
            "The security master was captured after the historical pilot session; "
            "classification is suitable for Phase 1 comparison but retains survivorship and symbol-change risk."
        ),
    }
    (output_dir / "data-quality.json").write_text(
        json.dumps(_json_safe(quality), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "experiment_version": EXPERIMENT_VERSION,
        "ranking_version": RANKING_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "session_date": str(features.session_date.iloc[0]),
        "research_only": True,
        "orders_supported": False,
        "stock_only_primary_universe": True,
        "dormant_activation_enabled": False,
        "current_premarket_activity_required": True,
        "profiles_kept_separate": [
            "activation", "momentum_quality", "opening_confirmation"
        ],
        "primary_ordering": "v2_activation uses daily-volume-activation proxy; no consensus average",
        "candidate_routes": sorted(CHANNEL_CONFIG),
        "comparison_models": sorted(rankings.model.unique()),
        "ranking_outcome_separation": not bool(FUTURE_COLUMNS & set(rankings.columns)),
        "limitations": [
            "Five-minute broad features only; one-minute candidate detail is Phase 2.",
            "Activation uses the pilot daily-volume baseline, not a same-time historical premarket baseline.",
            "Corporate-action-verified true gaps remain unavailable.",
            "Catalysts, options, float, short interest, quotes, and spread are not used in Phase 1.",
            "SEC issuer identity is not yet used; ambiguous beneficial-interest securities remain unresolved.",
            quality["historical_classification_warning"],
        ],
        "files": sorted(path.name for path in output_dir.iterdir() if path.is_file()),
    }
    (output_dir / "run-manifest.json").write_text(
        json.dumps(_json_safe(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    digest = hashlib.sha256((output_dir / "run-manifest.json").read_bytes()).hexdigest()
    print(json.dumps({
        "analysis_dir": str(output_dir),
        "primary_stock_assets": quality["primary_stock_assets"],
        "primary_stocks_with_premarket_activity": quality["primary_stocks_with_premarket_activity"],
        "ranking_rows": len(rankings),
        "evaluation_rows": len(evaluation),
        "manifest_sha256": digest,
    }, sort_keys=True))
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-dir", required=True, type=Path)
    parser.add_argument("--security-master", required=True, type=Path)
    args = parser.parse_args()
    try:
        run(args.pilot_dir, args.security_master)
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
