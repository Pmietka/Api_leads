# Grid Search Lead Generator — Home Insulation Contractors
**Appointly Solutions** | Powered by Google Places API (New)

A command-line tool that finds every home insulation contractor across any US state
using a lat/lng grid search, then exports them to clean, deduplicated CSV files
ready for outreach. All 50 states plus DC are supported.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Output Example](#output-example)
3. [Requirements](#requirements)
4. [Installation](#installation)
5. [Google Cloud API Setup](#google-cloud-api-setup)
6. [Configuration](#configuration)
7. [Usage](#usage)
8. [All Command-Line Options](#all-command-line-options)
9. [How It Works](#how-it-works)
10. [Resume / Fault Tolerance](#resume--fault-tolerance)
11. [API Costs & Rate Limits](#api-costs--rate-limits)
12. [Troubleshooting](#troubleshooting)
13. [File Structure](#file-structure)

---

## What It Does

Target any US state — or any combination of states — by passing `--states` on the
command line. The default run covers **MA, CT, NJ, PA, and MI** (cold-climate states
with old housing stock and strong insulation demand), but any of the 50 states plus
DC are fully supported. Instead of searching by ZIP code (which returns the same
ranked results repeatedly), it:

1. Lays a **uniform lat/lng grid** across each state — one search point every ~20 miles
2. Applies a **denser 5-mile grid** over major metro areas for each selected state
3. For **each grid point**, runs 3 targeted search queries against the Google Places API (New):
   - `insulation contractor`
   - `insulation`
   - `spray foam insulation`
4. **Paginates** each query automatically (up to 3 pages × 20 results = 60 results per query)
5. **Deduplicates** every result by Google Place ID — each business appears exactly once
6. Saves progress in **SQLite** after every grid point — safe to interrupt and resume
7. Exports per-state **CSV files** plus a combined master CSV

---

## Output Example

```
exports/ma_leads.csv
```

| business_name | phone | website | formatted_address | city | state | zip_code | rating | review_count | source_zip | place_id |
|---|---|---|---|---|---|---|---|---|---|---|
| New England Spray Foam | (617) 555-0100 | https://nesprayfoam.com | 123 Main St, Boston, MA 02101 | Boston | MA | 02101 | 4.8 | 94 | MA_42.3600_-71.0600 | ChIJxxx... |
| CT Insulation Pros | (860) 555-0199 | | 45 Oak Ave, Hartford, CT 06101 | Hartford | CT | 06101 | 4.5 | 31 | CT_41.7600_-72.6800 | ChIJyyy... |

---

## Requirements

- Python **3.10** or newer
- A Google Cloud account with billing enabled
- Internet access

---

## Installation

### 1. Clone or download this repository

```bash
git clone https://github.com/Pmietka/Api_leads.git
cd Api_leads
```

### 2. (Recommended) Create a virtual environment

```bash
# macOS / Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

Two packages are required: `requests` (HTTP calls) and `python-dotenv` (reads your API key from `.env`).

---

## Google Cloud API Setup

One-time setup — takes about 5 minutes.

### Step 1 — Create a Google Cloud Project

1. Go to [https://console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown at the top → **New Project**
3. Give it a name (e.g. `appointly-lead-scraper`) and click **Create**

### Step 2 — Enable the Places API (New)

> **Important:** There are two Places APIs. You need the one labeled **(New)** —
> the legacy version uses a different endpoint and will not work.

1. Go to **APIs & Services → Library**
2. Search for **`Places API (New)`**
3. Click it and press **Enable**

### Step 3 — Enable Billing

The API requires a billing account even though the first $200/month is free.

1. Go to **Billing** in the left sidebar
2. Link a credit card or payment method
3. Recommended: set a **budget alert** at $10 under **Billing → Budgets & Alerts**

### Step 4 — Create an API Key

1. Go to **APIs & Services → Credentials**
2. Click **+ Create Credentials → API Key**
3. Copy the generated key

### Step 5 — Restrict the API Key (recommended)

1. Click **Edit API Key** on the key you just created
2. Under **API restrictions**, select **Restrict key**
3. Choose **Places API (New)** from the dropdown
4. Click **Save**

---

## Configuration

```bash
cp .env.example .env
```

Open `.env` and replace the placeholder with your real key:

```
GOOGLE_PLACES_API_KEY=AIzaSyABC123yourrealkeyhere
```

Never commit `.env` to source control — it contains your private API key.

---

## Usage

### Preview grid coverage without making API calls

```bash
python grid_search.py --dry-run
```

```
State    Grid Points    Est. API Calls (max)
--------------------------------------------
MA                84                     756
CT                35                     315
NJ                74                     666
PA               199                   1,791
MI               443                   3,987
--------------------------------------------
TOTAL            835                   7,515
```

### Run the default states (MA, CT, NJ, PA, MI)

```bash
python grid_search.py
```

### Run any state or combination of states

```bash
python grid_search.py --states MA
python grid_search.py --states PA,MI
python grid_search.py --states TX,FL,CA
python grid_search.py --states NY,NJ,CT,MA,VT,NH,ME
```

All 50 US states and DC are supported (pass the two-letter abbreviation).

### Export CSVs without making API calls

```bash
python grid_search.py --export-only
```

### Resume after interruption

Just re-run the same command — already-searched grid points are skipped automatically.

### Slower request rate (if you hit quota limits)

```bash
python grid_search.py --delay 1.0
```

### Example console output

```
2026-04-06 10:00:01  INFO     Added 835 new grid points to database.

============================================================
  State: MA  (84 total grid points)
============================================================
  [    1/835] MA_41.2300_-73.5100  results=12  new=12  api_calls=3  total_new=12
  [    2/835] MA_41.2300_-73.1474  results=8   new=6   api_calls=2  total_new=18
  ...
  [MA] done — 84 points, 312 new leads

============================================================
  State: CT  (35 total grid points)
============================================================
  ...

Search complete — 1,204 new leads added, 4,312 API calls made.
Exporting CSVs to exports/
  exports/ma_leads.csv  (312 leads)
  exports/ct_leads.csv  (187 leads)
  ...
  exports/all_leads_master.csv  (1,204 total leads — master)
```

---

## All Command-Line Options

| Flag | Type | Default | Description |
|---|---|---|---|
| `--states` | string | `MA,CT,NJ,PA,MI` | Comma-separated state abbreviations to search — any of the 50 US states plus DC |
| `--spacing` | float | `20.0` | Base grid spacing in miles |
| `--dense-spacing` | float | `10.0` | Grid spacing in miles for urban metro zones |
| `--radius` | float | `20000` | Search radius per grid point in meters |
| `--refresh-days` | int | `0` | Re-search grid points older than N days (0 = never) |
| `--export-only` | flag | off | Skip API calls, export CSVs from existing database |
| `--export-dir` | string | `exports/` | Directory for output CSV files |
| `--db-path` | string | `grid_leads.db` | SQLite database file path |
| `--delay` | float | `0.3` | Seconds to wait between API queries |
| `--dry-run` | flag | off | Print grid point counts per state and exit |
| `--state-summary` | flag | off | Print lead counts per state from database and exit |

---

## How It Works

### Grid generation

The tool divides each state into a rectangular bounding box and places search
points on a uniform grid. Latitude step is constant (`spacing_miles / 69`);
longitude step varies by latitude to keep true distance spacing consistent
(`spacing_miles / (69 × cos(lat))`).

Urban metro areas get a denser sub-grid at the dense spacing (default 5 mi). Metro
zones are defined by center coordinates and radius for every supported state. A
few examples:

| State | Metro zones |
|-------|-------------|
| MA | Boston (30 mi), Worcester (20 mi) |
| CT | Hartford (20 mi), New Haven (20 mi) |
| NJ | Newark/NYC border (30 mi), Camden/Philadelphia border (25 mi) |
| PA | Philadelphia (40 mi), Pittsburgh (35 mi) |
| MI | Detroit (40 mi), Grand Rapids (20 mi) |
| TX | Houston (40 mi), Dallas (40 mi), San Antonio (30 mi), Austin (30 mi) |
| CA | Los Angeles (40 mi), San Francisco (30 mi), San Diego (30 mi), Sacramento (25 mi) |
| NY | New York City (40 mi), Buffalo (25 mi), Rochester (20 mi), Albany (15 mi) |
| FL | Miami (35 mi), Orlando (30 mi), Tampa (30 mi), Jacksonville (25 mi) |
| … | All 50 states + DC have pre-configured metro zones |

Each point gets a stable ID (`STATE_lat_lng`, e.g. `MA_42.3600_-71.0600`) used
for resume tracking.

### Search queries

Three queries run per grid point:

1. `insulation contractor` — catches full-service companies
2. `insulation` — broader net for businesses that self-describe simply
3. `spray foam insulation` — catches specialty contractors who may not appear in generic searches

Different businesses use different terminology on Google Maps, so running all
three queries significantly increases recall.

### Pagination

Each query returns up to 20 results. If a `nextPageToken` is present, the tool
fetches the next page automatically (with a 2-second pause as required by
Google), up to a maximum of 3 pages = 60 results per query.

### Deduplication

Every Google Place has a unique `place_id`. Results are deduplicated in two
passes:
- **Within a grid point**: across all 3 queries, so a business found by multiple
  queries is counted once
- **Globally**: via SQLite `INSERT OR IGNORE` on `place_id` as the primary key,
  so a business found at overlapping nearby grid points is stored once

---

## Resume / Fault Tolerance

Progress is stored in the `grid_points` table in SQLite after every grid point.
If the script is interrupted for any reason — Ctrl+C, network error, power cut —
simply re-run the same command. Grid points with `status='completed'` are skipped.

```bash
# Run interrupted at point 412/835
python grid_search.py

# Output:
# Added 0 new grid points to database.  (already populated)
# Starting grid search: 423 pending points across MA, CT, NJ, PA, MI
# [  413/835] ...
```

To re-search already-completed points (e.g. to refresh stale data):

```bash
python grid_search.py --refresh-days 90
```

---

## API Costs & Rate Limits

### Pricing

The **Google Places API (New) Text Search** charges approximately **$17 per 1,000
requests** (Basic fields tier). Google provides a **$200/month free credit**:

> $200 ÷ $0.017 = **~11,700 free requests per month**

### Estimated calls by state selection

| Scenario | API Calls | Cost (beyond free tier) |
|---|---|---|
| Default 5 states, best case | ~2,500 | $0 (within free tier) |
| Default 5 states, realistic | ~5,000 | $0 (within free tier) |
| Default 5 states, worst case | ~7,515 | ~$0 (within free tier) |
| Large state like TX or CA | ~18,000–25,000 | May exceed free tier |

Use `--dry-run` before any large run to see the estimated API call count for your
chosen states.

### Rate limit handling

- Default delay between queries: **0.3 seconds**
- On HTTP `429` (quota exceeded): automatic retry after 5s, 10s, 20s (3 attempts)
- On HTTP `403` (key error): stops immediately with a clear error message
- On network errors: retries 3 times with exponential back-off

Increase delay if you see repeated 429 errors:

```bash
python grid_search.py --delay 1.0
```

---

## Troubleshooting

### `GOOGLE_PLACES_API_KEY not found`
- Confirm you created `.env` (not just `.env.example`)
- The file must be in the same directory you run the command from
- The variable must be exactly `GOOGLE_PLACES_API_KEY`

### `Permission denied (403)`
- Confirm **Places API (New)** is enabled (not the legacy "Places API")
- Confirm billing is set up on the Google Cloud project
- If you restricted the key, make sure "Places API (New)" is in the allowed list

### Results seem sparse
- The 20-mile radius per point may not cover the full gap between grid points —
  try `--radius 25000` to extend coverage
- Some areas may genuinely have few listings on Google Maps

### Script is running slowly
- This is normal — 835 points × 3 queries takes 1–2 hours at the default delay
- You can safely Ctrl+C and resume at any time

---

## File Structure

```
Api_leads/
├── grid_search.py           # Main script — the only file you need to run
├── requirements.txt         # Python dependencies (requests, python-dotenv)
├── .env.example             # Template — copy to .env and add your API key
├── .env                     # Your API key (never commit this)
│
├── lib/
│   ├── api_client.py        # Google Places API wrapper (retry, pagination)
│   ├── database.py          # SQLite schema, grid point tracking, lead storage
│   ├── exporter.py          # CSV export helpers
│   └── __init__.py
│
├── grid_leads.db            # SQLite database (auto-created on first run)
│
└── exports/                 # Auto-created on first run
    ├── ma_leads.csv         # One CSV per state searched (e.g. tx_leads.csv, ca_leads.csv)
    ├── ct_leads.csv
    ├── ...
    └── all_leads_master.csv # Combined master CSV across all searched states
```

---

*Built for Appointly Solutions — helping home service contractors grow.*
