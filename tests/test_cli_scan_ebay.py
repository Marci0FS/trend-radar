import json

from collectors import ebay
from collectors import google_trends
from collectors import reddit as reddit_collector
from storage import db as storage_db

import cli


def _base_watchlist():
    return {
        "categories": {"gadgets": {"keywords": ["test kw"], "subreddits": []}},
        "thresholds": {
            "trends_growth_pct": 20,
            "reddit_min_posts": 3,
            "reddit_min_avg_score": 10,
            "ebay_growth_pct": 20,
        },
    }


def _patch_common(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(google_trends, "fetch_interest_over_time", lambda *a, **k: [])

    def _raise_reddit_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_reddit_key_error)


def test_cmd_scan_skips_ebay_when_credentials_missing(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    def _raise_ebay_key_error():
        raise KeyError("EBAY_CLIENT_ID")

    monkeypatch.setattr(ebay, "get_app_token", _raise_ebay_key_error)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    assert data["watchlist"][0]["ebay_growth_pct"] == 0.0


def test_cmd_scan_continues_when_ebay_fails_for_one_keyword(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    monkeypatch.setattr(ebay, "get_app_token", lambda: "fake-token")

    def _flaky_fetch(keyword, **kwargs):
        raise ebay.EbayError("simulated failure")

    monkeypatch.setattr(ebay, "fetch_listing_count", _flaky_fetch)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    assert len(data["watchlist"]) == 1
    assert data["watchlist"][0]["keyword"] == "test kw"


def test_cmd_scan_stores_ebay_snapshot_when_available(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    monkeypatch.setattr(ebay, "get_app_token", lambda: "fake-token")
    monkeypatch.setattr(ebay, "fetch_listing_count", lambda keyword, **kwargs: 4213)

    cli.cmd_scan(_base_watchlist())

    conn = storage_db.get_connection()
    kid = storage_db.get_or_create_keyword(conn, "test kw", "gadgets")
    series = storage_db.get_ebay_snapshot_series(conn, kid)
    conn.close()
    assert series[-1][1] == 4213
