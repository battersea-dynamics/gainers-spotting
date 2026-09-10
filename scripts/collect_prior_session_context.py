#!/usr/bin/env python3
"""Collect prior-close, after-hours and daily dormancy context from Alpaca.

This research-only collector reads the same dated universe manifests as the
existing intraday collector.  It stores raw-adjusted daily history ending
before the research date and one-minute bars for the immediately preceding
session's 16:00-20:00 America/New_York after-hours window.  It never accesses
accounts, positions or orders.

Alpaca corporate-action coverage is deliberately not inferred.  Until a
verified corporate-action source is supplied, metadata marks true-gap features
as unverified; downstream analysis may retain a descriptive raw gap but must
not call it a corporate-action-safe true gap.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from collect_alpaca_bars import (
    API_URL,
    CollectionError,
    chunked,
    get_credentials,
    iso_z,
    load_universe,
    request_page_with_retry,
    utc_now_iso,
)


EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc
CONTEXT_VERSION = "prior-session-context-v1"
DEFAULT_LOOKBACK_CALENDAR_DAYS = 220
DEFAULT_DORMANCY_WINDOWS = (20, 60, 120)


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _normalise(
    bars_by_symbol: dict[str, list[dict[str, Any]]],
    group_by_symbol: dict[str, str],
    timeframe: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, bars in bars_by_symbol.items():
        for bar in bars:
            timestamp_utc = _timestamp(str(bar["t"]))
            timestamp_et = timestamp_utc.astimezone(EASTERN)
            rows.append({
                "group": group_by_symbol[symbol],
                "symbol": symbol,
                "timeframe": timeframe,
                "session_date": timestamp_et.date().isoformat(),
                "timestamp_utc": iso_z(timestamp_utc),
                "timestamp_et": timestamp_et.isoformat(),
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
                "volume": bar.get("v"),
                "trade_count": bar.get("n"),
                "vwap": bar.get("vw"),
            })
    rows.sort(key=lambda row: (str(row["symbol"]), str(row["timestamp_utc"])))
    return rows


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "group", "symbol", "timeframe", "session_date", "timestamp_utc",
        "timestamp_et", "open", "high", "low", "close", "volume",
        "trade_count", "vwap",
    ]
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_raw_page(
    raw_dir: Path, dataset: str, page_number: int, payload: dict[str, Any]
) -> str:
    directory = raw_dir / dataset
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"page-{page_number:04d}.json.gz"
    with gzip.open(directory / filename, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
    return f"raw/{dataset}/{filename}"


def _collect_dataset(
    *,
    dataset: str,
    symbols: list[str],
    group_by_symbol: dict[str, str],
    start_et: datetime,
    end_et: datetime,
    timeframe: str,
    raw_dir: Path,
    key: str,
    secret: str,
    batch_size: int,
    limit: int,
    timeout: int,
    max_attempts: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_bars: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    pending_batches = list(chunked(symbols, batch_size))
    failures: dict[str, str] = {}
    summary: dict[str, Any] = {
        "dataset": dataset,
        "endpoint": API_URL,
        "timeframe": timeframe,
        "feed": "sip",
        "adjustment": "raw",
        "start_et": start_et.isoformat(),
        "end_et": end_et.isoformat(),
        "end_semantics": "exclusive",
        "start_utc": iso_z(start_et.astimezone(UTC)),
        "end_utc": iso_z(end_et.astimezone(UTC)),
        "pages": 0,
        "page_files": [],
        "page_requests": [],
        "attempted_batches": 0,
        "split_batches": 0,
        "rejected_single_symbol_batches": 0,
        "completed": False,
        "bar_counts": {},
        "successful_symbols": [],
        "failures": {},
        "total_bars": 0,
    }
    while pending_batches:
        batch_symbols = pending_batches.pop(0)
        summary["attempted_batches"] += 1
        batch_number = summary["attempted_batches"]
        params: dict[str, str | int] = {
            "symbols": ",".join(batch_symbols),
            "timeframe": timeframe,
            "start": summary["start_utc"],
            "end": summary["end_utc"],
            "limit": limit,
            "adjustment": "raw",
            "feed": "sip",
            "sort": "asc",
        }
        pages_before_batch = int(summary["pages"])
        next_page_token: str | None = None
        seen_tokens: set[str] = set()
        try:
            while True:
                if next_page_token:
                    params["page_token"] = next_page_token
                else:
                    params.pop("page_token", None)
                requested_at = utc_now_iso()
                payload, status, safe_headers, attempts = request_page_with_retry(
                    params, key, secret, timeout, max_attempts
                )
                summary["pages"] += 1
                page_number = int(summary["pages"])
                page_file = _write_raw_page(raw_dir, dataset, page_number, payload)
                summary["page_files"].append(page_file)
                summary["page_requests"].append({
                    "page": page_number,
                    "batch": batch_number,
                    "batch_symbol_count": len(batch_symbols),
                    "requested_at_utc": requested_at,
                    "completed_at_utc": utc_now_iso(),
                    "status": status,
                    "attempts": attempts,
                    "rate_limit_headers": safe_headers,
                    "had_request_page_token": bool(next_page_token),
                    "has_next_page_token": bool(payload.get("next_page_token")),
                })
                for symbol, bars in (payload.get("bars") or {}).items():
                    if symbol in all_bars:
                        all_bars[symbol].extend(bars)
                new_token = payload.get("next_page_token")
                if not new_token:
                    break
                if new_token in seen_tokens:
                    raise CollectionError(
                        f"Alpaca repeated a pagination token for {dataset}"
                    )
                seen_tokens.add(str(new_token))
                next_page_token = str(new_token)
        except CollectionError as exc:
            initial_bad_request = (
                "Alpaca HTTP 400" in str(exc)
                and int(summary["pages"]) == pages_before_batch
            )
            if not initial_bad_request:
                raise
            if len(batch_symbols) == 1:
                failures[batch_symbols[0]] = str(exc)
                summary["rejected_single_symbol_batches"] += 1
                continue
            midpoint = len(batch_symbols) // 2
            pending_batches[0:0] = [
                batch_symbols[:midpoint], batch_symbols[midpoint:]
            ]
            summary["split_batches"] += 1

    rows = _normalise(all_bars, group_by_symbol, timeframe)
    counts = {
        symbol: len(symbol_rows)
        for symbol, symbol_rows in all_bars.items()
        if symbol_rows
    }
    summary["bar_counts"] = counts
    summary["successful_symbols"] = [
        symbol for symbol in symbols if counts.get(symbol, 0) > 0
    ]
    summary["failures"] = {
        symbol: failures.get(symbol, "No bars returned for the requested window")
        for symbol in symbols
        if counts.get(symbol, 0) == 0
    }
    summary["total_bars"] = len(rows)
    summary["completed"] = True
    return rows, summary


def previous_session_from_daily(rows: list[dict[str, Any]], research_date: str) -> str:
    candidates = {
        str(row["session_date"])
        for row in rows
        if str(row["session_date"]) < research_date
    }
    if not candidates:
        raise CollectionError("Daily history did not identify a previous US session")
    return max(candidates)


def collect_context(
    *,
    requested_date: str,
    universe_file: Path,
    output_root: Path,
    lookback_calendar_days: int = DEFAULT_LOOKBACK_CALENDAR_DAYS,
    batch_size: int = 200,
    limit: int = 10_000,
    timeout: int = 60,
    max_attempts: int = 4,
) -> tuple[Path, dict[str, Any]]:
    research_day = date.fromisoformat(requested_date)
    group_by_symbol, symbol_groups, universe_source = load_universe(
        requested_date, universe_file
    )
    symbols = list(group_by_symbol)
    context_dir = output_root / requested_date / "context"
    raw_dir = context_dir / "raw"
    context_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "collector": "scripts/collect_prior_session_context.py",
        "context_version": CONTEXT_VERSION,
        "research_only": True,
        "orders_supported": False,
        "research_date": requested_date,
        "requested_symbols": symbols,
        "symbol_groups": symbol_groups,
        "universe_source": universe_source,
        "dormancy_windows_sessions": list(DEFAULT_DORMANCY_WINDOWS),
        "lookback_calendar_days": lookback_calendar_days,
        "request_started_at_utc": utc_now_iso(),
        "request_finished_at_utc": None,
        "previous_session_date": None,
        "previous_close_source": {
            "field": "close",
            "dataset": "Alpaca SIP 1Day raw bar",
            "interpretation": "previous regular-session daily close",
        },
        "daily_history": {},
        "after_hours": {},
        "price_adjustment": {
            "daily_history": "raw",
            "after_hours": "raw",
            "current_session_expected": "raw",
            "comparable_basis": True,
            "warning": (
                "Raw prices are comparable only when no intervening corporate "
                "action changes the basis. Verified true-gap features remain "
                "unavailable until corporate actions are reconciled."
            ),
        },
        "corporate_actions": {
            "status": "unavailable_not_collected",
            "source": None,
            "affected_symbols": [],
            "warning": (
                "No verified corporate-action source was used. Descriptive raw "
                "gaps must not be treated as split-safe true gaps."
            ),
        },
        "files": ["daily-bars.csv.gz", "after-hours-bars.csv.gz"],
        "error": None,
    }
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
        )
        metadata["daily_history"] = daily_summary
        previous_session = previous_session_from_daily(daily_rows, requested_date)
        metadata["previous_session_date"] = previous_session
        _write_rows(context_dir / "daily-bars.csv.gz", daily_rows)
        previous_day = date.fromisoformat(previous_session)
        after_hours_start = datetime.combine(
            previous_day, datetime_time(16, 0), tzinfo=EASTERN
        )
        after_hours_end = datetime.combine(
            previous_day, datetime_time(20, 0), tzinfo=EASTERN
        )
        after_hours_rows, after_hours_summary = _collect_dataset(
            dataset="after-hours",
            symbols=symbols,
            group_by_symbol=group_by_symbol,
            start_et=after_hours_start,
            end_et=after_hours_end,
            timeframe="1Min",
            raw_dir=raw_dir,
            key=key,
            secret=secret,
            batch_size=batch_size,
            limit=limit,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        metadata["after_hours"] = after_hours_summary
        _write_rows(context_dir / "after-hours-bars.csv.gz", after_hours_rows)
    except (CollectionError, OSError, ValueError) as exc:
        metadata["error"] = str(exc)
    finally:
        metadata["request_finished_at_utc"] = utc_now_iso()
        (context_dir / "context-metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return context_dir, metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="US research date (YYYY-MM-DD)")
    parser.add_argument("--universe-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("data/research"))
    parser.add_argument(
        "--lookback-calendar-days", type=int,
        default=DEFAULT_LOOKBACK_CALENDAR_DAYS,
    )
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--limit", type=int, default=10_000)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--max-attempts", type=int, default=4)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.lookback_calendar_days < 180:
        print("--lookback-calendar-days must be at least 180", file=sys.stderr)
        return 2
    if not 1 <= args.limit <= 10_000 or not 1 <= args.batch_size <= 1_000:
        print("Invalid --limit or --batch-size", file=sys.stderr)
        return 2
    output_dir, metadata = collect_context(
        requested_date=args.date,
        universe_file=args.universe_file,
        output_root=args.output_root,
        lookback_calendar_days=args.lookback_calendar_days,
        batch_size=args.batch_size,
        limit=args.limit,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
    )
    result = {
        "output_dir": str(output_dir),
        "previous_session_date": metadata.get("previous_session_date"),
        "daily_bars": metadata.get("daily_history", {}).get("total_bars", 0),
        "after_hours_bars": metadata.get("after_hours", {}).get("total_bars", 0),
        "corporate_action_status": metadata["corporate_actions"]["status"],
        "error": metadata.get("error"),
    }
    print(json.dumps(result, sort_keys=True))
    complete = (
        metadata.get("error") is None
        and metadata.get("daily_history", {}).get("completed") is True
        and metadata.get("after_hours", {}).get("completed") is True
        and bool(metadata.get("previous_session_date"))
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
