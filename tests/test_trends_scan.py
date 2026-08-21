from unittest.mock import patch

import pytest

from collectors import ebay, youtube
from discovery import trends_scan


def _fake_rss_results(terms):
    return [{"trend": t} for t in terms]


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
