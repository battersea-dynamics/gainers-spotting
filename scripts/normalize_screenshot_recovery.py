#!/usr/bin/env python3
"""Normalize recovered Revolut screenshot OCR into dated research records.

The source archive is deliberately kept outside Git.  This script validates
its inventory, groups adjacent scrolling captures into checkpoints, merges
duplicate ticker appearances without inventing a global rank, and writes
compact date-level observations.  It can also create provisional collection
universes for dates that do not already have a reviewed universe file.

No broker, account, position, or order endpoint is used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


OBSERVATION_SCHEMA = "revolut-date-observations-v1"
UNIVERSE_SCHEMA = "revolut-recovery-universe-v1"
NORMALIZER_VERSION = "screenshot-recovery-normalizer-v1"
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
PERCENT_PATTERN = re.compile(r"^([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)%$")
PRICE_PATTERN = re.compile(r"^([$£€])\s*([0-9][0-9,]*(?:\.[0-9]+)?)$")
CURRENCY_CODES = {"$": "USD", "£": "GBP", "€": "EUR"}
PHASE_ORDER = {"premarket": 0, "market_open": 1, "post_open": 2}


class RecoveryError(RuntimeError):
    """Raised when the recovered archive is incomplete or inconsistent."""


@dataclass(frozen=True)
class RecoveryBundle:
    inventory: list[dict[str, str]]
    missing_fields: list[dict[str, str]]
    observations: dict[str, dict[str, Any]]


def bundle_fingerprint(bundle: RecoveryBundle) -> str:
    """Return a path-independent hash of the recovered structured content."""
    digest = hashlib.sha256()
    sections = (
        sorted(bundle.inventory, key=lambda row: row.get("screenshot_id", "")),
        sorted(bundle.missing_fields, key=lambda row: json.dumps(row, sort_keys=True)),
        {key: bundle.observations[key] for key in sorted(bundle.observations)},
    )
    for section in sections:
        digest.update(json.dumps(
            section, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _csv_rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))


def _find_member(names: Iterable[str], suffix: str) -> str:
    matches = [name for name in names if name.endswith(suffix)]
    if len(matches) != 1:
        raise RecoveryError(
            f"Expected one archive member ending in {suffix!r}; found {len(matches)}"
        )
    return matches[0]


def load_recovery(source: Path) -> RecoveryBundle:
    """Load and validate either a recovery ZIP or its extracted directory."""
    if source.is_file():
        try:
            archive = zipfile.ZipFile(source)
        except (OSError, zipfile.BadZipFile) as exc:
            raise RecoveryError(f"Could not open recovery ZIP: {source}") from exc
        with archive:
            names = archive.namelist()
            inventory_name = _find_member(names, "screenshots-inventory.csv")
            missing_name = _find_member(names, "missing-or-unreadable-screenshots.csv")
            base = str(PurePosixPath(inventory_name).parent)

            def read(relative: str) -> str:
                member = str(PurePosixPath(base) / relative)
                try:
                    return archive.read(member).decode("utf-8-sig")
                except KeyError as exc:
                    raise RecoveryError(f"Archive is missing {relative}") from exc

            inventory = _csv_rows(archive.read(inventory_name).decode("utf-8-sig"))
            missing = _csv_rows(archive.read(missing_name).decode("utf-8-sig"))
            observations = {
                row["json_file"]: json.loads(read(row["json_file"]))
                for row in inventory
            }
    elif source.is_dir():
        inventory_paths = list(source.rglob("screenshots-inventory.csv"))
        if len(inventory_paths) != 1:
            raise RecoveryError(
                "Expected exactly one screenshots-inventory.csv below the input directory"
            )
        base_path = inventory_paths[0].parent
        inventory = _csv_rows(inventory_paths[0].read_text(encoding="utf-8-sig"))
        missing_path = base_path / "missing-or-unreadable-screenshots.csv"
        if not missing_path.exists():
            raise RecoveryError("Recovery directory is missing unreadable-field report")
        missing = _csv_rows(missing_path.read_text(encoding="utf-8-sig"))
        observations = {}
        for row in inventory:
            path = base_path / row["json_file"]
            if not path.exists():
                raise RecoveryError(f"Recovery directory is missing {row['json_file']}")
            observations[row["json_file"]] = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise RecoveryError(f"Recovery input does not exist: {source}")

    validate_recovery(inventory, observations)
    return RecoveryBundle(inventory, missing, observations)


def validate_recovery(
    inventory: list[dict[str, str]], observations: dict[str, dict[str, Any]]
) -> None:
    required = {
        "screenshot_id", "source_filename", "trading_date",
        "actual_uk_screenshot_time", "market_phase", "visible_rows_extracted",
        "json_file", "access_status",
    }
    if not inventory:
        raise RecoveryError("Recovery inventory is empty")
    missing_columns = required - set(inventory[0])
    if missing_columns:
        raise RecoveryError(f"Inventory is missing columns: {sorted(missing_columns)}")
    ids: set[str] = set()
    for row in inventory:
        screenshot_id = row["screenshot_id"]
        if screenshot_id in ids:
            raise RecoveryError(f"Duplicate screenshot_id: {screenshot_id}")
        ids.add(screenshot_id)
        try:
            date.fromisoformat(row["trading_date"])
            datetime.strptime(row["actual_uk_screenshot_time"], "%H:%M")
            expected_rows = int(row["visible_rows_extracted"])
        except ValueError as exc:
            raise RecoveryError(f"Invalid inventory value for {screenshot_id}") from exc
        observation = observations.get(row["json_file"])
        if observation is None:
            raise RecoveryError(f"Missing observation JSON: {row['json_file']}")
        if observation.get("screenshot_id") != screenshot_id:
            raise RecoveryError(f"Screenshot ID mismatch: {screenshot_id}")
        if observation.get("trading_date") != row["trading_date"]:
            raise RecoveryError(f"Trading-date mismatch: {screenshot_id}")
        if len(observation.get("observations", [])) != expected_rows:
            raise RecoveryError(f"Visible-row count mismatch: {screenshot_id}")


def parse_price(value: object) -> dict[str, object] | None:
    if not isinstance(value, str):
        return None
    match = PRICE_PATTERN.fullmatch(value.strip())
    if not match:
        return None
    return {
        "currency": CURRENCY_CODES[match.group(1)],
        "value": float(match.group(2).replace(",", "")),
        "raw": value,
    }


def parse_percentage(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    match = PERCENT_PATTERN.fullmatch(value.strip().replace("−", "-"))
    return float(match.group(1).replace(",", "")) if match else None


def _image_timestamp(row: dict[str, str]) -> datetime:
    return datetime.fromisoformat(
        f"{row['trading_date']}T{row['actual_uk_screenshot_time']}:00"
    )


def group_inventory(
    inventory: Iterable[dict[str, str]], tolerance_minutes: int = 2
) -> list[list[dict[str, str]]]:
    """Group same-phase captures whose timestamps form a close sequence."""
    ordered = sorted(
        inventory,
        key=lambda row: (
            row["trading_date"], _image_timestamp(row),
            PHASE_ORDER.get(row["market_phase"], 99),
            row["screenshot_id"],
        ),
    )
    groups: list[list[dict[str, str]]] = []
    tolerance = timedelta(minutes=tolerance_minutes)
    for row in ordered:
        if not groups:
            groups.append([row])
            continue
        previous = groups[-1][-1]
        same_date = previous["trading_date"] == row["trading_date"]
        same_phase = previous["market_phase"] == row["market_phase"]
        close_in_time = _image_timestamp(row) - _image_timestamp(previous) <= tolerance
        if same_date and same_phase and close_in_time:
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def _unique(values: Iterable[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value is None or value == "":
            continue
        key = json.dumps(value, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _resolution(values: list[Any]) -> tuple[Any | None, str]:
    if not values:
        return None, "missing"
    if len(values) == 1:
        return values[0], "resolved"
    return None, "conflict_preserved"


def build_checkpoint(
    image_rows: list[dict[str, str]], observations: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    image_rows = sorted(image_rows, key=lambda row: (_image_timestamp(row), row["screenshot_id"]))
    ticker_appearances: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unreadable_rows: list[dict[str, Any]] = []
    source_images: list[dict[str, Any]] = []
    for image in image_rows:
        source = observations[image["json_file"]]
        source_images.append({
            "screenshot_id": image["screenshot_id"],
            "source_filename": image["source_filename"],
            "actual_uk_screenshot_time": image["actual_uk_screenshot_time"],
            "visible_rows_extracted": int(image["visible_rows_extracted"]),
        })
        for item in source.get("observations", []):
            ticker = str(item.get("ticker") or "").strip().upper()
            appearance = {
                "screenshot_id": image["screenshot_id"],
                "source_filename": image["source_filename"],
                "actual_uk_screenshot_time": image["actual_uk_screenshot_time"],
                "visible_position": item.get("visible_position"),
                "company_name": item.get("company_name"),
                "displayed_price": item.get("displayed_price"),
                "displayed_percentage_change": item.get("displayed_percentage_change"),
                "ocr_confidence": item.get("ocr_confidence"),
            }
            if not ticker:
                unreadable_rows.append(appearance)
            else:
                ticker_appearances[ticker].append(appearance)

    merged = []
    for ticker in sorted(ticker_appearances):
        appearances = ticker_appearances[ticker]
        names = _unique(item.get("company_name") for item in appearances)
        prices = _unique(parse_price(item.get("displayed_price")) for item in appearances)
        percentages = _unique(
            parse_percentage(item.get("displayed_percentage_change"))
            for item in appearances
        )
        name, name_status = _resolution(names)
        price, price_status = _resolution(prices)
        percentage, percentage_status = _resolution(percentages)
        merged.append({
            "ticker": ticker,
            "resolved_company_name": name,
            "resolved_price": price,
            "resolved_percentage_points": percentage,
            "field_status": {
                "company_name": name_status,
                "price": price_status,
                "percentage_change": percentage_status,
            },
            "appearances": appearances,
        })

    start = _image_timestamp(image_rows[0])
    end = _image_timestamp(image_rows[-1])
    checkpoint_id = f"{start:%Y-%m-%d_%H%M}_{image_rows[0]['market_phase']}"
    return {
        "checkpoint_id": checkpoint_id,
        "market_phase": image_rows[0]["market_phase"],
        "actual_uk_time_start": start.strftime("%H:%M"),
        "actual_uk_time_end": end.strftime("%H:%M"),
        "intended_checkpoint_time": None,
        "source_images": source_images,
        "symbols": merged,
        "unreadable_ticker_rows": unreadable_rows,
        "global_rank_policy": (
            "Not inferred. visible_position is preserved per scrolling capture."
        ),
    }


def load_known_classifications(
    universe_dir: Path,
) -> tuple[set[str], set[str], dict[str, dict[str, Any]]]:
    known_us: set[str] = set()
    known_non_us: set[str] = set()
    existing: dict[str, dict[str, Any]] = {}
    if not universe_dir.exists():
        return known_us, known_non_us, existing
    for path in sorted(universe_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") == UNIVERSE_SCHEMA:
            # Generated recovery universes are provisional outputs, not an
            # independent review source.  Loading them as prior evidence would
            # allow a rerun to promote their own symbols to verified status.
            continue
        research_date = str(payload.get("research_date") or path.stem)
        existing[research_date] = payload
        for symbols in payload.get("symbol_groups", {}).values():
            known_us.update(str(symbol).upper() for symbol in symbols)
        known_non_us.update(
            str(symbol).upper() for symbol in payload.get("excluded_non_us_symbols", [])
        )
    return known_us, known_non_us, existing


def load_asset_symbols(path: Path | None) -> set[str]:
    if path is None:
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(asset.get("symbol") or "").strip().upper()
        for asset in payload.get("assets", [])
        if asset.get("symbol")
    }


def currency_evidence(bundle: RecoveryBundle) -> dict[str, set[str]]:
    evidence: dict[str, set[str]] = defaultdict(set)
    for observation in bundle.observations.values():
        for item in observation.get("observations", []):
            ticker = str(item.get("ticker") or "").strip().upper()
            price = parse_price(item.get("displayed_price"))
            if ticker and price:
                evidence[ticker].add(str(price["currency"]))
    return evidence


def classify_symbols(
    tickers: Iterable[str],
    currencies: dict[str, set[str]],
    known_us: set[str],
    known_non_us: set[str],
    asset_symbols: set[str],
) -> dict[str, str]:
    classifications: dict[str, str] = {}
    for ticker in sorted(set(tickers)):
        observed_currencies = currencies.get(ticker, set())
        if not TICKER_PATTERN.fullmatch(ticker):
            status = "unresolved_invalid_ticker_format"
        elif ticker in known_us:
            status = "verified_existing_research_universe"
        elif ticker in known_non_us:
            status = "excluded_existing_non_us"
        elif ticker in asset_symbols:
            status = "verified_asset_snapshot"
        elif observed_currencies == {"USD"}:
            status = "provisional_usd_displayed"
        elif "USD" in observed_currencies and len(observed_currencies) > 1:
            status = "unresolved_currency_conflict"
        elif observed_currencies:
            status = "excluded_non_us_currency"
        else:
            status = "unresolved_no_currency_evidence"
        classifications[ticker] = status
    return classifications


def build_date_documents(
    bundle: RecoveryBundle,
    tolerance_minutes: int,
    universe_dir: Path,
    asset_file: Path | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    known_us, known_non_us, existing = load_known_classifications(universe_dir)
    assets = load_asset_symbols(asset_file)
    currencies = currency_evidence(bundle)
    groups = group_inventory(bundle.inventory, tolerance_minutes)
    checkpoints_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_tickers: set[str] = set()
    for group in groups:
        checkpoint = build_checkpoint(group, bundle.observations)
        day = group[0]["trading_date"]
        checkpoints_by_date[day].append(checkpoint)
        all_tickers.update(item["ticker"] for item in checkpoint["symbols"])
    classifications = classify_symbols(
        all_tickers, currencies, known_us, known_non_us, assets
    )
    source_bundle_sha256 = bundle_fingerprint(bundle)

    unreadable_by_screenshot = Counter(
        row.get("screenshot_id", "") for row in bundle.missing_fields
    )
    date_documents: dict[str, dict[str, Any]] = {}
    universes: dict[str, dict[str, Any]] = {}
    comparisons: dict[str, Any] = {}
    for day, checkpoints in sorted(checkpoints_by_date.items()):
        image_ids = {
            image["screenshot_id"]
            for checkpoint in checkpoints
            for image in checkpoint["source_images"]
        }
        phase_symbols: dict[str, set[str]] = defaultdict(set)
        unreadable_ticker_rows = 0
        for checkpoint in checkpoints:
            phase_symbols[checkpoint["market_phase"]].update(
                item["ticker"] for item in checkpoint["symbols"]
            )
            unreadable_ticker_rows += len(checkpoint["unreadable_ticker_rows"])
        day_symbols = set().union(*phase_symbols.values()) if phase_symbols else set()
        date_documents[day] = {
            "schema_version": OBSERVATION_SCHEMA,
            "normalizer_version": NORMALIZER_VERSION,
            "research_date": day,
            "source": "Recovered Revolut Top Movers screenshot OCR",
            "source_bundle_sha256": source_bundle_sha256,
            "research_only": True,
            "screenshots_are_scanner_inputs": False,
            "checkpoint_grouping_tolerance_minutes": tolerance_minutes,
            "checkpoints": checkpoints,
            "symbol_classification": {
                ticker: classifications[ticker] for ticker in sorted(day_symbols)
            },
            "quality_summary": {
                "source_images": len(image_ids),
                "checkpoints": len(checkpoints),
                "unique_readable_tickers": len(day_symbols),
                "unreadable_ticker_rows": unreadable_ticker_rows,
                "unreadable_field_records": sum(
                    unreadable_by_screenshot[screenshot_id]
                    for screenshot_id in image_ids
                ),
                "intended_checkpoint_times_recovered": 0,
                "global_numeric_ranks_available": False,
            },
        }

        eligible_statuses = {
            "verified_existing_research_universe",
            "verified_asset_snapshot",
            "provisional_usd_displayed",
        }
        premarket = {
            ticker for ticker in phase_symbols.get("premarket", set())
            if classifications[ticker] in eligible_statuses
        }
        later = set().union(
            phase_symbols.get("market_open", set()),
            phase_symbols.get("post_open", set()),
        )
        post_open_only = {
            ticker for ticker in later - premarket
            if classifications[ticker] in eligible_statuses
        }
        excluded = {
            ticker for ticker in day_symbols
            if classifications[ticker].startswith("excluded_")
        }
        unresolved = day_symbols - premarket - post_open_only - excluded
        universes[day] = {
            "schema_version": UNIVERSE_SCHEMA,
            "research_date": day,
            "source": (
                "Recovered timestamped Revolut Top Movers observations; "
                "USD-displayed symbols remain provisional until Alpaca historical validation"
            ),
            "research_only": True,
            "symbol_groups": {
                "premarket_observed": sorted(premarket),
                "post_open_only_observed": sorted(post_open_only),
            },
            "excluded_non_us_symbols": sorted(excluded),
            "unresolved_symbols": sorted(unresolved),
            "eligibility_status": {
                ticker: classifications[ticker] for ticker in sorted(day_symbols)
            },
            "limitations": [
                "Revolut membership is an external historical label, not a future scanner input.",
                "provisional_usd_displayed is a collection candidate, not verified exchange eligibility.",
                "Alpaca historical bar success and dated asset metadata should finalize eligibility.",
                "No global list rank is inferred from scrolling screenshots.",
            ],
        }

        if day in existing:
            old_groups = existing[day].get("symbol_groups", {})
            old_pm = set(old_groups.get("premarket_observed", []))
            old_post = set(old_groups.get("post_open_only_observed", []))
            comparisons[day] = {
                "existing_file_preserved": True,
                "premarket_missing_from_recovery": sorted(old_pm - premarket),
                "premarket_additional_in_recovery": sorted(premarket - old_pm),
                "post_open_missing_from_recovery": sorted(old_post - post_open_only),
                "post_open_additional_in_recovery": sorted(post_open_only - old_post),
            }

    summary = {
        "normalizer_version": NORMALIZER_VERSION,
        "source_bundle_sha256": source_bundle_sha256,
        "source_images": len(bundle.inventory),
        "source_access_status_counts": dict(sorted(Counter(
            row.get("access_status") or "unspecified" for row in bundle.inventory
        ).items())),
        "market_phase_image_counts": dict(sorted(Counter(
            row.get("market_phase") or "unspecified" for row in bundle.inventory
        ).items())),
        "source_observation_rows": sum(
            len(item.get("observations", [])) for item in bundle.observations.values()
        ),
        "source_unreadable_field_records": len(bundle.missing_fields),
        "unreadable_field_counts": dict(sorted(Counter(
            row.get("field") or "unspecified" for row in bundle.missing_fields
        ).items())),
        "dates": sorted(date_documents),
        "date_count": len(date_documents),
        "checkpoint_count": sum(len(doc["checkpoints"]) for doc in date_documents.values()),
        "unique_readable_tickers": len(all_tickers),
        "classification_counts": dict(Counter(classifications.values())),
        "existing_universe_comparisons": comparisons,
    }
    return date_documents, universes, summary


def write_json(path: Path, payload: dict[str, Any], force: bool = False) -> str:
    content = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == content:
            return "unchanged"
        if not force:
            raise RecoveryError(f"Refusing to replace changed file without --force: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "written"


def run(
    source: Path,
    observation_dir: Path,
    universe_dir: Path,
    asset_file: Path | None,
    tolerance_minutes: int,
    write_universes: bool,
    force: bool,
) -> dict[str, Any]:
    bundle = load_recovery(source)
    documents, universes, summary = build_date_documents(
        bundle, tolerance_minutes, universe_dir, asset_file
    )
    actions: dict[str, str] = {}
    for day, payload in documents.items():
        path = observation_dir / f"{day}.json"
        actions[str(path)] = write_json(path, payload, force=force)
    summary_path = observation_dir / "recovery-summary.json"
    actions[str(summary_path)] = write_json(summary_path, summary, force=force)

    if write_universes:
        for day, payload in universes.items():
            path = universe_dir / f"{day}.json"
            if path.exists() and day in summary["existing_universe_comparisons"]:
                actions[str(path)] = "preserved_existing_reviewed_universe"
            else:
                actions[str(path)] = write_json(path, payload, force=force)
    summary["file_actions"] = actions
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Recovery ZIP or directory")
    parser.add_argument(
        "--observation-dir", type=Path,
        default=Path("config/research-observations"),
    )
    parser.add_argument(
        "--universe-dir", type=Path,
        default=Path("config/research-universes"),
    )
    parser.add_argument(
        "--asset-file", type=Path,
        help="Optional dated Alpaca asset snapshot used only for symbol validation",
    )
    parser.add_argument("--checkpoint-tolerance-minutes", type=int, default=2)
    parser.add_argument(
        "--write-universes", action="store_true",
        help="Create missing dated universe files; preserve existing reviewed files",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Replace changed normalized observation files",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 0 <= args.checkpoint_tolerance_minutes <= 10:
        print("--checkpoint-tolerance-minutes must be between 0 and 10", file=sys.stderr)
        return 2
    try:
        summary = run(
            source=args.input,
            observation_dir=args.observation_dir,
            universe_dir=args.universe_dir,
            asset_file=args.asset_file,
            tolerance_minutes=args.checkpoint_tolerance_minutes,
            write_universes=args.write_universes,
            force=args.force,
        )
    except (OSError, RecoveryError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
