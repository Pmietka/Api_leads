"""
US zip code data loader using the `zipcodes` package.

The zipcodes library ships with a bundled dataset of all US zip codes
including latitude, longitude, population (IRS estimate), and type.
No database download required — data is included in the package itself.

Filtering applied:
  - Exclude PO Box-only zip codes (zip_code_type == 'PO BOX')
  - Exclude zips with known population below `min_population` (default 500)
  - Exclude zips without valid lat/lon coordinates
  - Exclude non-continental territories (only 50 states + DC)
"""

import logging
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State reference data
# ---------------------------------------------------------------------------

STATE_NAMES: Dict[str, str] = {
    "AL": "Alabama",              "AK": "Alaska",
    "AZ": "Arizona",              "AR": "Arkansas",
    "CA": "California",           "CO": "Colorado",
    "CT": "Connecticut",          "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida",
    "GA": "Georgia",              "HI": "Hawaii",
    "ID": "Idaho",                "IL": "Illinois",
    "IN": "Indiana",              "IA": "Iowa",
    "KS": "Kansas",               "KY": "Kentucky",
    "LA": "Louisiana",            "ME": "Maine",
    "MD": "Maryland",             "MA": "Massachusetts",
    "MI": "Michigan",             "MN": "Minnesota",
    "MS": "Mississippi",          "MO": "Missouri",
    "MT": "Montana",              "NE": "Nebraska",
    "NV": "Nevada",               "NH": "New Hampshire",
    "NJ": "New Jersey",           "NM": "New Mexico",
    "NY": "New York",             "NC": "North Carolina",
    "ND": "North Dakota",         "OH": "Ohio",
    "OK": "Oklahoma",             "OR": "Oregon",
    "PA": "Pennsylvania",         "RI": "Rhode Island",
    "SC": "South Carolina",       "SD": "South Dakota",
    "TN": "Tennessee",            "TX": "Texas",
    "UT": "Utah",                 "VT": "Vermont",
    "VA": "Virginia",             "WA": "Washington",
    "WV": "West Virginia",        "WI": "Wisconsin",
    "WY": "Wyoming",
}

_NAME_TO_ABBR: Dict[str, str] = {v.lower(): k for k, v in STATE_NAMES.items()}


# ---------------------------------------------------------------------------
# State normalisation
# ---------------------------------------------------------------------------

def normalize_state(state_input: str) -> Optional[str]:
    """
    Convert any state name or abbreviation to an uppercase two-letter code.
    Returns None if the input is not a recognised US state.

    Examples
    --------
    >>> normalize_state("washington") → "WA"
    >>> normalize_state("WA")         → "WA"
    >>> normalize_state("New York")   → "NY"
    """
    s = state_input.strip()
    if s.upper() in STATE_NAMES:
        return s.upper()
    return _NAME_TO_ABBR.get(s.lower())


def get_ordered_states(priority_states: List[str]) -> List[str]:
    """
    Return all state abbreviations with priority states first,
    followed by the remaining states in alphabetical order.

    Invalid state names in priority_states are silently ignored.
    """
    all_states = sorted(STATE_NAMES.keys())
    seen: set = set()
    ordered: List[str] = []

    for s in priority_states:
        norm = normalize_state(s)
        if norm and norm not in seen:
            ordered.append(norm)
            seen.add(norm)

    for s in all_states:
        if s not in seen:
            ordered.append(s)

    return ordered


# ---------------------------------------------------------------------------
# Zip code loading
# ---------------------------------------------------------------------------

def load_zipcodes(
    states: Optional[List[str]] = None,
    min_population: int = 500,
) -> List[Dict]:
    """
    Return a list of zip code dicts filtered by population and type.

    Parameters
    ----------
    states          : list of state abbreviations to load, or None for all states
    min_population  : minimum population threshold (0 = no filter, 500 = default)

    Each returned dict has keys: zip_code, state, latitude, longitude.

    Raises ImportError if zipcodes is not installed.
    """
    try:
        import zipcodes as zc  # type: ignore
    except ImportError:
        raise ImportError(
            "The 'zipcodes' package is required.\n"
            "Install it with:  pip install zipcodes"
        )

    target_states = states or list(STATE_NAMES.keys())
    results: List[Dict] = []
    skipped_po_box = 0
    skipped_population = 0
    skipped_no_coords = 0

    log.info(
        f"Loading zip codes for {len(target_states)} state(s) "
        f"(min_population={min_population}) …"
    )

    for state_abbr in target_states:
        try:
            state_zips = zc.filter_by(state=state_abbr)
        except Exception as exc:
            log.warning(f"Could not load zip codes for {state_abbr}: {exc}")
            continue

        for z in state_zips:
            # Filter PO Box zips
            if z.get("zip_code_type") == "PO BOX":
                skipped_po_box += 1
                continue

            # Validate coordinates
            raw_lat = z.get("lat")
            raw_lng = z.get("long")
            if not raw_lat or not raw_lng:
                skipped_no_coords += 1
                continue
            try:
                lat = float(raw_lat)
                lng = float(raw_lng)
            except (TypeError, ValueError):
                skipped_no_coords += 1
                continue

            # Population filter — only applied when a non-zero value is known
            pop = z.get("irs_estimated_population") or 0
            if pop > 0 and pop < min_population:
                skipped_population += 1
                continue

            results.append({
                "zip_code":  z["zip_code"],
                "state":     z["state"],
                "latitude":  lat,
                "longitude": lng,
            })

    log.info(
        f"Loaded {len(results):,} zip codes  "
        f"(skipped: {skipped_po_box} PO Box, "
        f"{skipped_population} low-pop, "
        f"{skipped_no_coords} no coords)"
    )
    return results
