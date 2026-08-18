import json

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
        "thresholds": {"trends_growth_pct": 20, "reddit_min_posts": 3, "reddit_min_avg_score": 10},
    }

    cli.cmd_scan(watchlist)

    data = json.loads((tmp_path / "signals.json").read_text())
    keywords_in_results = [r["keyword"] for r in data["watchlist"]]
    assert "good kw" in keywords_in_results
    assert "bad kw" not in keywords_in_results
