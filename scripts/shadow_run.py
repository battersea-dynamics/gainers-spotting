#!/usr/bin/env python3
"""CLI for one shadow-mode job: python scripts/shadow_run.py --job rank --date 2026-10-23 --cutoff 09:30."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shadow_live  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, choices=shadow_live.JOBS)
    parser.add_argument("--date", default="", help="ET session date; default today in America/New_York")
    parser.add_argument("--cutoff", default="", help="HH:MM ET (snapshot/rank only)")
    parser.add_argument("--data-root", type=Path, default=Path("shadow-data"))
    parser.add_argument("--force", action="store_true", help="write .rerun-<id> copies instead of skipping")
    parser.add_argument("--limit", type=int, help="debug: only the first N primary symbols")
    parser.add_argument("--no-wait", action="store_true", help="fail instead of sleeping for the SIP delay")
    parser.add_argument("--top-n", type=int, default=shadow_live.DEFAULTS["top_n"])
    parser.add_argument("--random-n", type=int, default=shadow_live.DEFAULTS["random_n"])
    args = parser.parse_args()
    day = args.date or datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    if args.job in ("snapshot", "rank") and not args.cutoff:
        parser.error("--cutoff is required for snapshot/rank")
    ctx = shadow_live.RunContext(args.job, day, args.cutoff or None, args.data_root, force=args.force,
                                 limit=args.limit, no_wait=args.no_wait,
                                 cfg={"top_n": args.top_n, "random_n": args.random_n})
    log = shadow_live.run(ctx)
    print(json.dumps({k: log[k] for k in ("job", "day", "cutoff", "status", "flags") if k in log}
                     | {"details": log.get("details"), "error": log.get("error")}, indent=2, default=str))
    return 1 if log["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
