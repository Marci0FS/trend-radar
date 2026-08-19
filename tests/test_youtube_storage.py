from storage import db


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def test_insert_and_get_youtube_snapshot_series(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "led face mask", "gadgets")
    db.insert_youtube_snapshot(conn, kid, "2026-08-19", 15000)
    db.insert_youtube_snapshot(conn, kid, "2026-08-20", 22000)
    series = db.get_youtube_snapshot_series(conn, kid)
    assert series == [("2026-08-19", 15000), ("2026-08-20", 22000)]
    conn.close()


def test_insert_youtube_snapshot_ignores_duplicate_date(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "led face mask", "gadgets")
    db.insert_youtube_snapshot(conn, kid, "2026-08-19", 15000)
    db.insert_youtube_snapshot(conn, kid, "2026-08-19", 99999)
    series = db.get_youtube_snapshot_series(conn, kid)
    assert series == [("2026-08-19", 15000)]
    conn.close()
