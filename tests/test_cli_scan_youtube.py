import json
from datetime import datetime, timezone

from collectors import aliexpress
from collectors import ebay
from collectors import google_trends
from collectors import reddit as reddit_collector
from collectors import youtube
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
            "aliexpress_growth_pct": 20,
            "youtube_growth_pct": 20,
        },
    }


def _patch_common(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(google_trends, "fetch_interest_over_time", lambda *a, **k: [])
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    def _raise_reddit_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_reddit_key_error)

    def _raise_ebay_key_error():
        raise KeyError("EBAY_CLIENT_ID")

    monkeypatch.setattr(ebay, "get_app_token", _raise_ebay_key_error)

    def _raise_aliexpress_key_error():
        raise KeyError("ALIEXPRESS_APP_KEY")

    monkeypatch.setattr(aliexpress, "get_access_token", _raise_aliexpress_key_error)


def test_cmd_scan_skips_youtube_when_credentials_missing(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    assert data["watchlist"][0]["youtube_growth_pct"] == 0.0


def test_cmd_scan_skips_youtube_when_api_key_is_empty_string(tmp_path, monkeypatch):
    """.env.example expedie YOUTUBE_API_KEY= (valeur vide) et le README dit de
    faire `cp .env.example .env` : un utilisateur qui n'a pas encore rempli sa
    cle se retrouve avec une variable d'env presente mais vide via
    python-dotenv. Le pre-check doit tester la valeur (truthiness), pas
    seulement la presence de la cle, sinon chaque mot-cle declenche un appel
    YouTube voue a l'echec au lieu d'un message clair unique en debut de scan."""
    _patch_common(tmp_path, monkeypatch)
    monkeypatch.setenv("YOUTUBE_API_KEY", "")

    def _fail_if_called(keyword, **kwargs):
        raise AssertionError("should not be called")

    monkeypatch.setattr(youtube, "fetch_recent_view_count", _fail_if_called)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    assert data["watchlist"][0]["youtube_growth_pct"] == 0.0


def test_cmd_scan_continues_when_youtube_fails_for_one_keyword(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    def _flaky_fetch(keyword, **kwargs):
        raise youtube.YouTubeError("simulated failure")

    monkeypatch.setattr(youtube, "fetch_recent_view_count", _flaky_fetch)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    assert len(data["watchlist"]) == 1
    entry = data["watchlist"][0]
    assert entry["keyword"] == "test kw"
    assert entry["trends_growth_pct"] == 0.0
    assert isinstance(entry["convergence_score"], (int, float))


def test_cmd_scan_ebay_succeeds_when_youtube_fails_for_one_keyword(tmp_path, monkeypatch):
    """eBay et YouTube sont deux blocs independants dans la boucle par
    mot-cle : un echec YouTube ne doit pas empecher eBay de tourner
    normalement pour ce meme mot-cle (meme preuve d'independance que pour
    les paires Reddit/eBay et eBay/AliExpress deja testees)."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(google_trends, "fetch_interest_over_time", lambda *a, **k: [])
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    def _raise_reddit_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_reddit_key_error)

    def _raise_aliexpress_key_error():
        raise KeyError("ALIEXPRESS_APP_KEY")

    monkeypatch.setattr(aliexpress, "get_access_token", _raise_aliexpress_key_error)

    monkeypatch.setattr(ebay, "get_app_token", lambda: "fake-ebay-token")
    monkeypatch.setattr(ebay, "fetch_listing_count", lambda keyword, **kwargs: 4213)

    def _flaky_fetch(keyword, **kwargs):
        raise youtube.YouTubeError("simulated failure")

    monkeypatch.setattr(youtube, "fetch_recent_view_count", _flaky_fetch)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    entry = data["watchlist"][0]
    assert entry["youtube_growth_pct"] == 0.0

    conn = storage_db.get_connection()
    kid = storage_db.get_or_create_keyword(conn, "test kw", "gadgets")
    series = storage_db.get_ebay_snapshot_series(conn, kid)
    conn.close()
    assert series[-1][1] == 4213


def test_cmd_scan_stores_youtube_snapshot_when_available(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda keyword: 15000)

    cli.cmd_scan(_base_watchlist())

    conn = storage_db.get_connection()
    kid = storage_db.get_or_create_keyword(conn, "test kw", "gadgets")
    series = storage_db.get_youtube_snapshot_series(conn, kid)
    conn.close()
    assert series[-1][1] == 15000


def test_cmd_scan_youtube_growth_survives_two_scans_into_signals_json(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    class _FrozenDatetime(datetime):
        _current = datetime(2026, 8, 18, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._current

    monkeypatch.setattr(cli, "datetime", _FrozenDatetime)

    _FrozenDatetime._current = datetime(2026, 8, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda keyword: 10000)
    cli.cmd_scan(_base_watchlist())

    _FrozenDatetime._current = datetime(2026, 8, 19, tzinfo=timezone.utc)
    monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda keyword: 20000)
    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    entry = data["watchlist"][0]
    assert entry["youtube_growth_pct"] == 100.0
    assert entry["sources_count"] == 1
