"""tests for the calculator module"""

import pandas as pd

from api.calculator import Calculator, Results

# load mock donors once
mock_donors = pd.read_csv("tests/mock_donors.csv")
# antigen default setting
mock_ag_defaults = {"B42": "B7", "DR9": "DR4"}
# mock matchability bands
mock_mbands = {
    "A": {1: 35, 2: 30, 3: 25, 4: 20, 5: 15, 6: 10, 7: 5, 8: 2, 9: 1, 10: 0},
    "O": {1: 45, 2: 35, 3: 30, 4: 25, 5: 20, 6: 15, 7: 10, 8: 5, 9: 2, 10: 1},
}
# a list of antigens 'allowed' for using in matchability calculation
mock_mantigens = {"B": ["B7", "B8", "B12", "B42", "B46"], "DR": ["DR3", "DR9"]}


def test_calculator_crf_a_one_spec():
    """test the crf for blood group A and one spec"""
    results = Calculator(donors=mock_donors, abo="A", specs=["A2"]).calculate()

    expected_results = Results(crf=0.5128205128205128, available=19)
    assert results == expected_results


def test_calculator_crf_a_multi_spec():
    """test the crf for blood group A and multiple specs"""
    results = Calculator(donors=mock_donors, abo="A", specs=["A1", "A2"]).calculate()
    expected_results = Results(crf=0.8717948717948718, available=5)
    assert results == expected_results


def test_calculator_crf_o_multi_spec():
    """test the crf for blood group O and multiple specs"""
    results = Calculator(donors=mock_donors, abo="O", specs=["A1", "B7", "B12", "DR18"]).calculate()
    expected_results = Results(crf=0.8163265306122449, available=9)
    assert results == expected_results


def test_calculator_crf_b_multi_spec():
    """test the crf for blood group B and multiple specs"""
    results = Calculator(donors=mock_donors, abo="B", specs=["A43", "B7", "B8", "DR17", "DR3"]).calculate()
    expected_results = Results(crf=0.42857142857142855, available=4)
    assert results == expected_results


def test_calculator_crf_ab_multi_spec():
    """test the crf for blood group AB and multiple specs"""
    results = Calculator(donors=mock_donors, abo="AB", specs=["DR17", "B42", "B46", "DR9"]).calculate()
    expected_results = Results(crf=0.4, available=3)
    assert results == expected_results


def test_calculator_crf_broad_vs_split_spec():
    """test if the broad spec covers the split spec"""
    results1 = Calculator(donors=mock_donors, abo="A", specs=["A9", "A24"]).calculate()
    results2 = Calculator(donors=mock_donors, abo="A", specs=["A9"]).calculate()
    results3 = Calculator(donors=mock_donors, abo="A", specs=["A24"]).calculate()
    expected_results1 = Results(crf=0.28205128205128205, available=28)
    expected_results3 = Results(crf=0.23076923076923078, available=30)
    assert results1 == results2
    assert results1 != results3
    assert results2 != results3
    assert results1 == expected_results1
    assert results3 == expected_results3


def test_calculator_full_a_one_spec():
    """test the full calculator for blood group A and one spec"""
    mock_patient = {"B": {"B7", "B8"}, "DR": {"DR3"}}
    results = Calculator(
        donors=mock_donors,
        abo="A",
        specs=["A2"],
        ag_defaults=mock_ag_defaults,
        matchability_bands=mock_mbands,
        hla_bdr=mock_mantigens,
        recipient_bdr=mock_patient,
    ).calculate()
    expected_results = Results(
        crf=0.5128205128205128,
        available=19,
        favourable=19,
        matchability=5,
        match_counts={"fav": 19, "m12a": 19, "m2b": 0, "m3a": 0, "m3b": 0, "m4a": 0, "m4b": 0},
    )
    assert results == expected_results


def test_calculator_full_a_multi_spec():
    """test the full calculator for blood group A and multiple specs"""
    mock_patient = {"B": {"B12", "B8"}, "DR": {"DR9"}}
    results = Calculator(
        donors=mock_donors,
        abo="A",
        specs=["A43", "DR17"],
        ag_defaults=mock_ag_defaults,
        matchability_bands=mock_mbands,
        hla_bdr=mock_mantigens,
        recipient_bdr=mock_patient,
    ).calculate()
    expected_results = Results(
        crf=0.28205128205128205,
        available=28,
        favourable=28,
        matchability=3,
        match_counts={"fav": 28, "m12a": 28, "m2b": 0, "m3a": 0, "m3b": 0, "m4a": 0, "m4b": 0},
    )
    assert results == expected_results


def test_calculator_full_o_multi_spec():
    """test the full calculator for blood group A and multiple specs"""
    mock_patient = {"B": {"B42", "B46"}, "DR": {"DR9", "DR3"}}
    results = Calculator(
        donors=mock_donors,
        abo="O",
        specs=["B7", "B8", "A24"],
        ag_defaults=mock_ag_defaults,
        matchability_bands=mock_mbands,
        hla_bdr=mock_mantigens,
        recipient_bdr=mock_patient,
    ).calculate()
    expected_results = Results(
        crf=0.7959183673469388,
        available=10,
        favourable=10,
        matchability=7,
        match_counts={"fav": 10, "m12a": 10, "m2b": 0, "m3a": 0, "m3b": 0, "m4a": 0, "m4b": 0},
    )
    assert results == expected_results


def test_calculator_full_default_antigens():
    """test the full calculator for blood group A and multiple specs"""
    mock_patient1 = {"B": {"B7", "B46"}, "DR": {"DR4", "DR3"}}
    mock_patient2 = {"B": {"B42", "B46"}, "DR": {"DR9", "DR3"}}
    results1 = Calculator(
        donors=mock_donors,
        abo="O",
        specs=["B7", "B8", "A24"],
        ag_defaults=mock_ag_defaults,
        matchability_bands=mock_mbands,
        hla_bdr=mock_mantigens,
        recipient_bdr=mock_patient1,
    ).calculate()
    results2 = Calculator(
        donors=mock_donors,
        abo="O",
        specs=["B7", "B8", "A24"],
        ag_defaults=mock_ag_defaults,
        matchability_bands=mock_mbands,
        hla_bdr=mock_mantigens,
        recipient_bdr=mock_patient2,
    ).calculate()
    expected_results1 = Results(
        crf=0.7959183673469388,
        available=10,
        favourable=9,
        matchability=8,
        match_counts={"fav": 9, "m12a": 9, "m2b": 0, "m3a": 0, "m3b": 1, "m4a": 0, "m4b": 0},
    )
    expected_results2 = Results(
        crf=0.7959183673469388,
        available=10,
        favourable=10,
        matchability=7,
        match_counts={"fav": 10, "m12a": 10, "m2b": 0, "m3a": 0, "m3b": 0, "m4a": 0, "m4b": 0},
    )
    assert results1 == expected_results1
    assert results2 == expected_results2
    assert results1.crf == results2.crf
    assert results1.available == results2.available
    assert results1.favourable < results2.favourable
    assert results1.matchability > results2.matchability


def test_calculator_minial_input():
    """test the calculator with minimal input"""
    results = Calculator(donors=mock_donors, abo="O", specs=[]).calculate()
    expected_results = Results(crf=0.0, available=49, favourable=None, matchability=None)
    assert results == expected_results


def test_calculator_no_specs():
    """test the calculator with no specs"""
    mock_patient = {"B": {"B7", "B46"}, "DR": {"DR4", "DR3"}}
    results = Calculator(
        donors=mock_donors,
        abo="O",
        specs=[],
        ag_defaults=mock_ag_defaults,
        matchability_bands=mock_mbands,
        hla_bdr=mock_mantigens,
        recipient_bdr=mock_patient,
    ).calculate()
    expected_results = Results(
        crf=0.0,
        available=49,
        favourable=45,
        matchability=1,
        match_counts={"fav": 45, "m12a": 45, "m2b": 0, "m3a": 3, "m3b": 1, "m4a": 0, "m4b": 0},
    )
    assert results == expected_results
