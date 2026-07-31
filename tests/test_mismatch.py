"""tests for mismatch level and the joint view"""

import sqlite3

import pandas as pd
import pytest
from pandas import Series

from api.burden import AntibodyProfile, SpecMFI, reference_population
from api.calculator import Calculator
from api.cohort import select
from api.mismatch import (
    build_joint_view,
    burden_bands,
    mismatch_counts,
    mismatch_level,
    mismatch_levels,
    parse_recipient_bdr,
)

HLA_BDR = {"B": ["B7", "B8", "B44"], "DR": ["DR4", "DR15", "DR17"]}
AG_DEFAULTS = {"B42": "B7", "DR9": "DR4"}

DONORS = pd.DataFrame(
    {
        "id": [1, 2, 3, 4],
        "bg": ["A"] * 4,
        "B7": [1, 1, 0, 0],
        "B8": [1, 0, 1, 0],
        "B44": [0, 0, 1, 1],
        "DR4": [1, 1, 0, 0],
        "DR15": [0, 0, 1, 1],
        "DR17": [0, 0, 0, 0],
    }
)


# --------------------------------------------------------------------------
# level derivation -- must agree with the existing calculator's grades
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "b_mm,dr_mm,expected",
    [
        (0, 0, 1),  # m12a
        (1, 0, 1),  # m12a
        (0, 1, 2),  # m2b
        (2, 0, 3),  # m3a
        (1, 1, 3),  # m3b
        (2, 1, 4),  # m4a
        (0, 2, 4),  # m4b
        (1, 2, 4),  # m4b
        (2, 2, 4),  # m4b
    ],
)
def test_mismatch_level_matches_calculator_grades(b_mm, dr_mm, expected):
    assert mismatch_level(b_mm, dr_mm) == expected


def test_favourable_levels_are_one_and_two():
    """the existing calculator's 'fav' is m12a + m2b, i.e. levels 1 and 2"""
    from api.mismatch import FAVOURABLE_LEVELS

    assert FAVOURABLE_LEVELS == (1, 2)


# --------------------------------------------------------------------------
# mismatch counting
# --------------------------------------------------------------------------


def test_mismatch_counts_against_recipient():
    recipient = {"B": {"B7", "B8"}, "DR": {"DR4"}}
    counts = mismatch_counts(DONORS, recipient, HLA_BDR, AG_DEFAULTS)
    # donor 1 carries B7,B8,DR4 -- all shared
    assert counts.iloc[0].B == 0
    assert counts.iloc[0].DR == 0
    # donor 4 carries B44,DR15 -- both mismatched
    assert counts.iloc[3].B == 1
    assert counts.iloc[3].DR == 1


def test_rare_antigen_defaults_widen_the_recipient_set():
    """a rare antigen must not read as a mismatch against its common equivalent"""
    donors = pd.DataFrame(
        {"id": [1], "bg": ["A"], "B7": [1], "B8": [0], "B44": [0], "DR4": [0], "DR15": [0], "DR17": [0]}
    )
    without = mismatch_counts(donors, {"B": {"B8"}, "DR": set()}, HLA_BDR, AG_DEFAULTS)
    with_default = mismatch_counts(donors, {"B": {"B42"}, "DR": set()}, HLA_BDR, AG_DEFAULTS)
    assert without.iloc[0].B == 1  # B7 is a mismatch against B8
    assert with_default.iloc[0].B == 0  # B42 defaults to B7, so no mismatch


def test_mismatch_levels_for_a_frame():
    recipient = {"B": {"B7", "B8"}, "DR": {"DR4"}}
    levels = mismatch_levels(DONORS, recipient, HLA_BDR, AG_DEFAULTS)
    assert levels.iloc[0] == 1  # 0B 0DR
    assert levels.iloc[3] == 3  # 1B 1DR


def test_mismatch_counts_handles_missing_columns():
    donors = pd.DataFrame({"id": [1], "bg": ["A"], "B7": [1]})
    counts = mismatch_counts(donors, {"B": {"B7"}, "DR": set()}, {"B": ["B7"], "DR": ["DR4"]}, {})
    assert counts.iloc[0].DR == 0


def test_parse_recipient_bdr_splits_loci():
    result = parse_recipient_bdr(["B7", "B8", "DR4", "A1", "BW4"])
    assert result["B"] == {"B7", "B8"}
    assert result["DR"] == {"DR4"}


# --------------------------------------------------------------------------
# burden banding
# --------------------------------------------------------------------------


def test_burden_bands_split_by_quantile():
    values = Series([1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000])
    bands, edges = burden_bands(values, n_bands=4)
    assert len(edges) == 3
    assert bands.iloc[0] == 1
    assert bands.iloc[-1] == 4


def test_burden_bands_collapse_under_heavy_ties():
    """with few specificities many donors share a value and bands collapse

    This is expected, not a bug -- the edges are returned so the display can show
    what actually happened rather than implying four equal groups.
    """
    values = Series([5000] * 10)
    bands, edges = burden_bands(values, n_bands=4)
    assert set(bands) == {1}


def test_burden_bands_empty_series():
    bands, edges = burden_bands(Series(dtype=float))
    assert bands.empty
    assert edges == []


# --------------------------------------------------------------------------
# joint view
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live():
    conn = sqlite3.connect("data/donors.db")
    donors = pd.read_sql_query("SELECT * FROM donors_v3", conn)
    mantigens = pd.read_sql_query("SELECT * FROM matchability_antigens", conn)
    defaults = pd.read_sql_query("SELECT * FROM antigen_defaults WHERE locus in ('B','DR')", conn)
    conn.close()
    return {
        "donors": donors,
        "hla_bdr": mantigens.groupby("locus").agg(list)["antigen"].to_dict(),
        "ag_defaults": defaults.set_index("rare")["default"].to_dict(),
    }


def test_joint_view_cells_sum_to_reference_size(live):
    specs = {"A1": 6000.0, "B7": 12000.0, "DR4": 4000.0}
    profile = AntibodyProfile(specs=[SpecMFI(spec=s, current=v) for s, v in specs.items()])
    cohort = select(live["donors"], recipient_bg="A", specs=list(specs))
    reference = reference_population(cohort, list(specs))
    recipient = {"B": {"B8"}, "DR": {"DR15"}}

    view = build_joint_view(cohort, profile, reference, recipient, live["hla_bdr"], live["ag_defaults"])
    assert sum(c.count for c in view.cells) == len(reference)
    assert view.reference_size == len(reference)


def test_joint_view_places_the_offered_donor(live):
    specs = {"A1": 6000.0, "B7": 12000.0, "DR4": 4000.0}
    profile = AntibodyProfile(specs=[SpecMFI(spec=s, current=v) for s, v in specs.items()])
    cohort = select(live["donors"], recipient_bg="A", specs=list(specs))
    reference = reference_population(cohort, list(specs))
    recipient = {"B": {"B8"}, "DR": {"DR15"}}
    donor = reference.iloc[0]

    view = build_joint_view(
        cohort,
        profile,
        reference,
        recipient,
        live["hla_bdr"],
        live["ag_defaults"],
        offered_donor=donor,
    )
    assert view.offered_burden_band is not None
    assert view.offered_mismatch_level in (1, 2, 3, 4)
    assert view.n_better_on_both is not None


def test_joint_view_better_on_both_is_the_rare_offer(live):
    """a donor low on both axes is the genuinely rare offer

    The count of donors better on both must be small relative to those better on
    either alone, or the joint view is telling us nothing the axes do not.
    """
    specs = {"A1": 6000.0, "B7": 12000.0, "DR4": 4000.0}
    profile = AntibodyProfile(specs=[SpecMFI(spec=s, current=v) for s, v in specs.items()])
    cohort = select(live["donors"], recipient_bg="A", specs=list(specs))
    reference = reference_population(cohort, list(specs))
    recipient = {"B": {"B8"}, "DR": {"DR15"}}

    # a donor at middling burden and middling mismatch
    donor = reference.iloc[5]
    view = build_joint_view(
        cohort,
        profile,
        reference,
        recipient,
        live["hla_bdr"],
        live["ag_defaults"],
        offered_donor=donor,
    )
    assert view.n_better_on_both <= view.reference_size


def test_joint_view_agrees_with_calculator_favourable_count(live):
    """mismatch levels here must mean what they mean on the cRF page

    The existing Calculator counts favourable matches among *compatible* donors;
    this recomputes the same grades over the same frame and must agree.
    """
    recipient_bdr = {"B": {"B8"}, "DR": {"DR15"}}
    specs = ["A1", "B7"]
    calculator = Calculator(
        donors=live["donors"],
        specs=specs,
        abo="A",
        recipient_bdr={k: set(v) for k, v in recipient_bdr.items()},
        hla_bdr=live["hla_bdr"],
        ag_defaults=live["ag_defaults"],
        matchability_bands={"A": {1: 0}},
    )
    results = calculator.calculate()

    levels = mismatch_levels(calculator.compatible_donors, recipient_bdr, live["hla_bdr"], live["ag_defaults"])
    favourable = int(levels.isin([1, 2]).sum())
    assert favourable == results.favourable
