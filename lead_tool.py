#!/usr/bin/env python3
"""
lead_tool.py — National Insulation Contractor Database Builder
==============================================================

Searches the Google Places API (New) for insulation contractors across every
US zip code and stores results in a local SQLite database with full resume
support, monthly quota enforcement, and per-state / master CSV export.

QUICK START
-----------
1.  Copy .env.example → .env and add your Google Places API key.
2.  pip install -r requirements.txt
3.  python lead_tool.py --state illinois
    python lead_tool.py --state all --priority illinois,texas,florida
    python lead_tool.py --state all --allow-paid --max-spend 50
    python lead_tool.py --export-only

COST MODEL (Places API New, 2025)
----------------------------------
  Free tier : 5,000 Text Search requests / month (resets 1st of each month)
  Paid tier : ~$32 per 1,000 requests after the free tier is exhausted
  Each zip  : 1–3 API calls (1 call per page of 20 results, max 60 results)

The tool stops automatically when the free quota is exhausted and resumes
next month from where it left off.  Pass --allow-paid --max-spend <dollars>
to continue into the paid tier with a hard dollar cap.

See setup_guide.md for full Google Cloud setup instructions.
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Logging  (must be set up before importing lib modules that log at import)
# ---------------------------------------------------------------------------

def _setup_logging() -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console: INFO and above
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # File: DEBUG and above (full trace for debugging)
    fh = logging.FileHandler("lead_tool.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Silence noisy third-party loggers
    for noisy in ("urllib3", "requests", "uszipcode"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger(__name__)


log = _setup_logging()


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lead_tool.py",
        description=(
            "Build a national insulation contractor database "
            "using the Google Places API (New)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python lead_tool.py --state illinois
  python lead_tool.py --state all --priority illinois,texas,florida
  python lead_tool.py --state all --refresh-days 180
  python lead_tool.py --state all --allow-paid --max-spend 50
  python lead_tool.py --export-only
  python lead_tool.py --export-only --state illinois
""",
    )

    # -- What to search --
    parser.add_argument(
        "--state",
        default="all",
        metavar="STATE",
        help=(
            "State name or two-letter abbreviation to search, "
            "or 'all' for all 50 states + DC (default: all)"
        ),
    )
    parser.add_argument(
        "--priority",
        default="",
        metavar="STATES",
        help=(
            "Comma-separated states to search first when --state all is used "
            "(e.g. illinois,texas,florida)"
        ),
    )

    # -- Cache / staleness --
    parser.add_argument(
        "--refresh-days",
        type=int,
        default=180,
        metavar="N",
        help=(
            "Re-search zip codes that were last searched more than N days ago "
            "(default: 180, use 0 to skip all previously searched zips)"
        ),
    )

    # -- Cost controls --
    parser.add_argument(
        "--allow-paid",
        action="store_true",
        help="Allow searches beyond the 5,000 free-tier monthly quota (charges apply)",
    )
    parser.add_argument(
        "--max-spend",
        type=float,
        default=50.0,
        metavar="DOLLARS",
        help=(
            "Hard dollar cap on paid API calls when --allow-paid is set "
            "(default: $50.00)"
        ),
    )

    # -- Output --
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Skip all API calls and just export CSVs from the current database",
    )
    parser.add_argument(
        "--export-dir",
        default="exports",
        metavar="DIR",
        help="Directory for exported CSV files (default: exports/)",
    )

    # -- Advanced --
    parser.add_argument(
        "--db-path",
        default="insulation_leads.db",
        metavar="PATH",
        help="Path to the SQLite cache database (default: insulation_leads.db)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.3,
        metavar="SECONDS",
        help="Seconds to pause between API requests (default: 0.3)",
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=25_000,
        metavar="METERS",
        help=(
            "Search radius in metres around each zip code centre "
            "(default: 25000 = 25 km ≈ 15 miles)"
        ),
    )
    parser.add_argument(
        "--min-population",
        type=int,
        default=500,
        metavar="N",
        help="Minimum zip code population to include (default: 500)",
    )

    return parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_api_key() -> str:
    load_dotenv()
    key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not key:
        log.error(
            "GOOGLE_PLACES_API_KEY is not set.\n"
            "  1. Copy .env.example → .env\n"
            "  2. Replace the placeholder with your real API key.\n"
            "  See setup_guide.md for full instructions."
        )
        sys.exit(1)
    return key


def _fmt_cost(dollars: float) -> str:
    return f"${dollars:.2f}"


def _print_quota_banner(stats: dict) -> None:
    month_name = datetime(stats["year"], stats["month"], 1).strftime("%B %Y")
    free_pct = min(100, stats["free_used"] * 100 // stats["free_limit"])
    paid_info = ""
    if stats["allow_paid"]:
        paid_info = (
            f" | Paid: {stats['paid_used']:,} calls "
            f"({_fmt_cost(stats['estimated_cost'])} / "
            f"{_fmt_cost(stats['max_spend'])} cap, "
            f"{_fmt_cost(stats['spend_remaining'])} remaining)"
        )
    log.info(
        f"[QUOTA {month_name}]  "
        f"Free: {stats['free_used']:,} / {stats['free_limit']:,} "
        f"({free_pct}% used, {stats['free_remaining']:,} remaining)"
        + paid_info
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _build_parser().parse_args()

    # Lazy imports keep startup fast and avoid issues if lib/ isn't importable
    from lib.database import (
        init_db,
        populate_zipcodes,
        count_zips_by_state,
        get_pending_zips,
        mark_zip_searched,
        upsert_lead,
        get_lead_count,
        get_lead_count_by_state,
    )
    from lib.zipcode_data import (
        normalize_state,
        get_ordered_states,
        load_zipcodes,
        STATE_NAMES,
    )
    from lib.quota import QuotaManager
    from lib.api_client import PlacesAPIClient
    from lib.exporter import export_all

    db_path = args.db_path

    log.info("=" * 65)
    log.info("  lead_tool.py — Insulation Contractor Database Builder")
    log.info("=" * 65)
    log.info(f"Database : {Path(db_path).resolve()}")
    log.info(f"Export   : {Path(args.export_dir).resolve()}")

    # ------------------------------------------------------------------ #
    # Initialise database                                                  #
    # ------------------------------------------------------------------ #
    init_db(db_path)

    # ------------------------------------------------------------------ #
    # Resolve which state(s) to operate on                                #
    # ------------------------------------------------------------------ #
    state_arg = args.state.strip().lower()
    priority_raw = [s.strip() for s in args.priority.split(",") if s.strip()]

    if state_arg == "all":
        priority_states = [s for s in priority_raw if normalize_state(s)]
        invalid_priority = [s for s in priority_raw if not normalize_state(s)]
        if invalid_priority:
            log.warning(f"Unrecognised priority state(s) ignored: {invalid_priority}")
        target_states = get_ordered_states(priority_states)
        log.info(
            f"Scope    : all {len(target_states)} states"
            + (f" | Priority: {', '.join(priority_states)}" if priority_states else "")
        )
    else:
        norm = normalize_state(state_arg)
        if not norm:
            log.error(
                f"Unknown state: '{args.state}'.\n"
                "Use a full state name (e.g. illinois) or two-letter abbreviation (e.g. IL)."
            )
            sys.exit(1)
        target_states = [norm]
        log.info(f"Scope    : {STATE_NAMES.get(norm, norm)} ({norm})")

    # ------------------------------------------------------------------ #
    # Export-only shortcut                                                 #
    # ------------------------------------------------------------------ #
    if args.export_only:
        log.info("Export-only mode: writing CSVs from existing database …")
        export_states = target_states if state_arg != "all" else None
        exports = export_all(db_path, args.export_dir, export_states)
        n_state_files = len(exports) - 1
        log.info(
            f"Done. {n_state_files} state file(s) + master CSV "
            f"written to {args.export_dir}/"
        )
        return

    # ------------------------------------------------------------------ #
    # Populate zip codes for any states not yet in the database           #
    # ------------------------------------------------------------------ #
    existing_counts = count_zips_by_state(db_path)
    missing_states = [s for s in target_states if existing_counts.get(s, 0) == 0]

    if missing_states:
        log.info(
            f"Loading zip codes for {len(missing_states)} new state(s) "
            f"from uszipcode …"
        )
        zip_list = load_zipcodes(missing_states, min_population=args.min_population)
        inserted = populate_zipcodes(db_path, zip_list)
        log.info(f"Added {inserted:,} new zip codes to the database.")
    else:
        total_zips = sum(existing_counts.get(s, 0) for s in target_states)
        log.info(f"Zip codes already loaded ({total_zips:,} for target states).")

    # ------------------------------------------------------------------ #
    # Determine which zips still need to be searched                      #
    # ------------------------------------------------------------------ #
    pending = get_pending_zips(db_path, target_states, args.refresh_days)

    if not pending:
        log.info(
            "No pending zip codes found. "
            "All target zips have already been searched.\n"
            f"  → Use --refresh-days <N> to re-search zips older than N days.\n"
            f"  → Use --export-only to regenerate CSVs."
        )
        log.info("Exporting current results …")
        export_all(db_path, args.export_dir, target_states if state_arg != "all" else None)
        return

    log.info(f"Pending zip codes : {len(pending):,}")

    # ------------------------------------------------------------------ #
    # Initialise API client and quota manager                              #
    # ------------------------------------------------------------------ #
    api_key = _load_api_key()
    client = PlacesAPIClient(api_key, delay=args.delay)
    quota = QuotaManager(
        db_path,
        allow_paid=args.allow_paid,
        max_spend=args.max_spend,
    )

    _print_quota_banner(quota.get_stats())

    # Pre-flight quota check
    if not quota.can_make_calls(1):
        stats = quota.get_stats()
        log.warning(
            "Monthly free quota is already exhausted "
            f"({stats['free_used']:,}/{stats['free_limit']:,} calls used)."
        )
        if not args.allow_paid:
            log.warning("  → Add --allow-paid --max-spend <dollars> to continue on the paid tier.")
        else:
            log.warning(
                f"  → Max spend of {_fmt_cost(args.max_spend)} already reached "
                f"({_fmt_cost(stats['estimated_cost'])} used)."
            )
        log.info("Exporting current results …")
        export_all(db_path, args.export_dir, target_states if state_arg != "all" else None)
        return

    # ------------------------------------------------------------------ #
    # Main search loop                                                     #
    # ------------------------------------------------------------------ #
    total_leads = get_lead_count(db_path)
    new_leads_run = 0
    zips_processed = 0
    current_state: str = ""

    log.info("")
    log.info("Starting search. Press Ctrl+C to stop — progress is saved after every zip.")
    log.info("")

    try:
        for idx, zip_info in enumerate(pending):
            zip_code = zip_info["zip_code"]
            state    = zip_info["state"]
            lat      = zip_info["latitude"]
            lng      = zip_info["longitude"]

            # -- State transition header ----------------------------------
            if state != current_state:
                current_state = state
                state_zips_remaining = sum(
                    1 for z in pending[idx:] if z["state"] == state
                )
                state_leads_so_far = get_lead_count_by_state(db_path, state)
                log.info(
                    f"\n─── {STATE_NAMES.get(state, state)} ({state})  "
                    f"│ {state_zips_remaining} zip(s) remaining  "
                    f"│ {state_leads_so_far:,} leads so far ───"
                )

            # -- Quota check before each call ----------------------------
            if not quota.can_make_calls(1):
                stats = quota.get_stats()
                log.warning("")
                log.warning("Quota limit reached — stopping search loop.")
                if args.allow_paid:
                    log.warning(
                        f"  Max spend of {_fmt_cost(args.max_spend)} reached "
                        f"({_fmt_cost(stats['estimated_cost'])} used)."
                    )
                else:
                    log.warning(
                        f"  Free tier exhausted "
                        f"({stats['free_used']:,}/{stats['free_limit']:,} calls)."
                    )
                    log.warning(
                        "  Add --allow-paid --max-spend <dollars> to continue, "
                        "or re-run next month."
                    )
                break

            # -- API call ------------------------------------------------
            try:
                places, call_count = client.search_zip(
                    zip_code, lat, lng, radius_meters=args.radius
                )
            except PermissionError as exc:
                log.error(str(exc))
                sys.exit(1)
            except Exception as exc:
                log.warning(f"  [{zip_code}] API error: {exc}")
                mark_zip_searched(db_path, zip_code, 0, error=str(exc))
                continue

            # -- Record quota usage --------------------------------------
            quota.record_calls(call_count)

            # -- Store unique leads in database --------------------------
            new_for_zip = 0
            for place in places:
                if upsert_lead(db_path, place):
                    new_for_zip += 1
                    new_leads_run += 1
                    total_leads += 1

            mark_zip_searched(db_path, zip_code, len(places))
            zips_processed += 1

            # -- Progress line -------------------------------------------
            stats = quota.get_stats()
            zips_left = len(pending) - zips_processed
            log.info(
                f"  [{zip_code}] {state}  "
                f"│ +{new_for_zip:2d} new  "
                f"│ total {total_leads:,}  "
                f"│ free left {stats['free_remaining']:,}  "
                + (
                    f"│ cost {_fmt_cost(stats['estimated_cost'])}  "
                    if args.allow_paid else ""
                )
                + f"│ zips left {zips_left:,}"
            )

    except KeyboardInterrupt:
        log.info("")
        log.info("Interrupted by user — saving progress and exporting.")

    # ------------------------------------------------------------------ #
    # Final summary and CSV export                                         #
    # ------------------------------------------------------------------ #
    log.info("")
    log.info("=" * 65)
    log.info(f"  Run complete")
    log.info(f"  Zips searched this run : {zips_processed:,}")
    log.info(f"  New leads this run     : {new_leads_run:,}")
    log.info(f"  Total leads in DB      : {total_leads:,}")
    _print_quota_banner(quota.get_stats())
    log.info("")
    log.info("Exporting CSVs …")

    export_states = target_states if state_arg != "all" else None
    exports = export_all(db_path, args.export_dir, export_states)

    n_state_files = len(exports) - 1
    log.info(
        f"Exported {n_state_files} state file(s) + master CSV "
        f"to {args.export_dir}/"
    )
    log.info("=" * 65)


if __name__ == "__main__":
    main()
