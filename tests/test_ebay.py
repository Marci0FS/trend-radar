import time
from unittest.mock import MagicMock, patch

import pytest

from collectors import ebay


def test_get_app_token_caches_token(monkeypatch):
    monkeypatch.setenv("EBAY_CLIENT_ID", "test-id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("EBAY_ENVIRONMENT", "PRODUCTION")
    ebay._token_cache.clear()

    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "tok123", "expires_in": 7200}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.ebay.requests.post", return_value=mock_response) as mock_post:
        token1 = ebay.get_app_token()
        token2 = ebay.get_app_token()

    assert token1 == "tok123"
    assert token2 == "tok123"
    mock_post.assert_called_once()


def test_get_app_token_missing_credentials_raises_key_error(monkeypatch):
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("EBAY_ENVIRONMENT", "PRODUCTION")
    ebay._token_cache.clear()

    with pytest.raises(KeyError):
        ebay.get_app_token()


def test_fetch_listing_count_parses_total(monkeypatch):
    ebay._token_cache["PRODUCTION"] = ("cached-token", time.time() + 999)

    mock_response = MagicMock()
    mock_response.json.return_value = {"total": 4213, "itemSummaries": []}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.ebay.requests.get", return_value=mock_response) as mock_get:
        count = ebay.fetch_listing_count("led face mask")

    assert count == 4213
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs["params"]["q"] == "led face mask"
    assert call_kwargs["params"]["limit"] == 1


def test_fetch_listing_count_raises_ebay_error_on_http_failure(monkeypatch):
    ebay._token_cache["PRODUCTION"] = ("cached-token", time.time() + 999)

    import requests as requests_module

    with patch(
        "collectors.ebay.requests.get",
        side_effect=requests_module.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(ebay.EbayError):
            ebay.fetch_listing_count("led face mask")


def test_get_app_token_raises_ebay_error_on_http_failure(monkeypatch):
    monkeypatch.setenv("EBAY_CLIENT_ID", "test-id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("EBAY_ENVIRONMENT", "PRODUCTION")
    ebay._token_cache.clear()

    import requests as requests_module

    with patch(
        "collectors.ebay.requests.post",
        side_effect=requests_module.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(ebay.EbayError):
            ebay.get_app_token()


def test_fetch_listing_count_raises_ebay_error_when_total_is_none(monkeypatch):
    ebay._token_cache["PRODUCTION"] = ("cached-token", time.time() + 999)

    mock_response = MagicMock()
    mock_response.json.return_value = {"total": None}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.ebay.requests.get", return_value=mock_response):
        with pytest.raises(ebay.EbayError):
            ebay.fetch_listing_count("led face mask")


def test_fetch_listing_count_raises_ebay_error_when_body_is_a_list(monkeypatch):
    ebay._token_cache["PRODUCTION"] = ("cached-token", time.time() + 999)

    mock_response = MagicMock()
    mock_response.json.return_value = ["not", "a", "dict"]
    mock_response.raise_for_status.return_value = None

    with patch("collectors.ebay.requests.get", return_value=mock_response):
        with pytest.raises(ebay.EbayError):
            ebay.fetch_listing_count("led face mask")


def test_fetch_listing_count_raises_ebay_error_when_total_is_non_numeric(monkeypatch):
    ebay._token_cache["PRODUCTION"] = ("cached-token", time.time() + 999)

    mock_response = MagicMock()
    mock_response.json.return_value = {"total": "abc"}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.ebay.requests.get", return_value=mock_response):
        with pytest.raises(ebay.EbayError):
            ebay.fetch_listing_count("led face mask")


def test_fetch_listing_count_raises_ebay_error_when_total_field_missing(monkeypatch):
    """Un champ 'total' absent (reponse avec seulement 'warnings', par ex.) doit
    lever EbayError plutot que d'etre silencieusement traite comme 0 annonce —
    un faux 0 stocke en snapshot fabriquerait un faux signal de convergence
    "FORT" au prochain scan (growth_pct : avg_previous == 0 => +100%)."""
    ebay._token_cache["PRODUCTION"] = ("cached-token", time.time() + 999)

    mock_response = MagicMock()
    mock_response.json.return_value = {"warnings": [{"message": "quota exceeded"}]}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.ebay.requests.get", return_value=mock_response):
        with pytest.raises(ebay.EbayError):
            ebay.fetch_listing_count("led face mask")


def test_get_app_token_raises_ebay_error_on_missing_access_token_field(monkeypatch):
    monkeypatch.setenv("EBAY_CLIENT_ID", "test-id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("EBAY_ENVIRONMENT", "PRODUCTION")
    ebay._token_cache.clear()

    mock_response = MagicMock()
    mock_response.json.return_value = {"expires_in": 7200}  # Missing access_token
    mock_response.raise_for_status.return_value = None

    with patch("collectors.ebay.requests.post", return_value=mock_response):
        with pytest.raises(ebay.EbayError):
            ebay.get_app_token()
