from unittest.mock import patch

import pytest

from collectors import ebay, youtube
from discovery import product_filter, trends_scan


def _fake_rss_results(terms):
    return [{"trend": t} for t in terms]


@pytest.fixture(autouse=True)
def _bypass_product_filter(monkeypatch):
    """Isole ces tests du filtre produit Claude (Phase 4) : ils testent la
    confirmation eBay/YouTube, pas le filtre semantique en amont. Sans ca,
    ils appelleraient l'API Claude reelle a chaque run (cle absente en test
    -> echec reseau inutile, ou pire, cle presente -> appel paye reel)."""
    monkeypatch.setattr(product_filter, "filter_product_terms", lambda terms: terms)


def test_fetch_trending_candidates_confirms_term_with_ebay_signal(monkeypatch):
    with patch(
        "discovery.trends_scan.download_google_trends_rss",
        return_value=_fake_rss_results(["led face mask"]),
    ):
        monkeypatch.setattr(ebay, "fetch_listing_count", lambda term, **kwargs: 42)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 0)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert len(candidates) == 1
    assert candidates[0] == {
        "phrase": "led face mask",
        "source": "google_trends",
        "mention_count": 0,
        "growth_pct": 0,
        "ebay_signal": True,
        "youtube_signal": False,
        "ebay_count": 42,
        "youtube_views": 0,
    }


def test_fetch_trending_candidates_confirms_term_with_youtube_signal_only(monkeypatch):
    with patch(
        "discovery.trends_scan.download_google_trends_rss",
        return_value=_fake_rss_results(["mini projecteur"]),
    ):
        monkeypatch.setattr(ebay, "fetch_listing_count", lambda term, **kwargs: 0)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 1500)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert len(candidates) == 1
    assert candidates[0]["ebay_signal"] is False
    assert candidates[0]["youtube_signal"] is True
    assert candidates[0]["ebay_count"] == 0
    assert candidates[0]["youtube_views"] == 1500


def test_fetch_trending_candidates_discards_term_with_no_signal(monkeypatch):
    with patch(
        "discovery.trends_scan.download_google_trends_rss",
        return_value=_fake_rss_results(["celebrity gossip"]),
    ):
        monkeypatch.setattr(ebay, "fetch_listing_count", lambda term, **kwargs: 0)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 0)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert candidates == []


def test_fetch_trending_candidates_limits_to_first_n_terms(monkeypatch):
    terms = [f"term {i}" for i in range(30)]

    call_count = {"ebay": 0}

    def _counting_ebay(term, **kwargs):
        call_count["ebay"] += 1
        return 1

    with patch(
        "discovery.trends_scan.download_google_trends_rss",
        return_value=_fake_rss_results(terms),
    ):
        monkeypatch.setattr(ebay, "fetch_listing_count", _counting_ebay)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 0)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert call_count["ebay"] == 20
    assert len(candidates) == 20


def test_fetch_trending_candidates_one_term_failure_does_not_affect_others(monkeypatch):
    def _flaky_ebay(term, **kwargs):
        if term == "flaky term":
            raise ebay.EbayError("simulated failure")
        return 5

    with patch(
        "discovery.trends_scan.download_google_trends_rss",
        return_value=_fake_rss_results(["flaky term", "good term"]),
    ):
        monkeypatch.setattr(ebay, "fetch_listing_count", _flaky_ebay)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 0)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    phrases = [c["phrase"] for c in candidates]
    assert "good term" in phrases
    assert "flaky term" not in phrases


def test_fetch_trending_candidates_treats_missing_ebay_credentials_as_no_signal(monkeypatch):
    """KeyError (credentials manquantes) doit etre traite comme 'pas de
    signal', pas comme une erreur qui remonte — coherent avec le reste du
    projet ou une source sans credentials est silencieusement desactivee."""

    def _raise_key_error(term, **kwargs):
        raise KeyError("EBAY_CLIENT_ID")

    with patch(
        "discovery.trends_scan.download_google_trends_rss",
        return_value=_fake_rss_results(["led face mask"]),
    ):
        monkeypatch.setattr(ebay, "fetch_listing_count", _raise_key_error)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 100)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert len(candidates) == 1
    assert candidates[0]["ebay_signal"] is False
    assert candidates[0]["youtube_signal"] is True
    assert candidates[0]["ebay_count"] == 0
    assert candidates[0]["youtube_views"] == 100


def test_fetch_trending_candidates_raises_runtime_error_on_google_trends_failure(monkeypatch):
    with patch(
        "discovery.trends_scan.download_google_trends_rss",
        side_effect=RuntimeError("boom"),
    ):
        monkeypatch.setattr(trends_scan.time, "sleep", lambda seconds: None)
        with pytest.raises(RuntimeError):
            trends_scan.fetch_trending_candidates(geo="FR", limit=20)


def test_fetch_trending_candidates_applies_product_filter(monkeypatch):
    """Les termes rejetes par le filtre produit ne doivent jamais atteindre
    eBay/YouTube : ca economise aussi le quota YouTube (100 appels/jour,
    deja tendu, cf. memoire projet), pas seulement la precision."""
    ebay_calls = []

    def _tracking_ebay(term, **kwargs):
        ebay_calls.append(term)
        return 5

    monkeypatch.setattr(
        product_filter, "filter_product_terms", lambda terms: ["masque LED visage"]
    )
    with patch(
        "discovery.trends_scan.download_google_trends_rss",
        return_value=_fake_rss_results(["masque LED visage", "chaleur"]),
    ):
        monkeypatch.setattr(ebay, "fetch_listing_count", _tracking_ebay)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 0)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert ebay_calls == ["masque LED visage"]  # "chaleur" jamais interroge
    assert [c["phrase"] for c in candidates] == ["masque LED visage"]


def test_fetch_trending_candidates_degrades_when_product_filter_fails(monkeypatch):
    """Si Claude est indisponible (cle manquante, panne API...), discover ne
    doit pas se bloquer entierement : retombe sur l'ancien comportement
    (eBay/YouTube seuls, aucun terme pre-filtre)."""

    def _raise(terms):
        raise product_filter.ProductFilterError("simulated failure")

    monkeypatch.setattr(product_filter, "filter_product_terms", _raise)
    with patch(
        "discovery.trends_scan.download_google_trends_rss",
        return_value=_fake_rss_results(["led face mask"]),
    ):
        monkeypatch.setattr(ebay, "fetch_listing_count", lambda term, **kwargs: 42)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 0)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert len(candidates) == 1
    assert candidates[0]["phrase"] == "led face mask"
