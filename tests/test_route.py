"""Calculator API endpoint tests"""

import warnings
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import api
from api.data import DataProvenance
from api.route import load_data

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    client = TestClient(api)

# load mock donors once
mock_donors = pd.read_csv("tests/mock_donors.csv")
mock_ag_defaults = {"B42": "B7", "DR9": "DR4"}
mock_mbands = {
    "A": {1: 35, 2: 30, 3: 25, 4: 20, 5: 15, 6: 10, 7: 5, 8: 2, 9: 1, 10: 0},
    "O": {1: 45, 2: 35, 3: 30, 4: 25, 5: 20, 6: 15, 7: 10, 8: 5, 9: 2, 10: 1},
}
mock_mantigens = {"B": ["B7", "B8", "B12", "B42", "B46"], "DR": ["DR3", "DR9"]}
mock_data = MagicMock()
mock_data.donors = (mock_donors, mock_donors)
mock_data.antigens = {
    "A": ["A1", "A43"],
    "B": ["B7", "B8", "B12", "B42", "B46"],
    "DR": ["DR3", "DR9", "DR17"],
}
mock_data.mantigens = mock_mantigens
mock_data.mbands = mock_mbands
mock_data.antigen_defaults = mock_ag_defaults
mock_data.broad_split = {
    "broad_to_splits": {"B12": ["B44"], "DR3": ["DR17"]},
    "split_to_broad": {
        "B44": "B12",
        "DR17": "DR3",
        # Canonical rare values must not be replaced by generic mappings.
        "B42": "B7",
        "DR9": "DR4",
    },
}
mock_data.provenance = DataProvenance(
    upstream_source_file="test-source.xlsb",
    upstream_source_file_size_signature=123_456,
    donor_database="test-donors.db",
    donor_database_sha256="a" * 64,
    donor_table="test_donors",
    matchability_band_version=7,
)


def test_calc_get_endpoint():
    """test the calc GET endpoint"""
    api.dependency_overrides[load_data] = lambda: mock_data

    def endpoint(params):
        return client.get("/calc/", params=params)

    # test with no params
    response = endpoint({})
    results = response.json().get("results")
    assert response.status_code == 422
    assert results is None

    # test with a blood group only
    response = endpoint({"bg": "A"})
    results = response.json().get("results")
    assert response.status_code == 200
    assert results["crf"] == 0
    assert results["available"] == 39
    assert results["matchability"] is None
    assert results["favourable"] is None

    # test with a blood group and a spec
    response = endpoint({"bg": "B", "specs": "A43,B7,B8,DR17,DR3"})
    results = response.json().get("results")
    assert response.status_code == 200
    assert results["crf"] == 0.42857142857142855
    assert results["available"] == 4

    # test with full params
    response = endpoint(
        {
            "bg": "O",
            "specs": "DR17,B42,B46,DR9",
            "recip_hla": "B7",
            "hla_bdr": mock_data.mantigens,
            "ag_defaults": mock_data.antigen_defaults,
            "matchability_bands": mock_data.mbands,
        }
    )
    results = response.json().get("results")
    assert response.status_code == 200
    assert results["crf"] ==  0.2857142857142857
    assert results["available"] == 35
    assert results["favourable"] == 35
    assert results["matchability"] == 2

    api.dependency_overrides.clear()


def test_calc_canonicalises_recipient_splits_before_matchability():
    """API split input must score exactly like its matchability broad."""
    api.dependency_overrides[load_data] = lambda: mock_data
    try:
        broad = client.get("/calc/", params={"bg": "A", "recip_hla": "B12,DR3"})
        split = client.get("/calc/", params={"bg": "A", "recip_hla": "B44,DR17"})

        assert broad.status_code == 200
        assert split.status_code == 200
        assert split.json()["results"] == broad.json()["results"]
        assert split.json()["recip_hla"] == "B44,DR17"
        assert split.json()["recip_hla_used"] == ["B12", "DR3"]
        assert split.json()["recip_hla_conversions"] == {"B44": "B12", "DR17": "DR3"}
    finally:
        api.dependency_overrides.clear()


@pytest.mark.parametrize(
    "donor_set,donor_cohort,calculation_mode",
    [
        (0, "all_donors", "all_donors_reference"),
        (1, "dp_typed_only", "dp_typed_subset"),
    ],
)
def test_calc_reports_authoritative_context_and_data_provenance(donor_set, donor_cohort, calculation_mode):
    api.dependency_overrides[load_data] = lambda: mock_data
    try:
        response = client.get(
            "/calc/",
            params={"bg": "A", "recip_hla": "B12,DR3", "donor_set": donor_set},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["donor_set"] == donor_set
        assert body["donor_cohort"] == donor_cohort
        assert body["calculation_mode"] == calculation_mode
        assert body["total"] == len(mock_data.donors[donor_set])
        assert body["provenance"] == mock_data.provenance.model_dump()
        assert datetime.fromisoformat(body["calculated_at"]).utcoffset().total_seconds() == 0

        # Raw API calculations remain available for compatibility in both modes.
        assert body["results"]["matchability"] is not None
        assert body["results"]["favourable"] is not None
    finally:
        api.dependency_overrides.clear()


def test_calc_response_contract_is_exposed_in_openapi():
    response_schema = client.get("/openapi.json").json()["paths"]["/calc/"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]

    assert response_schema["$ref"].endswith("/CalculationResponse")


@pytest.mark.parametrize("specs", ["A9999", "A1,", "A1B7", "CW13"])
def test_calc_rejects_specificities_outside_exposed_vocabulary(specs):
    api.dependency_overrides[load_data] = lambda: mock_data
    try:
        response = client.get("/calc/", params={"bg": "A", "specs": specs})

        assert response.status_code == 422
        assert response.json()["detail"]["field"] == "specs"
    finally:
        api.dependency_overrides.clear()


@pytest.mark.parametrize("recip_hla", ["A1", "DQ5", "B999", "BW4", "B7,"])
def test_calc_rejects_unsupported_recipient_hla(recip_hla):
    api.dependency_overrides[load_data] = lambda: mock_data
    try:
        response = client.get("/calc/", params={"bg": "A", "recip_hla": recip_hla})

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["field"] == "recip_hla"
        assert detail["invalid"]
    finally:
        api.dependency_overrides.clear()
