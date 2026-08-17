from collectors import reddit as reddit_collector
from discovery import reddit_scan
from storage import db as storage_db

import cli


def test_cmd_discover_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
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
