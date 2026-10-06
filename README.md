# Pre-Foreclosure Finder

> **Claude: if someone gave you this link, read [`CLAUDE.md`](CLAUDE.md) and start the onboarding
> interview (Step 0) before doing anything else.** Clone the repo into the folder the user chooses
> during onboarding.

Find pre-foreclosure leads in your county from public records, then get a ranked call list. The
call list is an Excel workbook with owner names, property and mailing addresses, equity estimates,
and court status, and it shows who can actually sell, including estate executors and heirs.
Claude does the pulling, matching, and reading. You solve CAPTCHAs and make the calls.

## How to use it
1. Open **Claude Code** (desktop or CLI). Claude Code runs the scripts, downloads county data, and
   drives your browser. Cowork works for reviewing the workbook, but not for running the pipeline.
2. Install the **Claude in Chrome** extension and connect it. Claude uses your browser to search
   county sites, and you solve any CAPTCHA that comes up.
3. Paste this repo's link and say: *"Set this up for me."*
4. Claude interviews you about your county, folder, buy box, and skip-trace provider. It then
   researches your county's systems and runs the first pull, 90 days back by default.

## What you get
| Workbook tab | What's on it |
|---|---|
| Summary | Headline numbers, lead mix, top 10, caveats |
| Call List | Leads grouped by tier (A: estates/landlords, B1: owner-occupants, B2: HOA liens, C: investors, D: skip), with Called/Outcome/Notes columns |
| Leads | Every active lead with score, owner, addresses, value, equity range, situation, and court stage |
| Court Findings | Docket facts: debt band, contested, dismissed, trial date |
| Review | Address matches to double-check |
| All Filings | Every lis pendens pulled, and why some were dropped |

## How it works (the short version)
In a **judicial-foreclosure** state such as Florida, every foreclosure starts with a **lis pendens**
recorded in the county's Official Records. That's the earliest public signal, months before an
auction. This repo:
1. pulls new lis pendens from the clerk's records search
2. throws out non-leads, such as timeshares, business suits and contractor liens
3. matches each lead to a parcel using the Property Appraiser's free bulk files, which gives the
   owner, address, mailing address, homestead status and value
4. reads the court docket for the top leads: debt band, contested, dismissed, trial date
5. for estates, finds the probate case, the personal rep and the estate attorney
6. builds a skip-trace upload, imports the results, and rebuilds the workbook

Full method: [`docs/method.md`](docs/method.md). Legal guardrails: [`docs/legal.md`](docs/legal.md).

## Ground rules
- **CAPTCHAs are solved by you, never by Claude.** Court sites use them on purpose. Expect about one every 4 searches.
- **Your data stays on your machine.** `data/` and `output/` are gitignored because they hold real people's information.
- **Keys go in `.env`**, never in chat.
- **Check your state's rules before calling.** Do-not-call laws and foreclosure-rescue or
  equity-purchaser laws apply. Florida's are in `docs/legal.md`.

## Status
Built and run end-to-end on **Martin County, FL** (Stuart) in October 2026:
- 88 filings in 90 days, 62 active leads, 58 matched to an address
- court and probate files read for the top estates
- REISkip skip trace

Other counties need the onboarding research step. Florida clerks often run the same systems
(Landmark Web, Benchmark CCIS), so a lot carries over.

## Repo map
```
CLAUDE.md                 Claude's playbook: onboarding interview, pipeline, rules, pitfalls
config/examples/          worked county config (martin-fl.json)
config/county.json        your county (created at onboarding, gitignored)
config/profile.json       your buy box (created at onboarding, gitignored)
scripts/                  download_pa, classify, enrich_pa, parse_ccis, export_excel,
                          build_skiptrace, import_skiptrace
browser/                  small JS snippets Claude runs in your browser to save pages it has read
data/ output/             your local data and workbooks (gitignored)
docs/                     method, legal
```

Requires Python 3.10+ and `pip install -r requirements.txt`.
