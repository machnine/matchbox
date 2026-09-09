"""Policy-accessible donor pools.

The calculator scores against blood group identical donors. Kidney allocation
policy offers several recipients compatible non-identical donors as well, and
which ones depends on their tier [POL186/21 blood group eligibility].

Pool sizes are pinned against the figures quoted in the paper's Finding 2, which
were derived from this cohort independently of this implementation.
"""

import warnings

import pytest
from fastapi.testclient import TestClient

from api import api
from api.calculator import Calculator
from api.data import DataLoader

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    client = TestClient(api)

BASE = DataLoader().base_data
ALL_DONORS = BASE.donors[0]
GROUP_SIZES = {group: int((ALL_DONORS.bg == group).sum()) for group in ("O", "A", "B", "AB")}

# Recipient, tier -> donor groups and the resulting denominator.
EXPECTED_POOLS = {
    ("O", "tier_b"): (("O",), 4620),
    ("O", "tier_a"): (("O",), 4620),
    ("A", "tier_b"): (("A",), 4094),
    ("A", "tier_a"): (("A", "O"), 8714),
    ("B", "tier_b"): (("B", "O"), 5582),
    ("B", "tier_a"): (("B", "O"), 5582),
    ("AB", "tier_b"): (("AB", "A"), 4418),
    ("AB", "tier_a"): (("AB", "A", "O"), 9038),
}


def calculate(bg, pool_groups=None, specs=("A1", "B8", "DR17")):
    return Calculator(
        donors=ALL_DONORS,
        specs=list(specs),
        abo=bg,
        pool_groups=pool_groups,
        recipient_bdr={"B": {"B7"}, "DR": {"DR4"}},
        hla_bdr=BASE.mantigens,
        ag_defaults=BASE.antigen_defaults,
        matchability_bands=BASE.mbands,
    ).calculate()


@pytest.mark.parametrize("key, expected", sorted(EXPECTED_POOLS.items()))
def test_pool_membership_follows_allocation_policy(key, expected):
    """The eight pools, and the denominator each produces from the cohort."""
    groups, size = expected
    pool = BASE.abo_pools[key]

    assert pool.donor_groups == groups
    assert sum(GROUP_SIZES[group] for group in pool.donor_groups) == size


def test_pool_sizes_match_the_published_figures():
    """5,582 / 4,418 / 9,038 are the counts quoted in Finding 2."""
    assert GROUP_SIZES["B"] + GROUP_SIZES["O"] == 5582
    assert GROUP_SIZES["AB"] + GROUP_SIZES["A"] == 4418
    assert GROUP_SIZES["AB"] + GROUP_SIZES["A"] + GROUP_SIZES["O"] == 9038


def test_a_group_o_recipient_gains_nothing_from_either_tier():
    """Group O can only receive group O, so policy widens nothing."""
    assert BASE.abo_pools[("O", "tier_b")].donor_groups == ("O",)
    assert BASE.abo_pools[("O", "tier_a")].donor_groups == ("O",)


def test_b_and_ab_are_offered_non_identical_donors_in_both_tiers():
    """Which is why blood group identical has to stay reachable separately."""
    for recipient in ("B", "AB"):
        for tier in ("tier_b", "tier_a"):
            assert BASE.abo_pools[(recipient, tier)].donor_groups != (recipient,)


def test_the_calculator_defaults_to_blood_group_identical():
    """An existing caller that passes no pool must be unaffected."""
    for bg in ("O", "A", "B", "AB"):
        assert calculate(bg) == calculate(bg, pool_groups=[bg])


def test_a_wider_pool_scales_the_donor_counts():
    """Ad and Fm are counts of real donors, so they grow with the pool."""
    identical = calculate("AB", ["AB"])
    widened = calculate("AB", ["AB", "A", "O"])

    assert widened.available > identical.available
    assert widened.favourable > identical.favourable


def test_a_wider_pool_barely_moves_crf():
    """ABO and HLA are inherited independently, so each group holds much the
    same HLA composition as the pool as a whole (Finding 2)."""
    for bg, groups in (("A", ["A", "O"]), ("B", ["B", "O"]), ("AB", ["AB", "A", "O"])):
        identical = calculate(bg, [bg]).crf * 100
        widened = calculate(bg, groups).crf * 100

        assert abs(widened - identical) < 5


def test_the_band_is_read_against_the_recipients_own_blood_group():
    """Not the pool's. The bands are per blood group, and a pool spans several.

    This is also why the band is not comparable over a wider pool, which the API
    reports as a status rather than leaving the caller to infer.
    """
    widened = calculate("AB", ["AB", "A", "O"])
    bands = BASE.mbands["AB"]

    assert widened.matchability == next(
        band for band, threshold in sorted(bands.items()) if widened.favourable >= threshold
    )

    # Every policy pool happens to lead with the recipient's own group, so a
    # pool-derived index can look right by accident. Score a group B recipient
    # against a pool ordered O first: the band must still come from the B table.
    # A count of 106 is band 1 against B's thresholds and band 7 against O's.
    assert next(b for b, v in sorted(BASE.mbands["B"].items()) if 106 >= v) == 1
    assert next(b for b, v in sorted(BASE.mbands["O"].items()) if 106 >= v) == 7

    reordered = calculate("B", ["O", "B"])
    assert reordered.favourable == 106
    assert reordered.matchability == 1


@pytest.mark.parametrize(
    "bg, pool, groups, size",
    [
        ("O", "identical", ["O"], 4620),
        ("O", "tier_a", ["O"], 4620),
        ("A", "tier_b", ["A"], 4094),
        ("A", "tier_a", ["A", "O"], 8714),
        ("B", "tier_b", ["B", "O"], 5582),
        ("AB", "tier_a", ["AB", "A", "O"], 9038),
    ],
)
def test_api_reports_the_pool_it_scored_against(bg, pool, groups, size):
    response = client.get("/calc/", params={"bg": bg, "specs": "A1", "pool": pool})

    assert response.status_code == 200
    body = response.json()
    assert body["pool"] == pool
    assert body["pool_groups"] == groups
    assert body["pool_size"] == size


def test_api_defaults_to_identical():
    """No pool parameter must behave exactly as before this was added."""
    without = client.get("/calc/", params={"bg": "B", "specs": "A1"}).json()
    explicit = client.get("/calc/", params={"bg": "B", "specs": "A1", "pool": "identical"}).json()

    assert without["pool"] == "identical"
    assert without["pool_groups"] == ["B"]
    assert without["results"] == explicit["results"]


@pytest.mark.parametrize(
    "bg, pool, expected",
    [
        ("B", "identical", "banded"),
        ("O", "tier_a", "banded"),  # policy adds nothing, so the band still stands
        ("A", "tier_b", "banded"),  # likewise
        ("A", "tier_a", "not_comparable_wider_pool"),
        ("B", "tier_b", "not_comparable_wider_pool"),
        ("AB", "tier_a", "not_comparable_wider_pool"),
    ],
)
def test_matchability_status_flags_only_a_genuinely_wider_pool(bg, pool, expected):
    """The caveat must fire when the pool really is wider, and not otherwise."""
    response = client.get("/calc/", params={"bg": bg, "specs": "A1", "pool": pool})

    assert response.json()["matchability_status"] == expected


def test_api_rejects_an_unknown_pool():
    assert client.get("/calc/", params={"bg": "B", "pool": "everything"}).status_code == 422


def test_missing_pools_fail_closed():
    """An empty pool would score a patient against an empty denominator."""
    import pandas as pd

    loader = DataLoader()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(loader, "_load_table", lambda *_, **__: pd.DataFrame())
        with pytest.raises(Exception, match="Missing or malformed donor pool"):
            loader.abo_pools()
