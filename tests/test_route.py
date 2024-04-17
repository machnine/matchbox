"""Calculator API endpoint tests"""

import warnings
from unittest.mock import MagicMock, patch

import pandas as pd
from fastapi.testclient import TestClient

from api import api
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
mock_data.mantigens = mock_mantigens
mock_data.mbands = mock_mbands
mock_data.antigen_defaults = mock_ag_defaults


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
