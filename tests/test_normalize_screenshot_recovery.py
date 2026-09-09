import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "normalize_screenshot_recovery.py"
SPEC = importlib.util.spec_from_file_location("normalize_screenshot_recovery", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def image_row(screenshot_id, day, clock, phase="premarket", count=1):
    return {
        "screenshot_id": screenshot_id,
        "source_filename": f"{screenshot_id}.png",
        "trading_date": day,
        "actual_uk_screenshot_time": clock,
        "intended_checkpoint_time": "",
        "market_phase": phase,
        "display_title": "Top Movers",
        "visible_rows_extracted": str(count),
        "json_file": f"observations/{screenshot_id}.json",
        "access_status": "accessible",
        "notes": "",
    }


def observation(row, items):
    return {
        "schema_version": "revolut-screenshot-observation-v1",
        "screenshot_id": row["screenshot_id"],
        "source_filename": row["source_filename"],
        "trading_date": row["trading_date"],
        "actual_uk_screenshot_time": row["actual_uk_screenshot_time"],
        "market_phase": row["market_phase"],
        "observations": items,
    }


def item(position, ticker, price=None, percentage=None, name=None):
    return {
        "visible_position": position,
        "ticker": ticker,
        "company_name": name,
        "displayed_price": price,
        "displayed_percentage_change": percentage,
        "ocr_confidence": {},
    }


class ScreenshotRecoveryTests(unittest.TestCase):
    def test_bundle_fingerprint_is_stable_across_input_order(self):
        first = image_row("a", "2026-08-03", "09:11")
        second = image_row("b", "2026-08-03", "09:12")
        observations = {
            first["json_file"]: observation(first, [item(1, "ABCD", "$2.00")]),
            second["json_file"]: observation(second, [item(1, "EFGH", "$3.00")]),
        }
        forward = MODULE.RecoveryBundle([first, second], [], observations)
        reverse = MODULE.RecoveryBundle(
            [second, first], [], dict(reversed(list(observations.items())))
        )
        self.assertEqual(
            MODULE.bundle_fingerprint(forward), MODULE.bundle_fingerprint(reverse)
        )

    def test_groups_adjacent_same_phase_images_only(self):
        rows = [
            image_row("a", "2026-08-03", "09:11"),
            image_row("b", "2026-08-03", "09:12"),
            image_row("c", "2026-08-03", "09:15"),
            image_row("d", "2026-08-03", "09:15", "post_open"),
        ]
        groups = MODULE.group_inventory(rows, tolerance_minutes=2)
        self.assertEqual([[r["screenshot_id"] for r in group] for group in groups], [["a", "b"], ["c"], ["d"]])

    def test_merges_unique_adjacent_values_without_inventing_rank(self):
        first = image_row("a", "2026-08-03", "09:11")
        second = image_row("b", "2026-08-03", "09:12")
        observations = {
            first["json_file"]: observation(first, [item(8, "ABCD", "$2.00", None, "Example")]),
            second["json_file"]: observation(second, [item(1, "ABCD", None, "20.0%", "Example")]),
        }
        checkpoint = MODULE.build_checkpoint([first, second], observations)
        merged = checkpoint["symbols"][0]
        self.assertEqual(merged["resolved_price"]["value"], 2.0)
        self.assertEqual(merged["resolved_percentage_points"], 20.0)
        self.assertEqual(len(merged["appearances"]), 2)
        self.assertNotIn("displayed_rank", merged)
        self.assertIn("Not inferred", checkpoint["global_rank_policy"])

    def test_preserves_conflicting_values(self):
        first = image_row("a", "2026-08-03", "09:11")
        second = image_row("b", "2026-08-03", "09:12")
        observations = {
            first["json_file"]: observation(first, [item(1, "ABCD", "$2.00")]),
            second["json_file"]: observation(second, [item(1, "ABCD", "$2.10")]),
        }
        checkpoint = MODULE.build_checkpoint([first, second], observations)
        merged = checkpoint["symbols"][0]
        self.assertIsNone(merged["resolved_price"])
        self.assertEqual(merged["field_status"]["price"], "conflict_preserved")
        self.assertEqual(len(merged["appearances"]), 2)

    def test_classification_prefers_reviewed_status_then_currency(self):
        result = MODULE.classify_symbols(
            ["KNOWN", "NONUS", "ASSET", "DOLLAR", "POUND", "UNKNOWN"],
            {
                "KNOWN": {"GBP"}, "NONUS": {"USD"}, "DOLLAR": {"USD"},
                "POUND": {"GBP"},
            },
            known_us={"KNOWN"},
            known_non_us={"NONUS"},
            asset_symbols={"ASSET"},
        )
        self.assertEqual(result["KNOWN"], "verified_existing_research_universe")
        self.assertEqual(result["NONUS"], "excluded_existing_non_us")
        self.assertEqual(result["ASSET"], "verified_asset_snapshot")
        self.assertEqual(result["DOLLAR"], "provisional_usd_displayed")
        self.assertEqual(result["POUND"], "excluded_non_us_currency")
        self.assertEqual(result["UNKNOWN"], "unresolved_no_currency_evidence")

    def test_generated_universe_cannot_verify_its_own_symbols(self):
        with tempfile.TemporaryDirectory() as temp:
            universe_dir = Path(temp)
            reviewed = {
                "research_date": "2026-07-31",
                "symbol_groups": {"premarket_observed": ["KNOWN"]},
                "excluded_non_us_symbols": ["NONUS"],
            }
            generated = {
                "schema_version": MODULE.UNIVERSE_SCHEMA,
                "research_date": "2026-08-03",
                "symbol_groups": {"premarket_observed": ["PROVISIONAL"]},
                "excluded_non_us_symbols": ["AUTOEXCLUDED"],
            }
            (universe_dir / "2026-07-31.json").write_text(
                json.dumps(reviewed), encoding="utf-8"
            )
            (universe_dir / "2026-08-03.json").write_text(
                json.dumps(generated), encoding="utf-8"
            )

            known_us, known_non_us, existing = MODULE.load_known_classifications(
                universe_dir
            )

            self.assertEqual(known_us, {"KNOWN"})
            self.assertEqual(known_non_us, {"NONUS"})
            self.assertEqual(set(existing), {"2026-07-31"})

    def test_run_preserves_existing_reviewed_universe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recovered = root / "recovered"
            observations_dir = recovered / "observations"
            observations_dir.mkdir(parents=True)
            row = image_row("a", "2026-08-03", "09:11")
            payload = observation(row, [item(1, "ABCD", "$2.00", "20%", "Example")])
            (observations_dir / "a.json").write_text(json.dumps(payload), encoding="utf-8")
            inventory_fields = list(row)
            import csv
            with (recovered / "screenshots-inventory.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=inventory_fields)
                writer.writeheader()
                writer.writerow(row)
            (recovered / "missing-or-unreadable-screenshots.csv").write_text(
                "source_filename,screenshot_id,visible_position,field,issue_type,details\n",
                encoding="utf-8",
            )
            universe_dir = root / "universes"
            universe_dir.mkdir()
            existing = {
                "research_date": "2026-08-03",
                "symbol_groups": {"premarket_observed": ["ABCD"]},
                "excluded_non_us_symbols": [],
            }
            existing_path = universe_dir / "2026-08-03.json"
            existing_content = json.dumps(existing)
            existing_path.write_text(existing_content, encoding="utf-8")
            summary = MODULE.run(
                recovered,
                root / "output",
                universe_dir,
                None,
                2,
                True,
                False,
            )
            self.assertEqual(existing_path.read_text(encoding="utf-8"), existing_content)
            self.assertEqual(
                summary["file_actions"][str(existing_path)],
                "preserved_existing_reviewed_universe",
            )


if __name__ == "__main__":
    unittest.main()
