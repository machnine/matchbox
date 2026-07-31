"""tests for representativeness and replication

The statistical machinery is verified against known values on synthetic data;
the live cohorts are then run through it, which is the actual §3.2 and §3.3 work.
"""

import sqlite3

import numpy as np
import pandas as pd
import pytest

from api.burden import AntibodyProfile, SpecMFI
from api.validation import (
    check_representativeness,
    chi2_2xn,
    chi2_sf,
    compare_frequencies,
    replicate_across_sets,
)

# --------------------------------------------------------------------------
# chi-square
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chi2,df,expected",
    [
        (3.841, 1, 0.05),
        (6.635, 1, 0.01),
        (5.991, 2, 0.05),
        (9.210, 2, 0.01),
        (7.815, 3, 0.05),
        (16.919, 9, 0.05),
    ],
)
def test_chi2_sf_matches_published_critical_values(chi2, df, expected):
    assert chi2_sf(chi2, df) == pytest.approx(expected, abs=0.006)


def test_chi2_sf_of_zero_is_one():
    assert chi2_sf(0, 1) == 1.0


def test_chi2_detects_a_real_difference():
    """two groups with plainly different rates"""
    table = np.array([[900, 100], [100, 900]])
    chi2, p = chi2_2xn(table)
    assert chi2 > 100
    assert p < 1e-10


def test_chi2_finds_nothing_in_identical_groups():
    table = np.array([[500, 500], [500, 500]])
    chi2, p = chi2_2xn(table)
    assert chi2 == pytest.approx(0.0)
    assert p == pytest.approx(1.0)


def test_chi2_declines_when_expected_counts_too_small():
    """a p-value the approximation does not support is not reported"""
    table = np.array([[1, 2], [2, 1]])
    chi2, p = chi2_2xn(table)
    assert chi2 is None
    assert p is None


def test_chi2_handles_empty_table():
    assert chi2_2xn(np.array([[0, 0], [0, 0]])) == (None, None)


# --------------------------------------------------------------------------
# frequency comparison
# --------------------------------------------------------------------------


def test_compare_frequencies_flags_a_planted_difference():
    rng = np.random.default_rng(0)
    a = pd.DataFrame({"X": rng.binomial(1, 0.5, 1000), "Y": rng.binomial(1, 0.3, 1000)})
    b = pd.DataFrame({"X": rng.binomial(1, 0.5, 1000), "Y": rng.binomial(1, 0.6, 1000)})
    results = {c.antigen: c for c in compare_frequencies(a, b, ["X", "Y"])}
    assert results["Y"].significant is True
    assert results["X"].significant is False


def test_compare_frequencies_applies_bonferroni():
    rng = np.random.default_rng(1)
    cols = [f"C{i}" for i in range(20)]
    a = pd.DataFrame({c: rng.binomial(1, 0.4, 800) for c in cols})
    b = pd.DataFrame({c: rng.binomial(1, 0.4, 800) for c in cols})
    results = compare_frequencies(a, b, cols)
    # under the null, no column should survive correction
    assert sum(1 for r in results if r.significant) == 0


# --------------------------------------------------------------------------
# representativeness on synthetic data
# --------------------------------------------------------------------------


def make_donors(n, dp_rate, x_rate_typed, x_rate_untyped, seed=0):
    """donors where DP typing status may or may not relate to antigen X"""
    rng = np.random.default_rng(seed)
    typed = rng.random(n) < dp_rate
    x = np.where(typed, rng.random(n) < x_rate_typed, rng.random(n) < x_rate_untyped)
    return pd.DataFrame(
        {
            "id": range(n),
            "bg": rng.choice(["O", "A", "B", "AB"], n, p=[0.46, 0.41, 0.10, 0.03]),
            "X1": x.astype(int),
            "Y1": rng.binomial(1, 0.3, n),
            "DPB4": typed.astype(int),
        }
    )


def test_representativeness_passes_when_subset_is_random():
    donors = make_donors(4000, 0.36, 0.5, 0.5, seed=2)
    report = check_representativeness(donors, ["X1", "Y1"])
    assert report.representative is True
    assert report.n_significant == 0


def test_representativeness_fails_when_subset_is_biased():
    donors = make_donors(4000, 0.36, 0.8, 0.3, seed=3)
    report = check_representativeness(donors, ["X1", "Y1"])
    assert report.representative is False
    assert report.n_significant >= 1


def test_representativeness_excludes_dp_columns_from_the_test():
    """DP columns define the split, so testing them would be circular"""
    donors = make_donors(2000, 0.36, 0.5, 0.5, seed=4)
    report = check_representativeness(donors, ["X1", "Y1", "DPB4"])
    assert "DPB4" not in [c.antigen for c in report.comparisons]


def test_representativeness_reports_group_sizes():
    donors = make_donors(1000, 0.4, 0.5, 0.5, seed=5)
    report = check_representativeness(donors, ["X1"])
    assert report.subset_size + report.complement_size == 1000


def test_representativeness_summary_is_readable():
    donors = make_donors(2000, 0.36, 0.5, 0.5, seed=6)
    assert "no detectable difference" in check_representativeness(donors, ["X1"]).summary()


# --------------------------------------------------------------------------
# the live representativeness check (§3.2)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_frames():
    conn = sqlite3.connect("data/donors.db")
    frames = {
        name: pd.read_sql_query(f"SELECT * FROM {name}", conn) for name in ("donors_v1", "donors_v2", "donors_v3")
    }
    conn.close()
    return frames


def test_live_dp_subset_is_representative(live_frames):
    """§3.2 answered against the real cohort

    If this fails, the 3,642 DP-typed donors are not a random sample of set 3 and
    every DP assessment inherits that bias. It is a finding in its own right, not
    a test failure to be silenced.
    """
    donors = live_frames["donors_v3"]
    antigens = [c for c in donors.columns if c not in ("id", "bg")]
    report = check_representativeness(donors, antigens)

    assert report.subset_size == 3642
    assert report.abo_p > 0.05, f"ABO differs between typed and untyped: p={report.abo_p}"
    assert report.n_significant == 0, (
        f"{report.n_significant} antigens differ: {[c.antigen for c in report.comparisons if c.significant]}"
    )


def test_live_representativeness_tests_a_meaningful_number_of_antigens(live_frames):
    donors = live_frames["donors_v3"]
    antigens = [c for c in donors.columns if c not in ("id", "bg")]
    report = check_representativeness(donors, antigens)
    assert report.n_tested > 100


# --------------------------------------------------------------------------
# replication (§3.3)
# --------------------------------------------------------------------------


def test_replication_runs_across_all_three_sets_for_non_dp_profile(live_frames):
    profile = AntibodyProfile(
        specs=[
            SpecMFI(spec="A1", current=6000),
            SpecMFI(spec="B7", current=9000),
            SpecMFI(spec="DR4", current=4000),
        ]
    )
    donor = live_frames["donors_v3"].iloc[0]
    report = replicate_across_sets(live_frames, "A", profile, donor, label="non-DP profile")
    assert len(report.statements) == 3


def test_replication_unavailable_for_dp_profile(live_frames):
    """the DP debt: a DP assessment cannot be corroborated by sets 1 and 2"""
    profile = AntibodyProfile(specs=[SpecMFI(spec="A1", current=6000), SpecMFI(spec="DPB4", current=8000)])
    donor = live_frames["donors_v3"].iloc[0]
    report = replicate_across_sets(live_frames, "A", profile, donor, label="DP profile")
    assert len(report.statements) == 1
    assert report.statements[0].donor_set == "donors_v3"
    assert report.replicates is False  # cannot be established, not established false


def test_replication_holds_for_defined_pairs(live_frames):
    """positional statements should be stable across cohorts

    A donor top-decile in one set and mid-pack in another means the position is
    an artefact of cohort choice rather than a property of the patient.
    """
    profiles = {
        "broad, one dominant": [
            SpecMFI(spec="A1", current=3000),
            SpecMFI(spec="B7", current=15000),
            SpecMFI(spec="DR4", current=2500),
        ],
        "several moderate": [
            SpecMFI(spec="A2", current=5000),
            SpecMFI(spec="B8", current=5500),
            SpecMFI(spec="DR15", current=6000),
        ],
        "narrow": [SpecMFI(spec="A3", current=8000)],
    }

    v3 = live_frames["donors_v3"]
    failures = []
    for label, specs in profiles.items():
        profile = AntibodyProfile(specs=specs)
        spec_names = [s.spec for s in specs]
        # a donor carrying every specificity, so it is scorable in all sets
        carriers = v3[v3[spec_names].eq(1).all(axis=1)]
        if carriers.empty:
            continue
        donor = carriers.iloc[0]
        for bg in ("O", "A"):
            report = replicate_across_sets(live_frames, bg, profile, donor, label=f"{label} / {bg}")
            if not report.replicates:
                failures.append(report.summary())

    assert not failures, "positional statements not stable across sets:\n" + "\n".join(failures)
