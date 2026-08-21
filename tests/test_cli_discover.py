from collectors import google_trends, reddit as reddit_collector
from discovery import promote, reddit_scan, trends_scan
from storage import db as storage_db

import cli


def test_cmd_discover_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(trends_scan, "fetch_trending_candidates", lambda **kwargs: [])
    report_path = tmp_path / "discovery_report.md"
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", report_path)

    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())
    monkeypatch.setattr(
        reddit_scan,
        "scan_subreddits",
        lambda reddit, subreddits, post_limit: [
            {"subreddit": "gadgets", "title": "This LED face mask is amazing"},
            {"subreddit": "gadgets", "title": "I love my LED face mask so much"},
        ],
    )

    watchlist = {
        "discovery": {
            "subreddits": ["gadgets"],
            "post_limit": 10,
            "min_mentions": 1,
            "min_growth_pct": 0,
        }
    }

    cli.cmd_discover(watchlist)

    assert report_path.exists()
    assert "led face mask" in report_path.read_text()


def test_cmd_discover_skips_without_reddit_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(trends_scan, "fetch_trending_candidates", lambda **kwargs: [])

    def _raise_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_key_error)

    cli.cmd_discover({"discovery": {"subreddits": ["gadgets"]}})

    captured = capsys.readouterr()
    assert "credentials manquants" in captured.out


def test_cmd_promote_adds_keyword_to_watchlist(tmp_path, monkeypatch):
    watchlist_file = tmp_path / "watchlist.yaml"
    watchlist_file.write_text(
        'categories:\n'
        '  gadgets:\n'
        '    keywords:\n'
        '      - "mini projecteur"\n'
        '    subreddits:\n'
        '      - gadgets\n'
    )
    monkeypatch.setattr(cli, "WATCHLIST_PATH", watchlist_file)

    cli.cmd_promote("chargeur solaire portable", "gadgets")

    content = watchlist_file.read_text()
    assert '"chargeur solaire portable"' in content


def test_cmd_promote_skips_duplicate(tmp_path, monkeypatch, capsys):
    watchlist_file = tmp_path / "watchlist.yaml"
    watchlist_file.write_text(
        'categories:\n'
        '  gadgets:\n'
        '    keywords:\n'
        '      - "mini projecteur"\n'
        '    subreddits:\n'
        '      - gadgets\n'
    )
    monkeypatch.setattr(cli, "WATCHLIST_PATH", watchlist_file)

    cli.cmd_promote("mini projecteur", "gadgets")

    captured = capsys.readouterr()
    assert "deja" in captured.out
    assert content_unchanged(watchlist_file)


def content_unchanged(path):
    return path.read_text().count("mini projecteur") == 1


def test_cmd_promote_aborts_write_when_validation_guard_fails(tmp_path, monkeypatch, capsys):
    """Filet de securite (discovery finding #1) : si le texte YAML genere par
    add_keyword_to_yaml_text s'avere invalide ou n'a pas correctement place la
    phrase, cmd_promote doit s'arreter SANS ecrire sur le fichier watchlist.
    Le fix json.dumps() rend ce cas quasi-impossible en pratique pour des
    phrases normales ; ce test verifie que le garde-fou lui-meme fonctionne,
    en simulant une generation de YAML defaillante."""
    original_text = (
        'categories:\n'
        '  gadgets:\n'
        '    keywords:\n'
        '      - "mini projecteur"\n'
        '    subreddits:\n'
        '      - gadgets\n'
    )
    watchlist_file = tmp_path / "watchlist.yaml"
    watchlist_file.write_text(original_text)
    monkeypatch.setattr(cli, "WATCHLIST_PATH", watchlist_file)

    # Simule une generation de YAML cassee (ex: regression future dans promote.py)
    monkeypatch.setattr(
        promote, "add_keyword_to_yaml_text", lambda text, phrase, category: "categories: [broken"
    )

    cli.cmd_promote("nouveau produit", "gadgets")

    captured = capsys.readouterr()
    assert "Erreur" in captured.out
    assert watchlist_file.read_text() == original_text


def test_cmd_promote_aborts_write_when_phrase_lands_wrong_category(tmp_path, monkeypatch, capsys):
    """Meme garde-fou, mais pour le cas ou le YAML genere est valide mais la
    phrase n'a pas atterri au bon endroit (ex: categorie absente du dict)."""
    original_text = (
        'categories:\n'
        '  gadgets:\n'
        '    keywords:\n'
        '      - "mini projecteur"\n'
        '    subreddits:\n'
        '      - gadgets\n'
    )
    watchlist_file = tmp_path / "watchlist.yaml"
    watchlist_file.write_text(original_text)
    monkeypatch.setattr(cli, "WATCHLIST_PATH", watchlist_file)

    # YAML valide mais qui n'ajoute rien a la categorie 'gadgets' (bug simule)
    monkeypatch.setattr(
        promote, "add_keyword_to_yaml_text", lambda text, phrase, category: text
    )

    cli.cmd_promote("nouveau produit", "gadgets")

    captured = capsys.readouterr()
    assert "Erreur" in captured.out
    assert watchlist_file.read_text() == original_text


def test_cmd_discover_never_calls_legacy_per_keyword_google_trends(tmp_path, monkeypatch):
    """Discovery finding #7, mis a jour pour ce plan : `discover` ne doit
    jamais interroger le collecteur Google Trends historique
    (collectors.google_trends.fetch_interest_over_time), qui suit un
    mot-cle deja connu dans le temps -- inadapte a la decouverte sans
    mot-cle. Depuis ce plan, `discover` appelle bien Google Trends, mais
    via discovery.trends_scan (realtime_trending_searches, sans mot-cle
    fourni a l'avance), jamais via fetch_interest_over_time. `growth_pct`
    est legitimement appele par velocity.find_candidates."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(trends_scan, "fetch_trending_candidates", lambda **kwargs: [])
    report_path = tmp_path / "discovery_report.md"
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", report_path)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "cmd_discover ne doit jamais appeler le collecteur Google Trends "
            "historique (fetch_interest_over_time)"
        )

    monkeypatch.setattr(google_trends, "fetch_interest_over_time", _fail_if_called)

    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())
    monkeypatch.setattr(
        reddit_scan,
        "scan_subreddits",
        lambda reddit, subreddits, post_limit: [
            {"subreddit": "gadgets", "title": "This LED face mask is amazing"},
            {"subreddit": "gadgets", "title": "I love my LED face mask so much"},
        ],
    )

    watchlist = {
        "discovery": {
            "subreddits": ["gadgets"],
            "post_limit": 10,
            "min_mentions": 1,
            "min_growth_pct": 0,
        }
    }

    cli.cmd_discover(watchlist)

    assert report_path.exists()
    assert "led face mask" in report_path.read_text()


def test_cmd_discover_includes_google_trends_candidates_when_reddit_unavailable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", tmp_path / "discovery_report.md")

    def _raise_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_key_error)

    fake_candidate = {
        "phrase": "led face mask",
        "source": "google_trends",
        "mention_count": 0,
        "growth_pct": 0,
        "ebay_signal": True,
        "youtube_signal": False,
    }
    monkeypatch.setattr(trends_scan, "fetch_trending_candidates", lambda **kwargs: [fake_candidate])

    cli.cmd_discover({"discovery": {"subreddits": []}})

    import json

    data = json.loads((tmp_path / "signals.json").read_text())
    phrases = [c["phrase"] for c in data["discovery"]]
    assert "led face mask" in phrases
    sources = {c["phrase"]: c["source"] for c in data["discovery"]}
    assert sources["led face mask"] == "google_trends"


def test_cmd_discover_continues_when_google_trends_fails(tmp_path, monkeypatch):
    """Un echec Google Trends ne doit pas empecher les candidats Reddit
    d'apparaitre dans le meme run (independance des deux sources de
    decouverte, meme principe que cmd_scan)."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", tmp_path / "discovery_report.md")

    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())
    monkeypatch.setattr(
        reddit_scan,
        "scan_subreddits",
        lambda reddit, subreddits, post_limit: [
            {"subreddit": "gadgets", "title": "This LED face mask is amazing"},
            {"subreddit": "gadgets", "title": "I love my LED face mask so much"},
        ],
    )

    def _raise_runtime_error(**kwargs):
        raise RuntimeError("simulated Google Trends failure")

    monkeypatch.setattr(trends_scan, "fetch_trending_candidates", _raise_runtime_error)

    watchlist = {
        "discovery": {
            "subreddits": ["gadgets"],
            "post_limit": 10,
            "min_mentions": 1,
            "min_growth_pct": 0,
        }
    }

    cli.cmd_discover(watchlist)  # ne doit pas lever d'exception

    assert "led face mask" in (tmp_path / "discovery_report.md").read_text()


def test_cmd_discover_one_trending_term_failure_does_not_lose_reddit_candidates(
    tmp_path, monkeypatch
):
    """Verifie que la fusion des deux listes garde les candidats Reddit
    meme quand Google Trends renvoie une liste vide (aucun candidat
    confirme, sans que ce soit une erreur)."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", tmp_path / "discovery_report.md")

    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())
    monkeypatch.setattr(
        reddit_scan,
        "scan_subreddits",
        lambda reddit, subreddits, post_limit: [
            {"subreddit": "gadgets", "title": "This LED face mask is amazing"},
            {"subreddit": "gadgets", "title": "I love my LED face mask so much"},
        ],
    )
    monkeypatch.setattr(trends_scan, "fetch_trending_candidates", lambda **kwargs: [])

    watchlist = {
        "discovery": {
            "subreddits": ["gadgets"],
            "post_limit": 10,
            "min_mentions": 1,
            "min_growth_pct": 0,
        }
    }

    cli.cmd_discover(watchlist)

    import json

    data = json.loads((tmp_path / "signals.json").read_text())
    phrases = [c["phrase"] for c in data["discovery"]]
    assert "led face mask" in phrases
