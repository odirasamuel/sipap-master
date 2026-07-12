"""Integration tests for FastAPI endpoints.

Tests HTTP API endpoints:
- GET /health
- GET /sports
- POST /predict
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from sipap.api.handlers import app


@pytest.fixture
def client():
    """Create test client for FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_orchestrator():
    """Mock MainOrchestrator for API tests."""
    with patch("sipap.api.handlers.get_orchestrator") as mock:
        orchestrator = MagicMock()

        # Mock get_supported_sports
        orchestrator.get_supported_sports.return_value = ["soccer"]

        # Mock predict
        orchestrator.predict = AsyncMock(
            return_value={
                "status": "SUCCESS",
                "outcome": "Home Win",
                "probability": 0.65,
                "confidence": 78.0,
                "expected_value": {
                    "expected_value": 0.25,
                    "is_positive_ev": True,
                    "recommendation": "PLACE BET - Positive expected value",
                },
                "quality_gate": "PASSED",
                "recommendation": "Prediction ready for user",
                "reasoning": "Ensemble prediction favors home team",
                "evidence": ["Home team in better form", "H2H favors home"],
            }
        )

        mock.return_value = orchestrator
        yield mock


def test_root_endpoint(client):
    """
    Test root endpoint returns API information.

    Verifies:
    1. 200 status code
    2. Service name and version present
    """
    response = client.get("/")

    assert response.status_code == 200
    data = response.json()

    assert "service" in data
    assert "version" in data
    assert "SIPAP" in data["service"]


def test_health_check_success(client, mock_orchestrator):
    """
    Test health check endpoint when service is healthy.

    Verifies:
    1. 200 status code
    2. Status is "healthy"
    3. Version information present
    """
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "healthy"
    assert "version" in data
    assert "orchestrator" in data


def test_list_sports_success(client, mock_orchestrator):
    """
    Test sports listing endpoint.

    Verifies:
    1. 200 status code
    2. Soccer is in the list
    3. Count is accurate
    """
    response = client.get("/sports")

    assert response.status_code == 200
    data = response.json()

    assert "sports" in data
    assert "count" in data
    assert "soccer" in data["sports"]
    assert data["count"] == len(data["sports"])


def test_predict_success(client, mock_orchestrator):
    """
    Test successful prediction request.

    Verifies:
    1. 200 status code
    2. All required fields present
    3. Quality gate passed
    4. +EV detected
    """
    request_data = {
        "sport": "soccer",
        "match_id": "Man_United_vs_Liverpool",
        "market": "1X2",
    }

    response = client.post("/predict", json=request_data)

    assert response.status_code == 200
    data = response.json()

    # Verify structure
    assert data["status"] == "SUCCESS"
    assert data["match_id"] == "Man_United_vs_Liverpool"
    assert data["market"] == "1X2"
    assert data["outcome"] == "Home Win"
    assert data["probability"] == 0.65
    assert data["confidence"] == 78.0

    # Verify quality gate
    assert data["quality_gate"] == "PASSED"

    # Verify EV
    assert data["expected_value"]["is_positive_ev"] is True

    # Verify recommendation
    assert "Prediction ready for user" in data["recommendation"]


def test_predict_validation_failure(client):
    """
    Test prediction request with validation failure.

    Verifies:
    1. 422 status code for validation failure
    2. Error message explains the issue
    """
    with patch("sipap.api.handlers.get_orchestrator") as mock:
        orchestrator = MagicMock()
        orchestrator.predict = AsyncMock(
            return_value={
                "status": "FAILED",
                "reason": "Missing critical fields: fixture, odds",
                "validation": {"data_completeness": 40.0},
            }
        )
        mock.return_value = orchestrator

        request_data = {
            "sport": "soccer",
            "match_id": "test_match",
            "market": "1X2",
        }

        response = client.post("/predict", json=request_data)

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data


def test_predict_unsupported_sport(client):
    """
    Test prediction request with unsupported sport.

    Verifies:
    1. 400 status code
    2. Error message indicates sport not supported
    """
    with patch("sipap.api.handlers.get_orchestrator") as mock:
        orchestrator = MagicMock()
        orchestrator.predict = AsyncMock(
            side_effect=ValueError("Sport 'cricket' not supported")
        )
        mock.return_value = orchestrator

        request_data = {
            "sport": "cricket",
            "match_id": "test_match",
            "market": "Winner",
        }

        response = client.post("/predict", json=request_data)

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data


def test_predict_internal_error(client):
    """
    Test prediction request with unexpected internal error.

    Verifies:
    1. 500 status code
    2. Error details present
    """
    with patch("sipap.api.handlers.get_orchestrator") as mock:
        orchestrator = MagicMock()
        orchestrator.predict = AsyncMock(
            side_effect=RuntimeError("Database connection failed")
        )
        mock.return_value = orchestrator

        request_data = {
            "sport": "soccer",
            "match_id": "test_match",
            "market": "1X2",
        }

        response = client.post("/predict", json=request_data)

        assert response.status_code == 500
        data = response.json()
        assert "detail" in data


def test_predict_missing_fields(client):
    """
    Test prediction request with missing required fields.

    Verifies:
    1. 422 status code (validation error)
    2. Error indicates missing fields
    """
    request_data = {
        "sport": "soccer",
        # Missing match_id and market
    }

    response = client.post("/predict", json=request_data)

    assert response.status_code == 422
    data = response.json()
    assert "detail" in data


def test_predict_invalid_json(client):
    """
    Test prediction request with invalid JSON.

    Verifies:
    1. 422 status code
    2. JSON parsing error
    """
    response = client.post(
        "/predict",
        data="invalid json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
