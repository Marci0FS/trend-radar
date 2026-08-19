from unittest.mock import MagicMock, patch

import pytest

from collectors import aliexpress


def test_sign_request_produces_expected_md5():
    """Fixture verifiee independamment : MD5('shhh' + 'a1b2sign_methodmd5' +
    'shhh') = 498B7905B62F5C10A1544F20A06F8FE2 (parametres tries par cle :
    a, b, sign_method ; concatenation cle+valeur sans separateur)."""
    params = {"b": "2", "a": "1", "sign_method": "md5"}
    assert aliexpress._sign_request(params, "shhh") == "498B7905B62F5C10A1544F20A06F8FE2"


def test_get_access_token_missing_credentials_raises_key_error(monkeypatch):
    monkeypatch.delenv("ALIEXPRESS_APP_KEY", raising=False)
    monkeypatch.delenv("ALIEXPRESS_APP_SECRET", raising=False)
    monkeypatch.delenv("ALIEXPRESS_REFRESH_TOKEN", raising=False)
    monkeypatch.setattr(aliexpress, "_cached_access_token", None)

    with pytest.raises(KeyError):
        aliexpress.get_access_token()


def test_get_access_token_caches_within_process(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setenv("ALIEXPRESS_REFRESH_TOKEN", "test-refresh")
    monkeypatch.setattr(aliexpress, "_cached_access_token", None)

    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "tok123"}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response) as mock_get:
        token1 = aliexpress.get_access_token()
        token2 = aliexpress.get_access_token()

    assert token1 == "tok123"
    assert token2 == "tok123"
    mock_get.assert_called_once()


def test_get_access_token_raises_aliexpress_error_on_http_failure(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setenv("ALIEXPRESS_REFRESH_TOKEN", "test-refresh")
    monkeypatch.setattr(aliexpress, "_cached_access_token", None)

    import requests as requests_module

    with patch(
        "collectors.aliexpress.requests.get",
        side_effect=requests_module.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(aliexpress.AliExpressError):
            aliexpress.get_access_token()


def test_get_access_token_raises_aliexpress_error_on_missing_access_token_field(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setenv("ALIEXPRESS_REFRESH_TOKEN", "test-refresh")
    monkeypatch.setattr(aliexpress, "_cached_access_token", None)

    mock_response = MagicMock()
    mock_response.json.return_value = {"error": "invalid refresh token"}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response):
        with pytest.raises(aliexpress.AliExpressError):
            aliexpress.get_access_token()


def _query_response(products):
    return {
        "aliexpress_affiliate_product_query_response": {
            "resp_result": {"result": {"products": {"product": products}}}
        }
    }


def test_fetch_sales_volume_sums_volume_across_products(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    mock_response = MagicMock()
    mock_response.json.return_value = _query_response(
        [{"volume": 100}, {"volume": 250}, {"volume": 30}]
    )
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response) as mock_get:
        total = aliexpress.fetch_sales_volume("led face mask")

    assert total == 380
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs["params"]["keywords"] == "led face mask"
    assert call_kwargs["params"]["page_size"] == 10
    assert call_kwargs["params"]["ship_to_country"] == "FR"


def test_fetch_sales_volume_falls_back_to_lastest_volume_field(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    mock_response = MagicMock()
    mock_response.json.return_value = _query_response([{"lastest_volume": 42}])
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response):
        total = aliexpress.fetch_sales_volume("led face mask")

    assert total == 42


def test_fetch_sales_volume_returns_zero_for_empty_results(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    mock_response = MagicMock()
    mock_response.json.return_value = _query_response([])
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response):
        total = aliexpress.fetch_sales_volume("very obscure keyword")

    assert total == 0


def test_fetch_sales_volume_raises_aliexpress_error_when_product_missing_volume(monkeypatch):
    """Un produit sans champ 'volume' ni 'lastest_volume' doit lever
    AliExpressError plutot que d'etre silencieusement traite comme 0 —
    un faux 0 stocke en snapshot fabriquerait un faux signal de convergence
    au prochain scan (meme precaution que collectors/ebay.py)."""
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    mock_response = MagicMock()
    mock_response.json.return_value = _query_response([{"productId": 123}])
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response):
        with pytest.raises(aliexpress.AliExpressError):
            aliexpress.fetch_sales_volume("led face mask")


def test_fetch_sales_volume_raises_aliexpress_error_on_malformed_structure(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    mock_response = MagicMock()
    mock_response.json.return_value = {"error_response": {"msg": "Invalid session"}}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response):
        with pytest.raises(aliexpress.AliExpressError):
            aliexpress.fetch_sales_volume("led face mask")


def test_fetch_sales_volume_raises_aliexpress_error_when_volume_is_non_numeric(monkeypatch):
    """Une valeur de volume presente mais non convertible en int (chaine
    non numerique, par ex.) doit lever AliExpressError plutot que planter
    avec une ValueError brute ou etre traitee comme 0 (meme precaution que
    collectors/ebay.py::test_fetch_listing_count_raises_ebay_error_when_total_is_non_numeric)."""
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    mock_response = MagicMock()
    mock_response.json.return_value = _query_response([{"volume": "abc"}])
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response):
        with pytest.raises(aliexpress.AliExpressError):
            aliexpress.fetch_sales_volume("led face mask")


def test_fetch_sales_volume_raises_aliexpress_error_when_product_field_is_not_a_list(monkeypatch):
    """Si le champ 'product' de la reponse n'est pas une liste (un dict unique,
    par ex., comme peut le renvoyer un gateway TOP-style quand un seul produit
    correspond), on doit lever AliExpressError plutot que planter ou iterer sur
    autre chose que des produits (meme precaution que
    collectors/ebay.py::test_fetch_listing_count_raises_ebay_error_when_body_is_a_list)."""
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    mock_response = MagicMock()
    mock_response.json.return_value = _query_response({"volume": 100})
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response):
        with pytest.raises(aliexpress.AliExpressError):
            aliexpress.fetch_sales_volume("led face mask")


def test_fetch_sales_volume_raises_aliexpress_error_on_http_failure(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    import requests as requests_module

    with patch(
        "collectors.aliexpress.requests.get",
        side_effect=requests_module.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(aliexpress.AliExpressError):
            aliexpress.fetch_sales_volume("led face mask")
