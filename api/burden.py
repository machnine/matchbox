"""antibody burden metrics and placement of an offered donor

At the point of a deceased-donor offer, a patient being considered for
antibody-incompatible transplantation has a known DSA profile against the offered
donor. The question is not whether the donor is compatible -- by definition it is
not -- but whether this incompatibility is as easy as this patient is realistically
going to see, or ordinary.

This module answers that by scoring every donor in the reference population by
antibody burden and placing the offered donor on that distribution. Everything is
read off the cohort as it stands; nothing is predicted.

No metric is asserted to be correct. There is no settled measure of
desensitisation difficulty, so all four are exposed and the user decides. Where
they disagree, that disagreement is itself the signal -- low cumulative with high
max means one dominant antibody.
"""

from enum import Enum
from math import sqrt
from typing import Dict, List, Optional

from pandas import DataFrame, Series
from pydantic import BaseModel

from .calculator import split_by_dsa
from .cohort import Cohort

# Default MFI above which a specificity is treated as a DSA. Visible in every
# response: it determines both which donors are incompatible and which
# specificities enter the sums, so it propagates into every number downstream.
DEFAULT_DSA_THRESHOLD = 2000

# Below this many donors in the reference set, percentiles are suppressed and
# only raw counts with an interval are reported (§6.4).
MIN_REFERENCE_FOR_PERCENTILE = 200


class Metric(str, Enum):
    """burden metrics, all computed over the DSA present against each donor"""

    CUMULATIVE = "cumulative"  # sum of MFI across DSA -- what clinicians use
    MAX = "max"  # highest single specificity -- one strong vs several moderate
    MEAN = "mean"  # cumulative / DSA count -- typical strength per specificity
    MEDIAN = "median"  # median across DSA present -- robust to one outlier


class MFIBasis(str, Enum):
    """which MFI reading the metrics are computed on"""

    CURRENT = "current"
    PEAK = "peak"


class SpecMFI(BaseModel):
    """one specificity with its current and optionally peak MFI"""

    spec: str
    current: float
    peak: Optional[float] = None

    def value_for(self, basis: MFIBasis) -> Optional[float]:
        return self.current if basis is MFIBasis.CURRENT else self.peak


class AntibodyProfile(BaseModel):
    """a patient's antibody profile

    Peak is optional per specificity. If any specificity lacks a peak value the
    peak basis is unavailable for the whole profile rather than being computed
    over an inconsistent subset -- a peak sum over three of five specificities is
    not a peak sum, and would sit on the same axis as one that is.
    """

    specs: List[SpecMFI]
    threshold: float = DEFAULT_DSA_THRESHOLD

    @property
    def has_peak(self) -> bool:
        return bool(self.specs) and all(s.peak is not None for s in self.specs)

    @property
    def available_bases(self) -> List[MFIBasis]:
        bases = [MFIBasis.CURRENT]
        if self.has_peak:
            bases.append(MFIBasis.PEAK)
        return bases

    def series_for(self, basis: MFIBasis) -> Series:
        """spec -> MFI for the given basis, above threshold only

        Sub-threshold specificities are retained on the profile (so the threshold
        stays adjustable after paste) but excluded here.
        """
        values = {}
        for s in self.specs:
            v = s.value_for(basis)
            if v is not None and v >= self.threshold:
                values[s.spec] = v
        return Series(values, dtype=float)

    def below_threshold(self, basis: MFIBasis) -> List[str]:
        """specificities retained on the profile but not counted at this threshold"""
        out = []
        for s in self.specs:
            v = s.value_for(basis)
            if v is not None and v < self.threshold:
                out.append(s.spec)
        return out


class Distribution(BaseModel):
    """the burden distribution over a reference population, for one basis"""

    basis: MFIBasis
    threshold: float
    reference_size: int
    specs_used: List[str]
    specs_below_threshold: List[str]
    specs_not_in_cohort: List[str]
    percentiles_suppressed: bool
    # metric -> sorted ascending values, one per donor in the reference set
    values: Dict[Metric, List[float]]

    model_config = {"arbitrary_types_allowed": True}


class Placement(BaseModel):
    """where one offered donor sits on the distribution, for one metric"""

    metric: Metric
    basis: MFIBasis
    value: float
    n_lower: int
    n_equal: int
    n_higher: int
    reference_size: int
    percentile: Optional[float] = None
    percentile_ci: Optional[List[float]] = None
    suppressed_reason: Optional[str] = None


class OfferPlacement(BaseModel):
    """the full placement of an offered donor across metrics and bases"""

    dsa_specs: List[str]
    dsa_count: int
    placements: Dict[str, Placement]  # "basis:metric" -> Placement
    identical_dsa_set_count: int
    reference_size: int
    bases_available: List[MFIBasis]
    peak_unavailable_reason: Optional[str] = None


def wilson_interval(k: int, n: int, z: float = 1.96) -> List[float]:
    """Wilson score interval for a proportion

    Used instead of a bare percentage where counts are small -- a smooth-looking
    percentage over a handful of donors overstates what the cohort supports.
    """
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [max(0.0, centre - half), min(1.0, centre + half)]


def resolve_specs(profile_specs: List[str], donors: DataFrame) -> tuple[List[str], List[str]]:
    """split requested specificities into those the cohort can score and those it cannot

    A specificity absent from the donor matrix cannot contribute burden. Silently
    dropping it would understate burden; the caller is given the list so it can
    be surfaced.
    """
    present = [s for s in profile_specs if s in donors.columns]
    missing = [s for s in profile_specs if s not in donors.columns]
    return present, missing


def score(donors: DataFrame, mfi: Series) -> DataFrame:
    """burden metrics for every donor in a frame

    One pass over the whole reference set as matrix operations rather than a
    per-donor loop. Returns a frame indexed like `donors` with one column per
    metric.

    mean and median divide over the specificities *present* against each donor,
    never over all specificities in the profile -- the easy bug to introduce with
    a one-hot matrix, since a zero in a column the donor does not carry would
    otherwise drag both down.
    """
    if mfi.empty:
        zeros = Series(0.0, index=donors.index)
        return DataFrame(
            {
                Metric.CUMULATIVE.value: zeros,
                Metric.MAX.value: zeros,
                Metric.MEAN.value: zeros,
                Metric.MEDIAN.value: zeros,
                "n_dsa": Series(0, index=donors.index),
            }
        )

    hits = donors[list(mfi.index)].eq(1)
    burden = hits.mul(mfi, axis=1)
    n_dsa = hits.sum(axis=1)

    # where a donor carries none of the specificities, every metric is zero
    # rather than NaN: such donors are compatible and excluded from the reference
    # set by construction, but the offered donor is scored by this same function
    # and may legitimately carry none.
    present_only = burden.where(hits)
    cumulative = burden.sum(axis=1)
    maximum = present_only.max(axis=1).fillna(0.0)
    mean = (cumulative / n_dsa.where(n_dsa > 0)).fillna(0.0)
    median = present_only.median(axis=1).fillna(0.0)

    return DataFrame(
        {
            Metric.CUMULATIVE.value: cumulative,
            Metric.MAX.value: maximum,
            Metric.MEAN.value: mean,
            Metric.MEDIAN.value: median,
            "n_dsa": n_dsa,
        }
    )


def reference_population(cohort: Cohort, specs: List[str]) -> DataFrame:
    """donors in the cohort with at least one DSA -- the population the offer ranks within

    The incompatible half of the same split that produces the cRF denominator,
    so the two tools cannot disagree about what a DSA is.

    Note the inversion from a cRF calculation: for a cRF 99% patient this is ~99%
    of the eligible cohort, not 1%. Sparsity is not the binding constraint it
    would be for compatible-donor work.
    """
    return split_by_dsa(cohort.donors, specs)[1]


def build_distribution(
    cohort: Cohort,
    profile: AntibodyProfile,
    basis: MFIBasis,
    percentile_floor: int = MIN_REFERENCE_FOR_PERCENTILE,
) -> Distribution:
    """score the reference population and return the burden distribution

    Cacheable per resolved selection. The cache key must include everything in
    the cohort's provenance plus the threshold and basis -- not the patient
    profile alone, since the same profile under a different DP mode or ABO rule
    produces a different and non-comparable distribution.
    """
    mfi = profile.series_for(basis)
    present, missing = resolve_specs(list(mfi.index), cohort.donors)
    mfi = mfi[present] if present else Series(dtype=float)

    reference = reference_population(cohort, present)
    scored = score(reference, mfi)

    values = {m: sorted(scored[m.value].tolist()) for m in Metric}
    return Distribution(
        basis=basis,
        threshold=profile.threshold,
        reference_size=len(reference),
        specs_used=present,
        specs_below_threshold=profile.below_threshold(basis),
        specs_not_in_cohort=missing,
        percentiles_suppressed=len(reference) < percentile_floor,
        values=values,
    )


def place(
    distribution: Distribution,
    donor_value: float,
    metric: Metric,
) -> Placement:
    """place one value on a distribution

    Reports the count of donors with lower burden alongside the percentile. The
    count matters more: it survives translation into a clinical conversation, and
    it is sensitive to the ABO denominator in a way the percentile is not.

    Ties are counted separately rather than folded into either side. With MFI
    values from an SAB export exact ties are common -- values land on round
    numbers, and single-DSA donors sharing a specificity score identically -- so
    lower-vs-lower-or-equal would otherwise move the headline number silently.
    """
    values = distribution.values[metric]
    n = len(values)
    n_lower = sum(1 for v in values if v < donor_value)
    n_equal = sum(1 for v in values if v == donor_value)
    n_higher = n - n_lower - n_equal

    percentile = None
    ci = None
    reason = None
    if distribution.percentiles_suppressed:
        reason = f"reference set of {n} is below the floor of {MIN_REFERENCE_FOR_PERCENTILE} for percentiles"
    elif n:
        percentile = 100.0 * n_lower / n
        ci = [100.0 * b for b in wilson_interval(n_lower, n)]

    return Placement(
        metric=metric,
        basis=distribution.basis,
        value=donor_value,
        n_lower=n_lower,
        n_equal=n_equal,
        n_higher=n_higher,
        reference_size=n,
        percentile=percentile,
        percentile_ci=ci,
        suppressed_reason=reason,
    )


def identical_dsa_set_count(cohort: Cohort, specs: List[str], donor_specs: List[str]) -> int:
    """how many donors in the cohort carry exactly this donor's DSA specificity set"""
    if not specs:
        return 0
    hits = cohort.donors[specs].eq(1)
    target = Series({s: (s in donor_specs) for s in specs})
    return int(hits.eq(target, axis=1).all(axis=1).sum())


def assess_offer(
    cohort: Cohort,
    profile: AntibodyProfile,
    donor: Series,
    percentile_floor: int = MIN_REFERENCE_FOR_PERCENTILE,
) -> OfferPlacement:
    """place an offered donor on the reference distributions

    The offered donor is scored by the same function that scores the cohort, so
    a difference in position can never come from a difference in scoring.
    """
    bases = profile.available_bases
    peak_reason = None
    if MFIBasis.PEAK not in bases:
        missing = [s.spec for s in profile.specs if s.peak is None]
        peak_reason = f"peak MFI missing for {len(missing)} of {len(profile.specs)} specificities: {', '.join(missing)}"

    placements: Dict[str, Placement] = {}
    dsa_specs: List[str] = []
    reference_size = 0
    ident_count = 0

    for basis in bases:
        distribution = build_distribution(cohort, profile, basis, percentile_floor=percentile_floor)
        reference_size = distribution.reference_size
        mfi = profile.series_for(basis)[distribution.specs_used]

        donor_frame = donor.to_frame().T
        scored = score(donor_frame, mfi)

        if basis is MFIBasis.CURRENT:
            dsa_specs = [s for s in distribution.specs_used if donor.get(s) == 1]
            ident_count = identical_dsa_set_count(cohort, distribution.specs_used, dsa_specs)

        for metric in Metric:
            value = float(scored[metric.value].iloc[0])
            placements[f"{basis.value}:{metric.value}"] = place(distribution, value, metric)

    return OfferPlacement(
        dsa_specs=dsa_specs,
        dsa_count=len(dsa_specs),
        placements=placements,
        identical_dsa_set_count=ident_count,
        reference_size=reference_size,
        bases_available=bases,
        peak_unavailable_reason=peak_reason,
    )
