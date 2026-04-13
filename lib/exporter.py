"""
CSV export helpers for lead_tool.py.

Generates per-niche subdirectories so leads from different niches are never
mixed in the same file:

  exports/<niche>/all_leads.csv          — all leads for that niche
  exports/<niche>/<state>_leads.csv      — per-state file for that niche
  exports/all_leads_master.csv           — combined across every niche/state
"""

import csv
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

CSV_FIELDS = [
    "niche",
    "business_name",
    "phone",
    "website",
    "formatted_address",
    "city",
    "state",
    "zip_code",
    "rating",
    "review_count",
    "source_zip",
    "place_id",
]


def _niche_slug(niche: str) -> str:
    """Convert a niche name to a safe directory/filename component."""
    return re.sub(r"[^a-z0-9]+", "_", niche.lower()).strip("_") or "general"


# ---------------------------------------------------------------------------
# Internal writer
# ---------------------------------------------------------------------------

def _write_csv(path: Path, rows: List[Dict]) -> int:
    """Write rows to a CSV file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def export_niche_state_csv(db_path: str, niche: str, state: str, export_dir: str) -> Path:
    """
    Export leads for one niche + state to:
        <export_dir>/<niche_slug>/<state_lower>_leads.csv
    Returns the output Path.
    """
    from lib.database import get_leads_by_niche_and_state

    leads = get_leads_by_niche_and_state(db_path, niche, state)
    slug = _niche_slug(niche)
    path = Path(export_dir) / slug / f"{state.lower()}_leads.csv"
    count = _write_csv(path, leads)
    log.info(f"  {path}  ({count:,} leads)")
    return path


def export_niche_csv(db_path: str, niche: str, export_dir: str) -> Path:
    """
    Export all leads for one niche to:
        <export_dir>/<niche_slug>/all_leads.csv
    Returns the output Path.
    """
    from lib.database import get_leads_by_niche

    leads = get_leads_by_niche(db_path, niche)
    slug = _niche_slug(niche)
    path = Path(export_dir) / slug / "all_leads.csv"
    count = _write_csv(path, leads)
    log.info(f"  {path}  ({count:,} leads — niche master)")
    return path


def export_master_csv(db_path: str, export_dir: str) -> Path:
    """
    Export every lead in the database (all niches) to:
        <export_dir>/all_leads_master.csv
    Returns the output Path.
    """
    from lib.database import get_all_leads

    leads = get_all_leads(db_path)
    path = Path(export_dir) / "all_leads_master.csv"
    count = _write_csv(path, leads)
    log.info(f"  {path}  ({count:,} total leads — master)")
    return path


def export_all(
    db_path: str,
    export_dir: str,
    states: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Path]]:
    """
    Export CSVs separated by niche.

    For each niche found in the database:
      - One file per state:  <export_dir>/<niche>/<state>_leads.csv
      - One niche master:    <export_dir>/<niche>/all_leads.csv

    Also writes a cross-niche master: <export_dir>/all_leads_master.csv

    Returns a nested dict:
        {
          "<niche>": {
            "<STATE>": Path(...),
            "_all":    Path(...),
          },
          "_master": Path(...),
        }
    """
    from lib.database import get_niches_with_leads, get_states_with_leads_for_niche

    niches = get_niches_with_leads(db_path)
    exported: Dict[str, Dict[str, Path]] = {}

    log.info(f"Exporting CSVs to {export_dir}/  (niches: {', '.join(niches) or 'none'})")

    for niche in niches:
        niche_states = states or get_states_with_leads_for_niche(db_path, niche)
        exported[niche] = {}

        for state in niche_states:
            if state:
                path = export_niche_state_csv(db_path, niche, state, export_dir)
                exported[niche][state] = path

        niche_all_path = export_niche_csv(db_path, niche, export_dir)
        exported[niche]["_all"] = niche_all_path

    master_path = export_master_csv(db_path, export_dir)
    exported["_master"] = master_path  # type: ignore[assignment]
    return exported
