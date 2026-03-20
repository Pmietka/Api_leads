# Lead Scraper — Home Insulation Contractor Lead Generation
**Appointly Solutions** | Powered by Google Places API (New)

A command-line tool that finds every home insulation contractor in a US state, organized county-by-county, and exports them to a clean, deduplicated CSV file ready for outreach.

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
12. [County Count by State](#county-count-by-state)
13. [Troubleshooting](#troubleshooting)
14. [File Structure](#file-structure)

---

## What It Does

Given a US state name, this tool:

1. Fetches the complete list of every county/parish in that state from the US Census Bureau (free, no key needed)
2. For each county, runs **8 targeted search queries** against the Google Places API (New):
   - `home insulation contractor`
   - `spray foam insulation`
   - `blown in insulation`
   - `attic insulation`
   - `insulation installation`
   - `cellulose insulation`
   - `fiberglass batt insulation`
   - `insulation company`
3. Collects for every business found:
   - Business Name
   - Phone Number
   - Website URL
   - Full Address
   - Google Rating (1–5)
   - Total Review Count
4. Deduplicates across all county and query combinations using Google's unique Place ID
5. Handles pagination automatically (each query can return up to 60 results across 3 pages)
6. Saves progress after every county — safe to interrupt and resume at any time
7. Exports everything to a single clean CSV named `{state}_leads.csv`

---

## Output Example

```
illinois_leads.csv
```

| business_name | phone | website | address | rating | review_count | source_county | place_id |
|---|---|---|---|---|---|---|---|
| ABC Insulation LLC | (312) 555-0100 | https://abcinsulation.com | 123 Main St, Chicago, IL 60601 | 4.8 | 127 | Cook County | ChIJxxx... |
| Midwest Spray Foam | (217) 555-0199 | | 456 Oak Ave, Springfield, IL 62701 | 4.5 | 43 | Sangamon County | ChIJyyy... |

---

## Requirements

- Python **3.10** or newer (uses `str | None` union type syntax)
- A Google Cloud account with billing enabled
- Internet access (for the Places API and Census Bureau county data)

---

## Installation

### 1. Clone or download this repository

```bash
git clone <https://github.com/Pmietka/Api_leads.git>
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

The only two packages needed are:
- `requests` — HTTP calls to Google Places API and Census Bureau
- `python-dotenv` — reads your API key from the `.env` file

---

## Google Cloud API Setup

This is a one-time setup. It takes about 5 minutes.

### Step 1 — Create a Google Cloud Project

1. Go to [https://console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown at the top → **New Project**
3. Give it a name (e.g. `appointly-lead-scraper`) and click **Create**
4. Make sure the new project is selected in the dropdown

### Step 2 — Enable the Places API (New)

> **Important:** There are two Places APIs in Google Cloud. You need the one labeled **(New)** — the legacy version uses a different endpoint and will not work.

1. In the left sidebar, go to **APIs & Services → Library**
2. Search for **`Places API (New)`**
3. Click on it and press **Enable**

### Step 3 — Enable Billing

The Places API requires a billing account even though the first $200/month is free (see [API Costs](#api-costs--rate-limits) below).

1. Go to **Billing** in the left sidebar
2. Link a credit card or payment method to your project
3. Recommended: set a **budget alert** (e.g. $10/month) under **Billing → Budgets & Alerts** so you're notified before any significant charges

### Step 4 — Create an API Key

1. Go to **APIs & Services → Credentials**
2. Click **+ Create Credentials → API Key**
3. Copy the generated key — you'll need it in the next step

### Step 5 — Restrict the API Key (Security Best Practice)

1. Click **Edit API Key** on the key you just created
2. Under **API restrictions**, select **Restrict key**
3. In the dropdown, choose **Places API (New)**
4. Click **Save**

This ensures the key cannot be used for any other Google service even if it were ever exposed.

---

## Configuration

### Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` in any text editor and replace the placeholder with your real key:

```
GOOGLE_PLACES_API_KEY=AIzaSyABC123yourrealkeyhere
```

The `.env` file is read automatically at startup. Never commit this file to source control — it contains your private API key.

---

## Usage

### Basic usage

```bash
python lead_scraper.py --state illinois
```

```bash
python lead_scraper.py --state "new york"
```

```bash
python lead_scraper.py --state texas
```

State names are **case-insensitive** and should be the full English name. Both `Illinois` and `illinois` work.

### Slower request rate (if you hit quota limits)

```bash
python lead_scraper.py --state california --delay 1.5
```

### Ignore saved progress and restart from scratch

```bash
python lead_scraper.py --state illinois --fresh
```

### Example console output

```
2026-03-20 10:00:01  INFO     Fetching county list from Census Bureau for Illinois (FIPS 17)…
2026-03-20 10:00:02  INFO     Found 102 counties/parishes in Illinois.
2026-03-20 10:00:02  INFO     Starting scrape for Illinois | 102 total counties | 0 already done | 102 remaining | Delay: 0.8s
2026-03-20 10:00:02  INFO     Output file: illinois_leads.csv

2026-03-20 10:00:02  INFO     [1/102] Processing: Adams County, Illinois
2026-03-20 10:00:06  INFO       → 14 new leads found (running total: 14)
2026-03-20 10:00:07  INFO     [2/102] Processing: Alexander County, Illinois
2026-03-20 10:00:11  INFO       → 3 new leads found (running total: 17)
...
2026-03-20 12:47:33  INFO     ============================================================
2026-03-20 12:47:33  INFO       SCRAPE COMPLETE — Illinois
2026-03-20 12:47:33  INFO       New leads this run : 1,847
2026-03-20 12:47:33  INFO       Total leads in CSV : 1,847
2026-03-20 12:47:33  INFO       Output file        : /home/user/Api_leads/illinois_leads.csv
2026-03-20 12:47:33  INFO     ============================================================
```

---

## All Command-Line Options

| Flag | Type | Default | Description |
|---|---|---|---|
| `--state` | string | *(required)* | Full US state name, e.g. `illinois` or `"new york"` |
| `--delay` | float | `0.8` | Seconds to wait between API queries within a county. Increase to `1.5`–`2.0` if you hit 429 rate limit errors. |
| `--fresh` | flag | off | Ignore any saved progress file and restart the entire state from county 1. The existing CSV is overwritten. |

---

## How It Works

### County data

On first run for a state, the tool calls the **US Census Bureau API** (completely free, no key required) to get a full list of every county or county-equivalent (parishes in Louisiana, boroughs in Alaska, etc.). The result is cached to `data/{state}_counties.json` so subsequent runs don't need to re-fetch it.

### Search strategy

For each county, 8 distinct search queries are fired at the **Google Places API (New) Text Search** endpoint. Using multiple query terms is important because not all businesses self-describe the same way — a spray foam specialist may not appear in a generic "insulation contractor" search.

Queries are formatted as:
```
spray foam insulation in Cook County, Illinois
```

### Pagination

Each query can return up to 20 results. If a `nextPageToken` is present in the response, the tool automatically fetches the next page (up to 3 pages = 60 results per query) with a 2-second delay between pages as required by Google.

### Deduplication

Every place returned by the API has a unique `place_id`. The tool keeps a set of all seen place IDs in memory and only writes a lead to the CSV if its ID hasn't been seen before. This means a business that shows up in three neighboring counties under four different search queries is only recorded once.

On resume, the existing CSV is read at startup to reload the seen-ID set, so deduplication remains accurate across multiple sessions.

### Progress & resume

After every county is fully processed, two things happen:
1. Any new leads are appended to the CSV file on disk
2. The progress state is saved to `.progress/{state}_progress.json`

If the script stops for any reason — network error, power cut, Ctrl+C — simply re-run the exact same command. The tool will automatically detect the progress file, skip all already-completed counties, and pick up where it left off.

---

## Resume / Fault Tolerance

### Automatic resume

```bash
# Run was interrupted at county 47 of 102
python lead_scraper.py --state illinois

# Output:
# Resuming previous run. 46 counties already processed.
# [47/102] Processing: ...
```

### Force a fresh start

```bash
python lead_scraper.py --state illinois --fresh
```

This deletes the progress checkpoint and overwrites the existing CSV.

### Manual progress inspection

Progress files are plain JSON and can be inspected directly:

```bash
cat .progress/illinois_progress.json
```

```json
{
  "completed": [
    "Adams County",
    "Alexander County",
    "Bond County",
    ...
  ],
  "output_file": "illinois_leads.csv"
}
```

### Log file

Every run appends to `lead_scraper.log` in the working directory. This file includes DEBUG-level detail (every individual query and page result) that is not shown on the console. Useful for diagnosing issues.

---

## API Costs & Rate Limits

### Pricing

The **Google Places API (New) Text Search** is billed at approximately **$0.025 per request** (Basic tier, as of 2024). Google provides a **$200 monthly free credit** on all Maps Platform products, which covers:

> $200 ÷ $0.025 = **8,000 free requests per month**

### Estimated calls per state

| State | Counties | Queries/County | Min Calls | Paginated Est. |
|---|---|---|---|---|
| Illinois | 102 | 8 | 816 | ~1,200 |
| Texas | 254 | 8 | 2,032 | ~3,000 |
| California | 58 | 8 | 464 | ~700 |
| New York | 62 | 8 | 496 | ~750 |
| All 50 states | ~3,143 | 8 | ~25,144 | ~37,000 |

Most individual state runs comfortably fit within the free monthly tier. Running all 50 states in a single month may incur charges of **~$725** at the non-free rate, but in practice many rural counties will return few results with little pagination.

### Rate limit handling

- Default delay between queries: **0.8 seconds**
- On HTTP `429` (quota exceeded): automatic retry after 10s, 20s, 30s
- On HTTP `403` (key error): stops immediately with a clear error message
- On network errors: retries 3 times with 3-second gaps

If you frequently see 429 errors, increase the delay:
```bash
python lead_scraper.py --state texas --delay 2.0
```

---

## County Count by State

For planning purposes — larger states take longer and use more API calls.

| State | Counties | State | Counties |
|---|---|---|---|
| Texas | 254 | Missouri | 115 |
| Georgia | 159 | Oklahoma | 77 |
| Virginia | 133 | Iowa | 99 |
| Kentucky | 120 | Illinois | 102 |
| Kansas | 105 | Michigan | 83 |
| North Carolina | 100 | Tennessee | 95 |
| Ohio | 88 | Indiana | 92 |
| Mississippi | 82 | Wisconsin | 72 |
| Alabama | 67 | Pennsylvania | 67 |
| California | 58 | New York | 62 |

Small states like Rhode Island (5), Delaware (3), and Hawaii (5) complete in minutes.

---

## Troubleshooting

### `GOOGLE_PLACES_API_KEY not found`
- Make sure you've created a `.env` file (not just `.env.example`)
- The file must be in the same directory you're running the command from
- Check for typos: the variable must be exactly `GOOGLE_PLACES_API_KEY`

### `Permission denied (403)`
- Your API key may not have the **Places API (New)** enabled
- Go to Google Cloud Console → APIs & Services → Library and confirm "Places API (New)" shows as **Enabled**
- If you restricted the key to specific APIs, make sure "Places API (New)" is in the allowed list
- Note: do NOT enable the legacy "Places API" — it uses a different endpoint

### `Failed to fetch county data from Census Bureau`
- The Census Bureau API is occasionally slow; try again in a few minutes
- Check your internet connection
- If the cached file exists but is corrupted, delete `data/{state}_counties.json` and retry

### Results seem low / missing counties
- Some rural counties may genuinely have zero insulation contractors
- Try increasing queries by editing `SEARCH_QUERIES` in `lead_scraper.py` to add more terms like `"insulation contractor near me"` or `"rigid foam insulation"`
- Businesses without a Google Maps listing will not appear — this is a limitation of the Places API

### The script is running very slowly
- This is expected for large states. Texas (254 counties) takes 2–3 hours at default speed
- You can safely Ctrl+C and resume later — progress is saved after every county
- Reduce the delay with `--delay 0.5` if you're not hitting rate limits

### `Unknown state: 'xxx'`
- Use the full English name of the state, not an abbreviation
- Correct: `--state illinois`, `--state "new york"`, `--state "north carolina"`
- Incorrect: `--state IL`, `--state NY`

---

## File Structure

```
Api_leads/
├── lead_scraper.py          # Main script — the only file you need to run
├── requirements.txt         # Python dependencies (requests, python-dotenv)
├── .env.example             # Template — copy to .env and add your API key
├── .env                     # Your API key (create this; never commit to git)
├── lead_scraper.log         # Full debug log (created on first run)
│
├── data/                    # Auto-created on first run
│   └── illinois_counties.json    # Cached county list per state
│
├── .progress/               # Auto-created on first run
│   └── illinois_progress.json    # Resume checkpoint per state
│
└── illinois_leads.csv       # Output — created after first run
```

### Suggested `.gitignore` additions

```gitignore
.env
data/
.progress/
*.csv
*.log
```

---

*Built for Appointly Solutions — helping home service contractors grow.*
