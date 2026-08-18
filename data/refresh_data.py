"""refresh_data.py -- fetch and rebuild every data file in data/.

EVERY source below is public and KEYLESS -- rebuilding data/ from
scratch needs no credentials and no signup.

  1. OurAirports (airports.csv, runways.csv) -- a stable public CSV feed,
     no key, no rate limit, refreshed for real on every run.
  2. FAA Commercial Service Enplanements (CY2025 preliminary + CY2024
     final xlsx) -- FAA's own official passenger-boarding counts,
     published annually with roughly a 6-month lag. Refetched every run;
     the file names/paths change year to year, so if this 404s, check
     https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger
     for the current filenames and update FAA_CY_CURRENT_URL /
     FAA_CY_PRIOR_URL below.
  3. US Census -- two pieces: the Geocoder (airport coordinates -> county
     FIPS) and the Population Estimates Vintage 2025 county flat file
     (population + migration components, 2020-2025).
  4. BTS T100 Segment Summary By Origin Airport, filtered to ANC
     (bts_anc_origin_summary.json) -- a public Socrata API on
     data.bts.gov. NOT refetched by fetch_sources() below (it was pulled
     once via `curl`, see DECISIONS.md 2026-08-18); rerun manually if it
     needs refreshing:
       curl -s "https://data.bts.gov/resource/r495-tyji.json?origin_airport_code=ANC&\\$limit=5000&\\$order=reporting_month" -o data/bts_anc_origin_summary.json

build_candidates() joins (1), (2) and (3) into data/candidates.json --
the per-airport dataset the tools read. build_anc_traffic_mix() turns
(4) into data/anc_traffic_mix.json (Anchorage's domestic/international
departure mix for the long-haul-percentage question).

Run:
    python data/refresh_data.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import openpyxl

DATA_DIR = Path(__file__).parent
sys.path.insert(0, str(DATA_DIR.parent))

from app.runway_geometry import Runway, arrival_capacity  # noqa: E402

OURAIRPORTS_AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OURAIRPORTS_RUNWAYS_URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"

FAA_CY_CURRENT_URL = "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/arp-cy2025-commercial-service-enplanements-preliminary.xlsx"
FAA_CY_PRIOR_URL = "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/arp-cy2024-commercial-service-enplanements.xlsx"

NEW_ENGLAND = {"US-ME", "US-NH", "US-VT", "US-MA", "US-RI", "US-CT"}

# OurAirports iso_country values covering everything FAA can report on:
# the 50 states + DC (US), plus the five inhabited territories with
# commercial service. See _index_ourairports() for why this filter is a
# correctness requirement, not a performance one.
US_COUNTRIES = {"US", "PR", "GU", "VI", "AS", "MP"}

# Census Bureau. Both endpoints below are keyless.
CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"

# County population: the published Vintage 2025 flat file, NOT the Census
# Data API. The API's newest county-capable dataset is Vintage 2023
# (api.census.gov/data/2024/... and /2025/... both 404), i.e. the API lags
# the published files by two vintages. The flat file is strictly better on
# every axis: 6 years instead of 4, ends 2025 instead of 2023, carries
# birth/death/migration components the API's county endpoint does not, and
# needs no API key at all -- one less credential a reviewer has to obtain.
CENSUS_COUNTY_POP_URL = (
    "https://www2.census.gov/programs-surveys/popest/datasets/"
    "2020-2025/counties/totals/co-est2025-alldata.csv"
)

# Two windows, deliberately. 2020->2025 is the full published series;
# 2022->2025 excludes the 2020-21 pandemic migration shock, which was
# large enough to flip the SIGN of the trend for major metro counties (LA
# lost 195k domestic migrants in 2021 alone, vs ~105k in 2025). Reporting
# one window only would be presenting an artifact of the window choice as
# a structural finding -- the same reason ASSUMPTIONS.md rejects FAA's
# single-year '% Change' as a growth signal.
CENSUS_BASE_YEAR = 2020
CENSUS_RECENT_BASE_YEAR = 2022
CENSUS_LATEST_YEAR = 2025

# Airport 'type' rank, most-authoritative-for-commercial-service first.
# Used only to break local_code collisions (see build_candidates()) --
# never to filter the target set itself, which is now "every airport
# FAA lists in its enplanements file," not a curated list. See
# DECISIONS.md for why this replaced the earlier 27-airport target set.
_TYPE_RANK = {"large_airport": 0, "medium_airport": 1, "small_airport": 2, "seaplane_base": 3, "closed": 9}


def fetch_sources() -> None:
    for name, url in (
        ("airports.csv", OURAIRPORTS_AIRPORTS_URL),
        ("runways.csv", OURAIRPORTS_RUNWAYS_URL),
        ("faa_cy2025_enplanements_preliminary.xlsx", FAA_CY_CURRENT_URL),
        ("faa_cy2024_enplanements.xlsx", FAA_CY_PRIOR_URL),
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
    """Parses one FAA enplanements sheet into {locid: record}.

    Skips rows with no numeric Rank (r[0]) as well as rows with no
    Locid (r[3]) -- the sheet ends with unlabeled summary rows ('Large
    Count', 'Nonhub Count', 'Total Primary Airports', ...) that have a
    count in the Locid column position and no Rank. Checking Rank alone
    filters those out; checking only Locid does not (a bug found when
    the target set expanded from 27 curated airports, none of which
    happened to collide with a summary row, to the full ~500-airport
    FAA list, where 6 of these summary rows initially looked like
    unmatched real airports -- see DECISIONS.md).
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    out = {}
    for r in rows[1:]:
        if not r or r[0] is None or not r[3]:
            continue
        _rank, ro, st, locid, _city, _name, _sl, hub, this_yr, last_yr, pct = r[:11]
        out[locid] = {
            "region_office": ro, "state": st, "hub_class": hub,
            "enplanements": this_yr, "enplanements_prior_year": last_yr, "pct_change": pct,
        }
    return out


def _index_ourairports() -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """Loads airports.csv into two lookup indexes: by iata_code (the
    primary key) and by local_code (fallback -- see build_candidates()).
    Both indexes keep every matching row so collisions can be
    tie-broken deliberately instead of overwritten silently.

    Only US and US-territory airports are indexed. This is not an
    optimization -- it is a correctness requirement. FAA's enplanements
    file is US-only by definition, but a US FAA LID collides with a
    FOREIGN airport's IATA code often enough to matter: matching against
    the global index silently mapped FAA 'SAW' (Marquette/Sawyer,
    Michigan) onto Istanbul Sabiha Gokcen, 'IWA' (Mesa Gateway, Arizona)
    onto Ivanovo, Russia, and 12 more -- each one landing a real US
    airport's enplanements on a foreign airport's name and coordinates.
    Restricting the universe first makes the collision impossible rather
    than relying on a tie-break to notice it.
    """
    by_iata: dict[str, list[dict]] = {}
    by_local: dict[str, list[dict]] = {}
    with open(DATA_DIR / "airports.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["iso_country"] not in US_COUNTRIES:
                continue
            if row["iata_code"]:
                by_iata.setdefault(row["iata_code"], []).append(row)
            if row["local_code"]:
                by_local.setdefault(row["local_code"], []).append(row)
    return by_iata, by_local


def geocode_airports_to_counties(force: bool = False) -> None:
    """Resolves every FAA airport's lat/lon to the county (FIPS) it sits
    in, via the Census Geocoder (keyless), into data/airport_counties.json.

    Why geocode rather than string-match `municipality` to a county name:
    the same reason the FAA join is keyed on Locid and not on name --
    'Boston' names several places in the US, county names repeat across
    states (there are 30-odd Washington Counties), and a near-miss match
    fails SILENTLY with a plausible-looking wrong answer. Coordinates
    resolve to exactly one county, and the answer carries the FIPS code
    the Census population API is itself keyed on, so the join downstream
    is an exact code match with no fuzzy step anywhere.

    Results are cached: airports already in the file are skipped, so a
    re-run costs nothing and a partial failure can be resumed rather than
    restarting all ~515 lookups. Pass force=True to re-fetch everything.
    """
    out_path = DATA_DIR / "airport_counties.json"
    cached: dict[str, dict] = {}
    if out_path.exists() and not force:
        cached = json.loads(out_path.read_text()).get("airports", {})

    airports, _ = _resolve_faa_airports()
    todo = [(locid, a) for locid, a in airports.items() if locid not in cached]
    if not todo:
        print(f"airport_counties.json: all {len(cached)} airports already cached")
        return
    print(f"geocoding {len(todo)} airports ({len(cached)} cached)...")

    def lookup(item: tuple[str, dict]) -> tuple[str, dict | None]:
        locid, a = item
        url = (
            f"{CENSUS_GEOCODER_URL}?x={a['longitude_deg']}&y={a['latitude_deg']}"
            "&benchmark=Public_AR_Current&vintage=Current_Current"
            "&layers=Counties&format=json"
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    counties = json.loads(r.read())["result"]["geographies"].get("Counties", [])
                if not counties:
                    return locid, None
                c = counties[0]
                return locid, {
                    "county_fips": c["GEOID"],
                    "county_name": c["NAME"],
                    "state_fips": c["STATE"],
                }
            except Exception as exc:  # noqa: BLE001 -- retried, then reported
                if attempt == 2:
                    print(f"  {locid}: geocode failed after 3 tries ({type(exc).__name__})")
                    return locid, None
        return locid, None

    # 8 workers keeps a ~500-item batch under a minute without hammering a
    # public government endpoint.
    with ThreadPoolExecutor(max_workers=8) as pool:
        for locid, result in pool.map(lookup, todo):
            if result:
                cached[locid] = result

    unresolved = sorted(set(airports) - set(cached))
    out = {
        "_meta": {
            "description": (
                "FAA airport Locid -> the county (FIPS) its coordinates fall in. "
                "The join key between candidates.json and Census county population."
            ),
            "source": "US Census Geocoder (geocoding.geo.census.gov), coordinates -> Counties layer",
            "fetched_at": str(date.today()),
            "resolved_count": len(cached),
            "unresolved_locids": unresolved,
            "unresolved_note": (
                "Airports whose coordinates fall outside any US county polygon -- "
                "expected for territories the Census county layer does not cover "
                "(Guam, American Samoa, N. Mariana Is.). These simply get no "
                "population fields; they are not dropped from candidates.json."
            ),
        },
        "airports": dict(sorted(cached.items())),
    }
    out_path.write_text(json.dumps(out, indent=2))
    print(f"wrote airport_counties.json: {len(cached)} resolved, {len(unresolved)} unresolved")


def fetch_census_county_population() -> None:
    """Fetches July-1 population estimates and migration components for
    every US county, 2020-2025, into data/census_county_population.json.

    Source: Census Population Estimates Program, Vintage 2025 county
    totals flat file (see CENSUS_COUNTY_POP_URL for why the flat file
    beats the Data API here). Keyless.

    COVERAGE GAP, stated rather than silently absorbed: this file is the
    50 states + DC only (3,144 counties). Puerto Rico's municipios are
    published separately and the Vintage 2025 tree has no municipio
    totals file, so PR airports get no population fields -- as do Guam,
    American Samoa, USVI and the N. Marianas, which PEP does not cover at
    county level at all. That is 14 of 515 airports. They are NOT dropped:
    app/scoring.py renormalizes each item's weights across the criteria
    actually available for it, so these airports still rank on their
    remaining criteria instead of failing or scoring a spurious zero.
    """
    print("fetching Census county population estimates (Vintage 2025, 2020-2025)...")
    with urllib.request.urlopen(CENSUS_COUNTY_POP_URL, timeout=180) as r:
        # latin-1: the file carries non-UTF8 bytes in some county names
        # (e.g. Dona Ana County, NM), which utf-8 decoding rejects outright.
        text = r.read().decode("latin-1")

    years = list(range(CENSUS_BASE_YEAR, CENSUS_LATEST_YEAR + 1))
    counties: dict[str, dict] = {}
    for row in csv.DictReader(text.splitlines()):
        if row["SUMLEV"] != "050":  # 050 = county; 040 = state rollup rows
            continue
        fips = row["STATE"] + row["COUNTY"]
        counties[fips] = {
            "name": row["CTYNAME"],
            "state": row["STNAME"],
            "population_by_year": {str(y): int(row[f"POPESTIMATE{y}"]) for y in years},
            # Net migration is a better demand signal than total population
            # change for this domain: an in-migrant flies this year, a birth
            # doesn't for ~18. Kept separate rather than folded into one
            # number so a criterion can use either.
            "net_migration_by_year": {str(y): int(row[f"NETMIG{y}"]) for y in years},
            "domestic_migration_by_year": {str(y): int(row[f"DOMESTICMIG{y}"]) for y in years},
        }

    out = {
        "_meta": {
            "description": (
                f"July-1 resident population estimates and migration components by "
                f"county, {CENSUS_BASE_YEAR}-{CENSUS_LATEST_YEAR}, keyed by 5-digit "
                "state+county FIPS."
            ),
            "source": f"US Census Bureau PEP, Vintage 2025 county totals: {CENSUS_COUNTY_POP_URL}",
            "fetched_at": str(date.today()),
            "coverage": (
                "50 states + DC. Excludes Puerto Rico (published separately, no "
                "municipio totals file in the Vintage 2025 tree) and the island "
                "territories (not covered by PEP at county level)."
            ),
            "vintage_revision_note": (
                "Each vintage revises ALL prior years, so figures here differ from "
                "older vintages for the same year -- LA County 2023 is 9,732,568 in "
                "Vintage 2025 but was 9,663,345 in Vintage 2023 (+0.7%). Always compare "
                "within one vintage; never mix."
            ),
            "county_count": len(counties),
        },
        "counties": dict(sorted(counties.items())),
    }
    (DATA_DIR / "census_county_population.json").write_text(json.dumps(out, indent=2))
    print(f"wrote census_county_population.json: {len(counties)} counties")


def _resolve_faa_airports() -> tuple[dict[str, dict], list[str]]:
    """Joins FAA's enplanements Locids to OurAirports rows. Returns
    ({locid: ourairports_row}, unmatched_locids).

    The join key is FAA's Locid. Most Locids equal OurAirports'
    iata_code, but ~30 of the ~520 FAA rows are small/non-hub fields
    that OurAirports doesn't consider IATA-code-worthy -- for those,
    the same code is on OurAirports' local_code (FAA LID) field
    instead. Falling back to local_code recovers all but a genuine
    zero; not falling back would have silently dropped ~30 real
    airports from the join. A few local_codes are shared by more than
    one OurAirports row (e.g. a small GA strip and a real commercial
    field reusing the same 3-letter code in different states); those
    are tie-broken by airport type (large > medium > small), since an
    airport with real FAA enplenements data is never the GA strip.

    (The other half of the collision problem -- US LIDs colliding with
    FOREIGN IATA codes -- is handled upstream in _index_ourairports().)
    """
    faa_2025 = _load_faa(DATA_DIR / "faa_cy2025_enplanements_preliminary.xlsx")
    by_iata, by_local = _index_ourairports()

    airports: dict[str, dict] = {}
    unmatched: list[str] = []
    for locid in faa_2025:
        candidates_for_locid = by_iata.get(locid) or by_local.get(locid)
        if not candidates_for_locid:
            unmatched.append(locid)
            continue
        best = min(candidates_for_locid, key=lambda a: _TYPE_RANK.get(a["type"], 8))
        airports[locid] = best
    return airports, unmatched


def _load_population_layer() -> tuple[dict[str, dict], dict[str, dict]]:
    """Reads the two cached Census files if present. Returns
    ({locid: county_record}, {fips: population_record}) -- empty dicts if
    the caches don't exist, which is what makes population an OPTIONAL
    layer rather than a hard build dependency."""
    counties_path = DATA_DIR / "airport_counties.json"
    pop_path = DATA_DIR / "census_county_population.json"
    if not (counties_path.exists() and pop_path.exists()):
        return {}, {}
    airport_counties = json.loads(counties_path.read_text())["airports"]
    county_pop = json.loads(pop_path.read_text())["counties"]
    return airport_counties, county_pop


def _population_fields(locid: str, airport_counties: dict, county_pop: dict) -> dict:
    """Per-airport county population fields, or empty if this airport has
    no county match / the county has no usable population series.

    Reports compounded annual rates over two windows, never a single-year
    delta, for the same reason ASSUMPTIONS.md rejects FAA's own one-year
    '% Change' as a growth signal: one year is noise, a compounded rate is
    a trajectory. Both endpoint populations are carried alongside each
    rate so it is auditable rather than having to be trusted.
    """
    county = airport_counties.get(locid)
    if not county:
        return {}
    pop = county_pop.get(county["county_fips"])
    if not pop:
        return {}
    by_year = pop["population_by_year"]
    p_base = by_year.get(str(CENSUS_BASE_YEAR))
    p_recent = by_year.get(str(CENSUS_RECENT_BASE_YEAR))
    p_latest = by_year.get(str(CENSUS_LATEST_YEAR))
    if not p_base or not p_recent or not p_latest:
        return {}

    def cagr(start: int, end: int, span: int) -> float:
        return round((end / start) ** (1 / span) - 1, 5)

    # Recent-window migration: sum the last 3 published years rather than
    # taking the final year alone, for the same noise reason as above.
    recent_years = [str(y) for y in range(CENSUS_RECENT_BASE_YEAR + 1, CENSUS_LATEST_YEAR + 1)]
    net_mig = sum(pop["net_migration_by_year"].get(y, 0) for y in recent_years)
    dom_mig = sum(pop["domestic_migration_by_year"].get(y, 0) for y in recent_years)

    return {
        "county_fips": county["county_fips"],
        "county_name": county["county_name"],
        f"county_population_{CENSUS_BASE_YEAR}": p_base,
        f"county_population_{CENSUS_LATEST_YEAR}": p_latest,
        # Full published series (spans the pandemic shock).
        "county_population_cagr_full": cagr(p_base, p_latest, CENSUS_LATEST_YEAR - CENSUS_BASE_YEAR),
        # Post-shock window -- the one to lead with for a forward-looking
        # investment question; the pair is what makes the window
        # sensitivity visible instead of hidden.
        "county_population_cagr_recent": cagr(
            p_recent, p_latest, CENSUS_LATEST_YEAR - CENSUS_RECENT_BASE_YEAR
        ),
        "county_net_migration_recent": net_mig,
        "county_domestic_migration_recent": dom_mig,
        # Normalized so it is comparable across counties of wildly
        # different sizes -- a raw +20k means something very different in
        # Cook County than in a 30k-person rural county.
        "county_net_migration_recent_per_1000": round(net_mig / p_latest * 1000, 2),
    }


def _runway_geometry_fields(runways: list[Runway], total_runway_count: int) -> dict:
    """Arrival-stream counts and parallel-runway separation, derived from
    OurAirports runway coordinates. See app/runway_geometry.py for the
    model and the FAA separation standards it applies.

    `runway_geometry_complete` is False when some runways lacked usable
    coordinates, so a consumer can tell "this airport genuinely has one
    arrival stream" apart from "we could only see one of its runways."
    """
    cap = arrival_capacity(runways)
    return {
        "arrival_streams_vmc": cap.vmc_streams,
        "arrival_streams_imc": cap.imc_streams,
        "air_carrier_runway_count": cap.air_carrier_runways,
        "min_parallel_separation_ft": cap.min_parallel_separation_ft,
        "weather_capacity_degradation": round(cap.weather_degradation, 4),
        "parallel_runway_pairs": [
            {
                "runways": f"{p.runway_a}/{p.runway_b}",
                "separation_ft": p.separation_ft,
                "imc_capability": p.imc_capability,
            }
            for p in cap.parallel_pairs
        ],
        "runway_geometry_complete": len(runways) == total_runway_count,
    }


def build_candidates() -> None:
    """Joins OurAirports (geo/type/runways), FAA enplanements (CY2025
    preliminary + CY2024 final), and Census county population growth
    into data/candidates.json -- every airport FAA's Commercial Service
    Enplanements report lists (~500), not a curated subset. See
    DECISIONS.md for why this replaced the earlier 27-airport set.

    Population fields are attached only if the two cache files built by
    geocode_airports_to_counties() and fetch_census_county_population()
    exist; without them the build still succeeds and simply omits them,
    so a reviewer with no Census API key can still rebuild everything
    else. See attach_population().
    """
    faa_2025 = _load_faa(DATA_DIR / "faa_cy2025_enplanements_preliminary.xlsx")
    faa_2024 = _load_faa(DATA_DIR / "faa_cy2024_enplanements.xlsx")
    airports, unmatched = _resolve_faa_airports()
    if unmatched:
        print(f"WARNING: {len(unmatched)} FAA airports have no OurAirports match: {sorted(unmatched)}")

    id_to_locid = {a["id"]: locid for locid, a in airports.items()}
    runway_count = dict.fromkeys(airports, 0)
    # Full runway geometry, not just a count -- the arrival-capacity model
    # behind the unmet-demand question needs to know whether an airport's
    # parallel runways are far enough apart to fly independently when the
    # ceiling drops. See app/runway_geometry.py.
    runway_geom: dict[str, list[Runway]] = {locid: [] for locid in airports}
    with open(DATA_DIR / "runways.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            locid = id_to_locid.get(row["airport_ref"])
            if not locid or row.get("closed") == "1":
                continue
            runway_count[locid] += 1
            try:
                runway_geom[locid].append(
                    Runway(
                        ident=row["le_ident"],
                        latitude_deg=float(row["le_latitude_deg"]),
                        longitude_deg=float(row["le_longitude_deg"]),
                        heading_deg=float(row["le_heading_degT"]),
                        length_ft=float(row["length_ft"]),
                    )
                )
            except (TypeError, ValueError):
                # OurAirports leaves coordinates/heading blank on some
                # runways. Skipped rather than guessed: a runway with no
                # position contributes no geometry, and it still counts in
                # runway_count above. Reported per-airport below so a gap
                # is visible rather than silently degrading the model.
                continue

    def nearest_competitor(locid: str) -> tuple[str, float]:
        lat1 = float(airports[locid]["latitude_deg"])
        lon1 = float(airports[locid]["longitude_deg"])
        best, best_d = None, float("inf")
        for other in airports:
            if other == locid:
                continue
            lat2 = float(airports[other]["latitude_deg"])
            lon2 = float(airports[other]["longitude_deg"])
            d = haversine_miles(lat1, lon1, lat2, lon2)
            if d < best_d:
                best, best_d = other, d
        return best, round(best_d, 1)

    airport_counties, county_pop = _load_population_layer()
    if not airport_counties:
        print("NOTE: no Census cache found -- building without population fields. "
              "Run geocode_airports_to_counties() + fetch_census_county_population() first.")

    candidates = {}
    for locid, a in sorted(airports.items()):
        f25, f24 = faa_2025[locid], faa_2024.get(locid, {})
        nearest_iata, nearest_mi = nearest_competitor(locid)
        candidates[locid] = {
            "name": a["name"],
            # Keys of this dict are FAA LocIDs. For most airports that IS
            # the IATA code, but for ~30 it isn't (FAA LID 'SAW' is
            # Marquette, whose IATA code is MQT) -- so carry the real IATA
            # code explicitly rather than letting the key imply it. Entity
            # resolution needs both: a user may say either.
            "iata_code": a["iata_code"] or None,
            "municipality": a["municipality"],
            "iso_region": a["iso_region"],
            "is_new_england": a["iso_region"] in NEW_ENGLAND,
            "ourairports_type": a["type"],
            "latitude_deg": float(a["latitude_deg"]),
            "longitude_deg": float(a["longitude_deg"]),
            "runway_count": runway_count[locid],
            **_runway_geometry_fields(runway_geom[locid], runway_count[locid]),
            "faa_hub_class": f25["hub_class"],
            "enplanements_cy2025_prelim": f25["enplanements"],
            "enplanements_cy2024": f24.get("enplanements", f25["enplanements_prior_year"]),
            "enplanements_cy2023": f24.get("enplanements_prior_year"),
            "yoy_pct_change_2025": round(f25["pct_change"], 4) if f25["pct_change"] is not None else None,
            "yoy_pct_change_2024": round(f24["pct_change"], 4) if f24.get("pct_change") is not None else None,
            "nearest_competitor_iata": nearest_iata,
            "nearest_competitor_mi": nearest_mi,
            **_population_fields(locid, airport_counties, county_pop),
        }

    with_pop = sum(1 for c in candidates.values() if "county_population_cagr_recent" in c)

    out = {
        "_meta": {
            "description": (
                "Per-airport candidate metrics for every airport in FAA's Commercial "
                "Service Enplanements report -- the full national set, not a curated "
                "subset scoped to the brief's example questions."
            ),
            "sources": {
                "geo_type_runways": "OurAirports bulk CSV, fetched live",
                "enplanements": "FAA Commercial Service Enplanements, CY2025 preliminary + "
                                 "CY2024 final, fetched live from faa.gov",
                "county_population": (
                    f"US Census PEP Vintage 2025 (July-1 estimates, "
                    f"{CENSUS_BASE_YEAR}-{CENSUS_LATEST_YEAR}), joined via the Census "
                    "Geocoder on airport coordinates -> county FIPS. See "
                    "census_county_population.json and airport_counties.json."
                ),
            },
            "fetched_at": str(date.today()),
            "join_note": (
                "Joined on FAA Locid == OurAirports iata_code, falling back to "
                "OurAirports local_code (FAA LID) for airports without an assigned "
                "IATA code; local_code collisions tie-broken by airport type "
                "(large > medium > small). The OurAirports universe is restricted to "
                "US + territories BEFORE matching, because a US FAA LID can collide "
                "with a foreign airport's IATA code (FAA 'SAW' = Marquette, Michigan, "
                "not Istanbul)."
            ),
            "unmatched_faa_locids": unmatched,
            "population_note": (
                f"county_population_cagr is the compounded annual rate over "
                f"{CENSUS_LATEST_YEAR - CENSUS_BASE_YEAR} years (July {CENSUS_BASE_YEAR} "
                f"-> July {CENSUS_LATEST_YEAR}), not a single-year delta. This is the "
                "county the airport physically SITS IN -- not its catchment area, which "
                "for a major hub is much larger (BOS is in Suffolk County, pop ~792k, "
                "while Boston's metro catchment is ~4.9M). Read these fields as a "
                "regional growth-trend signal, NOT as market size; enplanements already "
                "measure size directly. Airports with no population fields are Puerto "
                "Rico (published separately, with no municipio totals file in the "
                "Vintage 2025 tree) and the island territories (Guam, Am. Samoa, USVI, "
                "N. Marianas), which Census PEP does not cover at county level."
            ),
            "airports_with_population": with_pop,
            "nearest_competitor_note": (
                "Computed against the full candidate set above (~500 airports), so this "
                "is a real geographic claim for every airport here, not an artifact of a "
                "curated subset."
            ),
            "airport_count": len(candidates),
        },
        "airports": candidates,
    }
    (DATA_DIR / "candidates.json").write_text(json.dumps(out, indent=2))
    print(f"wrote candidates.json: {len(candidates)} airports")


def build_anc_traffic_mix() -> None:
    """Builds data/anc_traffic_mix.json -- ANC's domestic vs.
    international departure mix, monthly and by year, for the 'percentage
    of long-haul flights out of Anchorage' question.

    Source: BTS 'T100 Segment Summary By Origin Airport' (data.bts.gov,
    dataset r495-tyji), filtered to ANC, hand-downloaded to
    data/bts_anc_origin_summary.json since it's a public Socrata API with
    no key/auth -- NOT the OpenFlights routes.dat this used to read
    (replaced 2026-08-18, see DECISIONS.md). This is real 2014-present
    monthly data, not a 2014 snapshot, and it's departure-COUNT weighted
    (a route flown daily counts 30x a route flown once a month), fixing
    OpenFlights' route-existence-only limitation.

    What it can't do: this table has no per-destination rows (see
    DECISIONS.md for the search across every T-100-tagged dataset on
    data.bts.gov that confirmed this), so there's no way to compute
    'percentage of flights over N miles' exactly -- only a domestic vs.
    international split, each with a real average distance/flight. For
    ANC specifically, international is a reasonable long-haul proxy: its
    average distance/flight (~4,300 mi in 2025) reflects trans-Pacific
    cargo/passenger routes to Asia, vs. domestic's ~1,450 mi average
    (itself already long-haul-heavy, since ANC-SEA alone is ~1,448 mi and
    is a large share of domestic departures).

    KEY DEFINITION, verified against the raw data: 'total_departures' ==
    'domestic_departures' + 'outbound_international' exactly (checked on
    every row). 'inbound_international' (flights arriving at ANC FROM
    abroad, i.e. ANC as destination) is a separate figure BTS reports
    alongside it and is deliberately EXCLUDED here -- it is not a flight
    OUT OF Anchorage, so including it would answer a different question
    ("ANC's total international exposure") under the guise of this one.
    """
    raw = json.loads((DATA_DIR / "bts_anc_origin_summary.json").read_text())

    monthly = []
    annual: dict[str, dict] = {}
    for r in sorted(raw, key=lambda r: r["reporting_month"]):
        total = float(r["total_departures"])
        dom = float(r["domestic_departures"])
        out_intl = float(r["outbound_international"])
        assert abs(total - (dom + out_intl)) < 1, f"{r['reporting_month']}: total_departures != domestic + outbound_international"
        monthly.append({
            "month": r["reporting_month"][:7],
            "total_departures": int(total),
            "domestic_departures": int(dom),
            "outbound_international_departures": int(out_intl),
            "international_share": round(out_intl / total, 4) if total else None,
            "avg_domestic_distance_mi": float(r["domestic_distance_flight"]) if dom else None,
            "avg_outbound_international_distance_mi": float(r["outbound_international_3"]) if out_intl else None,
        })
        y = r["year"]
        a = annual.setdefault(y, {"total": 0.0, "dom": 0.0, "out_intl": 0.0, "dom_dist_wt": 0.0, "intl_dist_wt": 0.0})
        a["total"] += total
        a["dom"] += dom
        a["out_intl"] += out_intl
        a["dom_dist_wt"] += dom * float(r["domestic_distance_flight"])
        a["intl_dist_wt"] += out_intl * float(r["outbound_international_3"])

    annual_summary = {}
    for y, a in sorted(annual.items()):
        if a["total"] == 0:
            continue
        annual_summary[y] = {
            "total_departures": int(a["total"]),
            "domestic_departures": int(a["dom"]),
            "outbound_international_departures": int(a["out_intl"]),
            "international_share": round(a["out_intl"] / a["total"], 4),
            "avg_domestic_distance_mi": round(a["dom_dist_wt"] / a["dom"], 1) if a["dom"] else None,
            "avg_outbound_international_distance_mi": round(a["intl_dist_wt"] / a["out_intl"], 1) if a["out_intl"] else None,
        }

    complete_years = [y for y in annual_summary if sum(1 for m in monthly if m["month"].startswith(y)) == 12]
    most_recent_full_year = max(complete_years) if complete_years else None

    out = {
        "_meta": {
            "description": (
                "ANC departure mix, domestic vs. outbound international, monthly and by "
                "year -- the long-haul proxy for the 'percentage of long-haul flights out "
                "of Anchorage' question, replacing an earlier OpenFlights-route-count "
                "approach. See this module's build_anc_traffic_mix() docstring for the "
                "full reasoning, including why the true distance-threshold percentage "
                "isn't computable from any publicly downloadable BTS table."
            ),
            "source": "BTS T100 Segment Summary By Origin Airport (data.bts.gov, dataset r495-tyji), filtered to ANC",
            "fetched_at": str(date.today()),
            "definition_note": "KEY DEFINITION" + build_anc_traffic_mix.__doc__.split("KEY DEFINITION")[1].strip(),
            "most_recent_full_calendar_year": most_recent_full_year,
            "months_covered": f"{monthly[0]['month']} to {monthly[-1]['month']}" if monthly else None,
        },
        "annual": annual_summary,
        "monthly": monthly,
    }
    (DATA_DIR / "anc_traffic_mix.json").write_text(json.dumps(out, indent=2))
    print(f"wrote anc_traffic_mix.json: {len(monthly)} months, {len(annual_summary)} years")


if __name__ == "__main__":
    fetch_sources()
    # Order matters: the two Census steps write the caches that
    # build_candidates() reads to attach population fields. Geocoding is
    # cached per-airport, so re-runs skip it and cost nothing.
    fetch_census_county_population()
    geocode_airports_to_counties()
    build_candidates()
    build_anc_traffic_mix()
