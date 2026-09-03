#!/usr/bin/env python3
"""Build a broad, dated Alpaca US-equity discovery universe.

This is a read-only market-data preparation tool. It never accesses accounts,
positions, or orders. The generated file records the asset snapshot used for a
future research run; it must not be represented as a historically complete
universe for dates before the snapshot was taken.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ASSETS_URL = "https://api.alpaca.markets/v2/assets"
ALLOWED_EXCHANGES = {"AMEX", "ARCA", "BATS", "NASDAQ", "NYSE"}
RULE_VERSION = "broad-us-equity-v1"


class UniverseError(RuntimeError):
    pass


def get_credentials() -> tuple[str, str]:
    key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
    secret = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise UniverseError("Alpaca credentials were not found in supported environment variables")
    return key, secret


def fetch_assets(key: str, secret: str, timeout: int) -> list[dict[str, Any]]:
    query = urlencode({"status": "active", "asset_class": "us_equity"})
    request = Request(
        f"{ASSETS_URL}?{query}",
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
            "User-Agent": "gainers-spotting-universe/1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise UniverseError(f"Alpaca HTTP {exc.code}") from exc
    except URLError as exc:
        raise UniverseError(f"Alpaca connection failed: {exc.reason}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UniverseError("Alpaca returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise UniverseError("Alpaca assets response was not a list")
    return payload


def eligible_assets(assets: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Apply broad eligibility only; no price or historical-volume floor."""
    accepted: list[dict[str, Any]] = []
    reasons: dict[str, int] = {}
    for asset in assets:
        reason = None
        symbol = str(asset.get("symbol") or "").strip().upper()
        exchange = str(asset.get("exchange") or "").strip().upper()
        if not symbol:
            reason = "blank_symbol"
        elif asset.get("asset_class") != "us_equity":
            reason = "not_us_equity"
        elif asset.get("status") != "active":
            reason = "not_active"
        elif not bool(asset.get("tradable")):
            reason = "not_tradable"
        elif exchange not in ALLOWED_EXCHANGES:
            reason = "unsupported_exchange"
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        accepted.append({
            "symbol": symbol,
            "name": asset.get("name"),
            "exchange": exchange,
            "easy_to_borrow": asset.get("easy_to_borrow"),
            "fractionable": asset.get("fractionable"),
            "marginable": asset.get("marginable"),
            "shortable": asset.get("shortable"),
        })
    accepted.sort(key=lambda row: row["symbol"])
    return accepted, reasons


def build_payload(research_date: str, assets: list[dict[str, Any]], rejected: dict[str, int]) -> dict[str, Any]:
    snapshot = datetime.now(timezone.utc).isoformat()
    return {
        "research_date": research_date,
        "created_at_utc": snapshot,
        "universe_snapshot_at_utc": snapshot,
        "universe_rule_version": RULE_VERSION,
        "source": ASSETS_URL,
        "research_only": True,
        "orders_supported": False,
        "historical_reproducibility": (
            "Exact for the saved asset snapshot only. Using it for an earlier date may introduce "
            "survivorship bias and must be disclosed."
        ),
        "eligibility": {
            "asset_class": "us_equity",
            "status": "active",
            "tradable": True,
            "exchanges": sorted(ALLOWED_EXCHANGES),
            "minimum_price": None,
            "minimum_historical_volume": None,
            "etf_filter": None,
            "note": "Instrument type is not inferred from company names; downstream research may annotate ETFs/ETPs separately.",
        },
        "asset_count": len(assets),
        "rejected_counts": rejected,
        "symbol_groups": {"dynamic_discovery_universe": [row["symbol"] for row in assets]},
        "assets": assets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="US research date (YYYY-MM-DD)")
    parser.add_argument("--output", type=Path, help="Output JSON path")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    date.fromisoformat(args.date)
    output = args.output or Path("data/research/universes") / f"{args.date}.json"
    try:
        assets, rejected = eligible_assets(fetch_assets(*get_credentials(), args.timeout))
        if not assets:
            raise UniverseError("No eligible Alpaca US equities were returned")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(build_payload(args.date, assets, rejected), indent=2) + "\n", encoding="utf-8")
    except (OSError, UniverseError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"output": str(output), "eligible_assets": len(assets), "rule_version": RULE_VERSION}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
