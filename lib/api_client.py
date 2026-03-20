"""
Google Places API (New) client for insulation contractor searches.

Endpoint: POST https://places.googleapis.com/v1/places:searchText
Docs:     https://developers.google.com/maps/documentation/places/web-service/text-search

Billing notes
-------------
- Each HTTP request (including each pagination page) = 1 API call.
- pageSize=20 per request; up to 3 pages = 60 results maximum per zip.
- Field mask below uses only Basic Data fields to avoid Pro/Enterprise billing
  escalation beyond the base Text Search charge.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

import requests

log = logging.getLogger(__name__)

PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"

# Only request fields we actually store.
# Keeping addressComponents on Basic tier keeps billing at Text Search rate.
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.nationalPhoneNumber",
    "places.websiteUri",
    "places.formattedAddress",
    "places.addressComponents",
    "places.rating",
    "places.userRatingCount",
    "nextPageToken",
])

SEARCH_TERM = "insulation contractor"
MAX_PAGES = 3          # 3 × 20 = 60 results max per zip
PAGE_SIZE = 20
INTER_PAGE_DELAY = 2.0  # Google requires a pause before fetching next page


class PlacesAPIClient:
    """
    Thin wrapper around the Places API (New) Text Search endpoint.

    All HTTP errors are retried with exponential back-off.  403 errors
    (bad key / quota) are raised immediately as PermissionError so the
    caller can abort cleanly.
    """

    def __init__(self, api_key: str, delay: float = 0.3) -> None:
        self.delay = max(0.0, delay)
        self._session = requests.Session()
        self._session.headers.update({
            "X-Goog-Api-Key":  api_key,
            "X-Goog-FieldMask": FIELD_MASK,
            "Content-Type":    "application/json",
        })

    # ------------------------------------------------------------------
    # Low-level request
    # ------------------------------------------------------------------

    def _post(self, body: Dict) -> Dict:
        """POST to the Places API with retry logic. Returns parsed JSON."""
        for attempt in range(3):
            try:
                resp = self._session.post(PLACES_API_URL, json=body, timeout=30)

                if resp.status_code == 429:
                    wait = 5 * (2 ** attempt)
                    log.warning(f"Rate limited (429). Retrying in {wait}s …")
                    time.sleep(wait)
                    continue

                if resp.status_code == 403:
                    raise PermissionError(
                        f"API returned 403 Forbidden. "
                        "Verify that:\n"
                        "  1. GOOGLE_PLACES_API_KEY in .env is correct.\n"
                        "  2. 'Places API (New)' is enabled in your Google Cloud project.\n"
                        "  3. Billing is enabled on the project.\n"
                        f"  Response body: {resp.text[:300]}"
                    )

                if resp.status_code == 400:
                    log.error(f"Bad request (400): {resp.text[:300]}")
                    return {}

                resp.raise_for_status()
                return resp.json()

            except PermissionError:
                raise
            except requests.exceptions.RequestException as exc:
                if attempt < 2:
                    wait = 2 ** attempt
                    log.warning(f"Request error (attempt {attempt+1}/3): {exc}. Retrying in {wait}s …")
                    time.sleep(wait)
                else:
                    raise

        raise RuntimeError("All retries exhausted for Places API request.")

    # ------------------------------------------------------------------
    # Public: search one zip code
    # ------------------------------------------------------------------

    def search_zip(
        self,
        zip_code: str,
        latitude: float,
        longitude: float,
        radius_meters: float = 25_000,
    ) -> Tuple[List[Dict], int]:
        """
        Search for insulation contractors centred on a zip code.

        Returns
        -------
        (places, api_call_count)
            places          – list of parsed lead dicts
            api_call_count  – number of HTTP requests made (for quota tracking)
        """
        all_places: List[Dict] = []
        call_count = 0

        # First page: include location bias
        body: Dict = {
            "textQuery": SEARCH_TERM,
            "pageSize":  PAGE_SIZE,
            "locationBias": {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": radius_meters,
                }
            },
        }

        for page_num in range(MAX_PAGES):
            response = self._post(body)
            call_count += 1

            raw_places = response.get("places", [])
            for place in raw_places:
                parsed = self._parse_place(place, zip_code)
                if parsed:
                    all_places.append(parsed)

            next_token = response.get("nextPageToken")
            if not next_token or not raw_places:
                break

            # Mandatory pause before requesting next page.
            # IMPORTANT: page_token requests must contain ONLY the pageToken —
            # sending any other field (textQuery, pageSize, locationBias) causes
            # a 400 "parameters must match initial request" error.
            time.sleep(INTER_PAGE_DELAY)
            body = {"pageToken": next_token}

        # Polite delay between zip searches
        time.sleep(self.delay)
        return all_places, call_count

    # ------------------------------------------------------------------
    # Parse a single place object
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_place(place: Dict, source_zip: str) -> Optional[Dict]:
        """Extract the fields we store from a raw Places API place object."""
        place_id = place.get("id")
        if not place_id:
            return None

        # Walk addressComponents for city, state abbreviation, and zip
        city = state = zip_code = ""
        for component in place.get("addressComponents", []):
            types = component.get("types", [])
            if "locality" in types:
                city = component.get("longText", "")
            elif "administrative_area_level_1" in types:
                state = component.get("shortText", "")   # e.g. "IL"
            elif "postal_code" in types:
                zip_code = component.get("longText", "")

        display_name = place.get("displayName", {})
        name = display_name.get("text", "") if isinstance(display_name, dict) else ""

        return {
            "place_id":           place_id,
            "business_name":      name,
            "phone":              place.get("nationalPhoneNumber", ""),
            "website":            place.get("websiteUri", ""),
            "formatted_address":  place.get("formattedAddress", ""),
            "city":               city,
            "state":              state,
            "zip_code":           zip_code,
            "rating":             place.get("rating"),
            "review_count":       place.get("userRatingCount", 0),
            "source_zip":         source_zip,
        }
