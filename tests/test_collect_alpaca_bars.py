import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import timezone
from pathlib import Path


MODULE_PATH = (
    Path(__file__).parents[1] / "scripts" / "collect_alpaca_bars.py"
)
SPEC = importlib.util.spec_from_file_location("collector", MODULE_PATH)
collector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


class CollectorTests(unittest.TestCase):
    def test_window_uses_new_york_dst_and_exclusive_end(self):
        window = collector.parse_window("2026-07-24")

        self.assertEqual("2026-07-24T04:00:00-04:00", window.start_et.isoformat())
        self.assertEqual("2026-07-24T16:00:00-04:00", window.end_et.isoformat())
        self.assertEqual("2026-07-24T08:00:00+00:00", window.start_utc.isoformat())
        self.assertEqual("2026-07-24T20:00:00+00:00", window.end_utc.isoformat())

    def test_normalised_rows_are_sorted_and_labeled(self):
        rows = collector.normalise_bars(
            {
                "RNG": [
                    {
                        "t": "2026-07-24T13:31:00Z",
                        "o": 1,
                        "h": 2,
                        "l": 0.5,
                        "c": 1.5,
                        "v": 100,
                        "n": 3,
                        "vw": 1.2,
                    }
                ],
                "LVWR": [
                    {
                        "t": "2026-07-24T08:00:00Z",
                        "o": 10,
                        "h": 11,
                        "l": 9,
                        "c": 10.5,
                        "v": 200,
                        "n": 4,
                        "vw": 10.2,
                    }
                ],
            }
        )

        self.assertEqual(["LVWR", "RNG"], [row["symbol"] for row in rows])
        self.assertEqual("premarket_candidate", rows[0]["group"])
        self.assertEqual("missed_runner_control", rows[1]["group"])
        self.assertEqual(
            "2026-07-24T04:00:00-04:00", rows[0]["timestamp_et"]
        )
        self.assertEqual(timezone.utc, collector.UTC)

    def test_universes_are_disjoint_and_complete(self):
        requested = list(collector.GROUP_BY_SYMBOL)

        self.assertEqual(44, len(requested))
        self.assertEqual(44, len(set(requested)))
        self.assertFalse(
            set(collector.PREMARKET_CANDIDATES)
            & set(collector.MISSED_RUNNERS_CONTROLS)
        )

    def test_loads_date_specific_universe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "universe.json"
            path.write_text(
                json.dumps(
                    {
                        "research_date": "2026-07-27",
                        "symbol_groups": {
                            "premarket_observed": ["lvwr", "SAFT"],
                            "post_open_only_observed": ["GOSS"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            labels, groups, source = collector.load_universe(
                "2026-07-27", path
            )

        self.assertEqual(
            {
                "LVWR": "premarket_observed",
                "SAFT": "premarket_observed",
                "GOSS": "post_open_only_observed",
            },
            labels,
        )
        self.assertEqual(["LVWR", "SAFT"], groups["premarket_observed"])
        self.assertEqual(str(path), source)

    def test_rejects_duplicate_symbol_across_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "universe.json"
            path.write_text(
                json.dumps(
                    {
                        "research_date": "2026-07-27",
                        "symbol_groups": {"a": ["LVWR"], "b": ["lvwr"]},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                collector.load_universe("2026-07-27", path)


if __name__ == "__main__":
    unittest.main()
