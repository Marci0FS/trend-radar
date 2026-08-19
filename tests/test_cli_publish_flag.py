import json
from unittest.mock import MagicMock

from collectors import google_trends
from collectors import reddit as reddit_collector
from discovery import reddit_scan
from storage import db as storage_db

import cli
import publish


def test_cmd_discover_writes_signals_json(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", tmp_path / "discovery_report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")

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
        "discovery": {"subreddits": ["gadgets"], "post_limit": 10, "min_mentions": 1, "min_growth_pct": 0}
    }
    cli.cmd_discover(watchlist)

    data = json.loads((tmp_path / "signals.json").read_text())
    assert any(c["phrase"] == "led face mask" for c in data["discovery"])


def test_cmd_discover_publishes_when_flag_set(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", tmp_path / "discovery_report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())
    monkeypatch.setattr(reddit_scan, "scan_subreddits", lambda reddit, subreddits, post_limit: [])

    mock_publish = MagicMock(return_value=True)
    monkeypatch.setattr(publish, "publish_json", mock_publish)

    cli.cmd_discover({"discovery": {"subreddits": []}}, publish_after=True)

    mock_publish.assert_called_once()


def test_cmd_discover_does_not_publish_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", tmp_path / "discovery_report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())
    monkeypatch.setattr(reddit_scan, "scan_subreddits", lambda reddit, subreddits, post_limit: [])

    mock_publish = MagicMock()
    monkeypatch.setattr(publish, "publish_json", mock_publish)

    cli.cmd_discover({"discovery": {"subreddits": []}})

    mock_publish.assert_not_called()


def test_cmd_scan_writes_signals_json_and_publishes(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    monkeypatch.setattr(google_trends, "fetch_interest_over_time", lambda *a, **k: [])

    def _raise_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_key_error)

    mock_publish = MagicMock(return_value=True)
    monkeypatch.setattr(publish, "publish_json", mock_publish)

    watchlist = {
        "categories": {"gadgets": {"keywords": ["test kw"], "subreddits": []}},
        "thresholds": {"trends_growth_pct": 20, "reddit_min_posts": 3, "reddit_min_avg_score": 10, "ebay_growth_pct": 20},
    }

    cli.cmd_scan(watchlist, publish_after=True)

    data = json.loads((tmp_path / "signals.json").read_text())
    assert data["watchlist"][0]["keyword"] == "test kw"
    mock_publish.assert_called_once()
