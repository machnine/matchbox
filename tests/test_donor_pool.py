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


@pytest.mark.parametrize(
    "bg, groups",
    [("A", ["A", "O"]), ("B", ["B", "O"]), ("AB", ["AB", "A"]), ("AB", ["AB", "A", "O"])],
)
def test_a_wider_pool_scales_the_donor_counts(bg, groups):
    """Ad and Fm are counts of real donors, so they grow with the pool."""
    identical = calculate(bg, [bg])
    widened = calculate(bg, groups)

    assert widened.available > identical.available
    assert widened.favourable > identical.favourable


# Ad and Fm for the worked patient below, over every blood group and pool. Both
# are counts of donors in the cohort, so they are pinned exactly; Mp is derived
# from the band table in force rather than hardcoded, because a band revision
# should not fail these.
WORKED_PATIENT_COUNTS = {
    ("O", "identical"): (2640, 91),
    ("O", "tier_b"): (2640, 91),
    ("O", "tier_a"): (2640, 91),
    ("A", "identical"): (2340, 96),
    ("A", "tier_b"): (2340, 96),
    ("A", "tier_a"): (4980, 187),
    ("B", "identical"): (533, 15),
    ("B", "tier_b"): (3173, 106),
    ("B", "tier_a"): (3173, 106),
    ("AB", "identical"): (177, 5),
    ("AB", "tier_b"): (2517, 101),
    ("AB", "tier_a"): (5157, 192),
}


def band_for(bg, favourable):
    """The band the table in force gives this count for this blood group."""
    return next(band for band, threshold in sorted(BASE.mbands[bg].items()) if favourable >= threshold)


@pytest.mark.parametrize("key, expected", sorted(WORKED_PATIENT_COUNTS.items()))
def test_counts_and_band_for_one_patient_across_every_pool(key, expected):
    """One patient, twelve pools: the compatible count, the favourable count,
    and the band each pool produces.

    Unacceptable A1, B8 and DR17 against a B7, DR4 recipient. Pinned so a change
    to the pool arithmetic shows up as a specific wrong number rather than only
    as a broken invariant.
    """
    bg, pool = key
    expected_available, expected_favourable = expected
    groups = [bg] if pool == "identical" else list(BASE.abo_pools[(bg, pool)].donor_groups)

    result = calculate(bg, groups)

    assert result.available == expected_available
    assert result.favourable == expected_favourable
    assert result.matchability == band_for(bg, expected_favourable)


@pytest.mark.parametrize("bg", ["O", "A", "B", "AB"])
def test_every_pool_for_a_blood_group_contains_the_identical_one(bg):
    """A policy pool only ever adds donors, so it can never score fewer."""
    identical = calculate(bg, [bg])

    for tier in ("tier_b", "tier_a"):
        widened = calculate(bg, BASE.abo_pools[(bg, tier)].donor_groups)
        assert widened.available >= identical.available
        assert widened.favourable >= identical.favourable


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


# Every blood group against every pool. Stated in full rather than sampled: the
# whole matrix is twelve rows, and the interesting cases are the asymmetric ones
# (AB in tier B gains A but not O; B gains O in both tiers).
API_MATRIX = {
    ("O", "identical"): (["O"], 4620, "banded"),
    ("O", "tier_b"): (["O"], 4620, "banded"),
    ("O", "tier_a"): (["O"], 4620, "banded"),
    ("A", "identical"): (["A"], 4094, "banded"),
    ("A", "tier_b"): (["A"], 4094, "banded"),
    ("A", "tier_a"): (["A", "O"], 8714, "not_comparable_wider_pool"),
    ("B", "identical"): (["B"], 962, "banded"),
    ("B", "tier_b"): (["B", "O"], 5582, "not_comparable_wider_pool"),
    ("B", "tier_a"): (["B", "O"], 5582, "not_comparable_wider_pool"),
    ("AB", "identical"): (["AB"], 324, "banded"),
    ("AB", "tier_b"): (["AB", "A"], 4418, "not_comparable_wider_pool"),
    ("AB", "tier_a"): (["AB", "A", "O"], 9038, "not_comparable_wider_pool"),
}


@pytest.mark.parametrize("key, expected", sorted(API_MATRIX.items()))
def test_api_reports_the_pool_it_scored_against(key, expected):
    bg, pool = key
    groups, size, _ = expected
    response = client.get("/calc/", params={"bg": bg, "specs": "A1", "pool": pool})

    assert response.status_code == 200
    body = response.json()
    assert body["pool"] == pool
    assert body["pool_groups"] == groups
    assert body["pool_size"] == size


@pytest.mark.parametrize("key, expected", sorted(API_MATRIX.items()))
def test_the_denominator_is_the_pool_the_api_reports(key, expected):
    """cRF must be scored over the pool named in the response, not some other one."""
    bg, pool = key
    groups, size, _ = expected
    response = client.get("/calc/", params={"bg": bg, "specs": "A1", "pool": pool}).json()

    available = response["results"]["available"]
    crf = response["results"]["crf"]

    assert available <= size
    assert crf == pytest.approx(1 - available / size, abs=1e-9)


def test_api_defaults_to_identical():
    """No pool parameter must behave exactly as before this was added."""
    without = client.get("/calc/", params={"bg": "B", "specs": "A1"}).json()
    explicit = client.get("/calc/", params={"bg": "B", "specs": "A1", "pool": "identical"}).json()

    assert without["pool"] == "identical"
    assert without["pool_groups"] == ["B"]
    assert without["results"] == explicit["results"]


@pytest.mark.parametrize("key, expected", sorted(API_MATRIX.items()))
def test_matchability_status_flags_only_a_genuinely_wider_pool(key, expected):
    """The caveat must fire when the pool really is wider, and not otherwise.

    A group O recipient, and a group A recipient in tier B, select a policy pool
    that adds nobody, so their band still stands and must not be flagged.
    """
    bg, pool = key
    _, _, status = expected
    response = client.get("/calc/", params={"bg": bg, "specs": "A1", "pool": pool})

    assert response.json()["matchability_status"] == status


def test_api_rejects_an_unknown_pool():
    assert client.get("/calc/", params={"bg": "B", "pool": "everything"}).status_code == 422


@pytest.mark.parametrize("pool", ["identical", "tier_b", "tier_a"])
def test_the_pool_applies_within_the_dp_typed_subset_too(pool):
    """The two selectors are independent: donor_set narrows the cohort, pool
    widens the blood groups taken from it."""
    response = client.get(
        "/calc/", params={"bg": "AB", "specs": "A1", "pool": pool, "donor_set": 1}
    ).json()

    typed = BASE.donors[1]
    expected = int(typed.bg.isin(response["pool_groups"]).sum())

    assert response["pool_size"] == expected
    assert response["donor_cohort"] == "dp_typed_only"
    assert response["results"]["available"] <= expected


@pytest.mark.parametrize("bg, pool", [("AB", "identical"), ("AB", "tier_a"), ("B", "tier_b")])
def test_dp4_weighting_applies_over_the_selected_pool(bg, pool):
    """An allele level DP4 entry is weighted against the DP4 donors of whichever
    pool is in force, not always the blood group identical ones."""
    params = {"bg": bg, "specs": "DPB0402", "pool": pool}
    weighted = client.get("/calc/", params=params).json()["results"]["crf"]
    broad = client.get("/calc/", params={**params, "specs": "DPB4"}).json()["results"]["crf"]

    fraction = BASE.dp4_frequencies["DPB0402"].carrier_fraction
    assert weighted == pytest.approx(broad * fraction, abs=1e-9)


def test_a_patient_with_no_antibodies_scores_zero_over_every_pool():
    """The denominator changes; a cRF of nothing excluded does not."""
    for bg in ("O", "A", "B", "AB"):
        for pool in ("identical", "tier_b", "tier_a"):
            response = client.get("/calc/", params={"bg": bg, "specs": "", "pool": pool}).json()

            assert response["results"]["crf"] == 0
            assert response["results"]["available"] == response["pool_size"]


def test_the_pool_survives_a_shared_url_round_trip():
    """The query contract the browser rebuilds its state from."""
    response = client.get(
        "/calc/",
        params={"bg": "AB", "specs": "A1,B8", "recip_hla": "B7,DR4", "pool": "tier_b", "donor_set": 0},
    ).json()

    assert response["pool"] == "tier_b"
    assert response["pool_groups"] == ["AB", "A"]
    assert response["bg"] == "AB"
    assert response["specs"] == ["A1", "B8"]


def test_missing_pools_fail_closed():
    """An empty pool would score a patient against an empty denominator."""
    import pandas as pd

    loader = DataLoader()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(loader, "_load_table", lambda *_, **__: pd.DataFrame())
        with pytest.raises(Exception, match="Missing or malformed donor pool"):
            loader.abo_pools()
