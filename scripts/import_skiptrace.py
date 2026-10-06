"""Turn a skip-trace provider's results file into data/skiptrace/<name>.csv keyed by lead_id.

Usage: python scripts/import_skiptrace.py output/ContactList.csv --upload output/skiptrace2.csv

Matching: lead_id column if the provider kept it; otherwise last name + first name (+ street) against
the upload file you sent. Rows that match nothing are reported, not guessed.
Built for REISkip's ContactList.csv (Phone 1..N, Phone N Type, Email 1..3, Mortgage Amount,
Estimated Value, Loan To Value, Primary Owner First/Last). Other providers: adjust COLS.
"""
import argparse, csv, os, re
from config import ROOT


def norm(s):
    return re.sub(r"[^A-Z0-9 ]", "", (s or "").upper()).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--upload", required=True, help="the CSV you uploaded (has lead_id)")
    ap.add_argument("--name", default=None)
    a = ap.parse_args()

    alias = {"first_name": "First Name", "last_name": "Last Name", "property_address": "Street Address",
             "street_address": "Street Address", "who": "Who"}
    sent = [{alias.get(k, k): v for k, v in s.items()}
            for s in csv.DictReader(open(a.upload, encoding="utf-8-sig"))]
    for s in sent:
        s.setdefault("Street Address", "")
        s.setdefault("Who", "")
    by_name = {}
    for s in sent:
        k = (norm(s["Last Name"]), norm(s["First Name"]).split()[0] if s["First Name"] else "")
        by_name.setdefault(k, []).append(s)

    out_rows, unmatched = [], []
    for r in csv.DictReader(open(a.results, encoding="utf-8-sig")):
        lid = r.get("lead_id")
        src = None
        if not lid:
            k = (norm(r.get("Last Name")), norm(r.get("First Name")).split()[0] if r.get("First Name") else "")
            cands = by_name.get(k, [])
            if len(cands) > 1:
                cands = [c for c in cands if norm(c["Street Address"])[:10] == norm(r.get("Street Address"))[:10]] or cands
            if cands:
                src, lid = cands[0], cands[0]["lead_id"]
        if not lid:
            unmatched.append(f'{r.get("First Name")} {r.get("Last Name")}')
            continue
        phones = [f'{r[k]} ({r.get(k + " Type", "")})'.replace(" ()", "") for k in r
                  if re.fullmatch(r"Phone \d+", k) and r[k]]
        emails = [r[k] for k in r if re.fullmatch(r"Email \d+", k) and r[k]]
        notes = []
        if src and src.get("Who") and src["Who"] != "Property owner":
            notes.append(src["Who"])
        po = f'{r.get("Primary Owner First", "")} {r.get("Primary Owner Last", "")}'.strip()
        if po and norm(r.get("Last Name")) not in norm(po) and src and src.get("Street Address"):
            notes.append(f"VERIFY: provider matched the property to owner {po.title()}")
        if not phones and not emails:
            notes.append("No match from provider")
        out_rows.append([lid, " / ".join(phones), " / ".join(emails), "; ".join(notes),
                         r.get("Mortgage Amount", ""), r.get("Estimated Value", ""), r.get("Loan To Value", "")])

    name = a.name or os.path.splitext(os.path.basename(a.upload))[0] + "_results"
    out = os.path.join(ROOT, "data", "skiptrace", f"{name}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lead_id", "phones", "emails", "skip_note", "skip_mortgage", "skip_est_value", "skip_ltv"])
        w.writerows(out_rows)
    hits = sum(1 for r in out_rows if r[1])
    print(f"wrote {out}: {len(out_rows)} rows, {hits} with phones")
    if unmatched:
        print("UNMATCHED (not imported):", ", ".join(unmatched))


if __name__ == "__main__":
    main()
