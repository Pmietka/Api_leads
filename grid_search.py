"""
grid_search.py — Grid-based insulation contractor lead scraper.

QUICK START
-----------
    python grid_search.py --dry-run                  # preview grid point counts
    python grid_search.py --states MA                # run one state
    python grid_search.py --states MA,CT,NJ,PA,MI   # run multiple states
    python grid_search.py                            # run all default states
    python grid_search.py --export-only              # export CSVs without API calls

HOW IT WORKS
------------
Instead of searching by ZIP code (which introduces ranking bias), this tool
lays a uniform lat/lng grid over each state and searches around every grid
point.  Urban metro areas get a denser sub-grid.  Three queries are run per
point ("insulation contractor", "insulation", "spray foam insulation"), each
paginated up to 3 pages × 20 results.  Results are deduplicated globally by
Google Place ID and stored in SQLite.

SUPPORTED STATES
----------------
All 50 US states plus DC are supported.  Pass any combination via --states.
Default states: MA, CT, NJ, PA, MI.

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

# Bounding boxes for all 50 US states + DC
STATE_BBOXES: Dict[str, Dict[str, float]] = {
    "AL": {"south": 30.14, "north": 35.01, "west": -88.47, "east": -84.89},
    "AK": {"south": 54.56, "north": 71.54, "west": -168.00, "east": -129.98},
    "AZ": {"south": 31.33, "north": 37.00, "west": -114.82, "east": -109.05},
    "AR": {"south": 33.00, "north": 36.50, "west": -94.62, "east": -89.64},
    "CA": {"south": 32.53, "north": 42.01, "west": -124.48, "east": -114.13},
    "CO": {"south": 36.99, "north": 41.00, "west": -109.06, "east": -102.04},
    "CT": {"south": 40.95, "north": 42.05, "west": -73.73, "east": -71.79},
    "DC": {"south": 38.79, "north": 38.99, "west": -77.12, "east": -76.91},
    "DE": {"south": 38.45, "north": 39.84, "west": -75.79, "east": -75.05},
    "FL": {"south": 24.52, "north": 31.00, "west": -87.63, "east": -80.03},
    "GA": {"south": 30.36, "north": 35.00, "west": -85.61, "east": -80.84},
    "HI": {"south": 18.91, "north": 22.24, "west": -160.25, "east": -154.81},
    "ID": {"south": 41.99, "north": 49.00, "west": -117.24, "east": -111.04},
    "IL": {"south": 36.97, "north": 42.51, "west": -91.51, "east": -87.02},
    "IN": {"south": 37.77, "north": 41.76, "west": -88.10, "east": -84.78},
    "IA": {"south": 40.38, "north": 43.50, "west": -96.64, "east": -90.14},
    "KS": {"south": 36.99, "north": 40.00, "west": -102.05, "east": -94.59},
    "KY": {"south": 36.50, "north": 39.15, "west": -89.57, "east": -81.96},
    "LA": {"south": 28.93, "north": 33.02, "west": -94.04, "east": -88.82},
    "ME": {"south": 43.06, "north": 47.46, "west": -71.08, "east": -66.95},
    "MD": {"south": 37.91, "north": 39.72, "west": -79.49, "east": -75.05},
    "MA": {"south": 41.23, "north": 42.89, "west": -73.51, "east": -69.93},
    "MI": {"south": 41.70, "north": 47.47, "west": -90.42, "east": -82.41},
    "MN": {"south": 43.50, "north": 49.38, "west": -97.24, "east": -89.49},
    "MS": {"south": 30.17, "north": 35.00, "west": -91.65, "east": -88.10},
    "MO": {"south": 35.99, "north": 40.61, "west": -95.77, "east": -89.10},
    "MT": {"south": 44.36, "north": 49.00, "west": -116.05, "east": -104.04},
    "NE": {"south": 40.00, "north": 43.00, "west": -104.05, "east": -95.31},
    "NV": {"south": 35.00, "north": 42.00, "west": -120.01, "east": -114.04},
    "NH": {"south": 42.70, "north": 45.31, "west": -72.56, "east": -70.70},
    "NJ": {"south": 38.93, "north": 41.36, "west": -75.56, "east": -73.89},
    "NM": {"south": 31.33, "north": 37.00, "west": -109.05, "east": -103.00},
    "NY": {"south": 40.50, "north": 45.01, "west": -79.76, "east": -71.86},
    "NC": {"south": 33.84, "north": 36.59, "west": -84.32, "east": -75.46},
    "ND": {"south": 45.94, "north": 49.00, "west": -104.05, "east": -96.55},
    "OH": {"south": 38.40, "north": 42.33, "west": -84.82, "east": -80.52},
    "OK": {"south": 33.62, "north": 37.00, "west": -103.00, "east": -94.43},
    "OR": {"south": 41.99, "north": 46.24, "west": -124.57, "east": -116.46},
    "PA": {"south": 39.72, "north": 42.27, "west": -80.52, "east": -74.69},
    "RI": {"south": 41.15, "north": 42.02, "west": -71.91, "east": -71.12},
    "SC": {"south": 32.03, "north": 35.21, "west": -83.35, "east": -78.55},
    "SD": {"south": 42.48, "north": 45.94, "west": -104.06, "east": -96.44},
    "TN": {"south": 34.98, "north": 36.68, "west": -90.31, "east": -81.65},
    "TX": {"south": 25.84, "north": 36.50, "west": -106.65, "east": -93.51},
    "UT": {"south": 37.00, "north": 42.00, "west": -114.05, "east": -109.04},
    "VT": {"south": 42.73, "north": 45.02, "west": -73.44, "east": -71.46},
    "VA": {"south": 36.54, "north": 39.47, "west": -83.68, "east": -75.24},
    "WA": {"south": 45.54, "north": 49.00, "west": -124.77, "east": -116.92},
    "WV": {"south": 37.20, "north": 40.64, "west": -82.64, "east": -77.72},
    "WI": {"south": 42.49, "north": 47.31, "west": -92.89, "east": -86.25},
    "WY": {"south": 40.99, "north": 45.01, "west": -111.06, "east": -104.05},
}

# Metro centers: (lat, lng, radius_miles) — major urban zones get denser grids
METRO_CENTERS: Dict[str, List[Tuple[float, float, float]]] = {
    "AL": [(33.52, -86.80, 25), (34.73, -86.59, 20)],          # Birmingham, Huntsville
    "AK": [(61.22, -149.90, 25)],                               # Anchorage
    "AZ": [(33.45, -112.07, 40), (32.22, -110.97, 25)],        # Phoenix, Tucson
    "AR": [(34.75, -92.29, 20), (36.08, -94.16, 15)],          # Little Rock, Fayetteville
    "CA": [(34.05, -118.24, 40), (37.77, -122.42, 30),         # LA, SF
           (32.72, -117.16, 30), (38.58, -121.49, 25)],        # San Diego, Sacramento
    "CO": [(39.74, -104.99, 35), (38.83, -104.82, 20)],        # Denver, Colorado Springs
    "CT": [(41.76, -72.68, 20), (41.31, -72.93, 20)],          # Hartford, New Haven
    "DC": [(38.91, -77.02, 20)],                                # Washington DC
    "DE": [(39.74, -75.55, 15)],                                # Wilmington
    "FL": [(25.77, -80.19, 35), (28.54, -81.38, 30),           # Miami, Orlando
           (27.95, -82.46, 30), (30.33, -81.66, 25)],          # Tampa, Jacksonville
    "GA": [(33.75, -84.39, 40), (32.08, -81.10, 15)],          # Atlanta, Savannah
    "HI": [(21.31, -157.86, 20)],                               # Honolulu
    "ID": [(43.62, -116.20, 20), (47.66, -117.43, 15)],        # Boise, Coeur d'Alene
    "IL": [(41.85, -87.65, 40), (39.80, -89.64, 15)],          # Chicago, Springfield
    "IN": [(39.77, -86.16, 30), (41.08, -85.14, 15)],          # Indianapolis, Fort Wayne
    "IA": [(41.60, -93.61, 20), (42.01, -91.64, 15)],          # Des Moines, Cedar Rapids
    "KS": [(37.69, -97.34, 25), (39.10, -94.63, 25)],          # Wichita, Kansas City area
    "KY": [(38.25, -85.76, 30), (38.05, -84.50, 20)],          # Louisville, Lexington
    "LA": [(30.00, -90.07, 30), (30.45, -91.15, 20)],          # New Orleans, Baton Rouge
    "ME": [(43.66, -70.26, 15), (44.80, -68.78, 10)],          # Portland, Bangor
    "MD": [(39.29, -76.61, 30), (38.90, -77.03, 25)],          # Baltimore, DC suburbs
    "MA": [(42.36, -71.06, 30), (42.27, -71.80, 20)],          # Boston, Worcester
    "MI": [(42.33, -83.05, 40), (42.96, -85.67, 20)],          # Detroit, Grand Rapids
    "MN": [(44.98, -93.27, 35), (44.95, -93.09, 25)],          # Minneapolis, St. Paul
    "MS": [(32.30, -90.18, 20), (30.37, -89.09, 15)],          # Jackson, Gulfport
    "MO": [(39.10, -94.58, 30), (38.63, -90.20, 35)],          # Kansas City, St. Louis
    "MT": [(45.78, -108.50, 15), (46.87, -114.02, 10)],        # Billings, Missoula
    "NE": [(41.26, -95.94, 25), (40.81, -96.70, 20)],          # Omaha, Lincoln
    "NV": [(36.17, -115.14, 35), (39.53, -119.81, 20)],        # Las Vegas, Reno
    "NH": [(42.99, -71.46, 15), (43.21, -71.54, 10)],          # Manchester, Concord
    "NJ": [(40.73, -74.17, 30), (39.95, -75.17, 25)],          # Newark, Camden/Philly border
    "NM": [(35.11, -106.61, 25), (35.69, -105.94, 15)],        # Albuquerque, Santa Fe
    "NY": [(40.71, -74.01, 40), (42.89, -78.88, 25),           # NYC, Buffalo
           (43.16, -77.61, 20), (42.65, -73.76, 15)],          # Rochester, Albany
    "NC": [(35.23, -80.84, 35), (35.78, -78.64, 30)],          # Charlotte, Raleigh
    "ND": [(46.88, -96.79, 15), (46.81, -100.78, 10)],         # Fargo, Bismarck
    "OH": [(39.96, -82.99, 35), (41.50, -81.69, 35),           # Columbus, Cleveland
           (39.10, -84.51, 30)],                                # Cincinnati
    "OK": [(35.47, -97.52, 30), (36.15, -95.99, 25)],          # Oklahoma City, Tulsa
    "OR": [(45.52, -122.68, 30), (44.05, -123.09, 15)],        # Portland, Eugene
    "PA": [(39.95, -75.17, 40), (40.44, -79.99, 35)],          # Philadelphia, Pittsburgh
    "RI": [(41.82, -71.42, 15)],                                # Providence
    "SC": [(34.00, -81.03, 20), (32.78, -79.94, 20)],          # Columbia, Charleston
    "SD": [(43.55, -96.73, 15), (44.08, -103.23, 10)],         # Sioux Falls, Rapid City
    "TN": [(36.17, -86.78, 30), (35.15, -90.05, 30),           # Nashville, Memphis
           (35.96, -83.92, 20)],                                # Knoxville
    "TX": [(29.76, -95.37, 40), (32.78, -96.80, 40),           # Houston, Dallas
           (29.42, -98.49, 30), (30.27, -97.74, 30)],          # San Antonio, Austin
    "UT": [(40.76, -111.89, 30), (40.23, -111.69, 20)],        # Salt Lake City, Provo
    "VT": [(44.48, -73.21, 15), (44.26, -72.58, 10)],          # Burlington, Montpelier
    "VA": [(37.54, -77.44, 25), (36.85, -75.98, 25),           # Richmond, Virginia Beach
           (38.90, -77.20, 30)],                                # Northern VA
    "WA": [(47.61, -122.33, 35), (47.66, -117.43, 20)],        # Seattle, Spokane
    "WV": [(38.35, -81.63, 15), (38.42, -82.45, 10)],          # Charleston, Huntington
    "WI": [(43.04, -87.91, 30), (43.07, -89.40, 20)],          # Milwaukee, Madison
    "WY": [(41.14, -104.82, 10), (42.87, -106.31, 10)],        # Cheyenne, Casper
}

DEFAULT_STATES = ["MA", "CT", "NJ", "PA", "MI"]
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
        help=f"Comma-separated state abbreviations to search — any of the 50 US states "
             f"plus DC are supported (default: {','.join(DEFAULT_STATES)})",
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
        supported = ", ".join(sorted(STATE_BBOXES))
        log.error(
            f"Unknown state(s): {', '.join(unknown)}.\n"
            f"Supported states: {supported}"
        )
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
