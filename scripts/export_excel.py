"""Build the review workbook from data/leads_enriched.json (+ court facts + optional skip-trace results).

Output: output/foreclosure_leads_<date>.xlsx  and  output/skiptrace_input_<date>.csv

Sheets:
  Summary         - headline numbers, lead mix, top 10, data notes
  Leads           - pursue=True, sorted by score; grouped headers; Google Maps link per address
  Court Findings  - leads whose court docket has been read (CCIS), with key docket events
  Review          - parcel matches that need a human look
  All Filings     - every lis pendens pulled, with why it was kept or dropped
  Key             - what every column and tag means

Score is PRELIMINARY. Equity only appears where the court case type gives a debt band.
"""
import csv, datetime, glob, json, os, re, urllib.parse
from collections import Counter
from openpyxl import Workbook
from openpyxl.formatting.rule import DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from config import CFG, ROOT, COUNTY_LABEL, PRICE_MIN, PRICE_MAX

TODAY = datetime.date.today().isoformat()

# ---- look ---------------------------------------------------------------------------------------
NAVY, TEAL, INK, MUTED = "1F3A5F", "2E7D7A", "1F2933", "6B7785"
BAND, LINE, PAPER = "F4F6F9", "D9DEE5", "FFFFFF"
STAGE_FILL = {"Closed / dismissed": "F2D7D5", "Sale scheduled": "F8CBAD", "Final judgment": "FCE4D6",
              "Contested, pre-trial": "FFF2CC", "Filed, serving defendants": "E2EFDA"}
GROUP_FILL = {"Lead": NAVY, "Owner & contact": "34567A", "Property": TEAL, "Situation": "7A5C2E",
              "Court file": "6B3A5C", "Record": "5A6470"}
F = lambda **k: Font(name="Calibri", **k)
thin = Side(style="thin", color=LINE)
BORDER = Border(bottom=thin)
HDR_FONT, BODY_FONT = F(bold=True, color="FFFFFF", size=10), F(color=INK, size=10)

TAG_TEXT = {
    "DECEASED_OWNER": "Owner deceased (estate named): heirs often want out",
    "PERSONAL_REP": "Personal representative named: estate/probate in play",
    "REVERSE_MORTGAGE": "Reverse mortgage: usually triggered by death or move-out",
    "TRUST_OWNED": "Held in a trust",
    "ENTITY_OWNED": "Owned by LLC/corp: investor property",
    "MULTI_PROPERTY_OWNER": "Same owner in 3+ filings: investor in broader distress",
    "HUD_LIEN": "HUD named: FHA partial-claim or reverse-mortgage lien",
    "GOV_LIEN": "Federal/state lien named (IRS/SBA/DOR): clouds title",
    "HOA_ALSO_NAMED": "HOA also a defendant: HOA dues likely unpaid too",
    "MOBILE_HOME": "Mobile home lot",
    "CONDO": "Condo unit",
    "COMMERCIAL": "Commercial property",
}
FLAG_TEXT = {
    "DISMISSED": "Case dismissed: loan likely reinstated or paid",
    "CONTESTED": "Answer filed: owner/party is contesting",
    "TENANT_OCCUPIED": "Tenant served: property is rented",
    "SERVICE_BY_PUBLICATION": "Served by publication: some parties hard to find",
    "DEFAULT_ENTERED": "Default entered: owner not responding",
    "FINAL_JUDGMENT": "Final judgment entered",
    "SALE_SET": "Foreclosure sale scheduled",
    "BANKRUPTCY": "Bankruptcy filed: STOP, automatic stay",
}
TYPE_TEXT = {
    "BANK_MORTGAGE": "Bank mortgage",
    "HOA_CONDO_LIEN": "HOA / condo lien",
    "PRIVATE_LENDER_OR_BUSINESS": "Private lender",
    "PRIVATE_PARTY": "Private party",
    "CONTRACTOR_LIEN": "Contractor lien",
    "TIMESHARE": "Timeshare",
}


def band_high(b):
    """'$50,001-$249,999' -> 249999 ; '$250,000+' -> None (unbounded)."""
    nums = [int(x.replace(",", "")) for x in re.findall(r"[\d,]+", b or "")]
    return nums[1] if len(nums) == 2 else None


def band_low(b):
    nums = [int(x.replace(",", "")) for x in re.findall(r"[\d,]+", b or "")]
    return nums[0] if nums else None


def money_k(x):
    return f'{"-" if x < 0 else ""}${abs(x) / 1000:,.0f}k'


def score(l):
    s, t = 0, set(l["tags"])
    s += {"BANK_MORTGAGE": 25, "HOA_CONDO_LIEN": 20, "PRIVATE_LENDER_OR_BUSINESS": 15}.get(l["type"], 0)
    s += 20 if "DECEASED_OWNER" in t or "REVERSE_MORTGAGE" in t else 0
    s += 10 if l.get("absentee") else 0
    s += 10 if l.get("homestead") is False and l.get("parcel_id") else 0
    s += 10 if "HOA_ALSO_NAMED" in t else 0
    s -= 10 if "GOV_LIEN" in t else 0
    s -= 10 if "MOBILE_HOME" in t else 0
    v = l.get("just_value") or 0
    s += 15 if PRICE_MIN <= v <= PRICE_MAX else 5 if v > PRICE_MAX else 0
    s += 10 if l.get("match_confidence") == "HIGH" else 0
    eq = l.get("equity_est")
    if eq is not None and v:
        s += 15 if eq / v >= 0.5 else 5 if eq / v >= 0.25 else -10
    return max(0, min(100, s))


def load_skiptrace():
    res = {}
    for f in glob.glob(os.path.join(ROOT, "data", "skiptrace", "*.csv")):
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                lid = r.get("lead_id") or r.get("Lead ID") or r.get("custom_field_1")
                if not lid:
                    continue
                if "phones" in r:  # our normalized format (scripts convert provider exports to this)
                    cur = res.setdefault(lid, {})
                    for k, v in r.items():
                        if k == "lead_id" or not v:
                            continue
                        if k in ("skip_mortgage", "skip_est_value"):
                            cur[k] = float(v)
                        elif k in ("phones", "emails", "skip_note") and cur.get(k) and v not in cur[k]:
                            cur[k] += ("\n" if k == "skip_note" else " / ") + v  # several heirs on one lead
                        else:
                            cur[k] = v
                    continue
                phones = [v for k, v in r.items() if k and re.search(r"phone", k, re.I) and v and re.search(r"\d{7}", v)]
                emails = [v for k, v in r.items() if k and re.search(r"email", k, re.I) and v and "@" in v]
                res[lid] = {"phones": " / ".join(dict.fromkeys(phones)), "emails": " / ".join(dict.fromkeys(emails))}
    return res


def load_leads():
    leads = json.load(open(os.path.join(ROOT, "data", "leads_enriched.json"), encoding="utf-8"))
    p = os.path.join(ROOT, "data", "ccis_parsed.json")
    court = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    skips = load_skiptrace()
    ep = os.path.join(ROOT, "data", "estate_research.json")
    estates = json.load(open(ep, encoding="utf-8")) if os.path.exists(ep) else {}
    for l in leads:
        if l["case_number"] in estates:
            l["estate"] = estates[l["case_number"]]
        l["lead_id"] = l["clerk_file_number"]
        l.update(court.get(l["case_number"], {}))
        l.update(skips.get(l["lead_id"], {}))
        hi, lo = band_high(l.get("debt_band")), band_low(l.get("debt_band"))
        v = l.get("just_value")
        l["equity_est"] = (v - (hi + lo) / 2) if hi is not None and v else None  # midpoint, for scoring
        l["equity_range"] = (f'{money_k(v - hi)} to {money_k(v - lo)}') if hi is not None and v else ""
        if "DISMISSED" in l.get("court_flags", []):
            l["pursue"], l["drop_reason"] = False, "Court case dismissed"
        l["score"] = score(l) if l["pursue"] else 0
        if not l["pursue"] and not l.get("drop_reason"):
            l["drop_reason"] = {"TIMESHARE": "Timeshare week", "CONTRACTOR_LIEN": "Contractor lien on association",
                                "PRIVATE_PARTY": "Private dispute / business suit"}.get(l["type"], "Commercial / business")
    return leads


# ---- columns: (group, header, getter, width, kind) ----------------------------------------------
def maps(l):
    a = l.get("property_address")
    return a or ""


COLS = [
    ("Lead", "Tier", lambda l: tier(l) if l.get("pursue") else "", 6, "center"),
    ("Lead", "Score", "score", 7, "score"),
    ("Lead", "Case #", "case_number", 11, ""),
    ("Lead", "Recorded", "record_date", 10, ""),
    ("Lead", "Type", lambda l: TYPE_TEXT.get(l["type"], l["type"]), 15, ""),
    ("Owner & contact", "Owner(s) per court", lambda l: "\n".join(l["owners"][:4]), 30, "wrap"),
    ("Owner & contact", "Mailing address", "mailing_address", 30, "wrap"),
    ("Owner & contact", "Phones", "phones", 16, "wrap"),
    ("Owner & contact", "Emails", "emails", 20, "wrap"),
    ("Property", "Property address", maps, 32, "link"),
    ("Property", f'Market value ({CFG["property_appraiser"]["value_year"]})', "just_value", 12, "money"),
    ("Property", "Equity range", "equity_range", 15, "center"),
    ("Property", "Beds/Baths", lambda l: f'{l.get("beds") or "-"} / {l.get("baths") or "-"}' if l.get("parcel_id") else "", 9, "center"),
    ("Property", "SqFt", lambda l: int(float(l["sqft"])) if l.get("sqft") and float(l["sqft"]) > 0 else "", 7, "int"),
    ("Property", "Built", lambda l: l.get("year_built") if l.get("year_built") not in ("0", 0) else "", 6, "center"),
    ("Property", "Homestead", lambda l: ("Yes" if l.get("homestead") else "No") if l.get("parcel_id") else "?", 9, "center"),
    ("Property", "Absentee", lambda l: ("Yes" if l.get("absentee") else "No") if l.get("parcel_id") else "?", 9, "center"),
    ("Situation", "Situation", lambda l: "\n".join([TAG_TEXT.get(t, t) for t in l["tags"]] +
                                                     [FLAG_TEXT.get(f, f) for f in l.get("court_flags", [])]), 46, "wrap"),
    ("Court file", "Stage", lambda l: l.get("court_stage") or "Not yet checked", 18, "stage"),
    ("Court file", "Debt band", "debt_band", 15, ""),
    ("Court file", "Trial", "trial_month", 10, ""),
    ("Court file", "Plaintiff", "plaintiff", 28, "wrap"),
    ("Record", "Parcel ID", "parcel_id", 22, ""),
    ("Record", "Match", "match_confidence", 10, "center"),
    ("Record", "Last sale", lambda l: f'${l["last_sale_price"]:,.0f} ({l["last_sale_date"]})'
                                      if l.get("last_sale_price") else (l.get("last_sale_date") or ""), 20, ""),
    ("Record", "Legal description", "legal", 40, "wrap"),
]


def val(l, c):
    g = c[2]
    v = g(l) if callable(g) else l.get(g, "")
    return "" if v is None else v


def write_table(ws, items, cols, start_row=1, title=None, subtitle=None):
    r = start_row
    if title:
        ws.cell(r, 1, title).font = F(bold=True, size=16, color=NAVY)
        ws.row_dimensions[r].height = 24
        r += 1
        if subtitle:
            ws.cell(r, 1, subtitle).font = F(italic=True, size=10, color=MUTED)
            r += 1
        r += 1
    # group band
    groups = []
    for i, c in enumerate(cols, 1):
        if groups and groups[-1][0] == c[0]:
            groups[-1][2] = i
        else:
            groups.append([c[0], i, i])
    for name, a, b in groups:
        if b > a:
            ws.merge_cells(start_row=r, start_column=a, end_row=r, end_column=b)
        cell = ws.cell(r, a, name.upper())
        cell.font = F(bold=True, size=9, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        for i in range(a, b + 1):
            ws.cell(r, i).fill = PatternFill("solid", fgColor=GROUP_FILL.get(name, NAVY))
    ws.row_dimensions[r].height = 16
    r += 1
    hdr = r
    for i, c in enumerate(cols, 1):
        cell = ws.cell(r, i, c[1])
        cell.font, cell.fill = HDR_FONT, PatternFill("solid", fgColor=GROUP_FILL.get(c[0], NAVY))
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = c[3]
    ws.row_dimensions[r].height = 30
    for n, l in enumerate(items):
        r += 1
        lines = 1
        for i, c in enumerate(cols, 1):
            v = val(l, c)
            cell = ws.cell(r, i, v)
            cell.font, cell.border = BODY_FONT, BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=c[4] in ("wrap", "link"),
                                       horizontal="center" if c[4] in ("center", "score", "int") else None)
            if n % 2:
                cell.fill = PatternFill("solid", fgColor=BAND)
            if c[4] == "money":
                cell.number_format = '"$"#,##0;[Red]-"$"#,##0'
            if c[4] == "int":
                cell.number_format = "#,##0"
            if c[4] == "link" and v:
                cell.hyperlink = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(v)
                cell.font = F(color="1F5FA8", underline="single", size=10)
            if c[4] == "stage" and v in STAGE_FILL:
                cell.fill = PatternFill("solid", fgColor=STAGE_FILL[v])
                cell.font = F(bold=True, size=10, color=INK)
            if c[4] == "wrap" and isinstance(v, str):
                lines = max(lines, v.count("\n") + 1, len(v) // max(1, int(c[3] * 1.1)) + 1)
        if l.get("match_confidence") not in ("HIGH", None) and l.get("pursue"):
            mc = [i for i, c in enumerate(cols, 1) if c[1] == "Match"]
            for i in mc:
                ws.cell(r, i).fill = PatternFill("solid", fgColor="FFE699")
        ws.row_dimensions[r].height = min(15 * lines, 90)
    sc = [i for i, c in enumerate(cols, 1) if c[4] == "score"]
    if sc and items:
        L = get_column_letter(sc[0])
        ws.conditional_formatting.add(f"{L}{hdr + 1}:{L}{r}",
                                      DataBarRule(start_type="num", start_value=0, end_type="num", end_value=100,
                                                  color="5B9BD5"))
    ws.freeze_panes = ws.cell(hdr + 1, 3)
    ws.auto_filter.ref = f"A{hdr}:{get_column_letter(len(cols))}{max(r, hdr + 1)}"
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation, ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = "landscape", 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{hdr}:{hdr}"
    return r


def summary(ws, leads, pursue):
    ws.sheet_view.showGridLines = False
    for col, w in zip("ABCDEFGHI", (3, 18, 18, 18, 18, 18, 18, 3, 3)):
        ws.column_dimensions[col].width = w
    ws.merge_cells("B2:G2")
    ws["B2"] = f"{COUNTY_LABEL} Pre-Foreclosure Leads"
    ws["B2"].font = F(bold=True, size=22, color=NAVY)
    dates = sorted(datetime.datetime.strptime(l["record_date"], "%m/%d/%Y") for l in leads)
    ws.merge_cells("B3:G3")
    ws["B3"] = (f"{CFG['area_label']}  ·  Lis pendens recorded "
                f"{dates[0]:%b %d} – {dates[-1]:%b %d, %Y}  ·  Built {TODAY}")
    ws["B3"].font = F(size=10, color=MUTED)
    ws.row_dimensions[2].height = 32

    court = [l for l in leads if l.get("court_stage")]
    kpis = [
        ("Filings pulled", len(leads)), ("Active leads", len(pursue)),
        ("Address matched", sum(1 for l in pursue if l.get("parcel_id"))),
        ("Estate / deceased", sum(1 for l in pursue if "DECEASED_OWNER" in l["tags"])),
        ("Absentee owners", sum(1 for l in pursue if l.get("absentee"))),
        ("Court files read", len(court)),
    ]
    for i, (label, n) in enumerate(kpis):
        c = 2 + i
        top, bot = ws.cell(5, c, n), ws.cell(6, c, label)
        top.font, bot.font = F(bold=True, size=24, color=NAVY), F(size=9, color=MUTED)
        for cell in (top, bot):
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.fill = PatternFill("solid", fgColor=BAND)
        top.border = Border(top=Side(style="thick", color=TEAL))
    ws.row_dimensions[5].height = 38

    def section(row, text):
        ws.cell(row, 2, text).font = F(bold=True, size=12, color=NAVY)
        for c in range(2, 8):
            ws.cell(row, c).border = Border(bottom=Side(style="medium", color=NAVY))

    section(8, "Lead mix")
    hdrs = ["Type", "Filings", "Active leads", "Avg score", "Median value", ""]
    for i, h in enumerate(hdrs):
        ws.cell(9, 2 + i, h).font = F(bold=True, size=10, color=MUTED)
    r = 10
    for t, name in TYPE_TEXT.items():
        allt = [l for l in leads if l["type"] == t]
        if not allt:
            continue
        act = [l for l in allt if l["pursue"]]
        vals = [l["just_value"] for l in act if l.get("just_value")]
        row = [name, len(allt), len(act), round(sum(l["score"] for l in act) / len(act)) if act else "",
               sorted(vals)[len(vals) // 2] if vals else ""]
        for i, v in enumerate(row):
            cell = ws.cell(r, 2 + i, v)
            cell.font = BODY_FONT
            cell.border = BORDER
            if i == 4:
                cell.number_format = '"$"#,##0'
        r += 1

    r += 1
    section(r, "Top 10 leads")
    r += 1
    for i, h in enumerate(["Score", "Case #", "Property", "", "Situation", "Court stage"]):
        ws.cell(r, 2 + i, h).font = F(bold=True, size=10, color=MUTED)
    for l in pursue[:10]:
        r += 1
        ws.merge_cells(start_row=r, start_column=4, end_row=r, end_column=5)
        sit = "; ".join([TAG_TEXT.get(t, t).split(":")[0] for t in l["tags"][:3]] +
                        [FLAG_TEXT.get(f, f).split(":")[0] for f in l.get("court_flags", [])[:2]])
        row = {2: l["score"], 3: l["case_number"], 4: l.get("property_address") or l["legal"][:40],
               6: sit, 7: l.get("court_stage") or "Not yet checked"}
        for c, v in row.items():
            cell = ws.cell(r, c, v)
            cell.font, cell.border = BODY_FONT, BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        if l.get("court_stage") in STAGE_FILL:
            ws.cell(r, 7).fill = PatternFill("solid", fgColor=STAGE_FILL[l["court_stage"]])
        ws.cell(r, 2).font = F(bold=True, size=11, color=NAVY)
        ws.cell(r, 2).alignment = Alignment(horizontal="center", vertical="top")
        ws.row_dimensions[r].height = 30

    r += 2
    section(r, "Read before using")
    notes = [
        "Score is preliminary (0–100): lead type, estate/reverse-mortgage, absentee, non-homestead, value band, "
        "match quality, and equity where the court debt band is known.",
        f"Equity range = {CFG['property_appraiser']['value_year']} market value minus the court's debt band (worst case to best case). Real payoff is in the complaint.",
        f"Market values are the {CFG['property_appraiser']['value_year']} certified roll and lag the market. Use comps before making an offer.",
        f"Court files read so far: {len(court)} of {len(pursue) + sum(1 for l in leads if l.get('drop_reason') == 'Court case dismissed')}. "
        "Leads marked 'Not yet checked' may already be dismissed.",
        "The county index runs about 1 week behind. Filings from the last few days are not in this pull.",
        "Phones/emails are blank until skip-trace results are loaded. Scrub against Do-Not-Call before dialing (FL FTSA).",
        "Buying from an owner in foreclosure is regulated (F.S. 501.1377): attorney-approved contract, 5-day rescission.",
    ]
    for n in notes:
        r += 1
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=7)
        c = ws.cell(r, 2, "•  " + n)
        c.font, c.alignment = F(size=10, color=INK), Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 28
    r += 2
    ws.cell(r, 2, f"Sources: {COUNTY_LABEL} Clerk Official Records · {COUNTY_LABEL} Clerk court dockets · "
                  f"{CFG['property_appraiser']['name']} data downloads").font = F(size=8, italic=True, color=MUTED)
    ws.page_setup.orientation = "portrait"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0


def court_sheet(ws, leads):
    items = [l for l in leads if l.get("court_stage")]
    items.sort(key=lambda l: (l["court_stage"] == "Closed / dismissed", -l["score"]))
    cols = [
        ("Lead", "Case #", "case_number", 11, ""),
        ("Lead", "Score", "score", 7, "score"),
        ("Property", "Property address", maps, 32, "link"),
        ("Owner & contact", "Owner(s)", lambda l: "\n".join(l["owners"][:4]), 28, "wrap"),
        ("Court file", "Stage", "court_stage", 18, "stage"),
        ("Court file", "Case type", "court_case_type", 30, "wrap"),
        ("Court file", "Debt band", "debt_band", 15, ""),
        ("Property", f'Market value ({CFG["property_appraiser"]["value_year"]})', "just_value", 12, "money"),
        ("Property", "Equity range", "equity_range", 15, "center"),
        ("Court file", "Filed", "court_filed", 10, ""),
        ("Court file", "Trial", "trial_month", 10, ""),
        ("Court file", "Judge", "judge", 16, ""),
        ("Situation", "What the docket shows", lambda l: "\n".join(FLAG_TEXT.get(f, f) for f in l.get("court_flags", [])), 34, "wrap"),
        ("Situation", "Key docket entries", lambda l: "\n".join(l.get("key_events", [])), 70, "wrap"),
        ("Record", "Pulled", "court_pulled", 10, ""),
    ]
    write_table(ws, items, cols, title="Court Findings",
                subtitle=f"Cases read from the {COUNTY_LABEL} Clerk court docket. Debt band comes from the court's case type.")


def key_sheet(ws):
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 26, 110
    ws["A1"] = "Key"
    ws["A1"].font = F(bold=True, size=16, color=NAVY)
    rows = [("COLUMNS", None),
            ("Score", "Preliminary 0–100. See Summary → Read before using."),
            ("Equity range", f"{CFG['property_appraiser']['value_year']} market value minus the court's debt band, worst to best case. Blank until the court file is read."),
            ("Stage", "From the court docket: Filed / Contested / Final judgment / Sale scheduled / Closed."),
            ("Debt band", "Amount in controversy from the court case type (roughly the loan balance)."),
            ("Homestead", "Owner claims homestead exemption (lives there)."),
            ("Absentee", "Owner's mailing street differs from the property street (rental, second home, or moved out)."),
            ("Match", "HIGH = owner name + lot/unit + subdivision agree. MEDIUM/LOW/LEGAL_ONLY = verify. Yellow = check."),
            ("Property address", "Click to open in Google Maps."),
            ("SITUATION TAGS", None)] + [(k.replace("_", " ").title(), v) for k, v in TAG_TEXT.items()] + \
           [("COURT FLAGS", None)] + [(k.replace("_", " ").title(), v) for k, v in FLAG_TEXT.items()] + \
           [("STAGE COLORS", None)] + [(k, "") for k in STAGE_FILL]
    r = 2
    for a, b in rows:
        r += 1
        ca = ws.cell(r, 1, a)
        if b is None:
            ca.font = F(bold=True, size=10, color="FFFFFF")
            ca.fill = ws.cell(r, 2).fill = PatternFill("solid", fgColor=NAVY)
            continue
        ca.font, ca.border = F(bold=True, size=10, color=INK), BORDER
        cb = ws.cell(r, 2, b)
        cb.font, cb.border = BODY_FONT, BORDER
        if a in STAGE_FILL:
            ca.fill = PatternFill("solid", fgColor=STAGE_FILL[a])


# ---- call tiers -----------------------------------------------------------------------------------
TIERS = [
    ("A", "Tier A: Call first",
     "Estates, reverse mortgages, and non-owner-occupied bank foreclosures. Heirs and landlords are the most motivated sellers.", "1E6B52"),
    ("B1", "Tier B1: Owner-occupants, bank foreclosure",
     "Behind on the mortgage and living in the home. Classic pre-foreclosure call: many reinstate, some sell. Be careful and respectful.", "2E7D7A"),
    ("B2", "Tier B2: HOA / condo lien",
     "Behind on HOA dues (usually small). Most pay it off once sued. Lowest odds of the callable groups; start with absentee owners.", "4F7FA8"),
    ("C", "Tier C: Investors / LLCs",
     "LLC-held or multi-property investor. One owner can hold several defaulted properties; call once. Phones are harder to trace.", "7A5C2E"),
    ("D", "Tier D: Skip for now",
     "Vacant land or no matched address. Not worth a skip-trace until fixed.", "8A939E"),
]
OUTCOMES = '"No answer,Left VM,Not interested,Interested,Wrong number,Do not call,Already resolved"'


def tier(l):
    t = set(l["tags"])
    if not l.get("parcel_id") or l.get("match_confidence") in ("NONE", "LOW"):
        return "D"
    if "COMMERCIAL" in t or "VACANT" in (l.get("land_use") or "").upper() or (l.get("just_value") or 0) < 20000:
        return "D"
    if "ENTITY_OWNED" in t or "MULTI_PROPERTY_OWNER" in t:
        return "C"
    if "DECEASED_OWNER" in t or "REVERSE_MORTGAGE" in t:
        return "A"
    if l["type"] == "BANK_MORTGAGE":
        return "B1" if l.get("homestead") else "A"
    if l["type"] == "HOA_CONDO_LIEN":
        return "B2"
    return "C"


def first_last(name):
    """Clerk index is 'LAST FIRST MIDDLE'; callers want 'First Middle Last'. Entities pass through."""
    n = re.sub(r"\b(PR|IND|EST|TR)\b", "", name).split()
    if re.search(r"\b(LLC|INC|CORP|TRUST)\b", name) or len(n) < 2:
        return " ".join(n).title()
    return " ".join(n[1:] + n[:1]).title()


def who_to_call(l):
    if l.get("estate"):
        e = l["estate"]
        return e["ask_for"] + (f'\nEstate attorney: {e["estate_attorney"]}' if e.get("estate_attorney") else "")
    o = l["owners"]
    pr = [x for x in o if re.search(r"\bPR\b", x)]
    if pr:
        return first_last(pr[0]) + " (personal rep)"
    if "DECEASED_OWNER" in l["tags"]:
        return "Heirs of " + first_last(o[0]) + " (names in court file)"
    if "MULTI_PROPERTY_OWNER" in l["tags"]:
        people = [x for x in o if not re.search(r"\b(LLC|INC)\b", x)]
        return first_last(people[0] if people else o[0]) + " (several in default)"
    return " & ".join(first_last(x) for x in o[:2]) if o else ""


def why_sell(l):
    return "\n".join([TAG_TEXT.get(t, t).split(":")[0] for t in l["tags"]] +
                     [FLAG_TEXT.get(f, f).split(":")[0] for f in l.get("court_flags", [])])


CALL_COLS = [
    ("Lead", "Score", "score", 7, "score"),
    ("Lead", "Case #", "case_number", 11, ""),
    ("Owner & contact", "Ask for", who_to_call, 34, "wrap"),
    ("Owner & contact", "Phones", "phones", 18, "wrap"),
    ("Owner & contact", "Emails", "emails", 22, "wrap"),
    ("Owner & contact", "Mailing address", "mailing_address", 28, "wrap"),
    ("Property", "Property address", maps, 30, "link"),
    ("Property", f'Value ({CFG["property_appraiser"]["value_year"]})', "just_value", 11, "money"),
    ("Property", "Equity range", "equity_range", 14, "center"),
    ("Property", "Lives there?", lambda l: ("Yes" if l.get("homestead") else "No") if l.get("parcel_id") else "?", 8, "center"),
    ("Situation", "Why they might sell", why_sell, 36, "wrap"),
    ("Court file", "Court stage", lambda l: l.get("court_stage") or "Not yet checked", 17, "stage"),
    ("Record", "Called", lambda l: "", 9, "center"),
    ("Record", "Outcome", lambda l: "", 16, ""),
    ("Record", "Notes", lambda l: "\n".join(x for x in [
        (f'Probate: {l["estate"]["probate_case"]}. {l["estate"]["notes"]}' if l.get("estate") else ""),
        l.get("skip_note", ""),
        f'REISkip: mortgage ${l["skip_mortgage"]:,.0f}, est. value ${l["skip_est_value"]:,.0f}'
        if l.get("skip_mortgage") and l.get("skip_est_value") else ""] if x), 34, "wrap"),
]


def call_sheet(ws, pursue):
    from openpyxl.worksheet.datavalidation import DataValidation
    ws.sheet_view.showGridLines = False
    ncol = len(CALL_COLS)
    ws.cell(1, 1, "Call List by Tier").font = F(bold=True, size=16, color=NAVY)
    ws.cell(2, 1, "Work top to bottom. Fill in Called / Outcome / Notes as you go. "
                  "Scrub phones against Do-Not-Call first.").font = F(italic=True, size=10, color=MUTED)
    for i, c in enumerate(CALL_COLS, 1):
        ws.column_dimensions[get_column_letter(i)].width = c[3]
    r = 4
    for i, c in enumerate(CALL_COLS, 1):
        cell = ws.cell(r, i, c[1])
        cell.font, cell.fill = HDR_FONT, PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[r].height = 28
    ws.freeze_panes = ws.cell(r + 1, 3)
    dv = DataValidation(type="list", formula1=OUTCOMES, allow_blank=True)
    ws.add_data_validation(dv)
    outcome_col = [i for i, c in enumerate(CALL_COLS, 1) if c[1] == "Outcome"][0]
    for code, name, desc, color in TIERS:
        items = sorted([l for l in pursue if tier(l) == code], key=lambda l: -l["score"])
        if not items:
            continue
        r += 2
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncol)
        h = ws.cell(r, 1, f"{name}   ·   {len(items)} lead{'s' if len(items) != 1 else ''}")
        h.font, h.alignment = F(bold=True, size=12, color="FFFFFF"), Alignment(vertical="center", indent=1)
        for i in range(1, ncol + 1):
            ws.cell(r, i).fill = PatternFill("solid", fgColor=color)
        ws.row_dimensions[r].height = 22
        r += 1
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncol)
        d = ws.cell(r, 1, desc)
        d.font, d.alignment = F(italic=True, size=10, color=INK), Alignment(indent=1)
        for i in range(1, ncol + 1):
            ws.cell(r, i).fill = PatternFill("solid", fgColor="EEF1F5")
        for n, l in enumerate(items):
            r += 1
            lines = 1
            for i, c in enumerate(CALL_COLS, 1):
                v = val(l, c)
                cell = ws.cell(r, i, v)
                cell.font, cell.border = BODY_FONT, BORDER
                cell.alignment = Alignment(vertical="top", wrap_text=c[4] in ("wrap", "link"),
                                           horizontal="center" if c[4] in ("center", "score") else None)
                if n % 2:
                    cell.fill = PatternFill("solid", fgColor=BAND)
                if c[4] == "money":
                    cell.number_format = '"$"#,##0'
                if c[4] == "link" and v:
                    cell.hyperlink = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(v)
                    cell.font = F(color="1F5FA8", underline="single", size=10)
                if c[4] == "stage" and v in STAGE_FILL:
                    cell.fill = PatternFill("solid", fgColor=STAGE_FILL[v])
                if c[4] == "wrap" and isinstance(v, str):
                    lines = max(lines, v.count("\n") + 1, len(v) // max(1, int(c[3] * 1.1)) + 1)
            ws.cell(r, 1).font = F(bold=True, size=11, color=color)
            dv.add(ws.cell(r, outcome_col))
            ws.row_dimensions[r].height = min(15 * lines, 90)
    ws.page_setup.orientation = "landscape"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = "4:4"


def main():
    leads = load_leads()
    pursue = sorted([l for l in leads if l["pursue"]], key=lambda l: -l["score"])

    wb = Workbook()
    summary(wb.active, leads, pursue)
    wb.active.title = "Summary"
    write_table(wb.create_sheet("Leads"), pursue, COLS, title="Active Leads",
                subtitle=f"{len(pursue)} leads, highest score first. Yellow 'Match' = verify the address. Click an address for Google Maps.")
    call_sheet(wb.create_sheet("Call List", 1), pursue)
    court_sheet(wb.create_sheet("Court Findings"), leads)
    rev = [l for l in pursue if l.get("match_confidence") != "HIGH"]
    write_table(wb.create_sheet("Review"), rev, COLS, title="Needs Review",
                subtitle="Parcel match is not high-confidence. Confirm the property before mailing or calling.")
    allc = [("Lead", "Kept?", lambda l: "Yes" if l["pursue"] else "No", 7, "center"),
            ("Lead", "Why dropped", lambda l: l.get("drop_reason", "") if not l["pursue"] else "", 22, "")] + COLS
    write_table(wb.create_sheet("All Filings"),
                sorted(leads, key=lambda l: (not l["pursue"], -l["score"])), allc, title="All Filings",
                subtitle=f"Every lis pendens pulled ({len(leads)}), including the ones dropped and why.")
    key_sheet(wb.create_sheet("Key"))
    for ws in wb.worksheets:
        ws.sheet_properties.tabColor = {"Summary": NAVY, "Call List": "1E6B52", "Leads": TEAL, "Court Findings": "6B3A5C",
                                        "Review": "C9A227", "All Filings": "5A6470", "Key": "A0A8B3"}[ws.title]

    os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)
    xlsx = os.path.join(ROOT, "output", f"foreclosure_leads_{TODAY}.xlsx")
    wb.save(xlsx)

    st = os.path.join(ROOT, "output", f"skiptrace_input_{TODAY}.csv")
    with open(st, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lead_id", "first_name", "last_name", "property_address", "property_city", "property_state",
                    "property_zip", "mailing_address", "mailing_city", "mailing_state", "mailing_zip"])
        for l in pursue:
            if not l.get("parcel_id") or l.get("match_confidence") == "NONE":
                continue
            person = next((o for o in l["owners"] if not re.search(r"\b(LLC|INC|CORP|TRUST|EST)\b", o)), None)
            if not person:
                continue
            p = re.sub(r"\b(EST|PR|TR|IND)\b", "", person).split()
            m = re.match(r"(.*), (.*) FL (\d{5})", l["property_address"] or "")
            mm = [x.strip() for x in (l.get("mailing_address") or "").split(",")]
            w.writerow([l["lead_id"], p[1].title() if len(p) > 1 else "", p[0].title(),
                        m.group(1) if m else "", m.group(2) if m else "", "FL", m.group(3) if m else "",
                        mm[0] if mm else "", mm[-3] if len(mm) >= 4 else "", mm[-2] if len(mm) >= 4 else "",
                        mm[-1][:5] if len(mm) >= 4 else ""])
    print("wrote", xlsx, "|", len(pursue), "active leads,", len(leads), "filings,",
          sum(1 for l in leads if l.get("court_stage")), "court files")


if __name__ == "__main__":
    main()
