# Pre-Foreclosure Finder: instructions for Claude

You are helping a real-estate investor or agent find pre-foreclosure leads from public county
records: pull new foreclosure filings, match each to a property and owner, read the court file,
add contact info, and rank who to call. This file is your playbook. Follow it in order.

**Before you do anything else, check whether `config/county.json` exists.**
- It doesn't → run **Step 0: Onboarding interview** below. Do not download, scrape, or build anything first.
- It does → read it and `config/profile.json`, say which county/folder you're set up for, and ask
  what they want to do (new pull, court files, skip trace, rebuild the workbook).

---

## Step 0: Onboarding interview

Keep it conversational, a few questions at a time. Use the AskUserQuestion tool where it's available.
Record answers as you go.

### 0.1 Say which tool to use (first message)
Recommend **Claude Code** (desktop app or CLI) for this work, and say why in one or two lines:
it runs the local Python scripts, downloads ~250 MB of county data, writes the Excel workbook to their
disk, and drives their Chrome through the Claude in Chrome extension while they solve CAPTCHAs.
**Cowork** is fine for reading the finished workbook, planning calls, or drafting letters, but the
pull-and-build pipeline belongs in Claude Code. If they're already in Claude Code, say so and move on.
If they're in Cowork, offer to continue planning there and give them the exact steps to open this
repo in Claude Code.

### 0.2 Ask
1. **County and state** to target (one county per setup). Ask which towns or ZIPs matter most.
2. **Working folder**: where this repo and its data should live on their machine (suggest
   `~/pre-foreclosure-finder` or a folder inside their existing projects). Data holds real people's
   names and addresses, so it should stay local and out of any shared or synced folder they don't control.
3. **Goal**: buying (investor), listing (agent), or both. This changes how the call list is framed.
4. **Buy box**: price range, property types (single-family / condo / townhome / mobile), and minimum
   equity they care about. Saved to `config/profile.json` and used in scoring.
5. **Lookback**: how far back the first pull should go (default 90 days).
6. **Skip-trace provider** and budget per lead. If none yet, recommend testing one under $0.25/record
   (REISkip ~$0.15 worked in Martin County, 2026-10). They create the account; you never do.
7. **Browser**: is the Claude in Chrome extension installed and connected? If several browsers are
   connected, ask which one is **on this machine** (downloads must land where the scripts run;
   check by saving a tiny file and confirming it appears in their Downloads folder).
8. **Python**: check `python --version` (3.10+) and `pip install -r requirements.txt` yourself.

### 0.3 Research the county (you do this, then confirm with them)
Find and verify, with dated notes:
- **Official Records search** (where a *lis pendens* is recorded): system name (Landmark Web,
  AcclaimWeb, Tyler/Odyssey, etc.), URL, the document-type code for lis pendens, whether it shows a
  disclaimer (ask the user before you accept it) or a CAPTCHA, and how far behind the index runs.
- **Court docket search**: URL, case-number format, CAPTCHA or login rules.
- **Property Appraiser bulk data downloads**: most Florida counties publish free owner/parcel/legal/
  exemption/value files. Record the URL pattern and dataset ids. If there are none, say so; parcel
  matching then needs per-address lookups and is slower.
- **Foreclosure auction site** (usually `<county>.realforeclose.com` in Florida).
- State-specific rules: is foreclosure **judicial** (court filings exist) or **non-judicial**
  (notices of default/trustee sale instead; the method changes; tell the user plainly).

Write `config/county.json` using `config/examples/martin-fl.json` as the template, and
`config/profile.json` from the buy box:
```json
{"goal": "investor", "price_min": 150000, "price_max": 600000, "property_types": ["SFR","condo","townhome"],
 "min_equity_pct": 25, "lookback_days": 90, "towns": ["Stuart","Palm City"], "skip_trace_provider": "REISkip",
 "skip_trace_budget_per_lead": 0.25, "browser_name": "Browser 1", "set_up": "YYYY-MM-DD"}
```
Then show them a short summary and get a yes before the first pull.

---

## Rules that don't bend
1. **Never solve, bypass, or work around a CAPTCHA.** Not by reading it, not by finding an API behind
   it, not by replaying requests. The user solves it in their browser; you continue in that session.
   Stop and ask when one appears. Expect one every ~4 court searches.
2. **Don't reverse-engineer a site to skip its access controls.** Using the site's own search form,
   its own export button, or published bulk downloads is fine. Hidden endpoints that dodge a gate are not.
3. **Ask before accepting any site disclaimer or terms**, before any download, and before anything
   that costs money (skip-trace runs). State the count and the cost.
4. **Never enter passwords or create accounts.** The user logs in; you work in their session.
5. **Never ask for API keys in chat.** Tell the user to put them in `.env`; read them from there and
   never print them.
6. **Bulk automated pulling from a court site can be blocked by Claude Code's permission system.** If a
   batch is denied, stop. Don't retry it in smaller pieces. Tell the user their options: add a
   permission rule for that site, search the cases themselves while you read the pages, or ask the
   clerk for a bulk/subscriber feed.
7. **Personal data stays local.** Everything in `data/` and `output/` is gitignored. Never commit,
   upload, or paste it into public places.
8. **Date everything.** URLs, prices, and site behavior change. Write the date you verified them.

---

## The pipeline

| # | Step | Who / how | Output |
|---|---|---|---|
| 1 | **Download Property Appraiser data** (once a year; values each July/Nov) | `python scripts/download_pa.py` | `data/pa/<dataset>/` |
| 2 | **Pull lis pendens** for the lookback window | Claude in Chrome on the Official Records site: search doc type (e.g. `LP`) for the date range, max records, page size All, then run `browser/landmark_extract.js` (adapt the column map for non-Landmark systems). Move the download to `data/raw/` | `data/raw/lis_pendens_<date>.json` |
| 3 | **Classify** | `python scripts/classify.py` | `data/leads.json` |
| 4 | **Match parcels** (owner, address, mailing, homestead, value) | `python scripts/enrich_pa.py` | `data/leads_enriched.json` |
| 5 | **Build workbook** | `python scripts/export_excel.py` | `output/foreclosure_leads_<date>.xlsx` |
| 6 | **Court files** for the top leads (score ≥ 50 first) | User solves CAPTCHA; you search each case number with the site's form, run `browser/save_case_page.js` on each case page, then `browser/export_saved.js`. Move to `data/ccis/`. `python scripts/parse_ccis.py` | `data/ccis_parsed.json` (stage, debt band, contested, dismissed, trial) |
| 7 | **Estates (tier A)**: find who can sell | Name-search the deceased owner's last name; open the case ending in `CP` (probate). Record personal rep, estate attorney, homestead determination, deadlines in `data/estate_research.json` (template: `data/estate_research.example.json`). No probate case = heirs from the foreclosure defendants | `data/estate_research.json` |
| 8 | **Skip trace** | `python scripts/build_skiptrace.py --tiers B1,B2,C --name skiptrace1` (+ `--tiers A` for estate people in `trace`, each with a street address). User uploads to the provider, downloads results into `output/`. `python scripts/import_skiptrace.py output/<results>.csv --upload output/skiptrace1.csv` | `data/skiptrace/*.csv` |
| 9 | **Rebuild** | `python scripts/export_excel.py` | workbook with phones, estates, court stage |

Re-running any step is safe; leads de-dupe on the clerk file number.

### The workbook
- **Summary**: headline counts, lead mix, top 10, caveats.
- **Call List**: grouped by tier with Called / Outcome (dropdown) / Notes columns.
  - **A, call first**: estates, reverse mortgages, non-owner-occupied bank foreclosures.
  - **B1**: owner-occupants in bank foreclosure. **B2**: HOA/condo liens (small debts, often paid).
  - **C**: LLC / multi-property investors (trace the person once). **D**: land / no address; skip.
- **Leads**, **Court Findings**, **Review** (uncertain address matches), **All Filings**, **Key**.

---

## Things that will trip you up (learned the hard way)
- **Wrong browser = files on the wrong computer.** Confirm the browser is on this machine before downloading.
- **Landmark document type**: typing "LIS PENDENS" fails; the code (`LP` in Martin) works. Read the
  hidden code next to the checkbox in the type picker.
- **The court's own search form is slow to load.** Wait ~2 s after navigating before filling it, or
  the submit is lost. Searches by exact case number are the most reliable.
- **Name search**: use LAST name only ("SMITH"), not "SMITH JOHN". Clicking result links sometimes
  doesn't navigate; search the case number directly instead.
- **The case number is in the lis pendens grantee list** ("26 729 CA"). Court format in Martin is
  `26000729CAAXMX` (yy + 6-digit seq + CA/CC + AXMX).
- **Property Appraiser master values can be zero** between rolls; use the value-summary file.
- **Absentee**: compare mailing *street* to property street. ZIP mismatches give false positives.
- **Timeshare weeks** show up as lis pendens in resort counties; they're excluded automatically.
- **One investor can own many defaulted LLC properties.** Trace them once.
- **Skip-tracing a dead owner returns the dead owner's old numbers.** For estates, trace the personal
  rep / heirs by name + city, and start with the estate attorney (public on the state bar site).
- **Condos need the unit in its own column** or the provider matches another unit's owner.
- **Skip tracing needs a street address.** REISkip (2026-10) matched 0 of 5 estate people sent as name + city
  only, versus 16/20 HOA-lien owners and 11/16 owner-occupants sent with property + mailing address. For
  executors/heirs, get their home address from the probate petition or affidavit of heirs first, or start
  with the estate attorney (state bar directory).
- **A filed case may already be dismissed.** Only the court file tells you; unread leads are unverified.
- Tool output gets truncated; save extracted data to a file through the browser instead of printing it.

## Compliance (tell the user once, briefly, before the first call list)
- Calls/texts: federal TCPA + DNC, and state rules (Florida: FTSA, F.S. 501.059). Scrub DNC. No autodialing or mass texting without consent.
- Buying from an owner in foreclosure is regulated in many states (Florida: F.S. 501.1377, equity
  purchaser rules, 5-business-day rescission). An attorney should approve the contract and scripts.
- Bankruptcy filed = stop contact about buying; automatic stay.
- See `docs/legal.md`.
