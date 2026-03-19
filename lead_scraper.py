#!/usr/bin/env python3
"""
=============================================================
  Lead Scraper - Home Insulation Contractor Lead Generation
  Appointly Solutions
=============================================================

GOOGLE CLOUD SETUP INSTRUCTIONS
---------------------------------
1. Go to https://console.cloud.google.com and create (or select) a project.
2. Navigate to "APIs & Services" > "Library".
3. Search for "Places API (New)" and click Enable.
4. Go to "APIs & Services" > "Credentials" > "Create Credentials" > "API Key".
5. (Recommended) Click "Edit API Key", under "API restrictions" select
   "Restrict key" and choose "Places API (New)".
6. Copy your key into the .env file:
       GOOGLE_PLACES_API_KEY=your_key_here

USAGE
------
    python lead_scraper.py --state illinois
    python lead_scraper.py --state "new york"
    python lead_scraper.py --state texas --delay 1.2

OUTPUT
------
    {state}_leads.csv    — Deduplicated CSV of all found businesses
    .progress/           — JSON resume checkpoints (auto-managed)
    data/                — Cached Census Bureau county data (auto-fetched)

NOTES
------
- Results are deduplicated by Google Place ID across all county/query combos.
- Progress is saved after every county so the run can be resumed if interrupted.
- Resume is automatic: re-run the same command and already-processed counties
  are skipped.
- API costs: each text-search call uses one "Basic" Places Text Search SKU.
  A state like Illinois (~102 counties × 8 queries) ≈ 816 calls minimum.
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Search queries sent per county. More queries = more coverage but more API cost.
SEARCH_QUERIES = [
    "home insulation contractor",
    "spray foam insulation",
    "blown in insulation",
    "attic insulation",
    "insulation installation",
    "cellulose insulation",
    "fiberglass batt insulation",
    "insulation company",
]

# Google Places API (New) – Text Search endpoint
PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"

# Fields to retrieve (controls billing tier – these are all "Basic" fields)
FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.nationalPhoneNumber,"
    "places.internationalPhoneNumber,"
    "places.websiteUri,"
    "places.rating,"
    "places.userRatingCount,"
    "nextPageToken"
)

# Census Bureau API for county lookup (no key needed)
CENSUS_API = (
    "https://api.census.gov/data/2020/dec/pl"
    "?get=NAME,GEO_ID&for=county:*&in=state:{fips}"
)

# FIPS codes for all 50 US states + DC
STATE_FIPS = {
    "alabama": "01",        "alaska": "02",         "arizona": "04",
    "arkansas": "05",       "california": "06",     "colorado": "08",
    "connecticut": "09",    "delaware": "10",       "district of columbia": "11",
    "florida": "12",        "georgia": "13",        "hawaii": "15",
    "idaho": "16",          "illinois": "17",       "indiana": "18",
    "iowa": "19",           "kansas": "20",         "kentucky": "21",
    "louisiana": "22",      "maine": "23",          "maryland": "24",
    "massachusetts": "25",  "michigan": "26",       "minnesota": "27",
    "mississippi": "28",    "missouri": "29",       "montana": "30",
    "nebraska": "31",       "nevada": "32",         "new hampshire": "33",
    "new jersey": "34",     "new mexico": "35",     "new york": "36",
    "north carolina": "37", "north dakota": "38",   "ohio": "39",
    "oklahoma": "40",       "oregon": "41",         "pennsylvania": "42",
    "rhode island": "44",   "south carolina": "45", "south dakota": "46",
    "tennessee": "47",      "texas": "48",          "utah": "49",
    "vermont": "50",        "virginia": "51",       "washington": "53",
    "west virginia": "54",  "wisconsin": "55",      "wyoming": "56",
}

# Directories
DATA_DIR = Path("data")
PROGRESS_DIR = Path(".progress")
DATA_DIR.mkdir(exist_ok=True)
PROGRESS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    """Configure console + file logging."""
    logger = logging.getLogger("lead_scraper")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler – INFO and above
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    # File handler – DEBUG and above (keeps full trace)
    fh = logging.FileHandler("lead_scraper.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


log = setup_logging()

# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------

def load_api_key() -> str:
    """Load Google Places API key from .env file."""
    load_dotenv()
    key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not key:
        log.error(
            "GOOGLE_PLACES_API_KEY not found. "
            "Create a .env file with: GOOGLE_PLACES_API_KEY=your_key_here"
        )
        sys.exit(1)
    return key

# ---------------------------------------------------------------------------
# County data
# ---------------------------------------------------------------------------

def get_counties(state_name: str) -> list[dict]:
    """
    Return list of county dicts for the given state.
    Results are fetched from the Census Bureau API and cached locally.

    Each dict has keys: 'name' (e.g. "Cook County"), 'fips'.
    """
    cache_path = DATA_DIR / f"{state_name.replace(' ', '_')}_counties.json"

    # Return cached data if available
    if cache_path.exists():
        log.debug(f"Loading county list from cache: {cache_path}")
        with cache_path.open() as f:
            return json.load(f)

    state_key = state_name.lower()
    if state_key not in STATE_FIPS:
        log.error(
            f"Unknown state '{state_name}'. "
            "Use the full state name, e.g. 'illinois' or 'new york'."
        )
        sys.exit(1)

    fips = STATE_FIPS[state_key]
    url = CENSUS_API.format(fips=fips)
    log.info(f"Fetching county list from Census Bureau for {state_name.title()} (FIPS {fips})…")

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error(f"Failed to fetch county data from Census Bureau: {exc}")
        sys.exit(1)

    rows = resp.json()
    # rows[0] is header: ["NAME", "GEO_ID", "state", "county"]
    counties = []
    for row in rows[1:]:
        raw_name = row[0]  # e.g. "Cook County, Illinois"
        county_name = raw_name.split(",")[0].strip()  # → "Cook County"
        geo_id = row[1]    # e.g. "0500000US17031"
        counties.append({"name": county_name, "fips": geo_id})

    # Sort alphabetically for consistent processing order
    counties.sort(key=lambda c: c["name"])

    # Cache for future runs
    with cache_path.open("w") as f:
        json.dump(counties, f, indent=2)
    log.info(f"Found {len(counties)} counties/parishes in {state_name.title()}.")
    return counties

# ---------------------------------------------------------------------------
# Progress (resume support)
# ---------------------------------------------------------------------------

def get_progress_path(state_name: str) -> Path:
    return PROGRESS_DIR / f"{state_name.replace(' ', '_')}_progress.json"


def load_progress(state_name: str) -> dict:
    """Load saved progress. Returns dict with 'completed' set and 'output_file'."""
    path = get_progress_path(state_name)
    if path.exists():
        with path.open() as f:
            data = json.load(f)
        # Convert list back to set
        data["completed"] = set(data.get("completed", []))
        log.info(
            f"Resuming previous run. "
            f"{len(data['completed'])} counties already processed."
        )
        return data
    return {"completed": set(), "output_file": None}


def save_progress(state_name: str, completed: set, output_file: str) -> None:
    """Persist progress so the run can be resumed if interrupted."""
    path = get_progress_path(state_name)
    with path.open("w") as f:
        json.dump(
            {"completed": sorted(completed), "output_file": output_file},
            f,
            indent=2,
        )


def clear_progress(state_name: str) -> None:
    """Remove progress file after a successful full run."""
    path = get_progress_path(state_name)
    if path.exists():
        path.unlink()
        log.debug("Progress file cleared.")

# ---------------------------------------------------------------------------
# Google Places API (New)
# ---------------------------------------------------------------------------

def search_places(
    query: str,
    api_key: str,
    page_token: str | None = None,
) -> dict:
    """
    Call the Google Places API (New) Text Search endpoint.

    Returns the raw JSON response dict, or an empty dict on error.
    On HTTP 429 (quota exceeded) the call is retried once after a 10-second wait.
    """
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    body: dict = {"textQuery": query, "pageSize": 20}
    if page_token:
        body["pageToken"] = page_token

    for attempt in range(3):  # up to 3 attempts per call
        try:
            resp = requests.post(
                PLACES_API_URL,
                headers=headers,
                json=body,
                timeout=30,
            )

            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                log.warning(f"Rate limit hit (429). Waiting {wait}s before retry…")
                time.sleep(wait)
                continue

            if resp.status_code == 400:
                log.error(f"Bad request (400): {resp.text[:300]}")
                return {}

            if resp.status_code == 403:
                log.error(
                    "Permission denied (403). Check that your API key has "
                    "'Places API (New)' enabled and is not restricted by IP/referrer."
                )
                return {}

            resp.raise_for_status()
            return resp.json()

        except requests.RequestException as exc:
            log.warning(f"Request error (attempt {attempt+1}/3): {exc}")
            if attempt < 2:
                time.sleep(3)

    log.error(f"All retries exhausted for query: '{query}'")
    return {}


def parse_place(place: dict) -> dict:
    """
    Extract the fields we care about from a single Places API place object.
    """
    display_name = place.get("displayName", {})
    name = display_name.get("text", "") if isinstance(display_name, dict) else str(display_name)
    return {
        "place_id":     place.get("id", ""),
        "business_name": name,
        "phone":        place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber", ""),
        "website":      place.get("websiteUri", ""),
        "address":      place.get("formattedAddress", ""),
        "rating":       place.get("rating", ""),
        "review_count": place.get("userRatingCount", ""),
    }

# ---------------------------------------------------------------------------
# Per-county search
# ---------------------------------------------------------------------------

def search_county(
    county_name: str,
    state_name: str,
    api_key: str,
    seen_ids: set,
    delay: float,
) -> list[dict]:
    """
    Run all SEARCH_QUERIES for one county and return a list of new lead dicts.
    Deduplicates against `seen_ids` (modified in place).
    """
    county_leads = []

    for i, query_template in enumerate(SEARCH_QUERIES):
        full_query = f"{query_template} in {county_name}, {state_name.title()}"
        log.debug(f"  Query {i+1}/{len(SEARCH_QUERIES)}: {full_query}")

        page_token = None
        page_num = 0

        while True:
            page_num += 1
            data = search_places(full_query, api_key, page_token)

            places = data.get("places", [])
            log.debug(f"    Page {page_num}: {len(places)} results")

            for place in places:
                parsed = parse_place(place)
                pid = parsed["place_id"]
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    # Tag with the county that surfaced this lead
                    parsed["source_county"] = county_name
                    county_leads.append(parsed)

            # Follow pagination
            page_token = data.get("nextPageToken")
            if not page_token:
                break

            # Google requires a short delay before requesting the next page
            time.sleep(2)

        # Polite delay between queries in the same county
        if i < len(SEARCH_QUERIES) - 1:
            time.sleep(delay)

    return county_leads

# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

CSV_FIELDNAMES = [
    "business_name",
    "phone",
    "website",
    "address",
    "rating",
    "review_count",
    "source_county",
    "place_id",
]


def get_output_path(state_name: str) -> Path:
    return Path(f"{state_name.lower().replace(' ', '_')}_leads.csv")


def write_leads(leads: list[dict], output_path: Path, append: bool = False) -> None:
    """Write (or append) leads to the output CSV file."""
    mode = "a" if append else "w"
    write_header = not output_path.exists() or not append

    with output_path.open(mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=CSV_FIELDNAMES,
            extrasaction="ignore",
        )
        if write_header:
            writer.writeheader()
        writer.writerows(leads)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lead Scraper – Find home insulation contractors via Google Places API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python lead_scraper.py --state illinois\n"
            "  python lead_scraper.py --state 'new york'\n"
            "  python lead_scraper.py --state texas --delay 1.5\n"
            "  python lead_scraper.py --state ohio --fresh   (ignore previous progress)\n"
        ),
    )
    parser.add_argument(
        "--state",
        required=True,
        help="Full US state name (e.g. 'illinois', 'new york').",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.8,
        help="Seconds to wait between API queries (default: 0.8). "
             "Increase if you hit quota limits.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore saved progress and start from scratch.",
    )
    args = parser.parse_args()

    state_name = args.state.strip().lower()
    delay = max(0.0, args.delay)

    # Validate state
    if state_name not in STATE_FIPS:
        # Try title-case lookup
        if state_name not in STATE_FIPS:
            log.error(
                f"Unknown state: '{args.state}'. "
                "Please use the full English name, e.g. 'illinois' or 'new york'."
            )
            sys.exit(1)

    api_key = load_api_key()

    # Load county list
    counties = get_counties(state_name)

    # Load (or initialise) progress
    if args.fresh:
        progress = {"completed": set(), "output_file": None}
        log.info("--fresh flag set: ignoring any previous progress.")
    else:
        progress = load_progress(state_name)

    completed: set = progress["completed"]
    output_path = get_output_path(state_name)

    # If resuming, load already-seen place IDs from the existing CSV to
    # prevent duplicates across resume boundaries.
    seen_ids: set = set()
    if output_path.exists() and completed:
        log.info(f"Loading existing place IDs from {output_path} for deduplication…")
        with output_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("place_id"):
                    seen_ids.add(row["place_id"])
        log.info(f"  {len(seen_ids)} existing place IDs loaded.")

    remaining = [c for c in counties if c["name"] not in completed]
    total = len(counties)
    done_count = len(completed)

    log.info(
        f"Starting scrape for {state_name.title()} | "
        f"{total} total counties | "
        f"{done_count} already done | "
        f"{len(remaining)} remaining | "
        f"Delay: {delay}s between queries"
    )
    log.info(f"Output file: {output_path}")
    print()  # blank line for readability

    all_new_leads: list[dict] = []
    total_new = 0

    for idx, county in enumerate(remaining, start=1):
        county_name = county["name"]
        overall_pos = done_count + idx
        log.info(
            f"[{overall_pos}/{total}] Processing: {county_name}, {state_name.title()}"
        )

        try:
            new_leads = search_county(
                county_name=county_name,
                state_name=state_name,
                api_key=api_key,
                seen_ids=seen_ids,
                delay=delay,
            )
        except KeyboardInterrupt:
            log.warning("\nInterrupted by user. Saving progress…")
            if all_new_leads:
                write_leads(all_new_leads, output_path, append=output_path.exists())
            save_progress(state_name, completed, str(output_path))
            log.info(
                f"Progress saved. Re-run with the same command to resume "
                f"from {county_name}."
            )
            sys.exit(0)
        except Exception as exc:
            log.error(f"Unexpected error processing {county_name}: {exc}", exc_info=True)
            # Save what we have and continue to next county
            if all_new_leads:
                write_leads(all_new_leads, output_path, append=output_path.exists())
                all_new_leads = []
            completed.add(county_name)
            save_progress(state_name, completed, str(output_path))
            continue

        if new_leads:
            total_new += len(new_leads)
            all_new_leads.extend(new_leads)
            log.info(
                f"  → {len(new_leads)} new leads found "
                f"(running total: {total_new})"
            )
        else:
            log.info(f"  → No new leads found for this county.")

        completed.add(county_name)

        # Flush to CSV and save progress every county so data is never lost
        if all_new_leads:
            write_leads(all_new_leads, output_path, append=output_path.exists())
            all_new_leads = []
        save_progress(state_name, completed, str(output_path))

        # Polite delay between counties
        if idx < len(remaining):
            time.sleep(delay)

    # ── Final summary ───────────────────────────────────────────────────────
    print()
    if total_new > 0 or output_path.exists():
        # Count final rows in file
        try:
            with output_path.open(newline="", encoding="utf-8") as f:
                total_rows = sum(1 for _ in csv.DictReader(f))
        except Exception:
            total_rows = "?"

        log.info("=" * 60)
        log.info(f"  SCRAPE COMPLETE — {state_name.title()}")
        log.info(f"  New leads this run : {total_new}")
        log.info(f"  Total leads in CSV : {total_rows}")
        log.info(f"  Output file        : {output_path.resolve()}")
        log.info("=" * 60)
    else:
        log.info(f"Scrape complete. No leads found for {state_name.title()}.")

    clear_progress(state_name)


if __name__ == "__main__":
    main()
