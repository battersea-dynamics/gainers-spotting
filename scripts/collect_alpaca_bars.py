#!/usr/bin/env python3
"""Collect historical Alpaca SIP minute bars for research only.

This module only calls Alpaca's historical stock-bars data endpoint. It contains
no trading client, account endpoint, position logic, or order submission code.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


API_URL = "https://data.alpaca.markets/v2/stocks/bars"
EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc

PREMARKET_CANDIDATES = (
    "LVWR,NVEC,SAFT,DOMO,NVCR,THRM,RELL,ENHA,CLF,ACU,MEDP,THC,OTLY,"
    "EQPT,ALLE,IMAX,PEPG,AADX,AGEN,WEX,URI,UTI,MBX,OSUR,DGX,LMT"
).split(",")

MISSED_RUNNERS_CONTROLS = (
    "RNG,FRMI,WRLD,SUPX,ELME,ORIC,DLR,SLB,AVBC,TTEC,IP,OII,UVE,DXC,"
    "SSNC,BAH,ARHS,AMTB"
).split(",")

GROUP_BY_SYMBOL = {
    **{symbol: "premarket_candidate" for symbol in PREMARKET_CANDIDATES},
    **{
        symbol: "missed_runner_control"
        for symbol in MISSED_RUNNERS_CONTROLS
    },
}

SAFE_RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
)


@dataclass(frozen=True)
class Window:
    requested_date: str
    start_et: datetime
    end_et: datetime
    start_utc: datetime
    end_utc: datetime


class CollectionError(RuntimeError):
    """A safe-to-record collection error that never includes credentials."""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_window(value: str) -> Window:
    session_date = date.fromisoformat(value)
    start_et = datetime.combine(
        session_date, datetime_time(4, 0), tzinfo=EASTERN
    )
    end_et = datetime.combine(
        session_date, datetime_time(16, 0), tzinfo=EASTERN
    )
    return Window(
        requested_date=value,
        start_et=start_et,
        end_et=end_et,
        start_utc=start_et.astimezone(UTC),
        end_utc=end_et.astimezone(UTC),
    )


def get_credentials() -> tuple[str, str]:
    key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
    secret = (
        os.getenv("APCA_API_SECRET_KEY")
        or os.getenv("ALPACA_SECRET_KEY")
    )
    if not key or not secret:
        raise CollectionError(
            "Alpaca credentials were not found in the supported environment "
            "variables"
        )
    return key, secret


def make_request(
    params: dict[str, str | int],
    key: str,
    secret: str,
    timeout: int,
) -> tuple[dict[str, Any], int, dict[str, str]]:
    request = Request(
        f"{API_URL}?{urlencode(params)}",
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
            "User-Agent": "gainers-spotting-research-collector/1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            safe_headers = {
                header: response.headers[header]
                for header in SAFE_RATE_LIMIT_HEADERS
                if response.headers.get(header) is not None
            }
            return payload, response.status, safe_headers
    except HTTPError as exc:
        retry_after = exc.headers.get("Retry-After")
        suffix = f"; retry-after={retry_after}" if retry_after else ""
        raise CollectionError(f"Alpaca HTTP {exc.code}{suffix}") from exc
    except URLError as exc:
        raise CollectionError(
            f"Alpaca connection failed: {exc.reason}"
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CollectionError("Alpaca returned invalid JSON") from exc


def request_page_with_retry(
    params: dict[str, str | int],
    key: str,
    secret: str,
    timeout: int,
    max_attempts: int,
) -> tuple[dict[str, Any], int, dict[str, str], int]:
    last_error: CollectionError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            payload, status, headers = make_request(
                params, key, secret, timeout
            )
            return payload, status, headers, attempt
        except CollectionError as exc:
            last_error = exc
            retryable = (
                "HTTP 429" in str(exc)
                or any(f"HTTP {code}" in str(exc) for code in range(500, 600))
                or "connection failed" in str(exc).lower()
            )
            if not retryable or attempt == max_attempts:
                break
            time.sleep(min(2 ** (attempt - 1), 30))
    assert last_error is not None
    raise last_error


def write_raw_page(
    raw_dir: Path, page_number: int, payload: dict[str, Any]
) -> str:
    filename = f"page-{page_number:04d}.json.gz"
    with gzip.open(raw_dir / filename, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
    return f"raw/{filename}"


def normalise_bars(
    bars_by_symbol: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, bars in bars_by_symbol.items():
        for bar in bars:
            timestamp_utc = datetime.fromisoformat(
                bar["t"].replace("Z", "+00:00")
            ).astimezone(UTC)
            rows.append(
                {
                    "group": GROUP_BY_SYMBOL[symbol],
                    "symbol": symbol,
                    "timestamp_utc": iso_z(timestamp_utc),
                    "timestamp_et": timestamp_utc.astimezone(
                        EASTERN
                    ).isoformat(),
                    "open": bar.get("o"),
                    "high": bar.get("h"),
                    "low": bar.get("l"),
                    "close": bar.get("c"),
                    "volume": bar.get("v"),
                    "trade_count": bar.get("n"),
                    "vwap": bar.get("vw"),
                }
            )
    rows.sort(key=lambda row: (row["symbol"], row["timestamp_utc"]))
    return rows


def write_clean_files(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "group",
        "symbol",
        "timestamp_utc",
        "timestamp_et",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trade_count",
        "vwap",
    ]
    with gzip.open(
        output_dir / "bars.jsonl.gz", "wt", encoding="utf-8"
    ) as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    with gzip.open(
        output_dir / "bars.csv.gz", "wt", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def base_metadata(window: Window, symbols: Iterable[str]) -> dict[str, Any]:
    requested_symbols = list(symbols)
    return {
        "collector": "scripts/collect_alpaca_bars.py",
        "collector_version": 1,
        "research_only": True,
        "orders_supported": False,
        "requested_symbols": requested_symbols,
        "symbol_groups": {
            "premarket_candidates": PREMARKET_CANDIDATES,
            "missed_runners_controls": MISSED_RUNNERS_CONTROLS,
        },
        "successful_symbols": [],
        "failures": {},
        "requested_time_window": {
            "date": window.requested_date,
            "timezone": "America/New_York",
            "start_et": window.start_et.isoformat(),
            "end_et": window.end_et.isoformat(),
            "end_semantics": "exclusive",
            "start_utc": iso_z(window.start_utc),
            "end_utc": iso_z(window.end_utc),
        },
        "feed": "sip",
        "timeframe": "1Min",
        "adjustment": "raw",
        "sort": "asc",
        "pagination": {
            "pages": 0,
            "page_files": [],
            "page_requests": [],
            "completed": False,
        },
        "request_started_at_utc": utc_now_iso(),
        "request_finished_at_utc": None,
        "bar_counts": {},
        "total_bars": 0,
        "clean_files": ["bars.jsonl.gz", "bars.csv.gz"],
    }


def write_metadata(output_dir: Path, metadata: dict[str, Any]) -> None:
    with (output_dir / "metadata.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)
        handle.write("\n")


def collect(
    requested_date: str,
    output_root: Path,
    limit: int,
    timeout: int,
    max_attempts: int,
) -> tuple[Path, dict[str, Any]]:
    window = parse_window(requested_date)
    symbols = list(GROUP_BY_SYMBOL)
    output_dir = output_root / requested_date
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    metadata = base_metadata(window, symbols)

    try:
        key, secret = get_credentials()
        params: dict[str, str | int] = {
            "symbols": ",".join(symbols),
            "timeframe": "1Min",
            "start": iso_z(window.start_utc),
            "end": iso_z(window.end_utc),
            "limit": limit,
            "adjustment": "raw",
            "feed": "sip",
            "sort": "asc",
        }
        all_bars: dict[str, list[dict[str, Any]]] = {
            symbol: [] for symbol in symbols
        }
        seen_tokens: set[str] = set()
        next_page_token: str | None = None

        while True:
            page_number = metadata["pagination"]["pages"] + 1
            if next_page_token:
                params["page_token"] = next_page_token
            else:
                params.pop("page_token", None)

            started_at = utc_now_iso()
            payload, status, rate_headers, attempts = request_page_with_retry(
                params, key, secret, timeout, max_attempts
            )
            finished_at = utc_now_iso()
            page_file = write_raw_page(raw_dir, page_number, payload)
            metadata["pagination"]["pages"] = page_number
            metadata["pagination"]["page_files"].append(page_file)
            metadata["pagination"]["page_requests"].append(
                {
                    "page": page_number,
                    "requested_at_utc": started_at,
                    "completed_at_utc": finished_at,
                    "status": status,
                    "attempts": attempts,
                    "rate_limit_headers": rate_headers,
                    "had_request_page_token": bool(next_page_token),
                    "has_next_page_token": bool(
                        payload.get("next_page_token")
                    ),
                }
            )

            page_bars = payload.get("bars") or {}
            for symbol, bars in page_bars.items():
                if symbol in all_bars:
                    all_bars[symbol].extend(bars)

            new_token = payload.get("next_page_token")
            if not new_token:
                metadata["pagination"]["completed"] = True
                break
            if new_token in seen_tokens:
                raise CollectionError(
                    "Alpaca repeated a pagination token; collection stopped"
                )
            seen_tokens.add(new_token)
            next_page_token = new_token

        rows = normalise_bars(all_bars)
        write_clean_files(output_dir, rows)
        counts = {
            symbol: len(all_bars[symbol])
            for symbol in symbols
            if all_bars[symbol]
        }
        metadata["bar_counts"] = counts
        metadata["total_bars"] = len(rows)
        metadata["successful_symbols"] = [
            symbol for symbol in symbols if counts.get(symbol, 0) > 0
        ]
        metadata["failures"] = {
            symbol: "No bars returned for the requested window"
            for symbol in symbols
            if counts.get(symbol, 0) == 0
        }
    except (CollectionError, ValueError) as exc:
        reason = str(exc)
        metadata["failures"] = {
            symbol: reason for symbol in metadata["requested_symbols"]
        }
    finally:
        metadata["request_finished_at_utc"] = utc_now_iso()
        write_metadata(output_dir, metadata)

    return output_dir, metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect paginated historical Alpaca SIP 1-minute bars for the "
            "fixed Gainers Spotting research universes."
        )
    )
    parser.add_argument(
        "--date",
        required=True,
        help="U.S. market date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/research"),
        help="Output root (default: data/research)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10_000,
        help="Alpaca page size (default: 10000)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Per-request timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=4,
        help="Maximum attempts for retryable requests (default: 4)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.limit <= 10_000:
        print("--limit must be between 1 and 10000", file=sys.stderr)
        return 2
    output_dir, metadata = collect(
        requested_date=args.date,
        output_root=args.output_root,
        limit=args.limit,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
    )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "successful_symbols": metadata["successful_symbols"],
                "failures": metadata["failures"],
                "pages": metadata["pagination"]["pages"],
                "total_bars": metadata["total_bars"],
            },
            sort_keys=True,
        )
    )
    return 0 if not metadata["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
