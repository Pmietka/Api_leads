"""
grid_search.py — Grid-based insulation contractor lead scraper.

QUICK START
-----------
    python grid_search.py --dry-run                  # preview grid point counts
    python grid_search.py --states MA                # run one state
    python grid_search.py                            # run all 5 target states
    python grid_search.py --export-only              # export CSVs without API calls

HOW IT WORKS
------------
Instead of searching by ZIP code (which introduces ranking bias), this tool
lays a uniform lat/lng grid over each state and searches around every grid
point.  Urban metro areas get a denser sub-grid.  Three queries are run per
point ("insulation contractor", "insulation", "spray foam insulation"), each
paginated up to 3 pages × 20 results.  Results are deduplicated globally by
Google Place ID and stored in SQLite.

TARGET STATES
-------------
MA, CT, NJ, PA, MI — Northeast/Midwest states with cold climates, old
housing stock, and strong insulation demand.

ESTIMATED COST
--------------
~3,000–4,000 grid points × up to 9 API calls = ~27,000–36,000 calls max.
Realistic cost with early pagination stops: ~20,000–25,000 calls.
Fits within or near Google's $200/month free-tier credit.
"""

import argparse
import logging
import os
import sys
import time
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRID_SEARCH_QUERIES = [
    "insulation contractor",
    "insulation",
    "spray foam insulation",
]

# Bounding boxes: (south_lat, north_lat, west_lng, east_lng)
STATE_BBOXES: Dict[str, Dict[str, float]] = {
    "MA": {"south": 41.23, "north": 42.89, "west": -73.51, "east": -69.93},
    "CT": {"south": 40.95, "north": 42.05, "west": -73.73, "east": -71.79},
    "NJ": {"south": 38.93, "north": 41.36, "west": -75.56, "east": -73.89},
    "PA": {"south": 39.72, "north": 42.27, "west": -80.52, "east": -74.69},
    "MI": {"south": 41.70, "north": 47.47, "west": -90.42, "east": -82.41},
}

# Metro centers: (lat, lng, radius_miles)
METRO_CENTERS: Dict[str, List[Tuple[float, float, float]]] = {
    "MA": [(42.36, -71.06, 30), (42.27, -71.80, 20)],          # Boston, Worcester
    "CT": [(41.76, -72.68, 20), (41.31, -72.93, 20)],          # Hartford, New Haven
    "NJ": [(40.73, -74.17, 30), (39.95, -75.17, 25)],          # Newark, Camden/Philly border
    "PA": [(39.95, -75.17, 40), (40.44, -79.99, 35)],          # Philadelphia, Pittsburgh
    "MI": [(42.33, -83.05, 40), (42.96, -85.67, 20)],          # Detroit, Grand Rapids
}

DEFAULT_STATES = list(STATE_BBOXES.keys())
DEFAULT_DB_PATH = "grid_leads.db"
DEFAULT_EXPORT_DIR = "exports"
DEFAULT_SPACING_MILES = 20.0
DEFAULT_DENSE_SPACING_MILES = 5.0
DEFAULT_RADIUS_METERS = 20_000
DEFAULT_DENSE_RADIUS_METERS = 10_000
DEFAULT_DELAY = 0.3

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(log_file: str = "grid_search.log") -> None:
    fmt = "%(asctime)s  %(levelname)-8s  %(message)s"
    logging.basicConfig(
        level=logging.DEBUG,
        format=fmt,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(fmt))
    logging.getLogger().addHandler(console)


# ---------------------------------------------------------------------------
# Grid generation
# ---------------------------------------------------------------------------

def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in miles between two lat/lng points."""
    R = 3_958.8  # Earth radius in miles
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return R * 2 * asin(sqrt(a))


def _is_in_metro(lat: float, lng: float, metros: List[Tuple[float, float, float]]) -> bool:
    """Return True if the point falls within any metro zone."""
    return any(_haversine_miles(lat, lng, mlat, mlng) <= radius
               for mlat, mlng, radius in metros)


def generate_grid_points(
    state: str,
    spacing_miles: float = DEFAULT_SPACING_MILES,
    dense_spacing_miles: float = DEFAULT_DENSE_SPACING_MILES,
) -> List[Dict]:
    """
    Generate lat/lng grid points covering a state.

    Base grid uses `spacing_miles`.  Urban metro zones (defined in
    METRO_CENTERS) use `dense_spacing_miles` for better coverage.

    Returns a list of dicts with keys:
        point_id, state, latitude, longitude, is_dense
    """
    bbox = STATE_BBOXES[state]
    metros = METRO_CENTERS.get(state, [])
    points: Dict[str, Dict] = {}  # keyed by point_id to deduplicate

    # ----- Pass 1: base grid (skip points that will be covered by dense grid) -----
    lat = bbox["south"]
    while lat <= bbox["north"]:
        lng_step = spacing_miles / (69.0 * max(cos(radians(lat)), 0.01))
        lng = bbox["west"]
        while lng <= bbox["east"]:
            if not _is_in_metro(lat, lng, metros):
                pid = f"{state}_{lat:.4f}_{lng:.4f}"
                points[pid] = {
                    "point_id": pid,
                    "state": state,
                    "latitude": round(lat, 4),
                    "longitude": round(lng, 4),
                    "is_dense": 0,
                }
            lng += lng_step
        lat += spacing_miles / 69.0

    # ----- Pass 2: dense grid over each metro zone -----
    for mlat, mlng, radius_mi in metros:
        lat_span = radius_mi / 69.0
        lat = mlat - lat_span
        while lat <= mlat + lat_span:
            lng_step = dense_spacing_miles / (69.0 * max(cos(radians(lat)), 0.01))
            lng_span = radius_mi / (69.0 * max(cos(radians(lat)), 0.01))
            lng = mlng - lng_span
            while lng <= mlng + lng_span:
                if _haversine_miles(lat, lng, mlat, mlng) <= radius_mi:
                    pid = f"{state}_{lat:.4f}_{lng:.4f}"
                    points[pid] = {
                        "point_id": pid,
                        "state": state,
                        "latitude": round(lat, 4),
                        "longitude": round(lng, 4),
                        "is_dense": 1,
                    }
                lng += lng_step
            lat += dense_spacing_miles / 69.0

    return list(points.values())


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Grid-based insulation contractor lead scraper.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--states",
        default=",".join(DEFAULT_STATES),
        help=f"Comma-separated state abbreviations to search "
             f"(default: {','.join(DEFAULT_STATES)})",
    )
    p.add_argument(
        "--spacing", type=float, default=DEFAULT_SPACING_MILES, metavar="MILES",
        help=f"Base grid spacing in miles (default: {DEFAULT_SPACING_MILES})",
    )
    p.add_argument(
        "--dense-spacing", type=float, default=DEFAULT_DENSE_SPACING_MILES,
        metavar="MILES",
        help=f"Urban grid spacing in miles (default: {DEFAULT_DENSE_SPACING_MILES})",
    )
    p.add_argument(
        "--radius", type=float, default=DEFAULT_RADIUS_METERS, metavar="METERS",
        help=f"Search radius for base grid points in meters (default: {DEFAULT_RADIUS_METERS})",
    )
    p.add_argument(
        "--dense-radius", type=float, default=DEFAULT_DENSE_RADIUS_METERS, metavar="METERS",
        help=f"Search radius for urban/dense grid points in meters (default: {DEFAULT_DENSE_RADIUS_METERS})",
    )
    p.add_argument(
        "--refresh-days", type=int, default=0, metavar="N",
        help="Re-search grid points older than N days (default: 0 = never)",
    )
    p.add_argument(
        "--export-only", action="store_true",
        help="Skip API calls and export CSVs from existing database",
    )
    p.add_argument(
        "--export-dir", default=DEFAULT_EXPORT_DIR, metavar="DIR",
        help=f"Output directory for CSV files (default: {DEFAULT_EXPORT_DIR})",
    )
    p.add_argument(
        "--db-path", default=DEFAULT_DB_PATH, metavar="PATH",
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    p.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY, metavar="SECONDS",
        help=f"Polite delay between API queries in seconds (default: {DEFAULT_DELAY})",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print grid point counts per state and exit without making API calls",
    )
    p.add_argument(
        "--state-summary", action="store_true",
        help="Print lead counts per state from the database and exit",
    )
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()
    _setup_logging()

    args = _build_parser().parse_args()
    states = [s.strip().upper() for s in args.states.split(",") if s.strip()]

    # Validate states
    unknown = [s for s in states if s not in STATE_BBOXES]
    if unknown:
        log.error(f"Unknown state(s): {', '.join(unknown)}. "
                  f"Supported: {', '.join(STATE_BBOXES)}")
        sys.exit(1)

    # Lazy imports (keep startup fast for --dry-run)
    from lib.database import (
        count_grid_points_by_state,
        get_lead_count_by_state,
        get_pending_grid_points,
        init_grid_db,
        mark_grid_point_searched,
        populate_grid_points,
        upsert_lead,
        increment_api_calls,
    )
    from lib.exporter import export_all

    # ----------------------------------------------------------------
    # --state-summary: just print DB stats and exit
    # ----------------------------------------------------------------
    if args.state_summary:
        init_grid_db(args.db_path)
        print(f"\n{'State':<6}  {'Grid Points':>12}  {'Leads':>8}")
        print("-" * 32)
        gp = count_grid_points_by_state(args.db_path)
        for s in states:
            leads = get_lead_count_by_state(args.db_path, s)
            print(f"{s:<6}  {gp.get(s, 0):>12,}  {leads:>8,}")
        print()
        return

    # ----------------------------------------------------------------
    # Generate grid points for all target states
    # ----------------------------------------------------------------
    all_points: List[Dict] = []
    for state in states:
        pts = generate_grid_points(state, args.spacing, args.dense_spacing)
        all_points.extend(pts)

    # ----------------------------------------------------------------
    # --dry-run: print counts and exit
    # ----------------------------------------------------------------
    if args.dry_run:
        print(f"\n{'State':<6}  {'Grid Points':>12}  {'Est. API Calls (max)':>22}")
        print("-" * 44)
        for state in states:
            pts = [p for p in all_points if p["state"] == state]
            est = len(pts) * len(GRID_SEARCH_QUERIES) * 3  # 3 pages worst-case
            print(f"{state:<6}  {len(pts):>12,}  {est:>22,}")
        total = len(all_points)
        est_total = total * len(GRID_SEARCH_QUERIES) * 3
        print("-" * 44)
        print(f"{'TOTAL':<6}  {total:>12,}  {est_total:>22,}")
        print(f"\nBase:  {args.spacing} mi spacing, {args.radius:,.0f} m radius")
        print(f"Dense: {args.dense_spacing} mi spacing, {args.dense_radius:,.0f} m radius\n")
        return

    # ----------------------------------------------------------------
    # Initialize DB and populate grid points
    # ----------------------------------------------------------------
    init_grid_db(args.db_path)
    new_pts = populate_grid_points(args.db_path, all_points)
    if new_pts:
        log.info(f"Added {new_pts:,} new grid points to database.")

    # ----------------------------------------------------------------
    # --export-only: skip API, just export
    # ----------------------------------------------------------------
    if args.export_only:
        export_all(args.db_path, args.export_dir, states)
        return

    # ----------------------------------------------------------------
    # Load API key
    # ----------------------------------------------------------------
    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        log.error(
            "GOOGLE_PLACES_API_KEY not set.  "
            "Add it to your .env file or set it as an environment variable."
        )
        sys.exit(1)

    from lib.api_client import PlacesAPIClient
    client = PlacesAPIClient(api_key, delay=args.delay)

    # ----------------------------------------------------------------
    # Main search loop
    # ----------------------------------------------------------------
    pending = get_pending_grid_points(args.db_path, states, args.refresh_days)

    if not pending:
        log.info("No pending grid points found.  "
                 "Use --refresh-days N to re-search completed points.")
        export_all(args.db_path, args.export_dir, states)
        return

    log.info(
        f"Starting grid search: {len(pending):,} pending points across "
        f"{', '.join(states)}"
    )

    current_state = None
    state_new = 0
    state_pts_done = 0
    total_new = 0
    total_calls = 0

    import datetime
    year = datetime.datetime.now().year
    month = datetime.datetime.now().month
    free_monthly_limit = 5_000

    try:
        for i, point in enumerate(pending, 1):
            state = point["state"]

            # State transition header
            if state != current_state:
                if current_state is not None:
                    log.info(
                        f"  [{current_state}] done — "
                        f"{state_pts_done:,} points, {state_new:,} new leads"
                    )
                current_state = state
                state_new = 0
                state_pts_done = 0
                total_pts = sum(1 for p in all_points if p["state"] == state)
                log.info(f"\n{'='*60}")
                log.info(f"  State: {state}  ({total_pts:,} total grid points)")
                log.info(f"{'='*60}")

            try:
                radius = args.dense_radius if point["is_dense"] else args.radius
                places, call_count = client.search_grid_point(
                    point["point_id"],
                    point["latitude"],
                    point["longitude"],
                    queries=GRID_SEARCH_QUERIES,
                    radius_meters=radius,
                )
            except PermissionError as exc:
                log.error(f"Permission error — aborting:\n{exc}")
                sys.exit(1)
            except Exception as exc:
                log.warning(f"  [{point['point_id']}] error: {exc}")
                mark_grid_point_searched(args.db_path, point["point_id"], 0, 0, error=str(exc))
                continue

            # Persist leads
            new_for_point = 0
            for place in places:
                if upsert_lead(args.db_path, place):
                    new_for_point += 1

            mark_grid_point_searched(
                args.db_path, point["point_id"], len(places), new_for_point
            )

            # Track API quota
            total_calls += call_count
            free_this = min(call_count, max(0, free_monthly_limit - total_calls + call_count))
            paid_this = call_count - free_this
            increment_api_calls(args.db_path, year, month, free_this, paid_this)

            state_new += new_for_point
            state_pts_done += 1
            total_new += new_for_point

            log.info(
                f"  [{i:>5}/{len(pending)}] {point['point_id']}  "
                f"results={len(places)}  new={new_for_point}  "
                f"api_calls={call_count}  total_new={total_new:,}"
            )

    except KeyboardInterrupt:
        log.info("\nInterrupted — progress saved.  Re-run to resume.")

    # ----------------------------------------------------------------
    # Final state summary
    # ----------------------------------------------------------------
    if current_state:
        log.info(
            f"  [{current_state}] done — "
            f"{state_pts_done:,} points, {state_new:,} new leads"
        )

    log.info(
        f"\nSearch complete — {total_new:,} new leads added, "
        f"{total_calls:,} API calls made."
    )

    # ----------------------------------------------------------------
    # Export CSVs
    # ----------------------------------------------------------------
    export_all(args.db_path, args.export_dir, states)


if __name__ == "__main__":
    main()
