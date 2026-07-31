"""Calculator API vocabulary validation tests."""

import pytest

from api.input_validation import AntigenValidationError, validate_recipient_hla, validate_specificities


def test_official_cohort_specificities_remain_allowed():
    vocabulary = {
        "A": ["A1", "A203"],
        "B": ["B7", "B5102"],
        "CW": ["CW7"],
    }

    assert validate_specificities(["A203", "B5102", "CW7"], vocabulary) == ["A203", "B5102", "CW7"]


def test_hidden_or_unknown_specificities_are_rejected():
    with pytest.raises(AntigenValidationError) as error:
        validate_specificities(["A1", "CW13", "A9999", ""], {"A": ["A1"]})

    assert error.value.field == "specs"
    assert error.value.invalid == ["CW13", "A9999", ""]


def test_recipient_hla_is_limited_to_canonical_matchability_broads():
    vocabulary = {"B": ["B7", "B12"], "DR": ["DR2", "DR3"]}

    assert validate_recipient_hla(["B12", "DR2"], vocabulary) == ["B12", "DR2"]

    with pytest.raises(AntigenValidationError) as error:
        validate_recipient_hla(["B44", "DR15", "A1"], vocabulary)

    assert error.value.field == "recip_hla"
    assert error.value.invalid == ["B44", "DR15", "A1"]
