import json

import cli


def test_write_signals_json_creates_file(tmp_path, monkeypatch):
    json_path = tmp_path / "signals.json"
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", json_path)

    cli.write_signals_json("watchlist", [{"keyword": "test", "convergence_score": 5.0}])

    data = json.loads(json_path.read_text())
    assert data["watchlist"] == [{"keyword": "test", "convergence_score": 5.0}]
    assert data["discovery"] == []
    assert "last_updated" in data


def test_write_signals_json_preserves_other_section(tmp_path, monkeypatch):
    json_path = tmp_path / "signals.json"
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", json_path)

    cli.write_signals_json("watchlist", [{"keyword": "a"}])
    cli.write_signals_json("discovery", [{"phrase": "b"}])

    data = json.loads(json_path.read_text())
    assert data["watchlist"] == [{"keyword": "a"}]
    assert data["discovery"] == [{"phrase": "b"}]


def test_write_signals_json_tolerates_corrupted_file(tmp_path, monkeypatch):
    json_path = tmp_path / "signals.json"
    json_path.write_text("{not valid json")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", json_path)

    cli.write_signals_json("watchlist", [{"keyword": "a"}])

    data = json.loads(json_path.read_text())
    assert data["watchlist"] == [{"keyword": "a"}]
    assert data["discovery"] == []
