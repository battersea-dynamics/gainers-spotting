import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_alpaca_universe.py"
SPEC = importlib.util.spec_from_file_location("build_alpaca_universe", SCRIPT)
universe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(universe)


class UniverseTests(unittest.TestCase):
    def test_paper_account_endpoint_is_the_safe_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                "https://paper-api.alpaca.markets/v2/assets",
                universe.resolve_assets_url(),
            )

    def test_rejects_non_alpaca_account_endpoint(self):
        with self.assertRaises(universe.UniverseError):
            universe.resolve_assets_url("https://example.com")

    def test_broad_universe_has_no_price_or_volume_floor(self):
        assets = [
            {"symbol": "CHEAP", "asset_class": "us_equity", "status": "active", "tradable": True, "exchange": "NASDAQ", "name": "Cheap Co"},
            {"symbol": "OTC", "asset_class": "us_equity", "status": "active", "tradable": True, "exchange": "OTC", "name": "OTC Co"},
            {"symbol": "HALT", "asset_class": "us_equity", "status": "inactive", "tradable": False, "exchange": "NYSE", "name": "Halted Co"},
        ]
        accepted, rejected = universe.eligible_assets(assets)
        self.assertEqual(["CHEAP"], [row["symbol"] for row in accepted])
        self.assertEqual(1, rejected["unsupported_exchange"])
        self.assertEqual(1, rejected["not_active"])

    def test_payload_is_compatible_with_historical_collector(self):
        payload = universe.build_payload("2026-09-03", [{"symbol": "ABC"}], {})
        self.assertEqual(["ABC"], payload["symbol_groups"]["dynamic_discovery_universe"])
        self.assertIsNone(payload["eligibility"]["minimum_price"])
        self.assertFalse(payload["orders_supported"])
        self.assertEqual(64, len(payload["universe_content_sha256"]))

    def test_universe_hash_is_independent_of_snapshot_time(self):
        assets = [{"symbol": "ABC"}, {"symbol": "XYZ"}]
        first = universe.build_payload("2026-09-03", assets, {})
        second = universe.build_payload("2026-09-03", assets, {})
        self.assertEqual(
            first["universe_content_sha256"],
            second["universe_content_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
