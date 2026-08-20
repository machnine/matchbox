"""verification tests for burden metrics and placement (§3.3)

Verification, not replication: every expected value here is hand-calculable from
the synthetic frame below. Replication across the three donor sets lives in
test_replication.py.
"""

import pandas as pd
import pytest
from pandas import Series

from api.burden import (
    AntibodyProfile,
    Metric,
    MFIBasis,
    SpecMFI,
    assess_offer,
    build_distribution,
    cohort_placement,
    compatible_population,
    identical_dsa_set_count,
    place,
    reference_population,
    resolve_specs,
    score,
    wilson_interval,
)
from api.cohort import select

# --------------------------------------------------------------------------
# synthetic cohort: 6 group-A donors, hand-checkable
# --------------------------------------------------------------------------
#  id  A1  B7  DR4   DSA vs profile {A1:4000, B7:2000, DR4:10000}
#   1   1   0    0   A1            -> cum 4000,  max 4000,  mean 4000,  med 4000
#   2   1   1    0   A1,B7         -> cum 6000,  max 4000,  mean 3000,  med 3000
#   3   0   0    1   DR4           -> cum 10000, max 10000, mean 10000, med 10000
#   4   1   1    1   A1,B7,DR4     -> cum 16000, max 10000, mean 5333.3, med 4000
#   5   0   0    0   none          -> compatible, excluded from reference set
#   6   0   1    0   B7            -> cum 2000,  max 2000,  mean 2000,  med 2000
DONORS = pd.DataFrame(
    {
        "id": [1, 2, 3, 4, 5, 6],
        "bg": ["A"] * 6,
        "A1": [1, 1, 0, 1, 0, 0],
        "B7": [0, 1, 0, 1, 0, 1],
        "DR4": [0, 0, 1, 1, 0, 0],
        "B8": [0, 0, 0, 0, 1, 0],
    }
)

PROFILE = AntibodyProfile(
    specs=[
        SpecMFI(spec="A1", current=4000, peak=8000),
        SpecMFI(spec="B7", current=2000, peak=2000),
        SpecMFI(spec="DR4", current=10000, peak=10000),
    ]
)

SPECS = ["A1", "B7", "DR4"]


def cohort_of(donors=DONORS, specs=SPECS):
    return select(donors, recipient_bg="A", specs=specs, stats_floor=0)


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------


def test_score_cumulative_is_sum_over_present_dsa():
    mfi = Series({"A1": 4000.0, "B7": 2000.0, "DR4": 10000.0})
    scored = score(DONORS, mfi)
    assert scored[Metric.CUMULATIVE.value].tolist() == [4000, 6000, 10000, 16000, 0, 2000]


def test_score_max_is_highest_single_specificity():
    mfi = Series({"A1": 4000.0, "B7": 2000.0, "DR4": 10000.0})
    scored = score(DONORS, mfi)
    assert scored[Metric.MAX.value].tolist() == [4000, 4000, 10000, 10000, 0, 2000]


def test_score_mean_divides_over_present_specs_not_all_specs():
    """the one-hot bug: dividing by 3 instead of by the DSA count"""
    mfi = Series({"A1": 4000.0, "B7": 2000.0, "DR4": 10000.0})
    scored = score(DONORS, mfi)
    means = scored[Metric.MEAN.value].tolist()
    assert means[0] == pytest.approx(4000)  # one DSA -> 4000/1, not 4000/3
    assert means[1] == pytest.approx(3000)  # two DSA -> 6000/2
    assert means[3] == pytest.approx(16000 / 3)


def test_score_median_ignores_absent_specificities():
    """donor 2 has DSA 4000 and 2000 -> median 3000, not 2000 (which a zero would give)"""
    mfi = Series({"A1": 4000.0, "B7": 2000.0, "DR4": 10000.0})
    scored = score(DONORS, mfi)
    medians = scored[Metric.MEDIAN.value].tolist()
    assert medians[1] == pytest.approx(3000)
    assert medians[3] == pytest.approx(4000)  # 2000,4000,10000 -> 4000


def test_score_counts_dsa():
    mfi = Series({"A1": 4000.0, "B7": 2000.0, "DR4": 10000.0})
    scored = score(DONORS, mfi)
    assert scored["n_dsa"].tolist() == [1, 2, 1, 3, 0, 1]


def test_score_donor_with_no_dsa_is_zero_not_nan():
    """the offered donor may legitimately carry none; must not produce NaN"""
    mfi = Series({"A1": 4000.0, "B7": 2000.0, "DR4": 10000.0})
    scored = score(DONORS, mfi)
    row = scored.iloc[4]
    assert row[Metric.MEAN.value] == 0
    assert row[Metric.MEDIAN.value] == 0
    assert row[Metric.MAX.value] == 0
    assert not scored.isna().any().any()


def test_score_with_no_specs_returns_zeros():
    scored = score(DONORS, Series(dtype=float))
    assert scored[Metric.CUMULATIVE.value].tolist() == [0] * 6
    assert scored["n_dsa"].tolist() == [0] * 6


# --------------------------------------------------------------------------
# reference population
# --------------------------------------------------------------------------


def test_reference_population_excludes_compatible_donors():
    ref = reference_population(cohort_of(), SPECS)
    assert list(ref.id) == [1, 2, 3, 4, 6]  # donor 5 has no DSA


def test_reference_population_empty_without_specs():
    assert reference_population(cohort_of(specs=[]), []).empty


def test_reference_is_most_of_cohort_for_broadly_sensitised():
    """the cRF inversion -- reference set is the incompatible majority"""
    ref = reference_population(cohort_of(), SPECS)
    assert len(ref) == 5
    assert len(ref) > len(DONORS) / 2


# --------------------------------------------------------------------------
# spec resolution
# --------------------------------------------------------------------------


def test_resolve_specs_separates_missing():
    present, missing = resolve_specs(["A1", "B99", "DR4"], DONORS)
    assert present == ["A1", "DR4"]
    assert missing == ["B99"]


def test_distribution_reports_specs_not_in_cohort():
    profile = AntibodyProfile(specs=[SpecMFI(spec="A1", current=4000), SpecMFI(spec="B99", current=5000)])
    dist = build_distribution(cohort_of(specs=["A1"]), profile, MFIBasis.CURRENT, percentile_floor=0)
    assert dist.specs_not_in_cohort == ["B99"]
    assert dist.specs_used == ["A1"]


# --------------------------------------------------------------------------
# threshold
# --------------------------------------------------------------------------


def test_threshold_excludes_subthreshold_specs():
    profile = AntibodyProfile(
        specs=[SpecMFI(spec="A1", current=4000), SpecMFI(spec="B7", current=500)],
        threshold=2000,
    )
    used = profile.series_for(MFIBasis.CURRENT)
    assert list(used.index) == ["A1"]
    assert profile.below_threshold(MFIBasis.CURRENT) == ["B7"]


def test_subthreshold_specs_retained_on_profile():
    """retained with a flag rather than dropped at ingest, so the threshold stays adjustable"""
    profile = AntibodyProfile(
        specs=[SpecMFI(spec="A1", current=4000), SpecMFI(spec="B7", current=500)],
        threshold=2000,
    )
    assert len(profile.specs) == 2
    lowered = AntibodyProfile(specs=profile.specs, threshold=400)
    assert list(lowered.series_for(MFIBasis.CURRENT).index) == ["A1", "B7"]


def test_threshold_is_inclusive_at_the_boundary():
    profile = AntibodyProfile(specs=[SpecMFI(spec="A1", current=2000)], threshold=2000)
    assert list(profile.series_for(MFIBasis.CURRENT).index) == ["A1"]


# --------------------------------------------------------------------------
# peak availability
# --------------------------------------------------------------------------


def test_peak_available_when_every_spec_has_it():
    assert PROFILE.has_peak is True
    assert PROFILE.available_bases == [MFIBasis.CURRENT, MFIBasis.PEAK]


def test_peak_unavailable_when_any_spec_lacks_it():
    """a peak sum over some specificities is not a peak sum"""
    profile = AntibodyProfile(specs=[SpecMFI(spec="A1", current=4000, peak=8000), SpecMFI(spec="B7", current=2000)])
    assert profile.has_peak is False
    assert profile.available_bases == [MFIBasis.CURRENT]


def test_offer_states_why_peak_unavailable():
    profile = AntibodyProfile(specs=[SpecMFI(spec="A1", current=4000, peak=8000), SpecMFI(spec="B7", current=2000)])
    result = assess_offer(cohort_of(specs=["A1", "B7"]), profile, DONORS.iloc[1], percentile_floor=0)
    assert result.peak_unavailable_reason is not None
    assert "B7" in result.peak_unavailable_reason


# --------------------------------------------------------------------------
# placement
# --------------------------------------------------------------------------


def test_placement_counts_lower_equal_higher():
    dist = build_distribution(cohort_of(), PROFILE, MFIBasis.CURRENT, percentile_floor=0)
    # cumulative values across the reference set: 4000, 6000, 10000, 16000, 2000
    p = place(dist, 6000, Metric.CUMULATIVE)
    assert p.n_lower == 2  # 2000, 4000
    assert p.n_equal == 1  # itself
    assert p.n_higher == 2  # 10000, 16000
    assert p.reference_size == 5


def test_placement_ties_counted_separately():
    """lower-vs-lower-or-equal must not move the headline number silently"""
    dist = build_distribution(cohort_of(), PROFILE, MFIBasis.CURRENT, percentile_floor=0)
    p = place(dist, 4000, Metric.MAX)
    # max values: 4000, 4000, 10000, 10000, 2000 -> one lower, two equal
    assert p.n_lower == 1
    assert p.n_equal == 2
    assert p.n_higher == 2


def test_placement_percentile_uses_strictly_lower():
    dist = build_distribution(cohort_of(), PROFILE, MFIBasis.CURRENT, percentile_floor=0)
    p = place(dist, 6000, Metric.CUMULATIVE)
    assert p.percentile == pytest.approx(40.0)  # 2/5
    assert p.empirical_percentile_range == pytest.approx([40.0, 60.0])


def test_placement_lowest_value_has_no_donors_below():
    dist = build_distribution(cohort_of(), PROFILE, MFIBasis.CURRENT, percentile_floor=0)
    p = place(dist, 2000, Metric.CUMULATIVE)
    assert p.n_lower == 0
    assert p.percentile == 0.0


def test_percentiles_suppressed_below_floor():
    """§6.4 -- refuse a smooth percentage over a handful of donors"""
    dist = build_distribution(cohort_of(), PROFILE, MFIBasis.CURRENT, percentile_floor=200)
    assert dist.percentiles_suppressed is True
    p = place(dist, 6000, Metric.CUMULATIVE)
    assert p.percentile is None
    assert p.suppressed_reason is not None
    assert p.n_lower == 2  # the count is still reported


def test_wilson_interval_brackets_the_estimate():
    lo, hi = wilson_interval(2, 5)
    assert lo < 0.4 < hi


def test_wilson_interval_is_wider_for_smaller_n():
    narrow = wilson_interval(40, 100)
    wide = wilson_interval(4, 10)
    assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])


def test_wilson_interval_handles_zero_n():
    assert wilson_interval(0, 0) == [0.0, 1.0]


# --------------------------------------------------------------------------
# identical DSA set
# --------------------------------------------------------------------------


def test_identical_dsa_set_count():
    # donor 2 carries A1+B7; no other donor carries exactly that set
    assert identical_dsa_set_count(cohort_of(), SPECS, ["A1", "B7"]) == 1
    # donor 1 carries A1 alone
    assert identical_dsa_set_count(cohort_of(), SPECS, ["A1"]) == 1
    # no donor carries A1+DR4 without B7
    assert identical_dsa_set_count(cohort_of(), SPECS, ["A1", "DR4"]) == 0


def test_identical_dsa_set_counts_compatible_donors_for_empty_set():
    """donor 5 carries none of the specificities"""
    assert identical_dsa_set_count(cohort_of(), SPECS, []) == 1


# --------------------------------------------------------------------------
# whole-offer assessment
# --------------------------------------------------------------------------


def test_assess_offer_identifies_dsa():
    result = assess_offer(cohort_of(), PROFILE, DONORS.iloc[3], percentile_floor=0)
    assert result.dsa_specs == ["A1", "B7", "DR4"]
    assert result.dsa_count == 3


def test_assess_offer_places_on_all_metrics_and_bases():
    result = assess_offer(cohort_of(), PROFILE, DONORS.iloc[1], percentile_floor=0)
    expected = {f"{b.value}:{m.value}" for b in (MFIBasis.CURRENT, MFIBasis.PEAK) for m in Metric}
    assert set(result.placements) == expected


def test_assess_offer_scores_donor_identically_to_cohort():
    """a difference in position must never come from a difference in scoring"""
    donor = DONORS.iloc[1]
    result = assess_offer(cohort_of(), PROFILE, donor, percentile_floor=0)
    cumulative = result.placements["current:cumulative"]
    assert cumulative.value == 6000
    # the donor is in the reference set, so it must tie with itself
    assert cumulative.n_equal >= 1


def test_assess_offer_current_and_peak_diverge():
    """divergence between bases is the signal, so both must be computed"""
    result = assess_offer(cohort_of(), PROFILE, DONORS.iloc[0], percentile_floor=0)
    current = result.placements["current:cumulative"].value
    peak = result.placements["peak:cumulative"].value
    assert current == 4000
    assert peak == 8000  # A1 peak is double its current


def test_peak_can_be_ranked_when_current_has_no_active_dsa():
    profile = AntibodyProfile(specs=[SpecMFI(spec="A1", current=1000, peak=8000)], threshold=2000)
    result = assess_offer(cohort_of(specs=["A1"]), profile, DONORS.iloc[0], percentile_floor=0)

    assert result.offer_status == "no_active_specificities"
    assert "current:cumulative" not in result.placements
    assert result.basis_summaries["peak"].status == "ranked_incompatible"
    assert result.placements["peak:cumulative"].value == 8000


def test_assess_offer_compatible_donor_is_not_ranked():
    """compatible donors do not belong in an incompatible-offer ranking."""
    result = assess_offer(cohort_of(), PROFILE, DONORS.iloc[4], percentile_floor=0)
    assert result.dsa_count == 0
    assert result.offer_status == "compatible_no_dsa"
    assert result.basis_summaries["current"].status == "compatible_no_dsa"
    assert not any(key.startswith("current:") for key in result.placements)


# --------------------------------------------------------------------------
# metric disagreement -- the clinical signal
# --------------------------------------------------------------------------


def test_distinct_burden_values_are_bounded_by_specificity_count():
    """burden is a function of which specificities a donor carries, not of the donor

    With n specificities there are at most 2**n - 1 distinct burden values in the
    reference set, however large the cohort. The distribution is therefore heavily
    tied and the percentile is a coarse quantity -- which is why counts, and
    n_equal in particular, carry the clinical meaning rather than the percentile.
    """
    dist = build_distribution(cohort_of(), PROFILE, MFIBasis.CURRENT, percentile_floor=0)
    distinct = len(set(dist.values[Metric.CUMULATIVE]))
    assert distinct <= 2 ** len(SPECS) - 1


def test_single_specificity_gives_a_degenerate_distribution():
    """every donor in the reference set has identical burden

    A percentile here is not informative and the count is the whole answer. The
    tool must not present a single-DSA ranking as though it discriminated.
    """
    profile = AntibodyProfile(specs=[SpecMFI(spec="A1", current=4000)])
    dist = build_distribution(cohort_of(specs=["A1"]), profile, MFIBasis.CURRENT, percentile_floor=0)
    assert len(set(dist.values[Metric.CUMULATIVE])) == 1
    p = place(dist, 4000, Metric.CUMULATIVE)
    assert p.n_lower == 0
    assert p.n_equal == dist.reference_size
    assert p.percentile == 0.0


def test_ties_are_reported_not_hidden():
    """n_equal must be visible: it is often most of the reference set"""
    dist = build_distribution(cohort_of(), PROFILE, MFIBasis.CURRENT, percentile_floor=0)
    p = place(dist, 4000, Metric.MAX)
    assert p.n_equal > 0
    assert p.n_lower + p.n_equal + p.n_higher == p.reference_size


def test_metrics_can_disagree_on_ordering():
    """low cumulative with high max = one dominant antibody; both must be exposed"""
    dist = build_distribution(cohort_of(), PROFILE, MFIBasis.CURRENT, percentile_floor=0)
    # donor 3: cumulative 10000 (3rd of 5), max 10000 (joint highest)
    cum = place(dist, 10000, Metric.CUMULATIVE)
    mx = place(dist, 10000, Metric.MAX)
    assert cum.n_lower == 3
    assert mx.n_lower == 3
    # donor 6: cumulative 2000 lowest, mean 2000 lowest
    low = place(dist, 2000, Metric.CUMULATIVE)
    assert low.n_lower == 0


# --------------------------------------------------------------------------
# cohort-wide placement
# --------------------------------------------------------------------------
# The incompatible-only reference answers "among incompatible offers, where does
# this sit". It cannot answer "is this a good donor for this patient", because
# every donor it excludes was excluded for being compatible -- i.e. better.
#
# Cumulative scores over DONORS: [4000, 6000, 10000, 16000, 0, 2000]
# Donor 5 scores 0: compatible.


def test_compatible_population_is_the_other_half_of_the_dsa_split():
    compatible = compatible_population(cohort_of(), SPECS)
    assert compatible.id.tolist() == [5]
    incompatible = reference_population(cohort_of(), SPECS)
    assert len(compatible) + len(incompatible) == len(DONORS)


def test_cohort_placement_counts_compatible_donors_as_better():
    """A donor carrying B7 alone scores 2000; only donor 5 (compatible) is lower."""
    donor = Series({"id": -1, "bg": "A", "A1": 0, "B7": 1, "DR4": 0, "B8": 0})
    placed = cohort_placement(cohort_of(), PROFILE, donor)
    assert placed.cohort_size == 6
    assert placed.n_compatible == 1  # donor 5
    assert placed.n_incompatible == 5
    assert placed.n_lower == 1  # donor 5 (0) is the only score below 2000
    assert placed.n_equal == 1  # donor 6 also scores 2000
    assert placed.n_higher == 4  # 4000, 6000, 10000, 16000
    assert placed.n_lower + placed.n_equal + placed.n_higher == 6


def test_cohort_placement_puts_a_heavy_offer_near_the_top():
    """Carrying all three specificities scores 16000 -- the worst in the frame."""
    donor = Series({"id": -1, "bg": "A", "A1": 1, "B7": 1, "DR4": 1, "B8": 0})
    placed = cohort_placement(cohort_of(), PROFILE, donor)
    assert placed.n_higher == 0
    assert placed.n_lower == 5
    assert placed.percentile == pytest.approx(100 * 5 / 6)


def test_cohort_placement_reports_the_compatible_share():
    donor = Series({"id": -1, "bg": "A", "A1": 1, "B7": 0, "DR4": 0, "B8": 0})
    placed = cohort_placement(cohort_of(), PROFILE, donor)
    assert placed.compatible_share == pytest.approx(100 / 6)


def test_single_dsa_profile_still_separates_compatible_from_incompatible():
    """The case that motivated this: with one specificity the incompatible set
    has a single distinct value, so ranking inside it is vacuous -- but the
    compatible/incompatible split is still informative."""
    profile = AntibodyProfile(specs=[SpecMFI(spec="B7", current=2000, peak=2000)])
    cohort = cohort_of(specs=["B7"])
    donor = Series({"id": -1, "bg": "A", "A1": 0, "B7": 1, "DR4": 0, "B8": 0})
    placed = cohort_placement(cohort, profile, donor)

    # donors 2, 4, 6 carry B7; the other three do not
    assert placed.n_incompatible == 3
    assert placed.n_compatible == 3
    assert placed.n_lower == 3  # every compatible donor is a better offer
    assert placed.n_equal == 3  # every incompatible donor is identical
    assert placed.n_higher == 0

    # and the incompatible-only view is indeed vacuous, which is the point
    distribution = build_distribution(cohort, profile, MFIBasis.CURRENT)
    assert len(set(distribution.values[Metric.CUMULATIVE])) == 1


def test_cohort_placement_is_none_without_active_specificities():
    profile = AntibodyProfile(specs=[SpecMFI(spec="A1", current=100)], threshold=2000)
    donor = Series({"id": -1, "bg": "A", "A1": 1, "B7": 0, "DR4": 0, "B8": 0})
    assert cohort_placement(cohort_of(), profile, donor) is None


def test_assess_offer_carries_cohort_placements_per_basis():
    donor = Series({"id": -1, "bg": "A", "A1": 1, "B7": 0, "DR4": 0, "B8": 0})
    result = assess_offer(cohort_of(), PROFILE, donor)
    assert set(result.cohort_placements) == {"current", "peak"}
    assert result.cohort_placements["current"].cohort_size == 6
