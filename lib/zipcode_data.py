"""
US zip code data loader using the `uszipcode` package.

The uszipcode library ships with a bundled SQLite database of all US zip
codes including latitude, longitude, population, and type.  The database
is downloaded automatically on first use (~3 MB).

Filtering applied:
  - Exclude PO Box-only zip codes (zipcode_type == 'PO BOX')
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
    >>> normalize_state("illinois")   → "IL"
    >>> normalize_state("IL")         → "IL"
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

    Raises ImportError if uszipcode is not installed.
    """
    try:
        from uszipcode import SearchEngine  # type: ignore
    except ImportError:
        raise ImportError(
            "The 'uszipcode' package is required.\n"
            "Install it with:  pip install uszipcode"
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

    search = SearchEngine()

    for state_abbr in target_states:
        try:
            # returns=0 → no LIMIT clause in the underlying SQL → all results
            zips = search.by_state(state_abbr, returns=0)
        except Exception as exc:
            log.warning(f"Could not load zip codes for {state_abbr}: {exc}")
            continue

        for z in zips:
            zip_type = getattr(z, "zipcode_type", "STANDARD") or "STANDARD"
            if zip_type == "PO BOX":
                skipped_po_box += 1
                continue

            if not z.lat or not z.lng:
                skipped_no_coords += 1
                continue

            pop = z.population or 0
            # Only filter on population when we have a known value above 0
            # (many zips have NULL population — we include them rather than
            #  risk missing real areas)
            if pop > 0 and pop < min_population:
                skipped_population += 1
                continue

            results.append({
                "zip_code":  z.zipcode,
                "state":     z.state,
                "latitude":  float(z.lat),
                "longitude": float(z.lng),
            })

    log.info(
        f"Loaded {len(results):,} zip codes  "
        f"(skipped: {skipped_po_box} PO Box, "
        f"{skipped_population} low-pop, "
        f"{skipped_no_coords} no coords)"
    )
    return results
