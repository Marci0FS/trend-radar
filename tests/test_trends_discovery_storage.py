from storage import db


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def test_insert_trends_discovery_candidate(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    db.insert_trends_discovery_candidate(conn, "led face mask", "2026-08-20", True, False)
    row = conn.execute(
        "SELECT term, date, ebay_signal, youtube_signal FROM trends_discovery_candidates"
    ).fetchone()
    assert row["term"] == "led face mask"
    assert row["date"] == "2026-08-20"
    assert row["ebay_signal"] == 1
    assert row["youtube_signal"] == 0
    conn.close()


def test_insert_trends_discovery_candidate_ignores_duplicate_term_and_date(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    db.insert_trends_discovery_candidate(conn, "led face mask", "2026-08-20", True, False)
    db.insert_trends_discovery_candidate(conn, "led face mask", "2026-08-20", False, True)
    rows = conn.execute("SELECT * FROM trends_discovery_candidates").fetchall()
    assert len(rows) == 1
    assert rows[0]["ebay_signal"] == 1  # la 1ere insertion gagne, INSERT OR IGNORE
    conn.close()
