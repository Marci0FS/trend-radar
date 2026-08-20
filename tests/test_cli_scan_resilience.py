import json

from collectors import aliexpress
from collectors import google_trends
from collectors import reddit as reddit_collector
from storage import db as storage_db

import cli


def test_cmd_scan_skips_keyword_on_trends_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    def _flaky_fetch(keyword, **kwargs):
        if keyword == "bad kw":
            raise RuntimeError("Echec fetch Google Trends pour 'bad kw'")
        return []

    monkeypatch.setattr(google_trends, "fetch_interest_over_time", _flaky_fetch)

    def _raise_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_key_error)

    watchlist = {
        "categories": {
            "gadgets": {"keywords": ["bad kw", "good kw"], "subreddits": []},
        },
        "thresholds": {"trends_growth_pct": 20, "reddit_min_posts": 3, "reddit_min_avg_score": 10, "ebay_growth_pct": 20, "aliexpress_growth_pct": 20, "youtube_growth_pct": 20},
    }

    cli.cmd_scan(watchlist)

    data = json.loads((tmp_path / "signals.json").read_text())
    keywords_in_results = [r["keyword"] for r in data["watchlist"]]
    assert "good kw" in keywords_in_results
    assert "bad kw" not in keywords_in_results


def test_cmd_scan_does_not_overwrite_signals_json_with_empty_watchlist_when_all_keywords_fail(
    tmp_path, monkeypatch
):
    """Si TOUTES les sources echouent pour TOUS les mots-cles (ex: Google
    Trends rate-limite + toutes les autres sources desactivees), le scan ne
    doit jamais publier une watchlist vide qui ecraserait les dernieres
    donnees valides connues sur le dashboard public."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    signals_path = tmp_path / "signals.json"
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", signals_path)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    existing_data = {
        "watchlist": [
            {
                "keyword": "old kw",
                "category": "gadgets",
                "convergence_score": 1.0,
                "sources_count": 1,
                "trends_growth_pct": 5.0,
                "reddit_post_count": 0,
                "reddit_avg_score": 0,
                "ebay_growth_pct": 0.0,
                "aliexpress_growth_pct": 0.0,
                "youtube_growth_pct": 0.0,
            }
        ],
        "discovery": [],
        "last_updated": "2026-08-18T00:00:00+00:00",
    }
    signals_path.write_text(json.dumps(existing_data))

    def _always_fail(keyword, **kwargs):
        raise RuntimeError(f"Echec fetch Google Trends pour '{keyword}'")

    monkeypatch.setattr(google_trends, "fetch_interest_over_time", _always_fail)

    def _raise_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_key_error)

    watchlist = {
        "categories": {"gadgets": {"keywords": ["kw1", "kw2"], "subreddits": []}},
        "thresholds": {
            "trends_growth_pct": 20,
            "reddit_min_posts": 3,
            "reddit_min_avg_score": 10,
            "ebay_growth_pct": 20,
            "aliexpress_growth_pct": 20,
            "youtube_growth_pct": 20,
        },
    }

    cli.cmd_scan(watchlist)

    data = json.loads(signals_path.read_text())
    assert len(data["watchlist"]) == 1
    assert data["watchlist"][0]["keyword"] == "old kw"


def test_cmd_scan_continues_when_reddit_search_fails_for_one_keyword(tmp_path, monkeypatch):
    """Reproduit un incident reel : PRAW execute la vraie requete HTTP au
    moment de l'iteration paresseuse sur le generateur retourne par
    .search(), pas au moment de l'appel lui-meme — une authentification
    invalide (401) levait donc une exception brute depuis l'interieur de
    la boucle for de collectors.reddit.search_keyword, qui n'etait
    enveloppee par AUCUN try/except dans cli.py (contrairement a
    Trends/eBay/AliExpress/YouTube). Un seul mot-cle en echec plantait
    tout le scan."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(google_trends, "fetch_interest_over_time", lambda *a, **k: [])

    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())

    def _flaky_search(reddit, keyword, subreddits, **kwargs):
        raise reddit_collector.RedditError("simulated 401")

    monkeypatch.setattr(reddit_collector, "search_keyword", _flaky_search)

    watchlist = {
        "categories": {"gadgets": {"keywords": ["kw1"], "subreddits": []}},
        "thresholds": {
            "trends_growth_pct": 20,
            "reddit_min_posts": 3,
            "reddit_min_avg_score": 10,
            "ebay_growth_pct": 20,
            "aliexpress_growth_pct": 20,
            "youtube_growth_pct": 20,
        },
    }

    cli.cmd_scan(watchlist)  # ne doit pas lever d'exception

    data = json.loads((tmp_path / "signals.json").read_text())
    assert data["watchlist"][0]["keyword"] == "kw1"


def test_cmd_scan_skips_aliexpress_when_a_credential_is_an_empty_string(tmp_path, monkeypatch):
    """Meme classe de bug que le pre-check YouTube corrige precedemment :
    une variable presente mais vide (ex: ALIEXPRESS_APP_KEY= sans valeur,
    exactement l'etat par defaut de .env.example) ne doit pas etre traitee
    comme 'credentials presentes' — sinon le scan tente un vrai appel API
    voue a l'echec (observe en production : erreur 'InvalidAppKey')
    au lieu d'un skip propre. get_access_token() n'est PAS mocke ici : on
    veut verifier son propre comportement face a des variables vides."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(google_trends, "fetch_interest_over_time", lambda *a, **k: [])
    monkeypatch.setattr(aliexpress, "_cached_access_token", None)

    def _raise_reddit_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_reddit_key_error)

    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "")
    monkeypatch.setenv("ALIEXPRESS_REFRESH_TOKEN", "")

    watchlist = {
        "categories": {"gadgets": {"keywords": ["kw1"], "subreddits": []}},
        "thresholds": {
            "trends_growth_pct": 20,
            "reddit_min_posts": 3,
            "reddit_min_avg_score": 10,
            "ebay_growth_pct": 20,
            "aliexpress_growth_pct": 20,
            "youtube_growth_pct": 20,
        },
    }

    cli.cmd_scan(watchlist)

    data = json.loads((tmp_path / "signals.json").read_text())
    assert data["watchlist"][0]["aliexpress_growth_pct"] == 0.0
