"""Parse saved CCIS case pages (data/ccis/*.json) into structured court facts per case.

Output: data/ccis_parsed.json keyed by the short case number used in leads ("26 733 CA").
Deterministic regex only. Each field says where it came from so it can be checked on the docket.
"""
import glob, json, os, re
from config import ROOT



def short(cn):  # 26000733CAAXMX -> "26 733 CA"
    m = re.match(r"(\d{2})(\d{6})(CA|CC)", cn)
    return f"{m.group(1)} {int(m.group(2))} {m.group(3)}" if m else cn


def parse(cn, page):
    t = page["text"]
    g = lambda pat: (re.search(pat, t) or [None, ""])[1].strip()
    case_type = g(r"Case Type:\s*\n?(.*)")
    status = g(r"\nStatus:\s*\n?(.*)")
    filed = g(r"Clerk File Date:\s*\n?(.*)")
    judge = g(r"Judge:\s*\n?(.*)")
    band = g(r"\$([\d,]+-\$[\d,]+|\d[\d,]*\+)")
    homestead = "NONHOME" not in case_type and "HOMESTEAD" in case_type

    docket = t.split("CASE DOCKETS")[-1]
    entries = []
    for line in docket.split("\n"):
        m = re.match(r"\s*\d+\s+\d*\s*(\d{1,2}/\d{1,2}/\d{4})\s+(.*)", line)
        if m and not re.search(r"ASSESSED|PAYMENT \$|PROPOSED 20 DAY", m.group(2)):
            entries.append((m.group(1), m.group(2).strip()))

    def has(p):
        return [e for e in entries if re.search(p, e[1])]

    flags = []
    if has(r"VOLUNTARY DISMISSAL|ORDER OF DISMISSAL|DISMISSED"):
        flags.append("DISMISSED")
    if has(r"FINAL JUDGMENT"):
        flags.append("FINAL_JUDGMENT")
    if has(r"NOTICE OF SALE|SALE SCHEDULED|CERTIFICATE OF SALE"):
        flags.append("SALE_SET")
    if has(r"BANKRUPTCY"):
        flags.append("BANKRUPTCY")
    if has(r"\bANSWER\b"):
        flags.append("CONTESTED")
    if has(r"DEFAULT"):
        flags.append("DEFAULT_ENTERED")
    if has(r"UNKNOWN TENANT.*SERVED ON|SERVED ON UNKNOWN TENANT|TENANT #\d N/K/A"):
        flags.append("TENANT_OCCUPIED")
    if has(r"PUBLICATION|CONSTRUCTIVE SERVICE"):
        flags.append("SERVICE_BY_PUBLICATION")
    trial = has(r"SETTING TRIAL IN ([A-Z]+ \d{4})")
    trial_month = re.search(r"SETTING TRIAL IN ([A-Z]+ \d{4})", trial[0][1]).group(1).title() if trial else ""

    key = [f"{d}: {e[:110]}" for d, e in entries if re.search(
        r"DISMISS|JUDGMENT|SALE|DEFAULT|ANSWER|TRIAL|BANKRUPT|SERVED ON|MEDIAT|TENANT", e)][:6]

    if "DISMISSED" in flags or status.upper().startswith("CLOSED"):
        stage = "Closed / dismissed"
    elif "SALE_SET" in flags:
        stage = "Sale scheduled"
    elif "FINAL_JUDGMENT" in flags:
        stage = "Final judgment"
    elif "CONTESTED" in flags:
        stage = "Contested, pre-trial"
    else:
        stage = "Filed, serving defendants"

    return short(cn), {
        "court_case_number": cn, "court_status": status, "court_stage": stage, "court_filed": filed,
        "court_case_type": case_type, "debt_band": f"${band}" if band else "", "court_homestead": homestead,
        "judge": judge, "trial_month": trial_month, "court_flags": flags,
        "docket_entries": len(entries), "key_events": key, "court_pulled": page.get("pulled", "")[:10],
    }


def main():
    out = {}
    for f in glob.glob(os.path.join(ROOT, "data", "ccis", "*.json")):
        for cn, page in json.load(open(f, encoding="utf-8")).items():
            k, v = parse(cn, page)
            out[k] = v
    json.dump(out, open(os.path.join(ROOT, "data", "ccis_parsed.json"), "w", encoding="utf-8"), indent=1)
    for k, v in out.items():
        print(k, "|", v["court_stage"], "|", v["debt_band"], "|", v["trial_month"], "|", ",".join(v["court_flags"]))


if __name__ == "__main__":
    main()
