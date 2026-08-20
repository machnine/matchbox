"""tests for antigen normalisation

The vocabulary used here is a realistic subset of the donor matrix columns,
including the CW/C and DPB quirks that trip real pasted input.
"""

import sqlite3

import pandas as pd
import pytest

from api.parser import normalise_spec, parse_donor_type

VOCAB = [
    "A1",
    "A2",
    "A3",
    "A24",
    "A68",
    "B7",
    "B8",
    "B27",
    "B44",
    "B57",
    "CW3",
    "CW6",
    "CW7",
    "DR4",
    "DR7",
    "DR15",
    "DR17",
    "DQ2",
    "DQ6",
    "DQ7",
    "DPB1",
    "DPB2",
    "DPB3",
    "DPB4",
    "DPB11",
]


# --------------------------------------------------------------------------
# normalisation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("A1", "A1"),
        ("a1", "A1"),
        ("  B7  ", "B7"),
        ("B07", "B7"),
        ("HLA-A2", "A2"),
        ("HLA A2", "A2"),
    ],
)
def test_normalise_basic_forms(raw, expected):
    assert normalise_spec(raw, VOCAB)[0] == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("C7", "CW7"),
        ("c7", "CW7"),
        ("Cw6", "CW6"),
        ("CW07", "CW7"),
        ("C*07:02", "CW7"),
    ],
)
def test_normalise_c_to_cw(raw, expected):
    """donor columns use CW; the broad/split table and most exports use C"""
    assert normalise_spec(raw, VOCAB)[0] == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("DPB1*04:01", "DPB4"),
        ("DPB1*0401", "DPB4"),
        ("DPB1*4", "DPB4"),
        ("DP4", "DPB4"),
        ("dpb4", "DPB4"),
        ("DPB04", "DPB4"),
        ("DPB1*11:01", "DPB11"),
    ],
)
def test_normalise_dpb_forms(raw, expected):
    assert normalise_spec(raw, VOCAB)[0] == expected


def test_normalise_allele_level_for_other_loci():
    assert normalise_spec("A*01:01", VOCAB)[0] == "A1"
    assert normalise_spec("B*44:02", VOCAB)[0] == "B44"
    assert normalise_spec("DRB1*04:01", VOCAB)[0] == "DR4"


@pytest.mark.parametrize(
    "raw,expected",
    [
        # allele fields are fixed-width two-digit groups: 0401 is 04 + 01, not 401
        ("A*0101", "A1"),
        ("B*4402", "B44"),
        ("DRB1*0401", "DR4"),
        ("C*0702", "CW7"),
        ("DPB1*1101", "DPB11"),
        # more than two fields
        ("A*02:01:01:01", "A2"),
        # null allele suffix
        ("B*07:02N", "B7"),
    ],
)
def test_normalise_colonless_allele_forms(raw, expected):
    """the colonless export form must not be read as a single number"""
    assert normalise_spec(raw, VOCAB)[0] == expected


def test_three_digit_specificities_survive_normalisation():
    """A203, B3901 and DPB105 are real antigens, not leading-zero artefacts"""
    vocab = ["A203", "B3901", "DPB105"]
    for ag in vocab:
        assert normalise_spec(ag, vocab)[0] == ag


def test_unrecognised_token_returns_suggestions_not_silence():
    """an unmatched token must surface, never be discarded"""
    spec, suggestions = normalise_spec("B4", VOCAB)
    assert spec is None
    assert suggestions  # something close is offered
    assert all(s in VOCAB for s in suggestions)


def test_unrecognised_nonsense_returns_no_match():
    spec, _ = normalise_spec("ZZZ999", VOCAB)
    assert spec is None


def test_empty_token_is_not_a_match():
    assert normalise_spec("", VOCAB)[0] is None
    assert normalise_spec("   ", VOCAB)[0] is None
    assert normalise_spec(None, VOCAB)[0] is None


def test_exact_vocabulary_hit_is_not_rewritten():
    """DPB1 is a real antigen; it must not be rewritten as an allele form"""
    assert normalise_spec("DPB1", VOCAB)[0] == "DPB1"


# --------------------------------------------------------------------------
# pasted antigen lists
# --------------------------------------------------------------------------


def test_parse_donor_type_mixed_delimiters():
    found, problems = parse_donor_type("A1, B7  DR4;CW7", VOCAB)
    assert found == ["A1", "B7", "DR4", "CW7"]
    assert not problems


def test_parse_donor_type_normalises():
    found, _ = parse_donor_type("a1 c7 dpb1*04:01", VOCAB)
    assert found == ["A1", "CW7", "DPB4"]


def test_parse_donor_type_deduplicates():
    found, _ = parse_donor_type("A1 A1 B7", VOCAB)
    assert found == ["A1", "B7"]


def test_parse_donor_type_flags_unknown():
    found, problems = parse_donor_type("A1 ZZZ9", VOCAB)
    assert found == ["A1"]
    assert problems and problems[0].token == "ZZZ9"


# --------------------------------------------------------------------------
# against the real vocabulary
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_vocabulary():
    conn = sqlite3.connect("data/donors.db")
    donors = pd.read_sql_query("SELECT * FROM donors_v3 LIMIT 1", conn)
    conn.close()
    return [c for c in donors.columns if c not in ("id", "bg")]


def test_real_vocabulary_round_trips(live_vocabulary):
    """every antigen in the cohort normalises to itself"""
    failures = [ag for ag in live_vocabulary if normalise_spec(ag, live_vocabulary)[0] != ag]
    assert not failures, f"antigens that do not round-trip: {failures}"


def test_real_vocabulary_lowercase_round_trips(live_vocabulary):
    failures = [ag for ag in live_vocabulary if normalise_spec(ag.lower(), live_vocabulary)[0] != ag]
    assert not failures, f"antigens that fail lowercase: {failures}"


def test_real_dpb_allele_forms_resolve(live_vocabulary):
    assert normalise_spec("DPB1*04:01", live_vocabulary)[0] == "DPB4"
    assert normalise_spec("DPB1*02:01", live_vocabulary)[0] == "DPB2"


def test_real_c_forms_resolve(live_vocabulary):
    assert normalise_spec("C7", live_vocabulary)[0] == "CW7"
    assert normalise_spec("C*04:01", live_vocabulary)[0] == "CW4"
