import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_engine_v2_phase1.py"
SPEC = importlib.util.spec_from_file_location("analyze_engine_v2_phase1", SCRIPT)
analysis = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(analysis)


class EngineV2Phase1Tests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        pilot = root / "pilot"
        v1 = pilot / "analysis"
        v1.mkdir(parents=True)
        universe = {
            "assets": [
                {"symbol": "STKA", "name": "Stock A", "exchange": "NASDAQ"},
                {"symbol": "STKB", "name": "Stock B", "exchange": "NYSE"},
                {"symbol": "FUND", "name": "Fund", "exchange": "ARCA"},
                {"symbol": "WARR.WS", "name": "Warrant", "exchange": "NYSE"},
                {"symbol": "UNKNOWN", "name": "Unknown", "exchange": "NASDAQ"},
            ]
        }
        (pilot / "universe.json").write_text(json.dumps(universe), encoding="utf-8")
        master = {
            "security_master_version": "test-master",
            "source_url": "fixture",
            "source_sha256": "a" * 64,
            "captured_at_utc": "2026-09-15T08:00:00+00:00",
            "securities": [
                {"source_symbol": "STKA", "aliases": ["STKA"], "security_name": "Stock A Common Stock", "instrument_type": "common_stock", "primary_stock_eligible": True, "possible_spac_common": False, "classification_reason": "EXPLICIT_COMMON_STOCK_DESCRIPTION"},
                {"source_symbol": "STKB", "aliases": ["STKB"], "security_name": "Stock B Ordinary Shares", "instrument_type": "ordinary_shares", "primary_stock_eligible": True, "possible_spac_common": False, "classification_reason": "EXPLICIT_ORDINARY_SHARE_DESCRIPTION"},
                {"source_symbol": "FUND", "aliases": ["FUND"], "security_name": "Example ETF", "instrument_type": "pooled_product", "primary_stock_eligible": False, "possible_spac_common": False, "classification_reason": "NASDAQ_ETF_OR_NEXTSHARES_FLAG"},
                {"source_symbol": "WARR.W", "aliases": ["WARR.WS"], "security_name": "Example Warrant", "instrument_type": "warrant", "primary_stock_eligible": False, "possible_spac_common": False, "classification_reason": "EXPLICIT_WARRANT_DESCRIPTION"},
            ],
        }
        master_path = root / "master.json"
        master_path.write_text(json.dumps(master), encoding="utf-8")

        feature_rows = []
        outcome_rows = []
        v1_rows = []
        for decision in analysis.DECISIONS:
            for symbol, activity, activation, momentum, absolute in [
                ("STKA", 1000, 0.95, 0.70, 0.85),
                ("STKB", 0, 0.90, 0.99, 0.80),
                ("FUND", 5000, 0.99, 0.98, 0.99),
                ("WARR.WS", 3000, 0.98, 0.97, 0.98),
                ("UNKNOWN", 2000, 0.97, 0.96, 0.97),
            ]:
                feature_rows.append({
                    "session_date": "2026-09-11", "symbol": symbol, "decision": decision,
                    "pm_volume": activity, "pm_bar_count": 1 if activity else 0,
                    "pm_active_bars": 1 if activity else 0,
                    "pm_dollar_volume": activity * 10,
                    "pm_trade_count": activity / 10,
                    "pm_log_volume_surprise_vs_daily_20": activation,
                    "pm_return_latest_15m": momentum,
                    "pm_price_acceleration_15m": momentum,
                    "pm_range_position": momentum,
                    "pm_drawdown_from_high": momentum,
                    "pm_last_vs_vwap": momentum,
                    "opening_return": momentum if decision != "open" else float("nan"),
                    "opening_range_position": momentum if decision != "open" else float("nan"),
                    "opening_drawdown_from_high": momentum if decision != "open" else float("nan"),
                    "opening_dollar_volume": activity if decision != "open" else 0,
                    "broad_collection_status": "completed",
                    "daily_volume_activation_score": activation,
                    "emerging_structure_score": momentum,
                    "absolute_activity_score": absolute,
                    "opening_confirmation_score": momentum if decision != "open" else float("nan"),
                    "data_quality_and_risk_flags": "SPREAD_UNAVAILABLE",
                })
                outcome_rows.append({
                    "session_date": "2026-09-11", "symbol": symbol, "decision": decision,
                    "mfe": 0.25 if symbol == "STKA" else 0.01,
                    "mae": -0.03, "ret_close": 0.10 if symbol == "STKA" else -0.01,
                })
                v1_rows.append({
                    "session_date": "2026-09-11", "symbol": symbol, "decision": decision,
                    "channel_budget": 100, "pilot_consensus_score": activation,
                    "pilot_consensus_rank": {
                        "FUND": 1, "WARR.WS": 2, "UNKNOWN": 3, "STKA": 4, "STKB": 5,
                    }[symbol],
                })
        pd.DataFrame(feature_rows).to_csv(v1 / "broad-features.csv.gz", index=False, compression="gzip")
        pd.DataFrame(outcome_rows).to_csv(v1 / "retrospective-outcomes.csv.gz", index=False, compression="gzip")
        pd.DataFrame(v1_rows).to_csv(v1 / "candidate-unions.csv.gz", index=False, compression="gzip")
        return pilot, master_path

    def test_classification_excludes_nonstocks_and_unresolved(self):
        with tempfile.TemporaryDirectory() as directory:
            pilot, master_path = self._fixture(Path(directory))
            universe = json.loads((pilot / "universe.json").read_text(encoding="utf-8"))
            master = json.loads(master_path.read_text(encoding="utf-8"))
            classified = analysis.classify_universe(universe, master).set_index("symbol")
            self.assertTrue(classified.at["STKA", "primary_stock_eligible"])
            self.assertFalse(classified.at["FUND", "primary_stock_eligible"])
            self.assertEqual("unique_alias", classified.at["WARR.WS", "master_match_status"])
            self.assertEqual("unknown", classified.at["UNKNOWN", "instrument_type"])

    def test_v2_scores_are_recomputed_inside_stock_only_population(self):
        features = pd.DataFrame([
            {
                "symbol": symbol,
                "decision": "open",
                "pm_volume": 100,
                "pm_bar_count": 1,
                "pm_active_bars": active_bars,
                "pm_dollar_volume": dollar_volume,
                "pm_trade_count": 10,
                "pm_log_volume_surprise_vs_daily_20": surprise,
                "pm_return_latest_15m": 0,
                "pm_price_acceleration_15m": 0,
                "pm_range_position": 0.5,
                "pm_drawdown_from_high": 0,
                "pm_last_vs_vwap": 0,
                "opening_return": float("nan"),
                "opening_range_position": float("nan"),
                "opening_drawdown_from_high": float("nan"),
                "opening_dollar_volume": 0,
                "broad_collection_status": "completed",
                "daily_volume_activation_score": old_score,
                "emerging_structure_score": 0,
                "absolute_activity_score": 0,
                "opening_confirmation_score": float("nan"),
            }
            for symbol, active_bars, dollar_volume, surprise, old_score in [
                ("HIGH", 10, 10_000, 5, 0.01),
                ("LOW", 1, 100, 1, 0.99),
            ]
        ])
        classifications = pd.DataFrame([
            {
                "symbol": symbol,
                "instrument_type": "common_stock",
                "primary_stock_eligible": True,
                "possible_spac_common": False,
                "classification_reason": "fixture",
                "master_match_status": "fixture",
            }
            for symbol in ("HIGH", "LOW")
        ])
        scored = analysis.build_stock_features(features, classifications).set_index("symbol")
        self.assertEqual(1, scored.at["HIGH", "activation_rank"])
        self.assertGreater(scored.at["HIGH", "activation_score"], scored.at["LOW", "activation_score"])

    def test_end_to_end_keeps_profiles_separate_and_removes_dormancy(self):
        with tempfile.TemporaryDirectory() as directory:
            pilot, master_path = self._fixture(Path(directory))
            output = analysis.run(pilot, master_path)
            manifest = json.loads((output / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["dormant_activation_enabled"])
            self.assertTrue(manifest["stock_only_primary_universe"])
            self.assertTrue(manifest["ranking_outcome_separation"])
            channels = pd.read_csv(output / "v2-channel-rankings.csv.gz")
            self.assertNotIn("dormant_activation", set(channels.channel))
            self.assertEqual({"STKA"}, set(channels.symbol))
            rankings = pd.read_csv(output / "model-rankings.csv.gz")
            v2 = rankings.loc[rankings.model.str.startswith("v2_")]
            self.assertEqual({"STKA"}, set(v2.symbol))
            v1 = rankings.loc[rankings.model == "v1_consensus_original"]
            self.assertIn("FUND", set(v1.symbol))
            self.assertFalse(set(analysis.FUTURE_COLUMNS) & set(rankings.columns))
            evaluation = pd.read_csv(output / "model-evaluation.csv")
            row = evaluation.loc[
                (evaluation.decision == "open")
                & (evaluation.model == "v2_activation")
                & (evaluation.top_k == 5)
                & (evaluation.threshold == 0.20)
            ].iloc[0]
            self.assertEqual(1, row.hits)
            self.assertEqual(1.0, row.precision)


if __name__ == "__main__":
    unittest.main()
