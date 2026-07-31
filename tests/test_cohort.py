"""tests for cohort selection

Two kinds of test here, kept separate on purpose (§3.3):

* Verification -- does the code compute what it claims? Uses a small synthetic
  frame with hand-checkable answers.
* Data pinning -- do the real cohorts still have the properties the design rests
  on? Uses the live database and will fail loudly if the donor tables change.
"""

import sqlite3

import pandas as pd
import pytest

from api.cohort import (
    DP_TYPED_SETS,
    LIVE_DONOR_SET,
    MIN_COHORT_FOR_STATS,
    ABOPolicyUnavailable,
    ABORule,
    CohortTooSmall,
    DPMode,
    Tier,
    donor_bgs_for,
    dp_columns,
    dp_typed_mask,
    resolve_dp_mode,
    select,
    split_dp_specs,
)

# --------------------------------------------------------------------------
# synthetic frame: 8 donors, hand-checkable
# --------------------------------------------------------------------------
# bg      A   A   A   O   O   B   B   AB
# A1      1   0   1   0   1   0   0   0
# DPB4    1   1   0   0   0   0   1   0   <- donors 0,1,6 DP-typed
# DPB2    0   1   0   0   0   0   0   0
SYNTHETIC = pd.DataFrame(
    {
        "id": [1, 2, 3, 4, 5, 6, 7, 8],
        "bg": ["A", "A", "A", "O", "O", "B", "B", "AB"],
        "A1": [1, 0, 1, 0, 1, 0, 0, 0],
        "B7": [0, 1, 0, 1, 0, 1, 0, 1],
        "DPB4": [1, 1, 0, 0, 0, 0, 1, 0],
        "DPB2": [0, 1, 0, 0, 0, 0, 0, 0],
    }
)

NO_DP = SYNTHETIC.drop(columns=["DPB4", "DPB2"])


def test_dp_columns_found():
    assert dp_columns(SYNTHETIC) == ["DPB4", "DPB2"]


def test_dp_columns_empty_for_non_dp_set():
    assert dp_columns(NO_DP) == []


def test_dp_typed_mask_identifies_typed_donors():
    mask = dp_typed_mask(SYNTHETIC)
    assert list(SYNTHETIC[mask].id) == [1, 2, 7]


def test_dp_typed_mask_all_false_without_dp_columns():
    assert not dp_typed_mask(NO_DP).any()


def test_split_dp_specs():
    dp, non_dp = split_dp_specs(["A1", "DPB4", "B7", "DPB2"])
    assert dp == ["DPB4", "DPB2"]
    assert non_dp == ["A1", "B7"]


@pytest.mark.parametrize(
    "requested,has_dp,expected",
    [
        (DPMode.AUTO, True, DPMode.INCLUDE),
        (DPMode.AUTO, False, DPMode.EXCLUDE),
        (DPMode.INCLUDE, False, DPMode.INCLUDE),
        (DPMode.EXCLUDE, True, DPMode.EXCLUDE),
    ],
)
def test_resolve_dp_mode(requested, has_dp, expected):
    assert resolve_dp_mode(requested, has_dp) == expected


# --------------------------------------------------------------------------
# ABO
# --------------------------------------------------------------------------


def test_identical_abo_returns_only_that_group():
    assert donor_bgs_for("A", ABORule.IDENTICAL) == frozenset({"A"})


def test_offerable_abo_raises_until_policy_encoded():
    """the offerable mapping must not be inferred -- see OFFERABLE_ABO"""
    with pytest.raises(ABOPolicyUnavailable):
        donor_bgs_for("AB", ABORule.OFFERABLE, organ="kidney", tier=Tier.A)


def test_offerable_abo_raises_without_organ_and_tier():
    with pytest.raises(ABOPolicyUnavailable):
        donor_bgs_for("AB", ABORule.OFFERABLE)


def test_offerable_abo_does_not_silently_fall_back_to_identical():
    """a policy gap must fail, not quietly understate the pool"""
    with pytest.raises(ABOPolicyUnavailable):
        select(
            SYNTHETIC,
            recipient_bg="A",
            specs=[],
            abo_rule=ABORule.OFFERABLE,
            organ="kidney",
            tier=Tier.A,
            stats_floor=0,
        )


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------


def test_identical_selection_filters_to_blood_group():
    cohort = select(SYNTHETIC, recipient_bg="A", specs=["A1"], stats_floor=0)
    assert len(cohort) == 3
    assert set(cohort.donors.bg) == {"A"}
    assert cohort.provenance.donor_bgs == ["A"]


def test_unknown_blood_group_rejected():
    with pytest.raises(ValueError, match="no donors of blood group"):
        select(SYNTHETIC, recipient_bg="Z", specs=[], stats_floor=0)


def test_auto_with_dp_specs_restricts_to_dp_typed():
    cohort = select(SYNTHETIC, recipient_bg="A", specs=["A1", "DPB4"], stats_floor=0)
    p = cohort.provenance
    assert p.dp_mode_applied is DPMode.INCLUDE
    assert p.dp_typed_only is True
    # of the three group-A donors, two are DP-typed
    assert p.set_size_before_dp == 3
    assert p.cohort_size == 2
    # DP specs are retained, not dropped
    assert cohort.specs == ["A1", "DPB4"]
    assert p.dp_specs_dropped == []


def test_auto_without_dp_specs_uses_full_set():
    cohort = select(SYNTHETIC, recipient_bg="A", specs=["A1"], stats_floor=0)
    p = cohort.provenance
    assert p.dp_mode_applied is DPMode.EXCLUDE
    assert p.dp_typed_only is False
    assert p.cohort_size == 3
    assert p.patient_has_dp_specs is False


def test_exclude_drops_dp_specs_and_records_them():
    """the discard must be visible, not silent"""
    cohort = select(
        SYNTHETIC,
        recipient_bg="A",
        specs=["A1", "DPB4", "DPB2"],
        dp_mode=DPMode.EXCLUDE,
        stats_floor=0,
    )
    p = cohort.provenance
    assert p.dp_typed_only is False
    assert p.cohort_size == 3  # full group-A set, not the typed subset
    assert cohort.specs == ["A1"]
    assert p.dp_specs_dropped == ["DPB4", "DPB2"]
    assert p.patient_has_dp_specs is True


def test_include_rejected_on_set_without_dp_typing():
    with pytest.raises(ValueError, match="carries no DP typing"):
        select(
            NO_DP,
            recipient_bg="A",
            specs=["A1", "DPB4"],
            donor_set="donors_v1",
            dp_mode=DPMode.INCLUDE,
            stats_floor=0,
        )


def test_dp_typed_selection_is_not_corroborable():
    """§3.1 -- a DP assessment cannot be checked against sets 1 and 2"""
    dp = select(SYNTHETIC, recipient_bg="A", specs=["DPB4"], stats_floor=0)
    non_dp = select(SYNTHETIC, recipient_bg="A", specs=["A1"], stats_floor=0)
    assert dp.provenance.is_dp_corroborable is False
    assert non_dp.provenance.is_dp_corroborable is True


def test_defaults_are_recorded_as_defaults():
    """§5.3 -- where a choice was made by default rather than explicitly, say so"""
    cohort = select(SYNTHETIC, recipient_bg="A", specs=["A1"], stats_floor=0)
    assert "dp_mode=auto" in cohort.provenance.defaulted
    assert "abo_rule=identical" in cohort.provenance.defaulted


def test_explicit_dp_mode_not_recorded_as_default():
    cohort = select(SYNTHETIC, recipient_bg="A", specs=["A1"], dp_mode=DPMode.EXCLUDE, stats_floor=0)
    assert "dp_mode=auto" not in cohort.provenance.defaulted


# --------------------------------------------------------------------------
# sparse cohorts (§6.4)
# --------------------------------------------------------------------------


def test_small_cohort_flagged_by_default():
    cohort = select(SYNTHETIC, recipient_bg="AB", specs=[], stats_floor=10)
    assert cohort.provenance.below_stats_floor is True
    assert cohort.provenance.cohort_size == 1


def test_small_cohort_raises_under_strict_floor():
    with pytest.raises(CohortTooSmall) as exc:
        select(SYNTHETIC, recipient_bg="AB", specs=[], stats_floor=10, strict_floor=True)
    assert exc.value.n == 1
    assert exc.value.floor == 10


def test_large_enough_cohort_not_flagged():
    cohort = select(SYNTHETIC, recipient_bg="A", specs=[], stats_floor=2)
    assert cohort.provenance.below_stats_floor is False


# --------------------------------------------------------------------------
# data pinning against the live database
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_donors():
    conn = sqlite3.connect("data/donors.db")
    frames = {t: pd.read_sql_query(f"SELECT * FROM {t}", conn) for t in ("donors_v1", "donors_v2", "donors_v3")}
    yield frames
    conn.close()


def test_only_v3_has_dp_typing(live_donors):
    assert dp_columns(live_donors["donors_v1"]) == []
    assert dp_columns(live_donors["donors_v2"]) == []
    assert len(dp_columns(live_donors["donors_v3"])) == 27
    assert DP_TYPED_SETS == frozenset({"donors_v3"})
    assert LIVE_DONOR_SET == "donors_v3"


def test_dp_typed_subset_size(live_donors):
    """the handoff spec says ~3,571; the database says 3,642"""
    assert int(dp_typed_mask(live_donors["donors_v3"]).sum()) == 3642


def test_dp_is_the_only_locus_with_untyped_donors(live_donors):
    """§6.3 collapses to the DP question alone in this data

    If this fails, another locus has acquired untyped donors and the
    untyped-vs-zero problem is no longer DP-only.
    """
    import re

    donors = live_donors["donors_v3"]
    by_locus = {}
    for col in donors.columns:
        if col in ("id", "bg"):
            continue
        if match := re.match(r"^([ABCDRQPW]{1,3})\d", col):
            by_locus.setdefault(match.group(1), []).append(col)

    untyped = {locus: int((donors[cols].sum(axis=1) == 0).sum()) for locus, cols in by_locus.items()}
    assert untyped["DPB"] == 6358
    for locus in ("A", "B", "CW", "DR", "DQ"):
        assert untyped[locus] == 0, f"{locus} now has untyped donors"


def test_live_identical_cohort_sizes(live_donors):
    """identical-only denominators, which cRF must keep using"""
    expected = {"O": 4620, "A": 4094, "B": 962, "AB": 324}
    for bg, n in expected.items():
        cohort = select(live_donors["donors_v3"], recipient_bg=bg, specs=[], stats_floor=0)
        assert cohort.provenance.cohort_size == n


def test_live_dp_typed_cohort_sizes(live_donors):
    """the sparse case that makes the ABO work load-bearing

    An AB patient with DP antibodies has 118 identical-only donors -- far below
    the floor for reporting percentiles.
    """
    expected = {"O": 1679, "A": 1481, "B": 364, "AB": 118}
    for bg, n in expected.items():
        cohort = select(live_donors["donors_v3"], recipient_bg=bg, specs=["DPB4"], stats_floor=0)
        assert cohort.provenance.dp_typed_only is True
        assert cohort.provenance.cohort_size == n


def test_ab_dp_patient_is_below_stats_floor(live_donors):
    cohort = select(live_donors["donors_v3"], recipient_bg="AB", specs=["DPB4"])
    assert cohort.provenance.below_stats_floor is True
    assert cohort.provenance.cohort_size < MIN_COHORT_FOR_STATS


def test_o_dp_patient_is_above_stats_floor(live_donors):
    cohort = select(live_donors["donors_v3"], recipient_bg="O", specs=["DPB4"])
    assert cohort.provenance.below_stats_floor is False
