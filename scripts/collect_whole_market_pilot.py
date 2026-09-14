#!/usr/bin/env python3
"""Collect the research-only whole-US-market five-minute pilot dataset.

The pilot uses a dated Alpaca asset snapshot supplied by
``build_alpaca_universe.py``. It collects raw-adjusted daily history ending
before the research session and five-minute bars from the preceding session's
after-hours window through the research-session close. It never accesses an
account, positions, or orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time as datetime_time, timedelta
from pathlib import Path

from collect_alpaca_bars import CollectionError, get_credentials, load_universe, utc_now_iso
from collect_prior_session_context import (
    EASTERN,
    _collect_dataset,
    _write_rows,
    previous_session_from_daily,
)


PILOT_VERSION = "whole-market-five-minute-pilot-v1"
DEFAULT_LOOKBACK_CALENDAR_DAYS = 60
DEFAULT_REQUEST_INTERVAL_SECONDS = 0.5


def _load_universe_metadata(path: Path, requested_date: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read universe file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Universe file is not valid JSON: {path}") from exc
    if payload.get("research_date") != requested_date:
        raise ValueError("Universe research_date does not match --date")
    if not payload.get("universe_content_sha256"):
        raise ValueError("Universe file is missing universe_content_sha256")
    return payload


def collect_pilot(
    *,
    requested_date: str,
    universe_file: Path,
    output_root: Path,
    lookback_calendar_days: int = DEFAULT_LOOKBACK_CALENDAR_DAYS,
    batch_size: int = 200,
    limit: int = 10_000,
    timeout: int = 60,
    max_attempts: int = 4,
    request_interval_seconds: float = DEFAULT_REQUEST_INTERVAL_SECONDS,
) -> tuple[Path, dict]:
    research_day = date.fromisoformat(requested_date)
    universe_metadata = _load_universe_metadata(universe_file, requested_date)
    group_by_symbol, symbol_groups, universe_source = load_universe(
        requested_date, universe_file
    )
    symbols = list(group_by_symbol)
    output_dir = output_root / requested_date
    raw_dir = output_dir / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    metadata: dict = {
        "collector": "scripts/collect_whole_market_pilot.py",
        "pilot_version": PILOT_VERSION,
        "research_only": True,
        "orders_supported": False,
        "research_date": requested_date,
        "data_mode": "historical_sip_zero_delay_assumption",
        "feed": "sip",
        "requested_symbols": symbols,
        "requested_symbol_count": len(symbols),
        "symbol_groups": symbol_groups,
        "universe_source": universe_source,
        "universe_snapshot_at_utc": universe_metadata.get("universe_snapshot_at_utc"),
        "universe_rule_version": universe_metadata.get("universe_rule_version"),
        "universe_content_sha256": universe_metadata["universe_content_sha256"],
        "universe_historical_warning": universe_metadata.get("historical_reproducibility"),
        "lookback_calendar_days": lookback_calendar_days,
        "request_interval_seconds": request_interval_seconds,
        "previous_session_date": None,
        "request_started_at_utc": utc_now_iso(),
        "request_finished_at_utc": None,
        "daily_history": {},
        "broad_five_minute": {},
        "price_adjustment": {
            "daily_history": "raw",
            "broad_five_minute": "raw",
            "comparable_basis": True,
            "warning": (
                "Raw prices are not corporate-action-safe. Raw gap and "
                "previous-close outcome fields are descriptive only."
            ),
        },
        "corporate_actions": {
            "status": "unavailable_not_collected",
            "source": None,
            "warning": (
                "Verified true-gap and extreme-gainer labels remain missing "
                "until corporate actions are reconciled."
            ),
        },
        "files": [
            "universe.json",
            "daily-bars.csv.gz",
            "broad-five-minute-bars.csv.gz",
            "collection-metadata.json",
        ],
        "error": None,
    }
    (output_dir / "universe.json").write_text(
        json.dumps(universe_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    try:
        key, secret = get_credentials()
        daily_start = datetime.combine(
            research_day - timedelta(days=lookback_calendar_days),
            datetime_time(0, 0),
            tzinfo=EASTERN,
        )
        daily_end = datetime.combine(
            research_day, datetime_time(0, 0), tzinfo=EASTERN
        )
        daily_rows, daily_summary = _collect_dataset(
            dataset="daily",
            symbols=symbols,
            group_by_symbol=group_by_symbol,
            start_et=daily_start,
            end_et=daily_end,
            timeframe="1Day",
            raw_dir=raw_dir,
            key=key,
            secret=secret,
            batch_size=batch_size,
            limit=limit,
            timeout=timeout,
            max_attempts=max_attempts,
            request_interval_seconds=request_interval_seconds,
        )
        metadata["daily_history"] = daily_summary
        previous_session = previous_session_from_daily(daily_rows, requested_date)
        metadata["previous_session_date"] = previous_session
        _write_rows(output_dir / "daily-bars.csv.gz", daily_rows)

        previous_day = date.fromisoformat(previous_session)
        broad_start = datetime.combine(
            previous_day, datetime_time(16, 0), tzinfo=EASTERN
        )
        broad_end = datetime.combine(
            research_day, datetime_time(16, 0), tzinfo=EASTERN
        )
        broad_rows, broad_summary = _collect_dataset(
            dataset="broad-five-minute",
            symbols=symbols,
            group_by_symbol=group_by_symbol,
            start_et=broad_start,
            end_et=broad_end,
            timeframe="5Min",
            raw_dir=raw_dir,
            key=key,
            secret=secret,
            batch_size=batch_size,
            limit=limit,
            timeout=timeout,
            max_attempts=max_attempts,
            request_interval_seconds=request_interval_seconds,
        )
        metadata["broad_five_minute"] = broad_summary
        _write_rows(output_dir / "broad-five-minute-bars.csv.gz", broad_rows)
    except (CollectionError, OSError, ValueError) as exc:
        metadata["error"] = str(exc)
    finally:
        metadata["request_finished_at_utc"] = utc_now_iso()
        (output_dir / "collection-metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return output_dir, metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Completed US session (YYYY-MM-DD)")
    parser.add_argument("--universe-file", required=True, type=Path)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/research/whole-market-pilot"),
    )
    parser.add_argument(
        "--lookback-calendar-days",
        type=int,
        default=DEFAULT_LOOKBACK_CALENDAR_DAYS,
    )
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--limit", type=int, default=10_000)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument(
        "--request-interval-seconds",
        type=float,
        default=DEFAULT_REQUEST_INTERVAL_SECONDS,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        research_day = date.fromisoformat(args.date)
    except ValueError:
        print("--date must use YYYY-MM-DD", file=sys.stderr)
        return 2
    if research_day >= datetime.now(EASTERN).date():
        print("--date must be a completed US session before today", file=sys.stderr)
        return 2
    if args.lookback_calendar_days < 35:
        print("--lookback-calendar-days must be at least 35", file=sys.stderr)
        return 2
    if not 1 <= args.batch_size <= 1_000 or not 1 <= args.limit <= 10_000:
        print("Invalid --batch-size or --limit", file=sys.stderr)
        return 2
    if args.request_interval_seconds < 0:
        print("--request-interval-seconds cannot be negative", file=sys.stderr)
        return 2

    output_dir, metadata = collect_pilot(
        requested_date=args.date,
        universe_file=args.universe_file,
        output_root=args.output_root,
        lookback_calendar_days=args.lookback_calendar_days,
        batch_size=args.batch_size,
        limit=args.limit,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
        request_interval_seconds=args.request_interval_seconds,
    )
    print(json.dumps({
        "output_dir": str(output_dir),
        "requested_symbols": metadata.get("requested_symbol_count", 0),
        "previous_session_date": metadata.get("previous_session_date"),
        "daily_bars": metadata.get("daily_history", {}).get("total_bars", 0),
        "broad_five_minute_bars": metadata.get("broad_five_minute", {}).get("total_bars", 0),
        "error": metadata.get("error"),
    }, sort_keys=True))
    complete = (
        metadata.get("error") is None
        and metadata.get("daily_history", {}).get("completed") is True
        and metadata.get("broad_five_minute", {}).get("completed") is True
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
