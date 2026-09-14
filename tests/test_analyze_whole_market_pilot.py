import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_whole_market_pilot.py"
SPEC = importlib.util.spec_from_file_location("analyze_whole_market_pilot", SCRIPT)
analysis = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(analysis)


class WholeMarketPilotAnalysisTests(unittest.TestCase):
    def test_completed_five_minute_bar_rule(self):
        frame = pd.DataFrame({
            "timestamp_et": pd.to_datetime([
                "2026-09-11T09:25:00-04:00",
                "2026-09-11T09:29:00-04:00",
            ], utc=True).tz_convert(analysis.EASTERN),
        })
        eligible = analysis._eligible_completed(
            frame, pd.Timestamp("2026-09-11 09:30", tz=analysis.EASTERN)
        )
        self.assertEqual(1, len(eligible))
        self.assertEqual(25, eligible.iloc[0].timestamp_et.minute)

    def test_channel_rank_ties_use_symbol_as_deterministic_tiebreaker(self):
        symbols = [f"S{number:02d}" for number in range(25)]
        frame = pd.DataFrame({
            "session_date": ["2026-09-11"] * 25,
            "symbol": symbols,
            "decision": ["open"] * 25,
            "decision_vs_previous_close_raw": [0.1] * 25,
            "pm_dollar_volume": [100.0] * 25,
            "pm_trade_count": [10.0] * 25,
            "pm_active_bars": [2.0] * 25,
            "pm_log_volume_surprise_vs_daily_20": [0.5] * 25,
            "dormancy_max_abs_close_return_20": [0.01] * 25,
            "dormancy_close_return_volatility_20": [0.01] * 25,
            "pm_return_latest_15m": [0.01] * 25,
            "pm_price_acceleration_15m": [0.0] * 25,
            "pm_range_position": [0.5] * 25,
            "pm_drawdown_from_high": [-0.01] * 25,
            "pm_last_vs_vwap": [0.0] * 25,
            "opening_return": [float("nan")] * 25,
            "opening_range_position": [float("nan")] * 25,
            "opening_drawdown_from_high": [float("nan")] * 25,
            "opening_dollar_volume": [0.0] * 25,
            "broad_collection_status": ["completed"] * 25,
        })
        _scored, channels = analysis.channel_scores(frame)
        activity = channels.loc[channels.channel == "absolute_activity"]
        self.assertEqual(list(range(1, 26)), activity.channel_rank.astype(int).tolist())
        self.assertEqual(symbols[:20], activity.loc[activity.channel_rank <= 20, "symbol"].tolist())

    def test_end_to_end_outputs_keep_future_outcomes_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe = {
                "research_date": "2026-09-11",
                "universe_snapshot_at_utc": "2026-09-10T12:00:00+00:00",
                "universe_rule_version": "test-universe",
                "universe_content_sha256": "b" * 64,
                "assets": [
                    {"symbol": "AAA", "exchange": "NASDAQ"},
                    {"symbol": "BBB", "exchange": "NYSE"},
                    {"symbol": "CCC", "exchange": "AMEX"},
                ],
            }
            (root / "universe.json").write_text(
                json.dumps(universe), encoding="utf-8"
            )
            metadata = {
                "pilot_version": analysis.PILOT_VERSION,
                "research_date": "2026-09-11",
                "previous_session_date": "2026-09-10",
                "universe_source": "unused.json",
                "universe_content_sha256": "b" * 64,
                "universe_rule_version": "test-universe",
                "request_interval_seconds": 0.5,
                "feed": "sip",
                "error": None,
                "daily_history": {
                    "completed": True, "successful_symbols": ["AAA", "BBB", "CCC"],
                    "failures": {}, "pages": 1, "page_requests": [{}],
                },
                "broad_five_minute": {
                    "completed": True, "successful_symbols": ["AAA", "BBB"],
                    "failures": {"CCC": "No bars returned for the requested window"},
                    "pages": 1, "page_requests": [{}],
                },
                "corporate_actions": {"status": "unavailable_not_collected"},
            }
            (root / "collection-metadata.json").write_text(
                json.dumps(metadata), encoding="utf-8"
            )

            daily_rows = []
            days = pd.bdate_range(end="2026-09-10", periods=20)
            for symbol, base in (("AAA", 1.0), ("BBB", 5.0), ("CCC", 10.0)):
                for index, day in enumerate(days):
                    price = base * (1 + index * 0.001)
                    daily_rows.append({
                        "group": "dynamic_discovery_universe", "symbol": symbol,
                        "timeframe": "1Day", "session_date": day.date().isoformat(),
                        "timestamp_utc": f"{day.date().isoformat()}T04:00:00Z",
                        "timestamp_et": f"{day.date().isoformat()}T00:00:00-04:00",
                        "open": price, "high": price * 1.01, "low": price * 0.99,
                        "close": price, "volume": 1000, "trade_count": 100,
                        "vwap": price,
                    })
            pd.DataFrame(daily_rows).to_csv(
                root / "daily-bars.csv.gz", index=False, compression="gzip"
            )

            broad_rows = []
            for symbol, base, multiplier in (("AAA", 1.02, 1.02), ("BBB", 5.10, 0.99)):
                times = [
                    "2026-09-10T16:00:00-04:00",
                    "2026-09-10T16:05:00-04:00",
                    "2026-09-11T09:00:00-04:00",
                    "2026-09-11T09:15:00-04:00",
                    "2026-09-11T09:25:00-04:00",
                    "2026-09-11T09:30:00-04:00",
                    "2026-09-11T09:35:00-04:00",
                    "2026-09-11T09:40:00-04:00",
                    "2026-09-11T09:45:00-04:00",
                    "2026-09-11T09:55:00-04:00",
                    "2026-09-11T10:00:00-04:00",
                    "2026-09-11T15:55:00-04:00",
                ]
                price = base
                for stamp in times:
                    close = price * multiplier
                    ts = pd.Timestamp(stamp)
                    broad_rows.append({
                        "group": "dynamic_discovery_universe", "symbol": symbol,
                        "timeframe": "5Min", "session_date": ts.date().isoformat(),
                        "timestamp_utc": ts.tz_convert("UTC").isoformat(),
                        "timestamp_et": ts.isoformat(), "open": price,
                        "high": max(price, close) * 1.01,
                        "low": min(price, close) * 0.99, "close": close,
                        "volume": 5000 if symbol == "AAA" else 100,
                        "trade_count": 100 if symbol == "AAA" else 5,
                        "vwap": (price + close) / 2,
                    })
                    price = close
            pd.DataFrame(broad_rows).to_csv(
                root / "broad-five-minute-bars.csv.gz", index=False, compression="gzip"
            )

            output = analysis.run(root)
            self.assertTrue((output / "run-manifest.json").exists())
            self.assertTrue((output / "pilot-evaluation.csv").exists())
            self.assertTrue((output / "retrospective-outcomes.csv.gz").exists())
            ranking = pd.read_csv(output / "rankings-open.csv.gz")
            self.assertFalse(set(analysis.FUTURE_COLUMNS) & set(ranking.columns))
            manifest = json.loads(
                (output / "run-manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["ranking_outcome_separation"])
            self.assertFalse(manifest["orders_supported"])
            channel_rows = pd.read_csv(output / "channel-rankings.csv.gz")
            raw_gap = channel_rows.loc[
                channel_rows.channel == "raw_positive_gap_descriptive"
            ]
            self.assertFalse(raw_gap.enabled_for_candidate_union.any())
            broad_features = pd.read_csv(output / "broad-features.csv.gz")
            no_trade = broad_features.loc[
                (broad_features.symbol == "CCC")
                & (broad_features.decision == "open")
            ].iloc[0]
            self.assertEqual("completed", no_trade.broad_collection_status)
            self.assertEqual(0, no_trade.pm_volume)


if __name__ == "__main__":
    unittest.main()
