"""Allele level HLA-DP4 scoring.

The donor cohort types HLA-DP at broad antigen level, so DPB1*04:01 and
DPB1*04:02 cannot be scored against a donor column. They are scored instead
against the expected carriers of the allele among the DP4 positive donors:

    cRF = (S + f * D) / N

The arithmetic is pinned here against the real cohort, because the expected
values were derived from it independently of this implementation.
"""

import warnings
from itertools import permutations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import api
from api.calculator import Calculator, weighted_incompatible_count
from api.data import DataLoader

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    client = TestClient(api)

BASE = DataLoader().base_data
DP4_WEIGHTS = {ag: (freq.broad, freq.carrier_fraction) for ag, freq in BASE.dp4_frequencies.items()}
ALL_DONORS = BASE.donors[0]


def crf(specs, bg="O", donors=None):
    """cRF as a percentage, the way the API reports it"""
    calculator = Calculator(
        donors=ALL_DONORS if donors is None else donors,
        specs=specs,
        abo=bg,
        dp4_weights=DP4_WEIGHTS,
    )
    return calculator.calculate().crf * 100


def test_carrier_fractions_come_from_the_published_series():
    """The fractions are Lemin 2021: 301/350 and 92/350 of DP4 positive donors."""
    assert BASE.dp4_frequencies["DPB0401"].carrier_fraction == pytest.approx(301 / 350, abs=1e-9)
    assert BASE.dp4_frequencies["DPB0402"].carrier_fraction == pytest.approx(92 / 350, abs=1e-9)
    assert {f.source for f in BASE.dp4_frequencies.values()} == {"lemin2021"}
    assert {f.source_n for f in BASE.dp4_frequencies.values()} == {456}


def test_broad_dp4_reproduces_the_cohort_frequency():
    """Broad DPB4 alone is the DP4 positive proportion of the blood group."""
    assert crf(["DPB4"]) == pytest.approx(28.23, abs=0.01)


@pytest.mark.parametrize(
    "allele, fraction",
    [("DPB0401", 301 / 350), ("DPB0402", 92 / 350)],
)
def test_allele_entry_scores_its_expected_carriers(allele, fraction):
    """An allele alone excludes f of the DP4 donors, not all of them."""
    assert crf([allele]) == pytest.approx(crf(["DPB4"]) * fraction, abs=0.01)


def test_both_alleles_resolve_to_the_broad_antigen():
    """Naming both alleles is the f = 1 limit: the broad antigen resolves it."""
    assert crf(["DPB0401", "DPB0402"]) == pytest.approx(crf(["DPB4"]), abs=1e-9)


def test_broad_and_allele_together_do_not_double_count():
    """A donor excluded by the broad entry is not counted again by the allele."""
    assert crf(["DPB4", "DPB0402"]) == pytest.approx(crf(["DPB4"]), abs=1e-9)


def test_other_specificities_are_deducted_before_weighting():
    """Only the DP4 donors the entry alone excludes are weighted.

    Pinned against S and D counted directly off the cohort, so the test fails if
    the implementation weights the whole DP4 column instead of the remainder.
    """
    group_o = ALL_DONORS[ALL_DONORS.bg == "O"]
    excluded_by_a1 = group_o["A1"].eq(1)
    s = int(excluded_by_a1.sum())
    d = int((group_o["DPB4"].eq(1) & ~excluded_by_a1).sum())
    expected = 100 * (s + (92 / 350) * d) / len(group_o)

    assert crf(["A1", "DPB0402"]) == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("bg", ["O", "A", "B", "AB"])
def test_weighted_value_sits_between_dropping_and_broad(bg):
    """The two limits of the expression bracket the weighted value."""
    dropped = crf(["A1"], bg=bg)
    weighted_0402 = crf(["A1", "DPB0402"], bg=bg)
    weighted_0401 = crf(["A1", "DPB0401"], bg=bg)
    broad = crf(["A1", "DPB4"], bg=bg)

    assert dropped <= weighted_0402 <= weighted_0401 <= broad


def test_weighting_applies_to_the_dp_typed_denominator_too():
    """The expression is a ratio over whichever denominator is in force."""
    typed = BASE.donors[1]
    broad = crf(["DPB4"], donors=typed)
    weighted = crf(["DPB0402"], donors=typed)

    assert weighted == pytest.approx(broad * 92 / 350, abs=0.01)
    assert broad == pytest.approx(77.67, abs=0.01)


def test_a_specificity_with_no_weight_is_unaffected():
    """Whole donor scoring is unchanged where no allele entry is present."""
    assert crf(["A1"]) == pytest.approx(32.58, abs=0.01)


def test_weighted_count_is_a_whole_number_without_allele_entries():
    """With no allele entry the expression collapses to the donor count."""
    group_o = ALL_DONORS[ALL_DONORS.bg == "O"]
    counted = weighted_incompatible_count(group_o, ["A1", "DPB4"], DP4_WEIGHTS)

    assert counted == float(int(counted))


def test_a_resolved_pair_does_not_double_count_against_another_pair():
    """A whole excluded donor must not also be counted as a fraction elsewhere.

    Only reachable once the frequency table holds a second allele pair, which it
    is keyed to support. Scored on a synthetic frame with a deliberate overlap:
    both DP4 alleles resolve DP4 to whole donors, so the ten donors shared with
    DP2 are already excluded and only the remaining twenty are weighted. Every
    ordering of the same specificities must agree.
    """
    donors = pd.DataFrame(
        [{"bg": "O", "DPB4": int(i < 40), "DPB2": int(30 <= i < 60)} for i in range(100)]
    )
    weights = {
        "DPB0401": ("DPB4", 0.86),
        "DPB0402": ("DPB4", 0.26),
        "DPB0201": ("DPB2", 0.70),
    }
    specs = ["DPB0401", "DPB0402", "DPB0201"]
    orderings = {
        round(weighted_incompatible_count(donors, list(order), weights), 9)
        for order in permutations(specs)
    }

    assert orderings == {40 + 0.70 * 20}


def test_matchability_scores_an_allele_entry_as_broad_dp4():
    """A fraction cannot be assigned a mismatch grade, so counts stay whole."""
    kwargs = dict(
        donors=ALL_DONORS,
        abo="O",
        recipient_bdr={"B": {"B7"}, "DR": {"DR4"}},
        hla_bdr=BASE.mantigens,
        ag_defaults=BASE.antigen_defaults,
        matchability_bands=BASE.mbands,
        dp4_weights=DP4_WEIGHTS,
    )
    allele = Calculator(specs=["DPB0402"], **kwargs).calculate()
    broad = Calculator(specs=["DPB4"], **kwargs).calculate()

    assert allele.available == broad.available
    assert allele.favourable == broad.favourable
    assert allele.matchability == broad.matchability
    assert allele.crf < broad.crf


def test_alleles_are_offered_next_to_the_broad_antigen():
    """The entries are selectable, and adjacent to the antigen they refine."""
    dpb = BASE.antigens["DPB"]

    assert dpb[dpb.index("DPB4") + 1 : dpb.index("DPB4") + 3] == ["DPB0401", "DPB0402"]


def test_missing_frequencies_fail_closed():
    """A missing fraction would silently score an allele as excluding nobody."""
    loader = DataLoader()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(loader, "_load_table", lambda *_, **__: pd.DataFrame())
        with pytest.raises(Exception, match="Missing HLA-DP4 allele carrier frequencies"):
            loader.dp4_allele_frequencies()


@pytest.mark.parametrize(
    "specs, expected_crf",
    [("DPB4", 28.23), ("DPB0401", 24.27), ("DPB0402", 7.42), ("DPB0401,DPB0402", 28.23)],
)
def test_api_serves_the_weighted_value(specs, expected_crf):
    """The allele entries are accepted as specs and scored over the API."""
    response = client.get("/calc/", params={"bg": "O", "specs": specs})

    assert response.status_code == 200
    assert response.json()["results"]["crf"] * 100 == pytest.approx(expected_crf, abs=0.01)


@pytest.mark.parametrize(
    "token, expected",
    [
        ("DPB1*04:01", "DPB0401"),
        ("DPB1*04:02", "DPB0402"),
        ("DPB1*0401", "DPB0401"),
        ("dpb1*04:02", "DPB0402"),
        # an allele with no fraction of its own still resolves to its broad
        ("DPB1*04:03", "DPB4"),
        ("DPB1*02:01", "DPB2"),
    ],
)
def test_allele_forms_normalise_to_the_scored_specificity(token, expected):
    """Pasting the allele form must not silently collapse to the broad antigen."""
    response = client.post("/normalise/", json={"text": token})

    assert response.json()["antigens"] == [expected]
