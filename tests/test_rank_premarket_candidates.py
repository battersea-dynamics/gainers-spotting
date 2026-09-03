import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[1] / "scripts" / "rank_premarket_candidates.py"
SPEC = importlib.util.spec_from_file_location("rank_premarket_candidates", SCRIPT)
ranker = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ranker)


def bars_for(symbol, pm_prices, regular_prices):
    rows = []
    for timestamp, price, volume in pm_prices + regular_prices:
        rows.append({
            "symbol": symbol,
            "timestamp_utc": timestamp,
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": volume,
            "vwap": price,
        })
    return rows


class PremarketRankerTests(unittest.TestCase):
    def setUp(self):
        self.rows = bars_for("CHEAP", [
            ("2026-07-27T12:30:00Z", 0.50, 1000),
            ("2026-07-27T13:00:00Z", 0.60, 5000),
            ("2026-07-27T13:29:00Z", 0.70, 10000),
        ], [
            ("2026-07-27T13:30:00Z", 0.71, 20000),
            ("2026-07-27T13:44:00Z", 0.80, 15000),
            ("2026-07-27T13:45:00Z", 0.81, 10000),
            ("2026-07-27T13:59:00Z", 0.90, 10000),
            ("2026-07-27T19:59:00Z", 1.00, 1000),
        ]) + bars_for("STEADY", [
            ("2026-07-27T12:30:00Z", 10.0, 1000),
            ("2026-07-27T13:00:00Z", 10.1, 1000),
            ("2026-07-27T13:29:00Z", 10.2, 1000),
        ], [
            ("2026-07-27T13:30:00Z", 10.2, 1000),
            ("2026-07-27T13:44:00Z", 10.1, 1000),
            ("2026-07-27T13:45:00Z", 10.0, 1000),
            ("2026-07-27T13:59:00Z", 9.9, 1000),
            ("2026-07-27T19:59:00Z", 9.8, 1000),
        ])

    def test_cheap_symbols_are_not_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            pd.DataFrame(self.rows).to_csv(path, index=False)
            bars = ranker.load_bars(path, "2026-07-27")
            result, _ = ranker.rank_decision(bars, "2026-07-27", "open")
            self.assertIn("CHEAP", set(result.symbol))

    def test_open_score_does_not_use_regular_session_bars(self):
        frame = pd.DataFrame(self.rows)
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.csv"
            second = Path(directory) / "second.csv"
            frame.to_csv(first, index=False)
            changed = frame.copy()
            mask = (changed.symbol == "CHEAP") & (changed.timestamp_utc >= "2026-07-27T13:30:00Z")
            changed.loc[mask, ["open", "high", "low", "close"]] = 99.0
            changed.to_csv(second, index=False)
            result_a, _ = ranker.rank_decision(ranker.load_bars(first, "2026-07-27"), "2026-07-27", "open")
            result_b, _ = ranker.rank_decision(ranker.load_bars(second, "2026-07-27"), "2026-07-27", "open")
            score_a = result_a.set_index("symbol").loc["CHEAP", "research_score"]
            score_b = result_b.set_index("symbol").loc["CHEAP", "research_score"]
            self.assertEqual(score_a, score_b)
            self.assertNotEqual(
                result_a.set_index("symbol").loc["CHEAP", "return_to_close_pct"],
                result_b.set_index("symbol").loc["CHEAP", "return_to_close_pct"],
            )

    def test_plus_15_uses_only_completed_first_15_minutes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            pd.DataFrame(self.rows).to_csv(path, index=False)
            result, fields = ranker.rank_decision(
                ranker.load_bars(path, "2026-07-27"), "2026-07-27", "open+15"
            )
            cheap = result.set_index("symbol").loc["CHEAP"]
            self.assertAlmostEqual(cheap.opening_return_pct, 100 * (0.80 / 0.71 - 1))
            self.assertIn("opening_return_pct", fields)

    def test_discovers_gzip_bar_file(self):
        with tempfile.TemporaryDirectory() as directory:
            date_dir = Path(directory) / "2026-07-27"
            date_dir.mkdir()
            path = date_dir / "bars.csv.gz"
            pd.DataFrame(self.rows).to_csv(path, index=False, compression="gzip")
            self.assertEqual(path, ranker.discover_input(Path(directory), "2026-07-27"))

    def test_written_rankings_do_not_contain_future_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "bars.csv.gz"
            pd.DataFrame(self.rows).to_csv(input_path, index=False, compression="gzip")
            written = ranker.run("2026-07-27", input_path, root, ["open"])
            ranking_path = next(path for path in written if path.name == "rankings_open.csv")
            outcome_path = next(path for path in written if path.name == "outcomes_open.csv")
            ranking = pd.read_csv(ranking_path)
            outcomes = pd.read_csv(outcome_path)
            self.assertNotIn("mfe_to_close_pct", ranking.columns)
            self.assertIn("mfe_to_close_pct", outcomes.columns)
            self.assertIn("score_version", ranking.columns)

    def test_post_open_only_symbols_are_not_ranked(self):
        frame = pd.DataFrame(self.rows)
        frame["group"] = frame["symbol"].map({
            "CHEAP": "premarket_observed",
            "STEADY": "post_open_only_observed",
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            frame.to_csv(path, index=False)
            result, _ = ranker.rank_decision(
                ranker.load_bars(path, "2026-07-27"), "2026-07-27", "open"
            )
            self.assertEqual(["CHEAP"], list(result.symbol))


if __name__ == "__main__":
    unittest.main()
