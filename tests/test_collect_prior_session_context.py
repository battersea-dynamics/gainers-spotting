import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "collect_prior_session_context.py"
SPEC = importlib.util.spec_from_file_location("context_collector", MODULE_PATH)
context_collector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = context_collector
SPEC.loader.exec_module(context_collector)


class PriorSessionContextCollectorTests(unittest.TestCase):
    def test_previous_session_is_derived_from_returned_daily_sessions(self):
        rows = [
            {"session_date": "2026-07-23"},
            {"session_date": "2026-07-24"},
            {"session_date": "2026-07-24"},
        ]
        self.assertEqual(
            "2026-07-24",
            context_collector.previous_session_from_daily(rows, "2026-07-27"),
        )

    def test_context_collection_marks_unverified_corporate_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe = root / "universe.json"
            universe.write_text(
                json.dumps({
                    "research_date": "2026-07-27",
                    "symbol_groups": {"premarket_observed": ["TEST"]},
                }),
                encoding="utf-8",
            )

            def fake_dataset(**kwargs):
                if kwargs["timeframe"] == "1Day":
                    return ([{
                        "group": "premarket_observed",
                        "symbol": "TEST",
                        "timeframe": "1Day",
                        "session_date": "2026-07-24",
                        "timestamp_utc": "2026-07-24T04:00:00Z",
                        "timestamp_et": "2026-07-24T00:00:00-04:00",
                        "open": 9.0,
                        "high": 10.5,
                        "low": 8.9,
                        "close": 10.0,
                        "volume": 1_000,
                        "trade_count": 20,
                        "vwap": 9.8,
                    }], {"completed": True, "total_bars": 1})
                return ([], {"completed": True, "total_bars": 0})

            with mock.patch.object(
                context_collector, "get_credentials", return_value=("key", "secret")
            ), mock.patch.object(
                context_collector, "_collect_dataset", side_effect=fake_dataset
            ):
                output, metadata = context_collector.collect_context(
                    requested_date="2026-07-27",
                    universe_file=universe,
                    output_root=root / "research",
                )

            saved = json.loads(
                (output / "context-metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual("2026-07-24", metadata["previous_session_date"])
            self.assertEqual(
                "unavailable_not_collected",
                saved["corporate_actions"]["status"],
            )
            self.assertTrue(saved["price_adjustment"]["comparable_basis"])
            self.assertIn("true-gap", saved["price_adjustment"]["warning"])
            self.assertTrue((output / "daily-bars.csv.gz").exists())
            self.assertTrue((output / "after-hours-bars.csv.gz").exists())

    def test_normalised_daily_rows_retain_raw_values_and_session(self):
        rows = context_collector._normalise(
            {"TEST": [{
                "t": "2026-07-24T04:00:00Z",
                "o": 9.0,
                "h": 10.5,
                "l": 8.9,
                "c": 10.0,
                "v": 1_000,
                "n": 20,
                "vw": 9.8,
            }]},
            {"TEST": "premarket_observed"},
            "1Day",
        )
        self.assertEqual("2026-07-24", rows[0]["session_date"])
        self.assertEqual("1Day", rows[0]["timeframe"])
        self.assertEqual(10.0, rows[0]["close"])

    def test_dataset_request_freezes_raw_adjustment_and_requested_window(self):
        calls = []

        def fake_request(params, *_args):
            calls.append(dict(params))
            return ({
                "bars": {"TEST": [{
                    "t": "2026-07-24T04:00:00Z",
                    "o": 9.0,
                    "h": 10.5,
                    "l": 8.9,
                    "c": 10.0,
                    "v": 1_000,
                    "n": 20,
                    "vw": 9.8,
                }]},
                "next_page_token": None,
            }, 200, {}, 1)

        eastern = ZoneInfo("America/New_York")
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            context_collector,
            "request_page_with_retry",
            side_effect=fake_request,
        ):
            rows, summary = context_collector._collect_dataset(
                dataset="daily",
                symbols=["TEST"],
                group_by_symbol={"TEST": "premarket_observed"},
                start_et=datetime(2026, 1, 1, tzinfo=eastern),
                end_et=datetime(2026, 7, 27, tzinfo=eastern),
                timeframe="1Day",
                raw_dir=Path(directory),
                key="key",
                secret="secret",
                batch_size=200,
                limit=10_000,
                timeout=1,
                max_attempts=1,
            )

        self.assertEqual("raw", calls[0]["adjustment"])
        self.assertEqual("sip", calls[0]["feed"])
        self.assertEqual("1Day", calls[0]["timeframe"])
        self.assertEqual("2026-01-01T05:00:00Z", calls[0]["start"])
        self.assertEqual("2026-07-27T04:00:00Z", calls[0]["end"])
        self.assertTrue(summary["completed"])
        self.assertEqual(1, len(rows))


if __name__ == "__main__":
    unittest.main()
