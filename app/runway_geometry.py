"""
runway_geometry.py -- how many independent arrival streams an airport
actually has, in good weather and in bad.

Same rules as scoring.py and analytics.py: ZERO I/O, ZERO LLM, pure
functions, fully testable with no key and no network. It is handed
runway coordinates and returns geometry; it never reads a file.

WHY THIS EXISTS. "Unmet demand at SFO, and why" needs a *mechanism*, not
a correlation. The real mechanism at SFO is published and physical: its
two parallel arrival runways (28L/28R) are about 750 ft apart, far below
the separation FAA requires to run two approach streams at once when the
ceiling drops. So in low visibility the pair collapses into a single
arrival stream and the airport's arrival rate roughly halves, while the
schedule stays exactly where it was. That gap is the unmet demand.

The important part: that 750 ft is not hardcoded here. It is COMPUTED
from OurAirports' published runway-end coordinates and true headings --
`parallel_pairs()` on SFO's real runway data returns 747 ft, which is
the published figure to within 0.4%. The same computation runs for every
airport in the set, so the model generalizes instead of being a fact
about one airport dressed up as a model.

The thresholds below are FAA's, not ours. That matters for the same
reason using FAA's hub classification for eligibility mattered: a number
we chose is a number we have to defend, and a number the regulator chose
is a citation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

# Feet per degree of latitude. Constant enough at the scale of a single
# airport (the variation with latitude is under 1% and swamped by the
# coordinate precision OurAirports publishes) that the extra accuracy of
# a full geodesic is not worth the dependency here -- unlike
# nearest-competitor distance, which spans thousands of miles and does
# use haversine.
FT_PER_DEG_LAT = 364_000.0

# Two runways count as "parallel" within this heading tolerance. Real
# parallel runways are built to identical headings, but published
# headings are true (not magnetic) and rounded, so an exact-equality test
# would miss real pairs. 15 degrees is comfortably wider than that noise
# and still far narrower than the ~30-degree gap to the next runway
# designator, so it cannot accidentally pair 09 with 04.
PARALLEL_HEADING_TOLERANCE_DEG = 15.0

# Below this length a runway is not carrying scheduled air-carrier
# arrivals, so it contributes no arrival stream regardless of geometry.
# This is what stops a short GA crosswind strip from reading as spare
# arrival capacity -- exactly the SNA overstatement ASSUMPTIONS.md flags
# for raw runway_count.
AIR_CARRIER_RUNWAY_MIN_LENGTH_FT = 5_000.0

# FAA separation standards for simultaneous parallel approaches. These
# are the regulator's numbers (FAA Order 7110.65 / AC 150/5300-13), not
# ours:
#   >= 4,300 ft  simultaneous INDEPENDENT approaches permitted -- the
#                two runways are genuinely two arrival streams in IMC.
#   >= 2,500 ft  simultaneous DEPENDENT (staggered) approaches -- some
#                benefit, but the streams are coupled, not independent.
#   <  2,500 ft  no simultaneous approaches in IMC. The pair operates as
#                ONE arrival stream. This is SFO's case at ~750 ft.
INDEPENDENT_APPROACH_MIN_SEPARATION_FT = 4_300.0
DEPENDENT_APPROACH_MIN_SEPARATION_FT = 2_500.0


@dataclass(frozen=True)
class Runway:
    """One runway, identified by its low-end threshold. `heading_deg` is
    TRUE heading, matching OurAirports' `le_heading_degT`."""

    ident: str
    latitude_deg: float
    longitude_deg: float
    heading_deg: float
    length_ft: float


@dataclass(frozen=True)
class ParallelPair:
    runway_a: str
    runway_b: str
    separation_ft: float
    # "independent" | "dependent" | "single_stream" -- which FAA band the
    # measured separation falls into.
    imc_capability: str


@dataclass(frozen=True)
class ArrivalCapacity:
    """Arrival streams available in each weather state, plus the geometry
    that produced them.

    `vmc_streams` / `imc_streams` are counts of runways that can take
    arrivals simultaneously. The ratio between them is the whole point:
    an airport where they are equal is weather-robust, and one where IMC
    halves them has a structural, physical constraint that no amount of
    terminal construction fixes.
    """

    vmc_streams: int
    imc_streams: int
    air_carrier_runways: int
    parallel_pairs: tuple[ParallelPair, ...]
    min_parallel_separation_ft: float | None

    @property
    def weather_degradation(self) -> float:
        """Fraction of good-weather arrival capacity lost when the ceiling
        drops. 0.0 = unaffected, 0.5 = arrival rate halves."""
        if self.vmc_streams <= 0:
            return 0.0
        return 1.0 - (self.imc_streams / self.vmc_streams)


def perpendicular_separation_ft(a: Runway, b: Runway) -> float:
    """Distance between two parallel runway CENTERLINES, measured
    perpendicular to the direction of flight.

    Not threshold-to-threshold distance, which is a different and larger
    number whenever the thresholds are staggered along the runway axis --
    at SFO that difference is 893 ft vs the correct 747 ft, enough to
    move the airport into the wrong FAA band. The fix is to project the
    offset between thresholds onto the axis perpendicular to the runway
    heading, discarding the along-track component.
    """
    ft_per_deg_lon = FT_PER_DEG_LAT * math.cos(math.radians(a.latitude_deg))
    east = (b.longitude_deg - a.longitude_deg) * ft_per_deg_lon
    north = (b.latitude_deg - a.latitude_deg) * FT_PER_DEG_LAT

    # Unit vector perpendicular to runway a's centerline. Heading is
    # measured clockwise from north, so the along-track unit vector is
    # (sin h, cos h) in (east, north) and the perpendicular is (cos h, -sin h).
    heading = math.radians(a.heading_deg)
    perp_east, perp_north = math.cos(heading), -math.sin(heading)
    return abs(east * perp_east + north * perp_north)


def _is_parallel(a: Runway, b: Runway) -> bool:
    delta = abs((a.heading_deg - b.heading_deg + 180.0) % 360.0 - 180.0)
    return delta <= PARALLEL_HEADING_TOLERANCE_DEG


def _imc_capability(separation_ft: float) -> str:
    if separation_ft >= INDEPENDENT_APPROACH_MIN_SEPARATION_FT:
        return "independent"
    if separation_ft >= DEPENDENT_APPROACH_MIN_SEPARATION_FT:
        return "dependent"
    return "single_stream"


def parallel_pairs(runways: Sequence[Runway]) -> tuple[ParallelPair, ...]:
    """Every pair of air-carrier-length parallel runways, with the
    measured centerline separation and its FAA band."""
    usable = [r for r in runways if r.length_ft >= AIR_CARRIER_RUNWAY_MIN_LENGTH_FT]
    pairs: list[ParallelPair] = []
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            a, b = usable[i], usable[j]
            if not _is_parallel(a, b):
                continue
            sep = perpendicular_separation_ft(a, b)
            pairs.append(
                ParallelPair(
                    runway_a=a.ident,
                    runway_b=b.ident,
                    separation_ft=round(sep, 1),
                    imc_capability=_imc_capability(sep),
                )
            )
    return tuple(pairs)


def arrival_capacity(runways: Iterable[Runway]) -> ArrivalCapacity:
    """Arrival streams available in good and bad weather.

    Model, stated plainly because it is a simplification and the caveat
    matters more than the number:

      VMC -- every air-carrier-length runway can take arrivals, so
      vmc_streams is just the count of them. Real airports do not run
      every runway for arrivals at once (crossing runways, noise
      procedures, wind), so this is an UPPER bound on good-weather
      capacity.

      IMC -- runways closer than FAA's dependent-approach minimum
      collapse into one stream. Implemented by union-find over the
      sub-minimum pairs: three runways each too close to the next form
      ONE stream, not two, and pairwise counting would get that wrong.

    What this deliberately does NOT model: crossing-runway interactions,
    wake-turbulence spacing by aircraft class, terrain-driven approach
    restrictions, or noise curfews. Every one of those reduces real
    capacity further, so treating this as an upper bound is the honest
    reading -- see ASSUMPTIONS.md.
    """
    usable = [r for r in runways if r.length_ft >= AIR_CARRIER_RUNWAY_MIN_LENGTH_FT]
    pairs = parallel_pairs(usable)

    # Union-find: merge runways that cannot be flown independently in IMC.
    parent = {r.ident: r.ident for r in usable}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for pair in pairs:
        if pair.imc_capability == "single_stream":
            ra, rb = find(pair.runway_a), find(pair.runway_b)
            if ra != rb:
                parent[ra] = rb

    imc_streams = len({find(r.ident) for r in usable})
    separations = [p.separation_ft for p in pairs]

    return ArrivalCapacity(
        vmc_streams=len(usable),
        imc_streams=imc_streams,
        air_carrier_runways=len(usable),
        parallel_pairs=pairs,
        min_parallel_separation_ft=min(separations) if separations else None,
    )
