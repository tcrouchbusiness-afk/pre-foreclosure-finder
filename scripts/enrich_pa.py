"""Match each lead to a county parcel using the Property Appraiser's free bulk files.

Inputs:  data/leads.json, data/pa/*/  (see config/county.json property_appraiser; scripts/download_pa.py)
Output:  data/leads_enriched.json

Match method (deterministic):
  1. Candidate parcels = parcels where any lead owner's LAST + FIRST name appears in the PA owner list.
  2. Score each candidate by overlap between the lis pendens legal description and the PA legal
     (lot/unit numbers count double, subdivision words count once).
  3. Best score wins. match_confidence = HIGH (lot number + subdivision word matched),
     MEDIUM (one of them), LOW (name only), NONE.
Never trust LOW matches without eyeballing; they are flagged in the Excel.
"""
import csv, glob, json, os, re, sys
from collections import defaultdict
from config import CFG, ROOT

csv.field_size_limit(10**9)
PA = os.path.join(ROOT, "data", "pa")
STOP = set("LOT LOTS BLOCK BLK OF THE AND A IN UNIT NO NUMBER PLAT PHASE SECTION SEC TWP RGE PB PG "
           "SUBDIVISION SUB CONDOMINIUM CONDO PARCEL AT BUILDING BLDG ALL THAT PART PORTION ACCORDING TO "
           "THEREOF RECORDED BOOK PAGE COUNTY PUD P.U.D. LYING WEST EAST NORTH SOUTH".split()) | set(CFG.get("legal_stopwords_extra", []))
SUFFIX = re.compile(r"\b(EST|PR|TR|IND|JR|SR|II|III|IV)\b")


def pa_file(key):
    """The one CSV inside data/pa/<key>/ (scripts/download_pa.py extracts each dataset there)."""
    hits = glob.glob(os.path.join(PA, key, "*.csv"))
    if not hits:
        sys.exit(f"missing data/pa/{key}/*.csv - run: python scripts/download_pa.py")
    return hits[0]


def rows(path):
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        yield from csv.DictReader(f, delimiter="|")


def norm(s):
    return re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper())


def tokens(legal):
    t = norm(legal).split()
    nums = {x for x in t if re.fullmatch(r"\d+[A-Z]?", x)}
    words = {x for x in t if x not in STOP and not x.isdigit() and len(x) > 2}
    return nums, words


def owner_key(name):
    """'NOHAVA EDWARD ANDREW' -> ('NOHAVA','EDWARD'). Clerk index is LAST FIRST MIDDLE."""
    p = SUFFIX.sub("", norm(name)).split()
    return (p[0], p[1]) if len(p) >= 2 else None


def main():
    leads = json.load(open(os.path.join(ROOT, "data", "leads.json"), encoding="utf-8"))
    wanted = {owner_key(o) for l in leads for o in l["owners"]} - {None}
    wanted_last = {k[0] for k in wanted}
    entity_names = {norm(o).strip() for l in leads for o in l["owners"] if re.search(r"\b(LLC|INC|TRUST)\b", o)}

    print("indexing owners…", file=sys.stderr)
    by_key = defaultdict(set)
    for r in rows(pa_file("owners")):
        last = norm(r["OwnerLastName"]).strip()
        if r["OwnerType"] == "Organization":
            n = " ".join(last.split())
            if n in entity_names:
                by_key[("ENTITY", n)].add(r["PropertyID"])
            continue
        if last in wanted_last:
            first = norm(r["OwnerFirstName"]).split()[:1]
            if first and (last, first[0]) in wanted:
                by_key[(last, first[0])].add(r["PropertyID"])

    cand_ids = set().union(*by_key.values()) if by_key else set()

    # Fallback: leads whose owners matched no parcel -> search every legal description for one that
    # contains all of the lead's lot numbers and subdivision words. Accept only a unique hit.
    print("legal-only fallback…", file=sys.stderr)
    all_legal = {r["PropertyID"]: r["LegalDescription"] for r in rows(pa_file("legal"))}
    legal_fallback = {}
    for l in leads:
        keys = [owner_key(o) for o in l["owners"]] + [("ENTITY", " ".join(norm(o).split())) for o in l["owners"]]
        if any(by_key.get(k) for k in keys if k):
            continue
        ln, lw = tokens(l["legal"])
        if not ln or not lw:
            continue
        hits = [pid for pid, lg in all_legal.items()
                if (lambda pn, pw: ln <= pn and len(lw & pw) >= min(2, len(lw)))(*tokens(lg))]
        if len(hits) == 1:
            legal_fallback[l["clerk_file_number"]] = hits[0]
            cand_ids.add(hits[0])
    print(len(cand_ids), "candidate parcels", file=sys.stderr)

    master = {r["PropertyID"]: r for r in rows(pa_file("master"))
              if r["PropertyID"] in cand_ids}
    legal = {r["PropertyID"]: r["LegalDescription"] for r in rows(pa_file("legal"))
             if r["PropertyID"] in cand_ids}
    homestead = {r["PropertyID"] for r in rows(pa_file("exemptions"))
                 if r["PropertyID"] in cand_ids and r["Exemption"].strip() == CFG["property_appraiser"]["homestead_exemption_code"]}

    import glob, openpyxl
    values = {}
    vf = glob.glob(os.path.join(PA, "values", "*.xlsx"))
    if vf:
        ws = openpyxl.load_workbook(vf[0], read_only=True).active
        for r in ws.iter_rows(min_row=2, values_only=True):
            if str(r[0]) in cand_ids:
                values[str(r[0])] = r[4]

    out = []
    for l in leads:
        keys = [owner_key(o) for o in l["owners"]] + [("ENTITY", " ".join(norm(o).split())) for o in l["owners"]]
        cands = set().union(*(by_key.get(k, set()) for k in keys if k)) if keys else set()
        via_legal = not cands and l["clerk_file_number"] in legal_fallback
        if via_legal:
            cands = {legal_fallback[l["clerk_file_number"]]}
        ln, lw = tokens(l["legal"])
        best, best_score, best_conf = None, -1, "NONE"
        for pid in cands:
            pn, pw = tokens(legal.get(pid, "") + " " + master.get(pid, {}).get("SubdivisionDescription", ""))
            num_hit, word_hit = len(ln & pn), len(lw & pw)
            score = num_hit * 2 + word_hit
            if score > best_score:
                best, best_score = pid, score
                best_conf = "HIGH" if num_hit and word_hit else "MEDIUM" if (num_hit or word_hit) else "LOW"
        if via_legal and best:
            best_conf = "LEGAL_ONLY"  # owner name on the parcel differs: verify (sold? name variant?)
        l = dict(l, match_confidence=best_conf if best else "NONE", candidates=len(cands))
        m = master.get(best) if best else None
        if m:
            situs = " ".join(x for x in [m["SitusStartNumber"].strip("0") and m["SitusStartNumber"], m["SitusStreetDirection"],
                                         m["SitusStreetName"], m["SitusStreetWay"]] if x and x != "0").strip()
            situs = " ".join(situs.split())
            if m["CondoUnit"]:
                situs += f' UNIT {m["CondoUnit"]}'
            mailing = ", ".join(" ".join(x.split()) for x in [m["Mailing Address"], m["Mailing Address Line 2"], m["City"],
                                            m["StateProvince"], m["ZipCode"]] if x and x.strip())
            def f(x):
                try: return float(x or 0)
                except ValueError: return 0.0
            l.update(
                parcel_id=m["ParcelID"], property_address=f"{situs}, {m['SitusCity']} FL {m['SitusPostal']}".strip(", "),
                pa_owners=" / ".join(x for x in [m["Owner1"], m["Owner2"], m["Owner3"]] if x.strip()),
                mailing_address=mailing,
                # Absentee = mailing street number+name differs from the property's (ZIPs alone are unreliable).
                absentee=bool(m["Mailing Address"].strip()) and
                         norm(m["Mailing Address"]).split()[:2] != norm(situs).split()[:2],
                homestead=best in homestead, land_use=m["LandUseCodeDescription"],
                year_built=m["YearBuilt"], beds=m["Beds"], baths=m["Baths"], sqft=m["TotalFinishedArea"],
                just_value=float(values.get(best) or 0), value_source=os.path.basename(vf[0]) if vf else "", last_sale_price=f(m["SalePrice"]), last_sale_date=m["SaleDate"],
                pa_legal=legal.get(best, "")[:200],
            )
        out.append(l)

    json.dump(out, open(os.path.join(ROOT, "data", "leads_enriched.json"), "w", encoding="utf-8"), indent=1)
    from collections import Counter
    print("match confidence:", Counter(l["match_confidence"] for l in out if l["pursue"]))


if __name__ == "__main__":
    main()
