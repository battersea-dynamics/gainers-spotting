import importlib.util
import math
import re
import sys
import tempfile
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("shadow_live", SCRIPTS / "shadow_live.py")
sl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(sl)

DAY = "2026-10-23"


def bars_for(symbol, start="04:00", end="11:00", price=10.0, step=0.01, volume=1000):
    rows, t, p = [], sl.et(DAY, start), price
    while t < sl.et(DAY, end):
        rows.append({"symbol": symbol, "session_date": DAY, "timestamp_et": t, "open": p, "high": p * 1.01,
                     "low": p * 0.99, "close": p * (1 + step), "volume": volume, "trade_count": 10, "vwap": p})
        p *= 1 + step
        t += timedelta(minutes=5)
    return rows


def context_row(symbol, prev_close=9.0, dv=5_000_000):
    return {"symbol": symbol, "previous_session": "2026-10-22", "previous_close_raw": prev_close,
            "previous_daily_volume": 1e6, "dormancy_sessions_available_20": 20,
            "dormancy_median_daily_volume_20": 5e5, "dormancy_median_daily_dollar_volume_20": dv,
            "dormancy_median_daily_range_20": 0.03, "dormancy_close_return_volatility_20": 0.02,
            "dormancy_max_abs_close_return_20": 0.05}


def classes(symbols):
    return pd.DataFrame([{"symbol": s, "instrument_type": "common_stock", "primary_stock_eligible": True,
                          "possible_spac_common": False, "classification_reason": "x", "master_match_status": "exact"}
                         for s in symbols])


class CalendarTests(unittest.TestCase):
    def test_trading_days(self):
        self.assertTrue(sl.is_trading_day("2026-10-23"))
        self.assertFalse(sl.is_trading_day("2026-10-24"))
        self.assertFalse(sl.is_trading_day("2026-11-26"))
        self.assertEqual(sl.close_time("2026-11-27"), "13:00")
        self.assertEqual(sl.previous_trading_day("2026-11-27"), "2026-11-25")
        self.assertEqual(sl.previous_trading_day("2026-11-02"), "2026-10-30")
        with self.assertRaises(ValueError):
            sl.is_trading_day("2028-01-03")

    def test_et_dst(self):
        self.assertEqual(sl.et("2026-10-30", "09:30").astimezone(timezone.utc).hour, 13)
        self.assertEqual(sl.et("2026-11-02", "09:30").astimezone(timezone.utc).hour, 14)

    def test_cutoffs_match_trigger_slot_table(self):
        schedule = Path("/workspace/gainers-shadow-trigger/src/schedule.ts")
        expected = {"snapshot": set(sl.SNAPSHOT_DECISIONS), "rank": set(sl.RANK_DECISIONS)}
        if schedule.exists():
            found = {"snapshot": set(), "rank": set()}
            for job, cutoff in re.findall(r'job: "(snapshot|rank)", cutoff: "([0-9:]+)"', schedule.read_text()):
                found[job].add(cutoff)
            self.assertEqual(found, expected)
        with self.assertRaises(ValueError):
            sl.decision_for("rank", "09:31")


class SafetyTests(unittest.TestCase):
    def test_guard_blocks_trading_endpoints(self):
        for url in ("https://paper-api.alpaca.markets/v2/orders", "https://paper-api.alpaca.markets/v2/account",
                    "https://paper-api.alpaca.markets/v2/positions", "https://api.alpaca.markets/v2/orders?x=1"):
            with self.assertRaises(sl.BlockedUrl):
                sl.guarded_urlopen(urllib.request.Request(url))
        with self.assertRaises(sl.BlockedUrl):
            sl.guarded_urlopen(urllib.request.Request("https://data.alpaca.markets/v2/stocks/bars?x", data=b"{}", method="POST"))

    def test_collectors_are_patched(self):
        for module in (sl.cab, sl.bau, sl.bssm):
            self.assertIs(module.urlopen, sl.guarded_urlopen)

    def test_no_trading_endpoint_strings(self):
        for name in ("shadow_live.py", "shadow_run.py"):
            text = (SCRIPTS / name).read_text()
            self.assertNotRegex(text, r"/v2/(orders|positions|account)")


class StoreTests(unittest.TestCase):
    def test_append_only_and_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = sl.Store(Path(tmp), DAY, "r1")
            self.assertIsNotNone(store.write_json("a/x.json", {"v": 1}))
            self.assertIsNone(store.write_json("a/x.json", {"v": 2}))
            rerun = store.write_json("a/x.json", {"v": 3}, force=True)
            self.assertEqual(rerun.name, "x.rerun-r1.json")
            self.assertEqual(store.read_json("a/x.json"), {"v": 1})


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.symbols = [f"S{i:02d}" for i in range(30)]
        rows = []
        for i, s in enumerate(self.symbols):
            rows += bars_for(s, step=0.001 * (i - 10), volume=1000 * (i + 1))
        self.bars = sl._bars_frame([{**r, "timestamp_et": r["timestamp_et"].isoformat()} for r in rows])
        self.context = pd.DataFrame([context_row(s, dv=(s != "S00") * 5e6) for s in self.symbols])
        self.classes = classes(self.symbols)

    def test_no_lookahead(self):
        decision = sl.decision_for("rank", "09:30")
        base = sl.compute_features(DAY, decision, self.bars, self.context, self.classes, self.symbols, set())
        poisoned = self.bars.copy()
        late = poisoned.timestamp_et >= sl.et(DAY, "09:25") + pd.Timedelta(minutes=5)
        poisoned.loc[late, ["open", "high", "low", "close"]] *= 50
        poisoned.loc[late, "volume"] *= 1000
        again = sl.compute_features(DAY, decision, poisoned, self.context, self.classes, self.symbols, set())
        cols = ["activation_score", "momentum_quality_score", "decision_price", "pm_volume"]
        pd.testing.assert_frame_equal(base[cols], again[cols])

    def test_snapshot_uses_only_bars_before_cutoff(self):
        decision = sl.decision_for("snapshot", "07:00")
        stock = sl.compute_features(DAY, decision, self.bars, self.context, self.classes, self.symbols, set())
        self.assertTrue((stock.pm_bar_count == 36).all())  # 04:00-06:55 = 36 five-minute bars

    def test_lists_and_controls(self):
        decision = sl.decision_for("rank", "10:00")
        stock = sl.compute_features(DAY, decision, self.bars, self.context, self.classes, self.symbols, set())
        cfg = {**sl.DEFAULTS, "top_n": 5, "random_n": 4}
        lists, meta = sl.build_lists(DAY, decision, stock, cfg)
        lists2, meta2 = sl.build_lists(DAY, decision, stock, cfg)
        pd.testing.assert_frame_equal(lists, lists2)
        self.assertEqual(meta["random_seed"], meta2["random_seed"])
        types = set(lists.list_type)
        self.assertIn("engine:v2_opening_confirmation", types)
        self.assertTrue({"control:gap_top", "control:rel_vol_top", "control:random_liquid"} <= types)
        gap = lists.loc[lists.list_type == "control:gap_top"]
        self.assertEqual(gap.iloc[0].symbol, "S29")  # largest step -> largest gap
        rnd = lists.loc[lists.list_type == "control:random_liquid", "symbol"]
        self.assertEqual(len(rnd), 4)
        self.assertNotIn("S00", set(rnd))  # illiquid by dv20
        self.assertEqual(meta["random_liquid_pool"], 29)
        self.assertNotEqual(sl.seed_for(DAY, "open"), sl.seed_for(DAY, "open+15"))


class OutcomeTests(unittest.TestCase):
    def test_first_touch_conservative(self):
        future = pd.DataFrame({"high": [10.2, 11.0], "low": [9.9, 9.0]})
        self.assertEqual(sl._first_touch(future, 10.0, 0.05, 0.05), 0.0)
        self.assertEqual(sl._first_touch(pd.DataFrame({"high": [10.6], "low": [9.9]}), 10.0, 0.05, 0.05), 1.0)
        self.assertEqual(sl._first_touch(pd.DataFrame({"high": [10.1], "low": [9.9]}), 10.0, 0.05, 0.05), 0.0)

    def test_outcomes_early_close(self):
        day = "2026-11-27"
        rows = [{**r, "session_date": day, "timestamp_et": (r["timestamp_et"] + timedelta(days=35)).isoformat()}
                for r in bars_for("AAA", start="09:30", end="16:00")]
        regular = sl._bars_frame(rows)
        decision = sl.decision_for("rank", "09:30")
        out = sl.compute_outcomes(day, [decision], ["AAA"], regular, pd.DataFrame([context_row("AAA")]))
        self.assertTrue(out.iloc[0].close_et.startswith("2026-11-27T13:00"))
        last_close = regular.loc[regular.timestamp_et < sl.et(day, "13:00")].iloc[-1].close
        self.assertAlmostEqual(out.iloc[0].ret_close, last_close / out.iloc[0].entry_price - 1)


class OrchestrationTests(unittest.TestCase):
    def test_non_trading_day_skips_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = sl.RunContext("rank", "2026-11-26", "09:30", Path(tmp))
            log = sl.run(ctx)
            self.assertEqual(log["status"], "skipped")
            self.assertEqual(len(list((Path(tmp) / "shadow" / "2026-11-26" / "runs").glob("*.json"))), 1)

    def test_wait_until(self):
        slept = []
        with tempfile.TemporaryDirectory() as tmp:
            ctx = sl.RunContext("rank", DAY, "09:30", Path(tmp), sleeper=slept.append)
            ctx.wait_until(datetime.now(timezone.utc) + timedelta(seconds=60))
            self.assertTrue(slept and 60 <= slept[0] <= 66)
            with self.assertRaises(RuntimeError):
                ctx.wait_until(datetime.now(timezone.utc) + timedelta(minutes=40))
            ctx.no_wait = True
            with self.assertRaises(RuntimeError):
                ctx.wait_until(datetime.now(timezone.utc) + timedelta(seconds=30))


if __name__ == "__main__":
    unittest.main()
