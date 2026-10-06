"""Classify raw county lis pendens rows into foreclosure leads.

Input:  data/raw/lis_pendens_*.json  (rows pulled from Landmark Web, doc type LP)
Output: data/leads.json  (one row per lis pendens, with type, owners, tags)

Deterministic rules only; no LLM. Every rule is visible here so a wrong
classification can be traced to the line that made it.
"""
import json, re, sys, glob, os
from config import CFG, ROOT
from collections import Counter


BANK_WORDS = re.compile(r"\b(BANK|MORTGAGE|LOAN SERVICING|SERVICING|FINANCIAL|FINANCE|LENDING|NEWREZ|"
                        r"SAVINGS FUND|TRUST COMPANY|NATIONAL ASSOCIATION|CREDIT UNION|SECURITIZATION|"
                        r"ACQUISITION TRUST|ROCKET|CARRINGTON|LAKEVIEW|LONGBRIDGE|SELENE|TRUIST|SOFI|SWBC)\b")
REVERSE_MORTGAGE = re.compile(r"\b(LONGBRIDGE|RECONVERSE|FINANCE OF AMERICA REVERSE|MUTUAL OF OMAHA MORTGAGE)\b")
ASSOC_WORDS = re.compile(r"\b(ASSOCIATION|ASSN|CONDOMINIUM|COUNTRY CLUB|CLUB INC|PROPERTY OWNERS|HOMEOWNERS|COMMUNITY)\b")
TIMESHARE = re.compile(r"\bUNIT WEEK\b")
CONTRACTOR = re.compile(r"\b(CONSTRUCTION|BUILDING SERVICES|ROOF|ROOFING|PLUMBING|ELECTRIC)\b")
GOV_OR_LIENHOLDER = re.compile(r"\b(UNITED STATES|SECRETARY OF HOUSING|SMALL BUSINESS ADMINISTRATION|DEPARTMENT|"
                               r"DEPARTMEN|FLORIDA HOUSING|" + "|".join(map(re.escape, CFG.get("government_parties_extra", []))) + "|"
                               r"FPL|SERVICE FINANCE|PREFEERRED CREDIT|PREFERRED CREDIT|UNLOCK PARTNERSHIP|"
                               r"PROLINE|WHITING)\b")
CASE_NO = re.compile(r"^\d{2}\s+\d+(\s+(CA|CC))?$")
ENTITY = re.compile(r"\b(LLC|INC|CORP|LP|LAND TRUST|TRUST|HOLDINGS)\b")


def split_parties(s):
    return [p.strip() for p in s.split(";") if p.strip()]


def classify(r):
    grantor, grantee, legal = r["grantor"], r["grantee"], r["legal"]
    parties = split_parties(grantee)
    case = next((p for p in parties if CASE_NO.match(p)), "")
    court = "CA" if case.endswith("CA") else "CC" if case.endswith("CC") else ""

    owners = [p for p in parties
              if p != case and not ASSOC_WORDS.search(p) and not GOV_OR_LIENHOLDER.search(p)
              and not BANK_WORDS.search(p)]

    tags = []
    if TIMESHARE.search(legal):
        kind = "TIMESHARE"
    elif BANK_WORDS.search(grantor):
        kind = "BANK_MORTGAGE"
    elif ASSOC_WORDS.search(grantor):
        kind = "HOA_CONDO_LIEN"
    elif CONTRACTOR.search(grantor):
        kind = "CONTRACTOR_LIEN"
    elif re.search(r"\b(LLC|INC|CORP|LP)\b", grantor):
        kind = "PRIVATE_LENDER_OR_BUSINESS"
    else:
        kind = "PRIVATE_PARTY"  # family/partition/contract disputes; read the complaint

    if REVERSE_MORTGAGE.search(grantor):
        tags.append("REVERSE_MORTGAGE")
    if any(re.search(r"\bEST\b", p) for p in owners):
        tags.append("DECEASED_OWNER")
    if any(re.search(r"\bPR\b", p) for p in owners):
        tags.append("PERSONAL_REP")
    if any(re.search(r"\b(TR|TRUST)\b", p) for p in owners):
        tags.append("TRUST_OWNED")
    if any(re.search(r"\b(LLC|INC|CORP)\b", p) for p in owners):
        tags.append("ENTITY_OWNED")
    if re.search(r"SECRETARY OF HOUSING", grantee):
        tags.append("HUD_LIEN")
    if re.search(r"UNITED STATES|SMALL BUSINESS ADMINISTRATION|DEPARTMENT OF REVENUE", grantee):
        tags.append("GOV_LIEN")
    if ASSOC_WORDS.search(grantee) and kind == "BANK_MORTGAGE":
        tags.append("HOA_ALSO_NAMED")
    if re.search(r"INDUSTRIAL|COMMERCIAL|WAREHOUSE", legal) or re.search(r"TECHNOLOGIES|VENTURES", grantor):
        tags.append("COMMERCIAL")
    if "MOBILE HOME" in legal:
        tags.append("MOBILE_HOME")
    if re.search(r"\b(UNIT|CONDOMINIUM|APARTMENT)\b", legal) and kind != "TIMESHARE":
        tags.append("CONDO")

    # First pass "is this worth a look" flag. Timeshares and business suits are out.
    pursue = "COMMERCIAL" not in tags and kind in ("BANK_MORTGAGE", "HOA_CONDO_LIEN", "PRIVATE_LENDER_OR_BUSINESS") \
        and not ("ENTITY_OWNED" in tags and kind == "PRIVATE_LENDER_OR_BUSINESS" and not owners)

    # Dedupe owner name variants ("NOHAVA EDWARD", "NOHAVA EDWARD A") -> keep the longest per surname+first.
    uniq = {}
    for o in owners:
        k = " ".join(re.sub(r"\b(EST|PR|TR|IND|JR|SR|II|III)\b", "", o).split()[:2])
        if len(o) > len(uniq.get(k, "")):
            uniq[k] = o

    return {
        "record_date": r["date"], "clerk_file_number": r["cfn"], "book_page": f'{r["book"]}/{r["page"]}',
        "case_number": case, "court": court, "plaintiff": grantor, "type": kind,
        "owners": list(uniq.values()), "all_defendants": parties, "legal": legal,
        "tags": tags, "pursue": pursue,
    }


def main():
    files = sorted(glob.glob(os.path.join(ROOT, "data", "raw", "lis_pendens_*.json")))
    if not files:
        sys.exit("no raw files in data/raw")
    seen, leads = set(), []
    for f in files:
        for r in json.load(open(f, encoding="utf-8")):
            if r["cfn"] in seen:
                continue
            seen.add(r["cfn"])
            leads.append(classify(r))
    # Same owner name on several filings = an investor in multi-property distress.
    counts = Counter(o.split()[0] + " " + o.split()[1] for l in leads for o in l["owners"]
                     if len(o.split()) > 1 and not ENTITY.search(o))
    for l in leads:
        if any(len(o.split()) > 1 and counts[o.split()[0] + " " + o.split()[1]] >= 3 for o in l["owners"]):
            l["tags"].append("MULTI_PROPERTY_OWNER")
    json.dump(leads, open(os.path.join(ROOT, "data", "leads.json"), "w", encoding="utf-8"), indent=1)
    print(len(leads), "lis pendens;", Counter(l["type"] for l in leads))
    print("pursue:", sum(l["pursue"] for l in leads))


if __name__ == "__main__":
    main()
