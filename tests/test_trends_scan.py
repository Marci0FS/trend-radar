from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from collectors import ebay, youtube
from discovery import trends_scan


def _fake_trending_df(titles):
    return pd.DataFrame({"title": titles})


def test_fetch_trending_candidates_confirms_term_with_ebay_signal(monkeypatch):
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.return_value = _fake_trending_df(["led face mask"])

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
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
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.return_value = _fake_trending_df(["mini projecteur"])

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
        monkeypatch.setattr(ebay, "fetch_listing_count", lambda term, **kwargs: 0)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 1500)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert len(candidates) == 1
    assert candidates[0]["ebay_signal"] is False
    assert candidates[0]["youtube_signal"] is True
    assert candidates[0]["ebay_count"] == 0
    assert candidates[0]["youtube_views"] == 1500


def test_fetch_trending_candidates_discards_term_with_no_signal(monkeypatch):
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.return_value = _fake_trending_df(["celebrity gossip"])

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
        monkeypatch.setattr(ebay, "fetch_listing_count", lambda term, **kwargs: 0)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 0)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert candidates == []


def test_fetch_trending_candidates_limits_to_first_n_terms(monkeypatch):
    titles = [f"term {i}" for i in range(30)]
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.return_value = _fake_trending_df(titles)

    call_count = {"ebay": 0}

    def _counting_ebay(term, **kwargs):
        call_count["ebay"] += 1
        return 1

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
        monkeypatch.setattr(ebay, "fetch_listing_count", _counting_ebay)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 0)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert call_count["ebay"] == 20
    assert len(candidates) == 20


def test_fetch_trending_candidates_one_term_failure_does_not_affect_others(monkeypatch):
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.return_value = _fake_trending_df(
        ["flaky term", "good term"]
    )

    def _flaky_ebay(term, **kwargs):
        if term == "flaky term":
            raise ebay.EbayError("simulated failure")
        return 5

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
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
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.return_value = _fake_trending_df(["led face mask"])

    def _raise_key_error(term, **kwargs):
        raise KeyError("EBAY_CLIENT_ID")

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
        monkeypatch.setattr(ebay, "fetch_listing_count", _raise_key_error)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 100)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert len(candidates) == 1
    assert candidates[0]["ebay_signal"] is False
    assert candidates[0]["youtube_signal"] is True
    assert candidates[0]["ebay_count"] == 0
    assert candidates[0]["youtube_views"] == 100


def test_fetch_trending_candidates_raises_runtime_error_on_google_trends_failure(monkeypatch):
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.side_effect = RuntimeError("boom")

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
        monkeypatch.setattr(trends_scan.time, "sleep", lambda seconds: None)
        with pytest.raises(RuntimeError):
            trends_scan.fetch_trending_candidates(geo="FR", limit=20)
