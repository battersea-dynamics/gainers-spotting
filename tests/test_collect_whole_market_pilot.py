import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "collect_whole_market_pilot.py"
SCRIPTS_DIR = str(SCRIPT.parent)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
SPEC = importlib.util.spec_from_file_location("collect_whole_market_pilot", SCRIPT)
pilot = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(pilot)


class WholeMarketPilotCollectorTests(unittest.TestCase):
    def test_collects_daily_then_previous_after_hours_through_session_close(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe = root / "universe.json"
            universe.write_text(json.dumps({
                "research_date": "2026-09-11",
                "universe_snapshot_at_utc": "2026-09-10T12:00:00+00:00",
                "universe_rule_version": "test",
                "universe_content_sha256": "a" * 64,
                "historical_reproducibility": "test snapshot",
                "symbol_groups": {"dynamic_discovery_universe": ["AAA", "BBB"]},
            }), encoding="utf-8")
            calls = []

            def fake_collect_dataset(**kwargs):
                calls.append(kwargs)
                if kwargs["dataset"] == "daily":
                    rows = [{
                        "group": "dynamic_discovery_universe",
                        "symbol": symbol,
                        "timeframe": "1Day",
                        "session_date": "2026-09-10",
                        "timestamp_utc": "2026-09-10T04:00:00Z",
                        "timestamp_et": "2026-09-10T00:00:00-04:00",
                        "open": 1, "high": 1, "low": 1, "close": 1,
                        "volume": 100, "trade_count": 10, "vwap": 1,
                    } for symbol in ("AAA", "BBB")]
                else:
                    rows = [{
                        "group": "dynamic_discovery_universe",
                        "symbol": "AAA",
                        "timeframe": "5Min",
                        "session_date": "2026-09-11",
                        "timestamp_utc": "2026-09-11T13:25:00Z",
                        "timestamp_et": "2026-09-11T09:25:00-04:00",
                        "open": 1, "high": 1.1, "low": 1, "close": 1.1,
                        "volume": 100, "trade_count": 10, "vwap": 1.05,
                    }]
                return rows, {
                    "completed": True,
                    "total_bars": len(rows),
                    "pages": 1,
                    "page_requests": [{}],
                    "successful_symbols": sorted({row["symbol"] for row in rows}),
                    "failures": {},
                }

            with mock.patch.object(pilot, "get_credentials", return_value=("key", "secret")), mock.patch.object(
                pilot, "_collect_dataset", side_effect=fake_collect_dataset
            ):
                output, metadata = pilot.collect_pilot(
                    requested_date="2026-09-11",
                    universe_file=universe,
                    output_root=root / "output",
                    request_interval_seconds=0,
                )

            self.assertIsNone(metadata["error"])
            self.assertEqual("2026-09-10", metadata["previous_session_date"])
            self.assertEqual("1Day", calls[0]["timeframe"])
            self.assertEqual("5Min", calls[1]["timeframe"])
            self.assertEqual("2026-09-10T16:00:00-04:00", calls[1]["start_et"].isoformat())
            self.assertEqual("2026-09-11T16:00:00-04:00", calls[1]["end_et"].isoformat())
            self.assertTrue((output / "universe.json").exists())
            self.assertTrue((output / "daily-bars.csv.gz").exists())
            self.assertTrue((output / "broad-five-minute-bars.csv.gz").exists())


if __name__ == "__main__":
    unittest.main()
