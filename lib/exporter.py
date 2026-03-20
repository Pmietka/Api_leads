"""
CSV export helpers for lead_tool.py.

Generates:
  exports/<state_abbr>_leads.csv   — one file per state with leads
  exports/all_leads_master.csv     — combined file across all states
"""

import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

CSV_FIELDS = [
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

def export_state_csv(db_path: str, state: str, export_dir: str) -> Path:
    """
    Export all leads for one state to <export_dir>/<state_lower>_leads.csv.
    Returns the output Path.
    """
    from lib.database import get_leads_by_state

    leads = get_leads_by_state(db_path, state)
    path = Path(export_dir) / f"{state.lower()}_leads.csv"
    count = _write_csv(path, leads)
    log.info(f"  {path}  ({count:,} leads)")
    return path


def export_master_csv(db_path: str, export_dir: str) -> Path:
    """
    Export every lead in the database to <export_dir>/all_leads_master.csv.
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
) -> Dict[str, Path]:
    """
    Export per-state CSVs for each state in `states` (or all states with
    leads if None), then write the master CSV.

    Returns a dict mapping state abbreviation → Path (plus "_master" key).
    """
    from lib.database import get_states_with_leads

    target_states = states or get_states_with_leads(db_path)
    exported: Dict[str, Path] = {}

    log.info(f"Exporting CSVs to {export_dir}/")
    for state in target_states:
        if state:
            path = export_state_csv(db_path, state, export_dir)
            exported[state] = path

    master_path = export_master_csv(db_path, export_dir)
    exported["_master"] = master_path
    return exported
