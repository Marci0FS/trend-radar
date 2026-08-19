from storage import db


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def test_insert_and_get_aliexpress_snapshot_series(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "led face mask", "gadgets")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-18", 1200, "FR")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-19", 1500, "FR")
    series = db.get_aliexpress_snapshot_series(conn, kid)
    assert series == [("2026-08-18", 1200), ("2026-08-19", 1500)]
    conn.close()


def test_insert_aliexpress_snapshot_ignores_duplicate_date(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "led face mask", "gadgets")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-18", 1200, "FR")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-18", 9999, "FR")
    series = db.get_aliexpress_snapshot_series(conn, kid)
    assert series == [("2026-08-18", 1200)]
    conn.close()
