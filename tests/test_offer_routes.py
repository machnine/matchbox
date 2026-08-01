"""tests for the offer assessment API

Exercised through the real app against the real donor data, since the numbers
these endpoints return are the product.
"""

from fastapi.testclient import TestClient

from api.app import create_app
from api.assets import asset_version

app = create_app()
client = TestClient(app)

PROFILE = {
    "bg": "A",
    "specs": [
        {"spec": "A1", "current": 6000, "peak": 9000},
        {"spec": "B7", "current": 12000, "peak": 12000},
        {"spec": "DR4", "current": 4000, "peak": 7000},
    ],
}


# --------------------------------------------------------------------------
# the cRF surface must be untouched
# --------------------------------------------------------------------------


def test_existing_calc_route_still_works():
    response = client.get("/calc/?bg=A&specs=A1,B7")
    assert response.status_code == 200
    assert "results" in response.json()


def test_index_still_renders():
    assert client.get("/").status_code == 200


# --------------------------------------------------------------------------
# shared normalisation -- one definition for both pages
# --------------------------------------------------------------------------


def test_normalise_endpoint_resolves_plain_antigens():
    body = client.post("/normalise/", json={"text": "A1 B7 DR4"}).json()
    assert body["antigens"] == ["A1", "B7", "DR4"]
    assert body["ok"] is True


def test_normalise_endpoint_resolves_allele_forms():
    """the cRF page could not do this before it shared the server's parser"""
    body = client.post("/normalise/", json={"text": "HLA-B*07:02 DRB1*04:01 C*07:02"}).json()
    assert body["antigens"] == ["B7", "DR4", "CW7"]


def test_normalise_endpoint_returns_suggestions():
    body = client.post("/normalise/", json={"text": "A1 B4"}).json()
    assert body["ok"] is False
    problem = next(p for p in body["problems"] if p["token"] == "B4")
    assert problem["suggestions"]


def test_normalise_and_offer_parse_donor_agree():
    """both pages must resolve a token to the same antigen"""
    text = "HLA-B*07:02 DPB1*04:01 C*07:02"
    shared = client.post("/normalise/", json={"text": text}).json()
    offer = client.post("/offer/parse-donor", json={"text": text}).json()
    assert shared["antigens"] == offer["antigens"]


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def test_parse_endpoint_returns_preview():
    response = client.post("/offer/parse", json={"text": "A1\t4000\nB7\t9000"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["recognised"] == 2
    assert [r["spec"] for r in body["rows"]] == ["A1", "B7"]


def test_parse_endpoint_normalises_allele_forms():
    response = client.post("/offer/parse", json={"text": "DPB1*04:01\t4000\nC*07:02\t3000"})
    body = response.json()
    assert [r["spec"] for r in body["rows"]] == ["DPB4", "CW7"]


def test_parse_endpoint_surfaces_unrecognised_tokens():
    response = client.post("/offer/parse", json={"text": "A1\t4000\nNOPE9\t2000"})
    body = response.json()
    assert body["ok"] is False
    assert any(p["kind"] == "unrecognised_specificity" for p in body["problems"])


def test_parse_donor_endpoint():
    response = client.post("/offer/parse-donor", json={"text": "a1, b7  dr4"})
    assert response.json()["antigens"] == ["A1", "B7", "DR4"]


# --------------------------------------------------------------------------
# distribution
# --------------------------------------------------------------------------


def test_distribution_returns_all_metrics_for_both_bases():
    response = client.post("/offer/distribution", json=PROFILE)
    assert response.status_code == 200
    body = response.json()
    assert set(body["distributions"]) == {"current", "peak"}
    for basis in ("current", "peak"):
        assert set(body["distributions"][basis]["summary"]) == {
            "cumulative",
            "max",
            "mean",
            "median",
        }


def test_distribution_carries_provenance():
    """§5.3 -- a stored result must be interpretable later"""
    body = client.post("/offer/distribution", json=PROFILE).json()
    meta = body["meta"]
    provenance = meta["provenance"]
    assert provenance["donor_set"] == "donors_v3"
    assert provenance["abo_rule"] == "identical"
    assert provenance["dp_mode_applied"] in ("include", "exclude")
    assert meta["threshold"] == 2000
    assert meta["policy_version"]
    assert meta["vocabulary_version"]
    assert len(meta["data_provenance"]["donor_database_sha256"]) == 64


def test_distribution_records_defaulted_choices():
    body = client.post("/offer/distribution", json=PROFILE).json()
    assert "dp_mode=auto" in body["meta"]["provenance"]["defaulted"]


def test_distribution_warns_that_identical_abo_understates_the_pool():
    body = client.post("/offer/distribution", json=PROFILE).json()
    assert any("understate" in note for note in body["meta"]["notes"])


def test_distribution_reports_distinct_value_count():
    """the tie structure bounds what a percentile can mean"""
    body = client.post("/offer/distribution", json=PROFILE).json()
    summary = body["distributions"]["current"]["summary"]["cumulative"]
    assert summary["distinct"] <= 2**3 - 1
    assert summary["n"] > 1000


def test_distribution_rejects_unknown_specificity():
    bad = {**PROFILE, "specs": [{"spec": "ZZZ9", "current": 4000}]}
    response = client.post("/offer/distribution", json=bad)
    assert response.status_code == 422
    assert "ZZZ9" in response.json()["detail"]


def test_distribution_rejects_unknown_blood_group():
    bad = {**PROFILE, "bg": "Z"}
    assert client.post("/offer/distribution", json=bad).status_code == 422


def test_distribution_rejects_negative_or_duplicate_profile_values():
    negative = {"bg": "A", "specs": [{"spec": "A1", "current": -1}]}
    duplicate = {
        "bg": "A",
        "specs": [{"spec": "A1", "current": 3000}, {"spec": "a1", "current": 4000}],
    }
    bad_threshold = {"bg": "A", "threshold": -1, "specs": [{"spec": "A1", "current": 3000}]}

    assert client.post("/offer/distribution", json=negative).status_code == 422
    assert client.post("/offer/distribution", json=duplicate).status_code == 422
    assert client.post("/offer/distribution", json=bad_threshold).status_code == 422


def test_distribution_reports_basis_specific_reference_sizes():
    profile = {
        "bg": "A",
        "specs": [
            {"spec": "A1", "current": 5000, "peak": 5000},
            {"spec": "B7", "current": 1000, "peak": 9000},
        ],
    }
    body = client.post("/offer/distribution", json=profile).json()
    assert body["distributions"]["current"]["reference_size"] != body["distributions"]["peak"]["reference_size"]


def test_distribution_current_only_when_peak_absent():
    profile = {"bg": "A", "specs": [{"spec": "A1", "current": 6000}]}
    body = client.post("/offer/distribution", json=profile).json()
    assert body["bases_available"] == ["current"]
    assert any("Peak MFI unavailable" in n for n in body["meta"]["notes"])


# --------------------------------------------------------------------------
# DP behaviour
# --------------------------------------------------------------------------


def test_dp_profile_restricts_cohort_and_says_so():
    profile = {
        "bg": "A",
        "specs": [{"spec": "A1", "current": 6000}, {"spec": "DPB4", "current": 8000}],
    }
    body = client.post("/offer/distribution", json=profile).json()
    provenance = body["meta"]["provenance"]
    assert provenance["dp_typed_only"] is True
    assert provenance["cohort_size"] == 1481  # DP-typed group A
    assert provenance["set_size_before_dp"] == 4094
    assert any("cannot be corroborated" in n for n in body["meta"]["notes"])


def test_dp_exclude_states_what_was_discarded():
    """§7.3 -- never silently produce a lower, official-looking number"""
    profile = {
        "bg": "A",
        "specs": [{"spec": "A1", "current": 6000}, {"spec": "DPB4", "current": 8000}],
        "dp_mode": "exclude",
    }
    body = client.post("/offer/distribution", json=profile).json()
    provenance = body["meta"]["provenance"]
    assert provenance["dp_specs_dropped"] == ["DPB4"]
    assert provenance["cohort_size"] == 4094
    assert body["distributions"]["current"]["specs_used"] == ["A1"]
    assert body["distributions"]["current"]["specs_excluded_by_cohort"] == ["DPB4"]
    assert any("discarded" in n for n in body["meta"]["notes"])


def test_ab_dp_patient_is_flagged_as_too_small():
    """the 118-donor case"""
    profile = {
        "bg": "AB",
        "specs": [{"spec": "A1", "current": 6000}, {"spec": "DPB4", "current": 8000}],
    }
    body = client.post("/offer/distribution", json=profile).json()
    assert body["meta"]["provenance"]["below_stats_floor"] is True
    assert any("too small to characterise" in n for n in body["meta"]["notes"])


# --------------------------------------------------------------------------
# ABO policy gap
# --------------------------------------------------------------------------


def test_offerable_abo_returns_not_implemented_rather_than_guessing():
    profile = {**PROFILE, "abo_rule": "offerable", "organ": "kidney", "tier": "A"}
    response = client.post("/offer/distribution", json=profile)
    assert response.status_code == 501
    assert "POL186" in response.json()["detail"]


# --------------------------------------------------------------------------
# placement
# --------------------------------------------------------------------------


def test_placement_returns_counts_and_percentiles():
    body = client.post("/offer/placement", json={**PROFILE, "donor_hla": ["A1", "B7", "DR15"]}).json()
    assert body["dsa_specs"] == ["A1", "B7"]
    assert body["dsa_count"] == 2
    placement = body["placements"]["current:cumulative"]
    assert placement["value"] == 18000
    assert placement["n_lower"] + placement["n_equal"] + placement["n_higher"] == placement["reference_size"]


def test_placement_reports_ties_separately():
    """with few specificities most donors tie; folding them would move the number"""
    body = client.post("/offer/placement", json={**PROFILE, "donor_hla": ["A1", "B7", "DR15"]}).json()
    assert body["placements"]["current:cumulative"]["n_equal"] > 0


def test_placement_counts_identical_dsa_sets():
    body = client.post("/offer/placement", json={**PROFILE, "donor_hla": ["A1", "B7", "DR15"]}).json()
    assert body["identical_dsa_set_count"] > 0


def test_placement_donor_with_no_dsa_is_not_ranked():
    body = client.post("/offer/placement", json={**PROFILE, "donor_hla": ["A2", "B8", "DR15"]}).json()
    assert body["dsa_count"] == 0
    assert body["offer_status"] == "compatible_no_dsa"
    assert body["basis_summaries"]["current"]["status"] == "compatible_no_dsa"
    assert "current:cumulative" not in body["placements"]


def test_placement_metrics_can_disagree():
    """the disagreement is itself the clinical signal (§2.2)

    A donor carrying two weak DSA sits well up the cumulative distribution but at
    the very bottom of the max distribution, because its strongest single
    antibody ties with every single-DSA donor. Same offer, opposite readings --
    which is why no metric is privileged and all four are exposed.
    """
    profile = {
        "bg": "A",
        "specs": [
            {"spec": "A1", "current": 2500},
            {"spec": "B7", "current": 20000},
            {"spec": "DR4", "current": 2500},
        ],
    }
    body = client.post("/offer/placement", json={**profile, "donor_hla": ["A1", "B8", "DR4"]}).json()
    cumulative = body["placements"]["current:cumulative"]
    maximum = body["placements"]["current:max"]
    assert cumulative["n_lower"] > 1000
    assert maximum["n_lower"] == 0


def test_placement_rejects_unknown_donor_antigen():
    response = client.post("/offer/placement", json={**PROFILE, "donor_hla": ["ZZZ9"]})
    assert response.status_code == 422


def test_placement_rejects_abo_mismatch_between_offer_and_reference_set():
    response = client.post(
        "/offer/placement",
        json={**PROFILE, "donor_hla": ["A1", "B7", "DR15"], "donor_bg": "O"},
    )
    assert response.status_code == 422
    assert "outside the selected" in response.json()["detail"]


def test_placement_rejects_missing_typing_at_an_antibody_locus():
    response = client.post("/offer/placement", json={**PROFILE, "donor_hla": ["A1", "B7"]})
    assert response.status_code == 422
    assert "missing typing" in response.json()["detail"]


def test_placement_keeps_current_and_peak_denominators_separate():
    profile = {
        "bg": "A",
        "specs": [
            {"spec": "A1", "current": 5000, "peak": 5000},
            {"spec": "B7", "current": 1000, "peak": 9000},
        ],
    }
    body = client.post(
        "/offer/placement",
        json={**profile, "donor_hla": ["A1", "B7"]},
    ).json()
    assert body["reference_size"] == body["basis_summaries"]["current"]["reference_size"]
    assert body["basis_summaries"]["current"]["reference_size"] != body["basis_summaries"]["peak"]["reference_size"]
    assert any("different incompatible reference populations" in note for note in body["meta"]["notes"])


def test_placement_agrees_with_distribution_reference_size():
    """the two calls must describe the same population"""
    dist = client.post("/offer/distribution", json=PROFILE).json()
    place = client.post("/offer/placement", json={**PROFILE, "donor_hla": ["A1", "B7", "DR15"]}).json()
    assert place["reference_size"] == dist["distributions"]["current"]["reference_size"]


# --------------------------------------------------------------------------
# joint view
# --------------------------------------------------------------------------


def test_placement_omits_joint_view_without_recipient_hla():
    body = client.post("/offer/placement", json={**PROFILE, "donor_hla": ["A1", "B7", "DR15"]}).json()
    assert body["joint"] is None


def test_placement_includes_joint_view_with_recipient_hla():
    body = client.post(
        "/offer/placement",
        json={**PROFILE, "donor_hla": ["A1", "B7", "DR15"], "recip_hla": "B8 DR15"},
    ).json()
    joint = body["joint"]
    assert joint is not None
    assert joint["cells"]
    assert joint["offered_mismatch_level"] in (1, 2, 3, 4)
    assert joint["n_better_on_both"] is not None


def test_placement_canonicalises_recipient_splits_for_mismatch():
    body = client.post(
        "/offer/placement",
        json={**PROFILE, "donor_hla": ["A1", "B44", "DR17"], "recip_hla": "B44 DR17"},
    ).json()
    assert body["recip_hla_used"] == ["B12", "DR3"]
    assert body["recip_hla_conversions"] == {"B44": "B12", "DR17": "DR3"}
    assert body["joint"] is not None


def test_joint_view_cells_sum_to_reference_size():
    body = client.post(
        "/offer/placement",
        json={**PROFILE, "donor_hla": ["A1", "B7", "DR15"], "recip_hla": "B8 DR15"},
    ).json()
    joint = body["joint"]
    assert sum(c["count"] for c in joint["cells"]) == body["reference_size"]


def test_joint_view_is_not_a_fifth_distribution():
    """mismatch must not appear alongside the burden metrics as a parallel ranking"""
    body = client.post(
        "/offer/placement",
        json={**PROFILE, "donor_hla": ["A1", "B7", "DR15"], "recip_hla": "B8 DR15"},
    ).json()
    assert not any("mismatch" in key for key in body["placements"])


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------


def test_offer_page_renders():
    response = client.get("/offer/")
    assert response.status_code == 200
    assert "Offer assessment" in response.text


def test_offer_page_has_provenance_strip():
    """§7.2 -- provenance is visible before any number is read"""
    html = client.get("/offer/").text
    for element in ("prov-set", "prov-dp", "prov-cohort", "prov-abo", "prov-threshold", "prov-data"):
        assert element in html


def test_offer_page_fingerprints_local_static_assets():
    html = client.get("/offer/").text
    for asset in (
        "bootstrap-5.2.3.min.css",
        "style.css",
        "offer.css",
        "favicon.ico",
        "bootstrap-5.2.3.bundle.min.js",
        "offer.js",
    ):
        assert f"/static/{asset}?v={asset_version(asset)}" in html


def test_threshold_changes_which_specs_count():
    low = client.post("/offer/distribution", json={**PROFILE, "threshold": 1000}).json()
    high = client.post("/offer/distribution", json={**PROFILE, "threshold": 10000}).json()
    assert len(low["distributions"]["current"]["specs_used"]) == 3
    assert len(high["distributions"]["current"]["specs_used"]) == 1
    assert high["meta"]["threshold"] == 10000
