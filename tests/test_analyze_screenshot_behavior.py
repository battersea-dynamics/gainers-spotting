import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


MODULE_PATH = (
    Path(__file__).parents[1] / "scripts" / "analyze_screenshot_behavior.py"
)
SPEC = importlib.util.spec_from_file_location("screenshot_behavior", MODULE_PATH)
analysis = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = analysis
SPEC.loader.exec_module(analysis)


class ScreenshotBehaviorTests(unittest.TestCase):
    def test_actual_uk_time_is_converted_before_phase_assignment(self):
        self.assertEqual(
            "same_session_premarket",
            analysis.classify_checkpoint("2026-08-04", "09:15"),
        )
        self.assertEqual(
            "previous_session_afterhours",
            analysis.classify_checkpoint("2026-08-04", "00:39"),
        )
        self.assertEqual(
            "same_session_afterhours",
            analysis.classify_checkpoint("2026-08-04", "23:00"),
        )

    def test_only_same_session_premarket_labels_are_aggregated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "research_date": "2026-08-04",
                "screenshots_are_scanner_inputs": False,
                "checkpoints": [
                    {
                        "checkpoint_id": "prior",
                        "actual_uk_time_start": "00:39",
                        "market_phase": "premarket",
                        "symbols": [
                            {
                                "ticker": "OLD",
                                "resolved_percentage_points": 5.0,
                            }
                        ],
                    },
                    {
                        "checkpoint_id": "early",
                        "actual_uk_time_start": "09:15",
                        "market_phase": "premarket",
                        "symbols": [
                            {
                                "ticker": "GOOD",
                                "resolved_percentage_points": 12.0,
                            }
                        ],
                    },
                    {
                        "checkpoint_id": "late",
                        "actual_uk_time_start": "14:00",
                        "market_phase": "premarket",
                        "symbols": [
                            {
                                "ticker": "GOOD",
                                "resolved_percentage_points": 18.0,
                            }
                        ],
                    },
                ],
            }
            (root / "2026-08-04.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            labels = analysis.load_checkpoint_labels(root, ["2026-08-04"])
            aggregated = analysis.aggregate_premarket_labels(labels)

        self.assertEqual(["GOOD"], aggregated.ticker.tolist())
        row = aggregated.iloc[0]
        self.assertEqual(2, row.premarket_checkpoint_appearances)
        self.assertEqual(1.0, row.persistence_share)
        self.assertEqual(12.0, row.first_valid_displayed_percentage_points)
        self.assertEqual(18.0, row.last_valid_displayed_percentage_points)

    def test_join_keeps_bar_observable_premarket_cohort_only(self):
        labels = pd.DataFrame(
            [
                {"date": "2026-08-04", "ticker": "GOOD"},
                {"date": "2026-08-04", "ticker": "LATE"},
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "features.csv"
            pd.DataFrame(
                [
                    {
                        "date": "2026-08-04",
                        "symbol": "GOOD",
                        "decision_et": "09:30",
                        "group": "premarket_observed",
                        "pm_observable": True,
                    },
                    {
                        "date": "2026-08-04",
                        "symbol": "LATE",
                        "decision_et": "09:30",
                        "group": "post_open_only_observed",
                        "pm_observable": True,
                    },
                ]
            ).to_csv(path, index=False)
            joined = analysis.join_bar_outcomes(labels, path)

        self.assertEqual(["GOOD"], joined.symbol.tolist())


if __name__ == "__main__":
    unittest.main()
