"""
Test suite for the Campaign Image Generator API.

Run with:  pytest

These tests mock the Cloudflare Workers AI HTTP call, so they run offline
and don't consume any real free-tier quota.
"""
import base64
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure env vars exist before main.py is imported (it validates them, and runs
# init_db(), at import time). Pointing DB_PATH at a throwaway file here stops the
# module-level init_db() call from creating history.db in the project root; each
# test still gets its own isolated DB via the `client` fixture below.
os.environ.setdefault("PYTEST_CURRENT_TEST", "1")
os.environ.setdefault("CF_ACCOUNT_ID", "test-account")
os.environ.setdefault("CF_API_TOKEN", "test-token")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "campaign_app_import_time.db"))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Fresh TestClient with an isolated, temporary SQLite database per test."""
    db_file = tmp_path / "test_history.db"
    monkeypatch.setattr(main, "DB_PATH", str(db_file))
    main.init_db()
    return TestClient(main.app)


def _fake_image_response(status_code=200, content_type="image/png", body=b"fake-image-bytes", json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": content_type}
    resp.content = body
    resp.json.return_value = json_body or {}
    resp.text = str(json_body) if json_body else ""
    return resp


# ---------- Health & metadata ----------

def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_campaign_types_lists_all_presets(client):
    response = client.get("/api/v1/campaign-types")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    keys = {t["key"] for t in data["types"]}
    assert keys == {"social", "banner", "poster", "product"}


# ---------- build_generation_params (pure logic, no HTTP) ----------

def test_build_generation_params_no_preset_returns_default_square():
    prompt, width, height = main.build_generation_params("a red apple", None)
    assert "a red apple" in prompt
    assert "photorealistic" in prompt  # default style suffix should be applied
    assert width == main.DEFAULT_DIMENSION
    assert height == main.DEFAULT_DIMENSION


def test_build_generation_params_banner_is_wide():
    prompt, width, height = main.build_generation_params("a sale poster", "banner")
    assert "a sale poster" in prompt
    assert width > height  # banner should be landscape


def test_build_generation_params_poster_is_tall():
    _, width, height = main.build_generation_params("a sale poster", "poster")
    assert height > width  # poster should be portrait


def test_build_generation_params_unknown_type_falls_back_to_default():
    prompt, width, height = main.build_generation_params("a red apple", "not-a-real-type")
    assert "a red apple" in prompt
    assert width == main.DEFAULT_DIMENSION


# ---------- generate-campaign endpoint ----------

def test_generate_campaign_empty_prompt_returns_error(client):
    response = client.post("/api/v1/generate-campaign", json={"prompt": "   "})
    assert response.status_code == 200  # API reports errors in the body, not HTTP status
    data = response.json()
    assert data["status"] == "error"
    assert "empty" in data["message"].lower()


@patch("main.requests.post")
def test_generate_campaign_success(mock_post, client):
    mock_post.return_value = _fake_image_response()

    response = client.post(
        "/api/v1/generate-campaign",
        json={"prompt": "a red apple on a white background", "num_variations": 1},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["failed_count"] == 0
    assert len(data["images"]) == 1
    assert base64.b64decode(data["images"][0]["image_base64"]) == b"fake-image-bytes"


@patch("main.requests.post")
def test_generate_campaign_applies_campaign_type_preset(mock_post, client):
    mock_post.return_value = _fake_image_response()

    response = client.post(
        "/api/v1/generate-campaign",
        json={"prompt": "a coffee shop", "num_variations": 1, "campaign_type": "banner"},
    )
    data = response.json()
    assert data["status"] == "success"
    assert data["campaign_type"] == "banner"
    assert "a coffee shop" in data["final_prompt"]
    assert data["final_prompt"] != data["prompt"]  # style suffix was appended

    # Confirm the width/height sent to Cloudflare matched the banner preset
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["width"] == main.CAMPAIGN_PRESETS["banner"]["width"]
    assert kwargs["json"]["height"] == main.CAMPAIGN_PRESETS["banner"]["height"]


@patch("main.requests.post")
def test_generate_campaign_sends_negative_prompt_against_cartoon_style(mock_post, client):
    mock_post.return_value = _fake_image_response()

    client.post(
        "/api/v1/generate-campaign",
        json={"prompt": "a red apple", "num_variations": 1},
    )

    _, kwargs = mock_post.call_args
    assert "cartoon" in kwargs["json"]["negative_prompt"]
    assert "illustration" in kwargs["json"]["negative_prompt"]


@patch("main.requests.post")
def test_generate_campaign_caps_variations_at_max(mock_post, client):
    mock_post.return_value = _fake_image_response()

    response = client.post(
        "/api/v1/generate-campaign",
        json={"prompt": "a red apple", "num_variations": 999},
    )
    data = response.json()
    assert data["requested"] == main.MAX_VARIATIONS
    assert mock_post.call_count == main.MAX_VARIATIONS


@patch("main.requests.post")
def test_generate_campaign_all_variations_fail(mock_post, client):
    mock_post.return_value = _fake_image_response(
        status_code=400, content_type="application/json",
        json_body={"errors": [{"message": "bad request"}]},
    )

    response = client.post(
        "/api/v1/generate-campaign",
        json={"prompt": "a red apple", "num_variations": 2},
    )
    data = response.json()
    assert data["status"] == "error"
    assert "All variations failed" in data["message"]
    assert len(data["details"]) == 2


@patch("main.requests.post")
def test_generate_campaign_partial_failure_still_succeeds(mock_post, client):
    # First call fails, second succeeds
    mock_post.side_effect = [
        _fake_image_response(status_code=500, content_type="application/json", json_body={"errors": [{"message": "server error"}]}),
        _fake_image_response(),
    ]

    response = client.post(
        "/api/v1/generate-campaign",
        json={"prompt": "a red apple", "num_variations": 2},
    )
    data = response.json()
    assert data["status"] == "success"
    assert data["failed_count"] == 1
    assert len(data["images"]) == 1


@patch("main.requests.post")
def test_generate_campaign_connection_error_is_reported(mock_post, client):
    mock_post.side_effect = main.requests.exceptions.ConnectionError("DNS failure")

    response = client.post(
        "/api/v1/generate-campaign",
        json={"prompt": "a red apple", "num_variations": 1},
    )
    data = response.json()
    assert data["status"] == "error"
    assert "DNS failure" in data["details"][0]


# ---------- history endpoints ----------

@patch("main.requests.post")
def test_history_contains_generated_entry(mock_post, client):
    mock_post.return_value = _fake_image_response()
    client.post("/api/v1/generate-campaign", json={"prompt": "a red apple", "num_variations": 1})

    response = client.get("/api/v1/history")
    data = response.json()
    assert data["status"] == "success"
    assert len(data["history"]) == 1
    assert data["history"][0]["prompt"] == "a red apple"


def test_history_empty_when_nothing_generated(client):
    response = client.get("/api/v1/history")
    data = response.json()
    assert data["history"] == []


@patch("main.requests.post")
def test_delete_history_item_removes_it(mock_post, client):
    mock_post.return_value = _fake_image_response()
    gen_response = client.post(
        "/api/v1/generate-campaign", json={"prompt": "a red apple", "num_variations": 1}
    )
    generation_id = gen_response.json()["generation_id"]

    delete_response = client.delete(f"/api/v1/history/{generation_id}")
    assert delete_response.json()["status"] == "success"

    history_response = client.get("/api/v1/history")
    assert history_response.json()["history"] == []


def test_delete_nonexistent_history_item_is_safe(client):
    response = client.delete("/api/v1/history/does-not-exist")
    assert response.status_code == 200
    assert response.json()["status"] == "success"
