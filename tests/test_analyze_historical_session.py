import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = (
    Path(__file__).parents[1] / "scripts" / "analyze_historical_session.py"
)
SPEC = importlib.util.spec_from_file_location("session_analysis", MODULE_PATH)
analysis = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = analysis
SPEC.loader.exec_module(analysis)


class HistoricalAnalysisTests(unittest.TestCase):
    def test_safe_return_percentage(self):
        self.assertAlmostEqual(10.0, analysis.safe_return_pct(100, 110))
        self.assertTrue(np.isnan(analysis.safe_return_pct(0, 110)))

    def test_cliffs_delta_direction(self):
        self.assertEqual(
            1.0,
            analysis.cliffs_delta(
                np.array([3.0, 4.0]), np.array([1.0, 2.0])
            ),
        )
        self.assertEqual(
            -1.0,
            analysis.cliffs_delta(
                np.array([1.0, 2.0]), np.array([3.0, 4.0])
            ),
        )

    def test_benjamini_hochberg_is_bounded(self):
        adjusted = analysis.benjamini_hochberg([0.01, 0.04, 0.2])
        self.assertTrue(np.all(adjusted >= 0))
        self.assertTrue(np.all(adjusted <= 1))
        self.assertAlmostEqual(0.03, adjusted[0])

    def test_json_safe_replaces_non_finite_values(self):
        cleaned = analysis.json_safe(
            {"values": [1.0, np.nan, np.inf, np.int64(2)]}
        )
        self.assertEqual({"values": [1.0, None, None, 2]}, cleaned)


if __name__ == "__main__":
    unittest.main()
