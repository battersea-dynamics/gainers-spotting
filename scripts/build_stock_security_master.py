#!/usr/bin/env python3
"""Build a dated, auditable stock/non-stock security master.

The source is Nasdaq Trader's daily ``nasdaqtraded.txt`` symbol directory.  The
directory describes Nasdaq-traded securities across US listing exchanges and
contains explicit ETF and test-issue flags plus the exchange security name.
Classification is deliberately conservative: only explicitly described common
shares, ordinary shares, or operating-company ADR/ADS securities enter the
primary stock universe. Unresolved instruments remain ``unknown``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SOURCE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
MASTER_VERSION = "nasdaq-trader-stock-master-v1"
CLASSIFIER_VERSION = "explicit-security-description-v1"


def _normalise_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _contains(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _aliases(row: dict[str, str]) -> list[str]:
    aliases: set[str] = set()
    for field in ("Symbol", "CQS Symbol", "NASDAQ Symbol"):
        value = str(row.get(field) or "").strip().upper()
        if value:
            aliases.add(value)
    symbol = str(row.get("Symbol") or "").strip().upper()
    if "$" in symbol:
        root, suffix = symbol.split("$", 1)
        if root and suffix:
            aliases.add(f"{root}.PR{suffix}")
    if symbol.endswith(".W"):
        aliases.add(f"{symbol}S")
    if symbol.endswith(".R"):
        aliases.add(f"{symbol}T")
    return sorted(aliases)


def classify_security(row: dict[str, str]) -> dict[str, object]:
    """Classify one official symbol-directory record conservatively."""
    name = _normalise_text(row.get("Security Name"))
    symbol = str(row.get("Symbol") or "").strip().upper()
    etf = str(row.get("ETF") or "").strip().upper() == "Y"
    next_shares = str(row.get("NextShares") or "").strip().upper() == "Y"
    test_issue = str(row.get("Test Issue") or "").strip().upper() == "Y"

    instrument_type = "unknown"
    reason = "NO_EXPLICIT_SUPPORTED_SECURITY_TYPE"
    if test_issue:
        instrument_type, reason = "test_security", "NASDAQ_TEST_ISSUE_FLAG"
    elif etf or next_shares:
        instrument_type, reason = "pooled_product", "NASDAQ_ETF_OR_NEXTSHARES_FLAG"
    elif symbol.endswith(".U") or _contains(name, r"\bunits?, each\b|\bunits? consisting\b| - units?\b"):
        instrument_type, reason = "unit", "EXPLICIT_UNIT_DESCRIPTION"
    elif symbol.endswith(".W") or _contains(name, r"\bwarrants?, each\b|\bwarrants? to purchase\b|\bcommon stock purchase warrant\b| - warrants?\b"):
        instrument_type, reason = "warrant", "EXPLICIT_WARRANT_DESCRIPTION"
    elif _contains(name, r"american depositary (shares?|receipts?)"):
        instrument_type, reason = "adr_ads", "EXPLICIT_ADR_ADS_DESCRIPTION"
    elif symbol.endswith(".R") or _contains(name, r"\brights?, each\b|\brights? to receive\b| - rights?\b"):
        instrument_type, reason = "right", "EXPLICIT_RIGHT_DESCRIPTION"
    elif _contains(name, r"\bfund\b"):
        instrument_type, reason = "pooled_product", "EXPLICIT_FUND_DESCRIPTION"
    elif "$" in symbol or _contains(
        name,
        r"\bpreferred stock\b|\bpreferred shares?\b|\bpreference shares?\b|"
        r"\bdepositary shares?.*\bpreferred\b",
    ):
        instrument_type, reason = "preferred", "EXPLICIT_PREFERRED_DESCRIPTION"
    elif _contains(
        name,
        r"\bnotes? due\b|\bsenior notes?\b|\bsubordinated notes?\b|"
        r"\bdebentures?\b|\bbonds? due\b",
    ):
        instrument_type, reason = "debt", "EXPLICIT_DEBT_DESCRIPTION"
    elif _contains(name, r"\bcommon shares? of beneficial interest\b") and not _contains(
        name, r"\(reit\)|\breal estate investment trust\b"
    ):
        instrument_type, reason = (
            "unknown",
            "BENEFICIAL_INTEREST_REQUIRES_ISSUER_CLASSIFICATION",
        )
    elif _contains(name, r"\bcommon stock\b"):
        instrument_type, reason = "common_stock", "EXPLICIT_COMMON_STOCK_DESCRIPTION"
    elif _contains(name, r"\bordinary shares?\b"):
        instrument_type, reason = "ordinary_shares", "EXPLICIT_ORDINARY_SHARE_DESCRIPTION"
    elif _contains(name, r"\bcommon shares?\b"):
        instrument_type, reason = "common_shares", "EXPLICIT_COMMON_SHARE_DESCRIPTION"

    primary_stock_eligible = instrument_type in {
        "common_stock", "common_shares", "ordinary_shares", "adr_ads"
    }
    possible_spac_common = bool(
        primary_stock_eligible
        and _contains(name, r"\bacquisition (corp|corporation|company)\b")
    )
    return {
        "instrument_type": instrument_type,
        "primary_stock_eligible": primary_stock_eligible,
        "classification_reason": reason,
        "possible_spac_common": possible_spac_common,
    }


def parse_directory(content: bytes) -> list[dict[str, object]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Nasdaq Trader symbol directory is not valid UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    required = {"Symbol", "Security Name", "Listing Exchange", "ETF", "Test Issue"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        missing = sorted(required - set(reader.fieldnames or []))
        raise ValueError(f"Symbol directory is missing fields: {', '.join(missing)}")
    records: list[dict[str, object]] = []
    for row in reader:
        symbol = str(row.get("Symbol") or "").strip().upper()
        if not symbol or symbol == "FILE CREATION TIME":
            continue
        classification = classify_security(row)
        records.append({
            "source_symbol": symbol,
            "aliases": _aliases(row),
            "security_name": str(row.get("Security Name") or "").strip(),
            "listing_exchange_code": str(row.get("Listing Exchange") or "").strip(),
            "market_category": str(row.get("Market Category") or "").strip(),
            "etf_flag": str(row.get("ETF") or "").strip().upper(),
            "test_issue_flag": str(row.get("Test Issue") or "").strip().upper(),
            "financial_status": str(row.get("Financial Status") or "").strip(),
            "next_shares_flag": str(row.get("NextShares") or "").strip().upper(),
            **classification,
        })
    if not records:
        raise ValueError("Symbol directory contained no securities")
    records.sort(key=lambda item: str(item["source_symbol"]))
    return records


def build_payload(content: bytes, source_url: str) -> dict[str, object]:
    records = parse_directory(content)
    counts = Counter(str(record["instrument_type"]) for record in records)
    return {
        "security_master_version": MASTER_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "research_only": True,
        "orders_supported": False,
        "classification_policy": (
            "Only explicit common/ordinary/ADR/ADS descriptions are primary-stock eligible; "
            "ETF/test flags and explicit non-stock descriptions are excluded; unresolved types remain unknown."
        ),
        "record_count": len(records),
        "primary_stock_count": sum(bool(record["primary_stock_eligible"]) for record in records),
        "instrument_type_counts": dict(sorted(counts.items())),
        "securities": records,
    }


def _download(url: str, timeout: int) -> bytes:
    request = Request(url, headers={"User-Agent": "gainers-spotting-security-master/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        raise ValueError(f"Nasdaq Trader returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"Nasdaq Trader request failed: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-file", type=Path)
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    try:
        if args.source_file:
            content = args.source_file.read_bytes()
            source = str(args.source_file)
        else:
            content = _download(args.source_url, args.timeout)
            source = args.source_url
        payload = build_payload(content, source)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({
        "output": str(args.output),
        "records": payload["record_count"],
        "primary_stocks": payload["primary_stock_count"],
        "source_sha256": payload["source_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
