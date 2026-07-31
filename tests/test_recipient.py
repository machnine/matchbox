"""Recipient HLA canonicalization tests."""

from api.recipient import canonicalise_recipient_hla

MATCHABILITY_ANTIGENS = {
    "B": ["B5", "B7", "B12", "B41", "B42"],
    "DR": ["DR2", "DR3", "DR13", "DR14"],
}

SPLIT_TO_BROAD = {
    "B44": "B12",
    "B51": "B5",
    "DR15": "DR2",
    "DR17": "DR3",
    # These generic relationships must not replace canonical rare values.
    "B41": "B40",
    "B42": "B7",
    "DR13": "DR6",
    "DR14": "DR6",
}


def test_common_splits_map_to_matchability_broads():
    canonical, conversions = canonicalise_recipient_hla(
        ["B44", "B51", "DR15", "DR17"],
        MATCHABILITY_ANTIGENS,
        SPLIT_TO_BROAD,
    )

    assert canonical == ["B12", "B5", "DR2", "DR3"]
    assert conversions == {"B44": "B12", "B51": "B5", "DR15": "DR2", "DR17": "DR3"}


def test_canonical_rare_values_win_over_generic_mapping():
    canonical, conversions = canonicalise_recipient_hla(
        ["B41", "B42", "DR13", "DR14"],
        MATCHABILITY_ANTIGENS,
        SPLIT_TO_BROAD,
    )

    assert canonical == ["B41", "B42", "DR13", "DR14"]
    assert conversions == {}


def test_sibling_splits_collapse_to_one_broad():
    canonical, conversions = canonicalise_recipient_hla(
        ["B44", "B44", "DR15", "DR15"],
        MATCHABILITY_ANTIGENS,
        SPLIT_TO_BROAD,
    )

    assert canonical == ["B12", "DR2"]
    assert conversions == {"B44": "B12", "DR15": "DR2"}
