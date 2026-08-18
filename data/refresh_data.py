"""refresh_data.py -- fetch and rebuild every data file in data/.

Two source types, refreshed differently:

  1. OurAirports (airports.csv, runways.csv) -- a stable public CSV feed,
     no key, no rate limit, refreshed for real on every run.
  2. FAA Commercial Service Enplanements (CY2025 preliminary + CY2024
     final xlsx) -- FAA's own official passenger-boarding counts,
     published annually with roughly a 6-month lag. Refetched every run;
     the file names/paths change year to year, so if this 404s, check
     https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger
     for the current filenames and update FAA_CY_CURRENT_URL /
     FAA_CY_PRIOR_URL below.

Then build_candidates() joins both into data/candidates.json (the
per-airport dataset the tools read) and data/anc_routes.json (Anchorage
route/distance data for the long-haul-percentage question -- see that
function's docstring for why the route source is OpenFlights, not BTS).

Run:
    python data/refresh_data.py
"""
from __future__ import annotations

import csv
import json
import math
import urllib.request
from datetime import date
from pathlib import Path

import openpyxl

DATA_DIR = Path(__file__).parent

OURAIRPORTS_AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OURAIRPORTS_RUNWAYS_URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"

FAA_CY_CURRENT_URL = "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/arp-cy2025-commercial-service-enplanements-preliminary.xlsx"
FAA_CY_PRIOR_URL = "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/arp-cy2024-commercial-service-enplanements.xlsx"

OPENFLIGHTS_ROUTES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"

NEW_ENGLAND = {"US-ME", "US-NH", "US-VT", "US-MA", "US-RI", "US-CT"}

# 'core' = named or implied by the brief's four example questions
# (New England set / LA basin / Anchorage / SF Bay Area). 'context' =
# major national hubs added for ranking breadth, not individually
# required by the brief. See DECISIONS.md for why these 27.
TARGETS = {
    "BOS": "core", "BDL": "core", "PWM": "core", "PVD": "core", "MHT": "core",
    "BGR": "core", "BTV": "core", "ORH": "core", "HVN": "core", "PSM": "core",
    "LAX": "core", "SNA": "core", "BUR": "core", "LGB": "core", "ONT": "core",
    "ANC": "core",
    "SFO": "core", "OAK": "core", "SJC": "core",
    "ATL": "context", "ORD": "context", "DFW": "context", "DEN": "context",
    "JFK": "context", "SEA": "context", "PHX": "context", "MIA": "context",
}


def fetch_sources() -> None:
    for name, url in (
        ("airports.csv", OURAIRPORTS_AIRPORTS_URL),
        ("runways.csv", OURAIRPORTS_RUNWAYS_URL),
        ("faa_cy2025_enplanements_preliminary.xlsx", FAA_CY_CURRENT_URL),
        ("faa_cy2024_enplanements.xlsx", FAA_CY_PRIOR_URL),
        ("openflights_routes.dat", OPENFLIGHTS_ROUTES_URL),
    ):
        dest = DATA_DIR / name
        print(f"fetching {url} -> {dest}")
        urllib.request.urlretrieve(url, dest)
        print(f"  ok, {dest.stat().st_size:,} bytes")


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _load_faa(path: Path) -> dict[str, dict]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    out = {}
    for r in rows[1:]:
        if not r or not r[3]:
            continue
        _rank, ro, st, locid, _city, _name, _sl, hub, this_yr, last_yr, pct = r[:11]
        out[locid] = {
            "region_office": ro, "state": st, "hub_class": hub,
            "enplanements": this_yr, "enplanements_prior_year": last_yr, "pct_change": pct,
        }
    return out


def build_candidates() -> None:
    """Joins OurAirports (geo/type/runways) with FAA enplanements
    (CY2025 preliminary + CY2024 final) into data/candidates.json, one
    row per airport in TARGETS."""
    airports, id_to_iata = {}, {}
    with open(DATA_DIR / "airports.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["iata_code"] in TARGETS:
                airports[row["iata_code"]] = row
                id_to_iata[row["id"]] = row["iata_code"]
    missing = set(TARGETS) - set(airports)
    if missing:
        raise RuntimeError(f"missing from OurAirports: {missing}")

    runway_count = dict.fromkeys(TARGETS, 0)
    with open(DATA_DIR / "runways.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            iata = id_to_iata.get(row["airport_ref"])
            if iata and row.get("closed") != "1":
                runway_count[iata] += 1

    faa_2025 = _load_faa(DATA_DIR / "faa_cy2025_enplanements_preliminary.xlsx")
    faa_2024 = _load_faa(DATA_DIR / "faa_cy2024_enplanements.xlsx")
    missing_faa = set(TARGETS) - set(faa_2025)
    if missing_faa:
        raise RuntimeError(f"missing from FAA CY2025: {missing_faa}")

    def nearest_competitor(iata: str) -> tuple[str, float]:
        lat1 = float(airports[iata]["latitude_deg"])
        lon1 = float(airports[iata]["longitude_deg"])
        best, best_d = None, float("inf")
        for other in TARGETS:
            if other == iata:
                continue
            lat2 = float(airports[other]["latitude_deg"])
            lon2 = float(airports[other]["longitude_deg"])
            d = haversine_miles(lat1, lon1, lat2, lon2)
            if d < best_d:
                best, best_d = other, d
        return best, round(best_d, 1)

    candidates = {}
    for iata, tier in sorted(TARGETS.items()):
        a = airports[iata]
        f25, f24 = faa_2025[iata], faa_2024.get(iata, {})
        nearest_iata, nearest_mi = nearest_competitor(iata)
        candidates[iata] = {
            "name": a["name"],
            "municipality": a["municipality"],
            "iso_region": a["iso_region"],
            "is_new_england": a["iso_region"] in NEW_ENGLAND,
            "tier": tier,
            "ourairports_type": a["type"],
            "latitude_deg": float(a["latitude_deg"]),
            "longitude_deg": float(a["longitude_deg"]),
            "runway_count": runway_count[iata],
            "faa_hub_class": f25["hub_class"],
            "enplanements_cy2025_prelim": f25["enplanements"],
            "enplanements_cy2024": f24.get("enplanements", f25["enplanements_prior_year"]),
            "enplanements_cy2023": f24.get("enplanements_prior_year"),
            "yoy_pct_change_2025": round(f25["pct_change"], 4) if f25["pct_change"] is not None else None,
            "yoy_pct_change_2024": round(f24["pct_change"], 4) if f24.get("pct_change") is not None else None,
            "nearest_competitor_iata": nearest_iata,
            "nearest_competitor_mi": nearest_mi,
        }

    out = {
        "_meta": {
            "description": (
                "Per-airport candidate metrics. 'core' tier = airports named or implied "
                "by the brief's four example questions. 'context' tier = major national "
                "hubs added for ranking breadth."
            ),
            "sources": {
                "geo_type_runways": "OurAirports bulk CSV, fetched live",
                "enplanements": "FAA Commercial Service Enplanements, CY2025 preliminary + "
                                 "CY2024 final, fetched live from faa.gov",
            },
            "fetched_at": str(date.today()),
            "nearest_competitor_caveat": (
                "Computed only against the other 26 airports in this candidate set, not "
                "the full US airport universe. Trustworthy for 'core' tier airports (the "
                "set was built so each core airport's real nearest competitor is in it); "
                "'context' tier values are an artifact of this set's composition, not a "
                "real geographic claim."
            ),
            "airport_count": len(candidates),
        },
        "airports": candidates,
    }
    (DATA_DIR / "candidates.json").write_text(json.dumps(out, indent=2))
    print(f"wrote candidates.json: {len(candidates)} airports")


def build_anc_routes() -> None:
    """Builds data/anc_routes.json -- distinct scheduled routes out of
    ANC with great-circle distance, for the 'percentage of long-haul
    flights out of Anchorage' question.

    Source is OpenFlights routes.dat, NOT BTS T-100 (the authoritative
    source for actual scheduled departures/seats/passengers per route),
    because T-100 is blocked behind TranStats' bot-protected download
    portal (verified: the PREZIP listing loads, HTTP 200; the actual
    file GET returns HTTP 404 behind an F5 session-cookie challenge),
    and data.transportation.gov's Socrata catalog does not carry T-100
    either. OpenFlights is a community-maintained, no-key dataset that
    is NOT continuously updated (last touched circa 2014), used here as
    a stated fallback, not presented as current.

    KNOWN LIMITATION: this is route EXISTENCE, not flight FREQUENCY -- a
    route flown daily and one flown weekly count identically (one row
    each). 'Percentage of long-haul flights' therefore actually measures
    'percentage of long-haul ROUTES' in this dataset -- and the two
    likely diverge, since short-haul Bush-Alaska routes plausibly fly
    more frequently than long-haul trunk routes, which would make the
    true flight-weighted long-haul share LOWER than what's reported
    here. If a real T-100 extract becomes available, swap it in.
    """
    geo = {}
    with open(DATA_DIR / "airports.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["iata_code"]:
                geo[row["iata_code"]] = (float(row["latitude_deg"]), float(row["longitude_deg"]), row["name"])
    anc_lat, anc_lon, _ = geo["ANC"]

    dest_codes = set()
    with open(DATA_DIR / "openflights_routes.dat", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 5:
                continue
            src, dst = row[2], row[4]
            if src == "ANC" and dst != "\\N":
                dest_codes.add(dst)

    routes, missing_geo = [], []
    for dst in sorted(dest_codes):
        if dst in geo:
            lat, lon, name = geo[dst]
            dist = round(haversine_miles(anc_lat, anc_lon, lat, lon), 1)
            routes.append({"destination_iata": dst, "destination_name": name, "distance_mi": dist})
        else:
            missing_geo.append(dst)
    routes.sort(key=lambda r: -r["distance_mi"])

    out = {
        "_meta": {
            "description": (
                "Distinct scheduled routes with a source of ANC, one row per unique "
                "destination, with great-circle distance from ANC."
            ),
            "source": "OpenFlights routes.dat, joined to OurAirports for destination coordinates",
            "fetched_at": str(date.today()),
            "why_not_bts_t100": build_anc_routes.__doc__.split("KNOWN LIMITATION")[0].strip(),
            "known_limitation": "KNOWN LIMITATION" + build_anc_routes.__doc__.split("KNOWN LIMITATION")[1].strip(),
            "missing_destination_geo": missing_geo,
            "route_count": len(routes),
        },
        "routes": routes,
    }
    (DATA_DIR / "anc_routes.json").write_text(json.dumps(out, indent=2))
    print(f"wrote anc_routes.json: {len(routes)} routes")


if __name__ == "__main__":
    fetch_sources()
    build_candidates()
    build_anc_routes()
