import json
from datetime import datetime, timezone

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
    entry = data["watchlist"][0]
    assert entry["keyword"] == "test kw"
    # Meme avec l'echec eBay, le reste du calcul de convergence tourne normalement
    # (pas de valeur corrompue ou manquante a cause du try/except eBay).
    assert entry["trends_growth_pct"] == 0.0
    assert isinstance(entry["convergence_score"], (int, float))


def test_cmd_scan_reddit_succeeds_when_ebay_fails_for_one_keyword(tmp_path, monkeypatch):
    """Reddit et eBay sont deux blocs independants dans la boucle par mot-cle :
    un echec eBay ne doit pas empecher Reddit de tourner normalement pour ce
    meme mot-cle. Contrairement a `_patch_common`, ce test active vraiment
    Reddit (au lieu de le desactiver via KeyError) pour prouver que les deux
    sources ne sont pas couplees (par ex. par un futur refactor qui les
    envelopperait dans un seul try/except)."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(google_trends, "fetch_interest_over_time", lambda *a, **k: [])

    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())
    mock_posts = [
        {
            "post_id": "p1",
            "subreddit": "gadgets",
            "title": "test post",
            "score": 50,
            "num_comments": 5,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "url": "https://reddit.com/r/gadgets/p1",
        }
    ]
    monkeypatch.setattr(reddit_collector, "search_keyword", lambda *a, **k: mock_posts)

    monkeypatch.setattr(ebay, "get_app_token", lambda: "fake-token")

    def _flaky_fetch(keyword, **kwargs):
        raise ebay.EbayError("simulated failure")

    monkeypatch.setattr(ebay, "fetch_listing_count", _flaky_fetch)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    entry = data["watchlist"][0]
    assert entry["ebay_growth_pct"] == 0.0
    assert entry["reddit_post_count"] == 1
    assert entry["reddit_avg_score"] == 50.0


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


def test_cmd_scan_ebay_growth_survives_two_scans_into_signals_json(tmp_path, monkeypatch):
    """Bout en bout : deux `cmd_scan` avec des comptages eBay differents sur deux
    dates differentes doivent produire un ebay_growth_pct NON NUL dans le
    signals.json ecrit sur disque, et ce signal doit compter dans sources_count
    (seuil ebay_growth_pct=20 dans _base_watchlist, largement depasse par une
    croissance de +100%). Aucun test existant ne fait tourner cmd_scan deux fois
    de suite avec des dates eBay differentes pour verifier ca."""
    _patch_common(tmp_path, monkeypatch)
    monkeypatch.setattr(ebay, "get_app_token", lambda: "fake-token")

    class _FrozenDatetime(datetime):
        """Sous-classe de datetime dont on peut piloter la valeur de now() ;
        remplace cli.datetime en entier, car cli.py fait
        `from datetime import datetime, timezone` (le nom `datetime` est donc
        un attribut du module cli, patchable directement avec monkeypatch)."""

        _current = datetime(2026, 8, 18, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._current

    monkeypatch.setattr(cli, "datetime", _FrozenDatetime)

    _FrozenDatetime._current = datetime(2026, 8, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(ebay, "fetch_listing_count", lambda keyword, **kwargs: 100)
    cli.cmd_scan(_base_watchlist())

    _FrozenDatetime._current = datetime(2026, 8, 19, tzinfo=timezone.utc)
    monkeypatch.setattr(ebay, "fetch_listing_count", lambda keyword, **kwargs: 200)
    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    entry = data["watchlist"][0]
    assert entry["ebay_growth_pct"] == 100.0
    # Trends (donnees vides) et Reddit (credentials absentes) ne peuvent pas
    # contribuer dans ce test : la seule source qui peut faire passer
    # sources_count a 1 est eBay, ce qui prouve que le signal eBay est bien
    # pris en compte par compute_convergence a partir des deux snapshots ecrits.
    assert entry["sources_count"] == 1
