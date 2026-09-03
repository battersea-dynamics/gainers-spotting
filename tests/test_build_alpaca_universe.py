import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_alpaca_universe.py"
SPEC = importlib.util.spec_from_file_location("build_alpaca_universe", SCRIPT)
universe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(universe)


class UniverseTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
