"""Load the county config. Every script imports CFG and ROOT from here.

config/county.json is created during onboarding (see CLAUDE.md). Worked example: config/examples/martin-fl.json.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_path = os.environ.get("COUNTY_CONFIG", os.path.join(ROOT, "config", "county.json"))
if not os.path.exists(_path):
    sys.exit("No config/county.json yet. Run onboarding first: ask Claude to 'start onboarding' (see CLAUDE.md), "
             "or copy config/examples/martin-fl.json to config/county.json to try the Martin County example.")
CFG = json.load(open(_path, encoding="utf-8"))
COUNTY_LABEL = f'{CFG["county"]} County'

# Buyer profile from onboarding (buy box). Optional; defaults match the original Martin County run.
_pp = os.path.join(ROOT, "config", "profile.json")
PROFILE = json.load(open(_pp, encoding="utf-8")) if os.path.exists(_pp) else {}
PRICE_MIN = PROFILE.get("price_min", 200_000)
PRICE_MAX = PROFILE.get("price_max", 900_000)
