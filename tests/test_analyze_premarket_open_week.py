import importlib.util
import math
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_premarket_open_week.py"
SPEC = importlib.util.spec_from_file_location("week_analysis", SCRIPT)
analysis = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(analysis)


class WeekAnalysisTests(unittest.TestCase):
    def setUp(self):
        tz = "America/New_York"
        times = ["08:00", "09:00", "09:29", "09:30", "09:44", "09:45", "09:59", "10:00", "10:04"]
        self.bars = pd.DataFrame({
            "timestamp_et": [pd.Timestamp(f"2026-07-27 {t}", tz=tz) for t in times],
            "open": [10, 11, 12, 12, 13, 14, 15, 16, 17],
            "high": [10.2, 11.2, 12.2, 12.2, 13.2, 14.2, 15.2, 16.2, 17.2],
            "low": [9.8, 10.8, 11.8, 11.8, 12.8, 13.8, 14.8, 15.8, 16.8],
            "close": [10.1, 11.1, 12.1, 12.1, 13.1, 14.1, 15.1, 16.1, 17.1],
            "volume": [100] * len(times), "trade_count": [10] * len(times), "vwap": [10, 11, 12, 12, 13, 14, 15, 16, 17],
        })

    def test_0930_features_exclude_opening_bar(self):
        row = analysis._base_features("2026-07-27", "TEST", "premarket_observed", self.bars, "09:30")
        self.assertEqual(row["pm_bar_count"], 3)
        self.assertTrue(math.isnan(row["open_return"]))
        self.assertAlmostEqual(row["price_at_decision"], 12.1)

    def test_0945_features_use_only_completed_opening_bars(self):
        row = analysis._base_features("2026-07-27", "TEST", "premarket_observed", self.bars, "09:45")
        self.assertAlmostEqual(row["open_return"], 13.1 / 12 - 1)
        self.assertAlmostEqual(row["price_at_decision"], 13.1)

    def test_entry_is_first_bar_at_or_after_decision(self):
        outcome = analysis._outcomes("2026-07-27", self.bars, "09:45")
        self.assertEqual(outcome["entry_price"], 14)
        self.assertTrue(outcome["entry_timestamp_et"].endswith("09:45:00-04:00"))

    def test_ranking_score_is_independent_of_outcomes(self):
        protocol = {
            "protocol_version": "test",
            "feature_set_version": "test",
            "outcome_set_version": "test",
            "ranking_models": {
                "signal": {"open_features": ["pm_return"], "delayed_features": []}
            },
        }
        rows = pd.DataFrame([
            {"date": "2026-07-27", "decision_et": "09:30", "symbol": "A", "group": "premarket_observed", "pm_return": 0.2, "mfe": 0.1},
            {"date": "2026-07-27", "decision_et": "09:30", "symbol": "B", "group": "premarket_observed", "pm_return": 0.1, "mfe": 0.9},
        ])
        first = analysis.build_rankings(rows, protocol)
        changed = rows.copy()
        changed["mfe"] = [9.0, -9.0]
        second = analysis.build_rankings(changed, protocol)
        self.assertEqual(first[["symbol", "score", "rank"]].to_dict("records"), second[["symbol", "score", "rank"]].to_dict("records"))

    def test_failure_labels_are_derived_from_future_path_only(self):
        outcome = analysis._outcomes("2026-07-27", self.bars, "09:45")
        self.assertIn("high_to_close_giveback", outcome)
        self.assertGreaterEqual(outcome["time_to_high_min"], 0)


if __name__ == "__main__":
    unittest.main()
