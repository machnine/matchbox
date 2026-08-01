"""tests for paste ingest and antigen normalisation

The vocabulary used here is a realistic subset of the donor matrix columns,
including the CW/C and DPB quirks that trip real exports.
"""

import sqlite3

import pandas as pd
import pytest

from api.parser import (
    ColumnRole,
    detect_delimiter,
    detect_header,
    infer_roles,
    normalise_spec,
    parse,
    parse_donor_type,
    to_number,
)

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
# delimiters and numbers
# --------------------------------------------------------------------------


def test_detect_tab_delimiter():
    assert detect_delimiter("A1\t4000\nB7\t2000")[1] == "tab"


def test_detect_comma_delimiter():
    assert detect_delimiter("A1,4000\nB7,2000")[1] == "comma"


def test_detect_whitespace_for_single_column():
    assert detect_delimiter("A1 4000\nB7 2000")[1] == "whitespace"


def test_tab_wins_over_comma_when_both_present():
    """an Excel paste may contain commas inside a cell"""
    text = "A1\t4,000\tstrong\nB7\t2,000\tweak"
    assert detect_delimiter(text)[1] == "tab"


@pytest.mark.parametrize(
    "raw,expected",
    [("4000", 4000.0), ("4,000", 4000.0), ("4000.5", 4000.5), (" 4000 ", 4000.0)],
)
def test_to_number(raw, expected):
    assert to_number(raw) == expected


def test_to_number_rejects_text():
    assert to_number("strong") is None
    assert to_number("") is None


def test_detect_header_by_absence_of_numbers():
    assert detect_header(["Specificity", "Current MFI"]) is True
    assert detect_header(["A1", "4000"]) is False


# --------------------------------------------------------------------------
# role inference
# --------------------------------------------------------------------------


def test_roles_from_header_names():
    header = ["Specificity", "Current MFI", "Peak MFI"]
    roles = infer_roles(header, [["A1", "4000", "8000"]], VOCAB)
    assert roles == [ColumnRole.SPEC, ColumnRole.CURRENT_MFI, ColumnRole.PEAK_MFI]


def test_peak_header_beats_bare_mfi():
    header = ["Bead", "Peak MFI", "MFI"]
    roles = infer_roles(header, [["A1", "8000", "4000"]], VOCAB)
    assert roles[1] == ColumnRole.PEAK_MFI
    assert roles[2] == ColumnRole.CURRENT_MFI


def test_roles_inferred_without_header():
    roles = infer_roles(None, [["A1", "4000"], ["B7", "2000"]], VOCAB)
    assert roles == [ColumnRole.SPEC, ColumnRole.CURRENT_MFI]


def test_column_order_not_prescribed():
    """every lab's export differs; MFI may precede the specificity"""
    roles = infer_roles(None, [["4000", "A1"], ["2000", "B7"]], VOCAB)
    assert roles == [ColumnRole.CURRENT_MFI, ColumnRole.SPEC]


def test_extra_columns_ignored():
    header = ["Bead ID", "Specificity", "Current MFI", "Notes"]
    rows = [["101", "A1", "4000", "strong"]]
    roles = infer_roles(header, rows, VOCAB)
    assert roles[1] == ColumnRole.SPEC
    assert roles[2] == ColumnRole.CURRENT_MFI
    assert roles[3] == ColumnRole.IGNORE


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def test_parse_simple_two_column_paste():
    result = parse("A1\t4000\nB7\t2000\nDR4\t9000", VOCAB)
    assert result.ok
    assert [r.spec for r in result.rows] == ["A1", "B7", "DR4"]
    assert [r.current for r in result.rows] == [4000, 2000, 9000]


def test_parse_with_header_and_peak():
    text = "Specificity\tCurrent\tPeak\nA1\t4000\t8000\nB7\t2000\t3000"
    result = parse(text, VOCAB)
    assert result.header_detected
    assert result.ok
    assert [r.peak for r in result.rows] == [8000, 3000]


def test_parse_normalises_while_keeping_raw():
    result = parse("DPB1*04:01\t4000", VOCAB)
    assert result.rows[0].spec == "DPB4"
    assert result.rows[0].raw_spec == "DPB1*04:01"


def test_parse_flags_unrecognised_without_dropping_row():
    result = parse("A1\t4000\nZZZ9\t2000", VOCAB)
    assert not result.ok
    assert len(result.rows) == 2  # the row survives for the user to fix
    assert result.rows[1].recognised is False
    assert len(result.recognised_rows) == 1
    kinds = {p.kind for p in result.problems}
    assert "unrecognised_specificity" in kinds


def test_parse_flags_duplicates():
    result = parse("A1\t4000\nA1\t5000", VOCAB)
    assert any(p.kind == "duplicate_specificity" for p in result.problems)


def test_parse_flags_duplicate_after_normalisation():
    """C7 and CW7 are the same specificity"""
    result = parse("C7\t4000\nCW7\t5000", VOCAB)
    assert any(p.kind == "duplicate_specificity" for p in result.problems)


def test_parse_flags_peak_below_current():
    result = parse("Spec\tCurrent\tPeak\nA1\t8000\t4000", VOCAB)
    assert any(p.kind == "peak_below_current" for p in result.problems)
    assert result.rows[0].peak is None
    assert result.ok


def test_parse_flags_negative_mfi():
    result = parse("A1\t-500", VOCAB)
    assert any(p.kind == "negative_mfi" for p in result.problems)


def test_parse_flags_missing_mfi():
    result = parse("Spec\tCurrent\nA1\t4000\nB7\t", VOCAB)
    assert any(p.kind == "missing_mfi" for p in result.problems)


def test_parse_empty_input():
    result = parse("", VOCAB)
    assert not result.ok
    assert result.problems[0].kind == "empty"


def test_parse_without_spec_column_fails_clearly():
    result = parse("4000\t8000\n2000\t3000", VOCAB)
    assert any(p.kind == "no_spec_column" for p in result.problems)


def test_parse_respects_supplied_roles():
    """the UI's per-column dropdown overrides detection"""
    text = "A1\t8000\t4000"
    roles = [ColumnRole.SPEC, ColumnRole.PEAK_MFI, ColumnRole.CURRENT_MFI]
    result = parse(text, VOCAB, roles=roles)
    assert result.rows[0].peak == 8000
    assert result.rows[0].current == 4000


def test_parse_handles_comma_separated_export():
    result = parse("Specificity,Current MFI\nA1,4000\nB7,2000", VOCAB)
    assert result.ok
    assert [r.spec for r in result.rows] == ["A1", "B7"]


def test_parse_handles_thousands_separators_in_tabbed_paste():
    result = parse("A1\t4,000\nB7\t12,500", VOCAB)
    assert [r.current for r in result.rows] == [4000, 12500]


def test_parse_forty_specificities():
    """the volume the bulk paste exists for"""
    specs = (VOCAB * 2)[:40]
    text = "\n".join(f"{s}\t{3000 + i * 100}" for i, s in enumerate(specs))
    result = parse(text, VOCAB)
    # duplicates are flagged but every row is parsed
    assert len(result.rows) == 40
    assert all(r.recognised for r in result.rows)


# --------------------------------------------------------------------------
# donor type entry -- one parser, two entry points
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
