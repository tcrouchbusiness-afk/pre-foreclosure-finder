# The method: finding pre-foreclosures in court records

Worked example: **Martin County, FL (Stuart)**. The steps carry over to any judicial-foreclosure county; the URLs and system names don't, so onboarding re-researches them.

Researched 2026-10-05. URLs and site behavior were checked that day. Re-verify before building on them, since county sites change.

Goal: every day, pull new foreclosure filings in Martin County, pull out the property and owner, add contact info, work out the owner's situation from the court file, and over time score which ones are good deals. All of it without anyone clicking through the clerk's site by hand.

---

## 1. How foreclosure works in Florida (why the court record is the signal)

Florida foreclosures are **judicial** (F.S. Chapter 702). Every one goes through the circuit court, so every one leaves a public trail in order:

| Stage | Document / event | Where it shows up | Typical timing | What it means for us |
|---|---|---|---|---|
| 0 | Missed payments, breach letter (30-day notice) | Not public | Months 1–4 delinquent | Invisible to us |
| 1 | **Lis Pendens** recorded, and **Complaint** filed as a "Mortgage Foreclosure" case | Official Records and the court docket | Day 0 | **This is the pre-foreclosure lead.** It's the earliest public signal |
| 2 | Summons served; owner answers or defaults | Docket | Days 20–90 | Default means the owner is checked out. An answer or attorney means they're fighting |
| 3 | Motion for Summary Judgment / Default Final Judgment | Docket | Months 3–12 (often longer) | Urgency rises |
| 4 | **Final Judgment of Foreclosure** with the exact payoff amount and **sale date** | Docket and Official Records | — | The judgment gives the true debt number. Sale is usually 20–35 days later |
| 5 | Online auction | martin.realforeclose.com | Sale date | Pre-foreclosure window closes; it becomes an auction play |
| 6 | Certificate of Sale / Title; surplus funds | Docket | +10 days | Surplus-funds leads (separate play) |

**Best deals come from stages 1–3.** That's when the owner still controls the house, has time, and has options: sell, short sale, or deed-in-lieu.

---

## 2. Martin County sources (the actual systems)

| Source | URL | Access | Use it for |
|---|---|---|---|
| **Official Records (Landmark Web)** | https://or.martinclerk.com/landmarkweb/ | Public. Click through a disclaimer. **No CAPTCHA** seen | **Primary daily feed.** Search by *Document Type = Lis Pendens* plus *Record Date* range. Returns grantor/grantee (bank vs. owner), instrument #, and often the legal description and case # |
| **Court Case Search (CCIS)** | https://court.martinclerk.com/Home.aspx/Search | Public search has a **CAPTCHA**. Registered accounts exist (notarized for Attorney/Party roles) | Docket detail: complaint, mortgage amount, defendants (spouses, HOA, second-lien holders, IRS), service status, attorney appearance, judgment, sale date. Filter case types are named "Mortgage Foreclosure" (homestead / non-homestead / commercial, split by value band such as $0–50k … $250k+) |
| **Foreclosure auctions** | https://martin.realforeclose.com | Public calendar | Scheduled sale dates. Confirms a lead has reached stage 4–5 |
| **Daily Court Docket** | https://www.martinclerk.com/337/Daily-Court-Docket | Public | Upcoming hearings (summary-judgment hearings mean urgency) |
| **Property Appraiser** | Martin County Property Appraiser site (search by parcel/owner) | Public | Owner name, **mailing address** (if it differs from the property, the owner may be absentee or a landlord), **homestead exemption**, just/assessed value, last sale price and date, beds/baths/sqft/year built |
| **Tax Collector** | Martin County Tax Collector | Public | Delinquent property taxes, a second distress signal |
| Pre-1986 records | https://kofilequicklinks.com/MartinFL/Default.aspx | Public | Rarely needed |

> The case-type value bands in CCIS matter. They encode the **amount in controversy** (roughly the loan balance) right in the filter, so you get a debt estimate before opening a single document.

---

## 3. The method, step by step (manual version, which the automation copies)

### Step 1: Pull new lis pendens (daily)
Landmark Web → Document search → type **LIS PENDENS** (also grab **NOTICE OF LIS PENDENS** if that type exists separately) → record date = yesterday. Save: instrument #, record date, grantor (plaintiff/lender), grantee (owner), legal description, and case # if listed.

### Step 2: Filter to foreclosures only
Not every lis pendens is a mortgage foreclosure. Others include quiet title, partition, HOA/condo lien foreclosures, and contract disputes. Keep it if:
- the plaintiff is a bank, servicer, or trust ("…National Association", "…Mortgage", "…as Trustee for…", "…Loan Servicing"), **or**
- the CCIS case type is *Mortgage Foreclosure*, **or**
- the plaintiff is an **HOA/condo association**. Keep these but tag them `HOA_LIEN`. They're often small debts on houses with lots of equity, which can make them some of the best deals.

### Step 3: Open the court case
Search CCIS by case #. Download the **Complaint** (and the attached mortgage/note). Read it for:
- **Original loan amount and date**, plus the default date ("failed to pay the installment due on …")
- **All defendants**: spouse, "Unknown Tenants" (could mean a rental), second mortgagee/HELOC, HOA, IRS/state liens, "Unknown Heirs" or "Estate of…" (**the owner is deceased, so this is probate, a strong motivated-seller signal**)
- Plaintiff's attorney (high-volume foreclosure mills move fast)

### Step 4: Property and equity
Property Appraiser by parcel/address: market value, homestead Y/N, mailing address, last sale.
**Equity estimate = market value − (original loan amortized to today + arrears + fees + junior liens).**
Then compare against the CCIS value band as a sanity check.

### Step 5: Owner situation (from the docket)
Classify each case:

| Signal in the file | Situation tag |
|---|---|
| "Estate of", "Unknown Heirs", probate case under the same name | `DECEASED_OWNER` |
| No answer, clerk's default entered | `DISENGAGED` (likely to sell or walk away) |
| Attorney appearance, contested answer, loss-mitigation motions | `FIGHTING` (harder, but longer runway) |
| Divorce case (DR) between the defendants | `DIVORCE` |
| Mailing address ≠ property, or "Unknown Tenant" served | `ABSENTEE/LANDLORD` |
| Bankruptcy suggestion filed (case stayed) | `BANKRUPTCY`: **do not contact about buying without counsel; the automatic stay applies** |
| Prior foreclosure case dismissed on the same property | `REPEAT_DEFAULT` |
| Delinquent taxes too | `TAX_DISTRESS` |
| Final judgment entered, sale date set | `URGENT` (days count down to the sale) |

### Step 6: Contact info (skip trace)
Owner name plus property and mailing address go to a skip-trace provider for phones and emails.
- Add a real skip-trace API: BatchData/BatchSkipTracing, REISkip, Tracerfy, or PropStream export. Roughly $0.10–0.25 per record.
- **Direct mail to the property and mailing address needs no skip trace** and is the most compliant first touch.

### Step 7: Score the deal
Score 0–100 from weighted factors (tune it once we have outcomes):

| Factor | Weight | Good |
|---|---|---|
| Equity % (value − debt) / value | 35 | ≥ 30% |
| Situation (deceased / disengaged / absentee / divorce) | 20 | any present |
| Time to sale | 15 | 60–240 days (enough time to close) |
| Property fit (SFR, 1990+, 3/2, in Stuart/Palm City/Jensen/Hobe Sound) | 15 | — |
| Lien stack simplicity (no IRS, no 2nd, HOA small) | 10 | clean |
| Contact found | 5 | phone + email |

Bad deal flags: underwater (equity < 10%), BANKRUPTCY, condo with a special assessment, flood zone VE, commercial.

"Good vs. bad" gets **calibrated** after ~100–200 leads: record the outcome of each (sold to us / listed / reinstated / went to auction, and at what price) and refit the weights.

---

---
How this is automated: see [`../CLAUDE.md`](../CLAUDE.md). Legal guardrails: [`legal.md`](legal.md).
