import importlib.util
import json
import math
import tempfile
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
            "symbol": ["TEST"] * len(times),
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

    def _daily_history(self, sessions=120):
        dates = pd.bdate_range(end="2026-07-24", periods=sessions)
        return pd.DataFrame({
            "symbol": ["TEST"] * sessions,
            "session_date": [value.date().isoformat() for value in dates],
            "open": [9.0] * sessions,
            "high": [9.1] * sessions,
            "low": [8.9] * sessions,
            "close": [9.0] * sessions,
            "volume": [1_000.0] * sessions,
            "trade_count": [100.0] * sessions,
            "vwap": [9.0] * sessions,
        })

    def _after_hours(self):
        tz = "America/New_York"
        return pd.DataFrame({
            "symbol": ["TEST", "TEST"],
            "timestamp_et": [
                pd.Timestamp("2026-07-24 16:00", tz=tz),
                pd.Timestamp("2026-07-24 19:59", tz=tz),
            ],
            "open": [9.1, 9.4],
            "high": [9.3, 9.8],
            "low": [9.0, 9.3],
            "close": [9.2, 9.5],
            "volume": [100.0, 200.0],
            "trade_count": [10.0, 20.0],
            "vwap": [9.15, 9.45],
        })

    def test_true_gap_requires_verified_corporate_action_status(self):
        common = dict(
            day="2026-07-27",
            symbol="TEST",
            group="premarket_observed",
            bars=self.bars,
            decision="09:30",
            daily_history=self._daily_history(),
            after_hours=self._after_hours(),
        )
        unavailable = analysis._base_features(
            **common,
            context_metadata={
                "corporate_actions": {"status": "unavailable_not_collected"},
                "price_adjustment": {"comparable_basis": True},
            },
        )
        verified = analysis._base_features(
            **common,
            context_metadata={
                "corporate_actions": {
                    "status": "checked_no_actions", "affected_symbols": []
                },
                "price_adjustment": {"comparable_basis": True},
            },
        )
        self.assertAlmostEqual(unavailable["true_overnight_gap_raw"], 10 / 9 - 1)
        self.assertTrue(math.isnan(unavailable["true_overnight_gap"]))
        self.assertAlmostEqual(verified["true_overnight_gap"], 10 / 9 - 1)
        self.assertTrue(verified["true_gap_verified"])

    def test_after_hours_and_long_dormancy_features_are_calculated(self):
        row = analysis._base_features(
            "2026-07-27",
            "TEST",
            "premarket_observed",
            self.bars,
            "09:30",
            daily_history=self._daily_history(),
            after_hours=self._after_hours(),
            context_metadata={
                "corporate_actions": {"status": "unavailable_not_collected"},
                "price_adjustment": {"comparable_basis": True},
            },
        )
        self.assertEqual(2, row["after_hours_active_bars"])
        self.assertAlmostEqual(row["after_hours_return"], 9.5 / 9.1 - 1)
        self.assertAlmostEqual(row["decision_vs_after_hours_high"], 12.1 / 9.8 - 1)
        for window in (20, 60, 120):
            self.assertEqual(window, row[f"dormancy_sessions_available_{window}"])
            self.assertAlmostEqual(
                row[f"dormancy_median_daily_volume_{window}"], 1_000
            )
            self.assertAlmostEqual(
                row[f"pm_volume_to_median_daily_volume_{window}"], 0.3
            )

    def test_premarket_reacceleration_uses_only_premarket_windows(self):
        tz = "America/New_York"
        times = ["08:30", "08:59", "09:00", "09:29", "09:30"]
        bars = pd.DataFrame({
            "symbol": ["TEST"] * len(times),
            "timestamp_et": [pd.Timestamp(f"2026-07-27 {t}", tz=tz) for t in times],
            "open": [10.0, 10.1, 10.2, 11.0, 99.0],
            "high": [10.1, 10.2, 10.3, 11.2, 100.0],
            "low": [9.9, 10.0, 10.1, 10.9, 98.0],
            "close": [10.0, 10.1, 10.2, 11.1, 99.0],
            "volume": [100.0] * len(times),
            "trade_count": [10.0] * len(times),
            "vwap": [10.0, 10.1, 10.2, 11.0, 99.0],
        })
        row = analysis._base_features(
            "2026-07-27", "TEST", "premarket_observed", bars, "09:30"
        )
        expected_previous = 10.1 / 10.0 - 1
        expected_latest = 11.1 / 10.2 - 1
        self.assertAlmostEqual(row["pm_return_previous_30m"], expected_previous)
        self.assertAlmostEqual(row["pm_return_latest_30m"], expected_latest)
        self.assertAlmostEqual(
            row["premarket_reacceleration_30m"],
            expected_latest - expected_previous,
        )

    def test_completed_after_hours_window_distinguishes_no_trades_from_missing_data(self):
        completed = analysis._base_features(
            "2026-07-27",
            "TEST",
            "premarket_observed",
            self.bars,
            "09:30",
            after_hours=pd.DataFrame(),
            context_metadata={
                "after_hours": {"completed": True},
                "corporate_actions": {"status": "unavailable_not_collected"},
            },
        )
        absent = analysis._base_features(
            "2026-07-27", "TEST", "premarket_observed", self.bars, "09:30"
        )
        failed = analysis._base_features(
            "2026-07-27",
            "TEST",
            "premarket_observed",
            self.bars,
            "09:30",
            after_hours=pd.DataFrame(),
            context_metadata={
                "after_hours": {
                    "completed": True,
                    "failures": {"TEST": "Alpaca HTTP 400"},
                },
                "corporate_actions": {"status": "unavailable_not_collected"},
            },
        )
        self.assertEqual(0, completed["after_hours_active_bars"])
        self.assertEqual(0.0, completed["after_hours_volume"])
        self.assertTrue(math.isnan(absent["after_hours_active_bars"]))
        self.assertTrue(math.isnan(failed["after_hours_active_bars"]))

    def test_context_loader_rejects_mismatched_research_date(self):
        with tempfile.TemporaryDirectory() as directory:
            date_dir = Path(directory) / "2026-07-27"
            context = date_dir / "context"
            context.mkdir(parents=True)
            (context / "context-metadata.json").write_text(
                json.dumps({
                    "research_date": "2026-07-28",
                    "context_version": "prior-session-context-v1",
                }),
                encoding="utf-8",
            )
            empty = pd.DataFrame(columns=[
                "symbol", "session_date", "timestamp_et", "open", "high",
                "low", "close", "volume", "trade_count", "vwap",
            ])
            empty.to_csv(context / "daily-bars.csv.gz", index=False, compression="gzip")
            empty.to_csv(
                context / "after-hours-bars.csv.gz", index=False, compression="gzip"
            )
            with self.assertRaisesRegex(ValueError, "research_date mismatch"):
                analysis.load_context(date_dir)


if __name__ == "__main__":
    unittest.main()
