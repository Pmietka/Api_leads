# Setup Guide — lead_tool.py

## Overview

`lead_tool.py` searches the **Google Places API (New)** across every US zip
code to build a national database of insulation contractors.  All results are
stored in a local SQLite database with automatic deduplication, monthly quota
tracking, and CSV export.

---

## 1 — Python environment

```bash
# Python 3.10 or later is recommended
python --version

# Install dependencies
pip install -r requirements.txt
```

`uszipcode` will download a ~3 MB bundled zip code database on first use.
An internet connection is required for this one-time step.

---

## 2 — Google Cloud project setup

### 2.1 Create or select a project

1. Go to <https://console.cloud.google.com>
2. Click the project selector at the top of the page
3. Click **New Project**, give it a name (e.g. `insulation-leads`), and click **Create**

### 2.2 Enable the Places API (New)

> **Important:** You must enable "Places API (New)" — NOT the legacy "Places API".
> They are separate products with different billing.

1. In the Cloud Console, go to **APIs & Services → Library**
2. Search for **Places API (New)**
3. Click the result, then click **Enable**

### 2.3 Enable billing

The free tier gives you 5,000 Text Search requests per month, but Google
requires a billing account to be linked even when you stay within the free tier.

1. Go to **Billing** in the Cloud Console
2. Click **Link a billing account** (or create one)
3. Enter a payment method

> Set a **budget alert** at \$10–\$20 to get an email if charges approach
> the paid tier unexpectedly:
> Billing → Budgets & Alerts → Create Budget

### 2.4 Create an API key

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → API Key**
3. Copy the key shown in the dialog

### 2.5 Restrict the API key (recommended)

Restricting the key prevents it from being abused if it is ever leaked.

1. In **Credentials**, click the pencil icon next to your new key
2. Under **API restrictions**, select **Restrict key**
3. Choose **Places API (New)** from the list
4. Click **Save**

### 2.6 Add the key to your .env file

```bash
cp .env.example .env
# Edit .env and replace the placeholder:
GOOGLE_PLACES_API_KEY=AIzaSy...your-real-key-here
```

---

## 3 — Understanding the cost model

| Metric | Value |
|--------|-------|
| Free tier | **5,000 requests / month** (resets on the 1st) |
| Paid tier | ~**$32 per 1,000 requests** after free tier |
| Requests per zip | 1–3 (1 per page of 20 results, max 60 results) |
| US zip codes (~pop ≥ 500) | ~28,000 |
| Months to cover all zips (free only) | ~6–10 months |

### Staying on the free tier

```bash
# Stop automatically at 5,000 free calls (the default behaviour)
python lead_tool.py --state all --priority illinois,texas,florida
```

The tool saves progress in SQLite after every zip.  Re-run the same command
next month — it picks up exactly where it left off.

### Allowing paid overage

```bash
# Allow up to $50 in paid calls, then stop
python lead_tool.py --state all --allow-paid --max-spend 50
```

At \$32/1,000 calls, a \$50 cap allows ~1,562 additional paid requests
(roughly 520–1,562 more zip codes, depending on pagination depth).

---

## 4 — Usage examples

```bash
# Search a single state
python lead_tool.py --state illinois
python lead_tool.py --state "new york"
python lead_tool.py --state TX

# Nationwide with priority states searched first
python lead_tool.py --state all --priority illinois,texas,florida

# Allow paid calls up to $30 after the free tier runs out
python lead_tool.py --state all --allow-paid --max-spend 30

# Refresh data older than 180 days
python lead_tool.py --state all --refresh-days 180

# Export CSVs without making any API calls
python lead_tool.py --export-only
python lead_tool.py --export-only --state illinois

# Faster searches (tighter delay between requests)
python lead_tool.py --state illinois --delay 0.1

# Use a custom database path
python lead_tool.py --state all --db-path ~/my_leads.db
```

---

## 5 — Output files

| File | Description |
|------|-------------|
| `insulation_leads.db` | SQLite database (cache + leads + quota tracking) |
| `exports/<state>_leads.csv` | Per-state CSV (e.g. `exports/il_leads.csv`) |
| `exports/all_leads_master.csv` | Master CSV combining all states |
| `lead_tool.log` | Full debug log for troubleshooting |

### CSV columns

| Column | Description |
|--------|-------------|
| `business_name` | Business display name |
| `phone` | Local phone number |
| `website` | Website URL |
| `formatted_address` | Full address string |
| `city` | City extracted from address components |
| `state` | State abbreviation (e.g. IL) |
| `zip_code` | Zip code from address components |
| `rating` | Google rating (1.0–5.0) |
| `review_count` | Number of Google reviews |
| `source_zip` | Zip code search that surfaced this result |
| `place_id` | Google Place ID (unique identifier, used for deduplication) |

---

## 6 — How deduplication works

The same business may appear in searches for several neighbouring zip codes.
Every result is stored with its **Google Place ID** as the primary key.  Any
place already in the database is silently ignored, so each business appears
exactly once in the final CSVs regardless of how many overlapping searches
surfaced it.

---

## 7 — Resume / crash recovery

Progress is stored in SQLite after every single zip code.  If the script is
interrupted (Ctrl+C, crash, network outage), simply re-run the same command
and it will skip every zip that was already successfully searched.

---

## 8 — Troubleshooting

### "403 Forbidden" errors

- Confirm `Places API (New)` is enabled (not the legacy Places API)
- Confirm billing is set up on the project
- Check that the API key restriction allows `Places API (New)`
- Make sure the key in `.env` matches exactly (no extra spaces or quotes)

### "429 Rate Limited" errors

The client automatically retries with exponential back-off.  If you see many
429s, increase the delay: `--delay 1.0`

### uszipcode download fails

`uszipcode` downloads its database from AWS S3 on first use.  If you're
behind a proxy, set the `HTTPS_PROXY` environment variable:

```bash
export HTTPS_PROXY=http://proxy.example.com:8080
python lead_tool.py --state illinois
```

### Quota resets

The free quota resets on the **1st of each calendar month**.  The tool
automatically detects the new month and resets its in-memory counters.
Historical usage is preserved in the database for auditing.
