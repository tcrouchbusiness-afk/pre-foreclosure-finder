"""Build a skip-trace upload CSV from the scored leads.

Usage: python scripts/build_skiptrace.py --tiers B1,B2,C --name skiptrace2
       python scripts/build_skiptrace.py --cases "26 733 CA,26 839 CA" --name test4

- Living owners are traced at the property + mailing address, with condo unit in its own column
  (without it, providers match the wrong unit's owner).
- One row per person: an investor with 7 defaulted LLC properties is traced once.
- LLC/trust-only leads are skipped (find the people on the state business registry instead).
- Estate leads (tier A): the dead owner is useless to trace. Put the personal rep / heirs in
  data/estate_research.json under "trace" and they are added by name + city.
"""
import argparse, csv, json, os, re, sys
from collections import Counter
from config import CFG, ROOT

sys.path.insert(0, os.path.dirname(__file__))
from export_excel import load_leads, tier  # noqa: E402


def split_addr(a):
    m = re.match(r"(.*?)(?:\s+UNIT\s+(\S+))?,\s*(.*)\s+FL\s+(\d{5})", a or "")
    return (m.group(1), m.group(2) or "", m.group(3), m.group(4)) if m else ("", "", "", "")


def split_mail(a):
    p = [x.strip() for x in (a or "").split(",")]
    return (p[0], p[-3], p[-2], p[-1][:5]) if len(p) >= 4 else ("", "", "", "")


def person(name):
    n = re.sub(r"\b(EST|PR|TR|IND)\b", "", name).split()  # clerk index is LAST FIRST MIDDLE
    return (" ".join(n[1:]).title(), n[0].title()) if len(n) > 1 else ("", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="B1,B2,C")
    ap.add_argument("--cases", default="")
    ap.add_argument("--name", default="skiptrace")
    a = ap.parse_args()
    tiers = set(a.tiers.split(",")) if not a.cases else set()
    cases = {c.strip() for c in a.cases.split(",") if c.strip()}

    rows, skipped, seen = [], [], set()
    for l in load_leads():
        if not l["pursue"]:
            continue
        t = tier(l)
        if not ((cases and l["case_number"] in cases) or (t in tiers)):
            continue
        if t == "A" and not cases:
            continue  # estates come from estate_research.json below
        ppl = [o for o in l["owners"] if not re.search(r"\b(LLC|INC|CORP|TRUST|EST)\b", o)]
        if not ppl:
            skipped.append(f'{l["case_number"]} ({l["owners"][0] if l["owners"] else "no owner"})')
            continue
        first, last = person(ppl[0])
        key = (first.split()[0] if first else "", last)
        if key in seen:
            continue
        seen.add(key)
        st, unit, city, z = split_addr(l.get("property_address"))
        ms, mc, mst, mz = split_mail(l.get("mailing_address"))
        rows.append([l["lead_id"], l["case_number"], t, first, last, st, unit, city, CFG["state"], z,
                     ms, mc, mst, mz, "Property owner"])

    ep = os.path.join(ROOT, "data", "estate_research.json")
    if os.path.exists(ep) and ("A" in tiers or cases):
        for case, e in json.load(open(ep, encoding="utf-8")).items():
            if case.startswith("_") or (cases and case not in cases):
                continue
            for p in e.get("trace", []):
                rows.append([e.get("lead_id", ""), case, "A", p["first"], p["last"], p.get("street", ""), "",
                             p.get("city", CFG["default_city"]), CFG["state"], p.get("zip", ""),
                             "", "", "", "", p.get("who", "Estate contact")])

    hdr = ["lead_id", "Case", "Tier", "First Name", "Last Name", "Street Address", "Unit", "City", "State",
           "Zip Code", "Mailing Street Address", "Mailing City", "Mailing State", "Mailing Zip Code", "Who"]
    out = os.path.join(ROOT, "output", f"{a.name}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        w.writerows(rows)
    price = CFG.get("skip_trace", {}).get("price_per_record_usd", 0.15)
    print(f"wrote {out}: {len(rows)} rows {dict(Counter(r[2] for r in rows))}, est ${len(rows) * price:.2f}")
    if skipped:
        print("skipped (no person to trace):", "; ".join(skipped))


if __name__ == "__main__":
    main()
