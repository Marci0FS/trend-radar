from storage import db


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def test_insert_and_get_ebay_snapshot_series(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "led face mask", "gadgets")
    db.insert_ebay_snapshot(conn, kid, "2026-08-18", 120, "EBAY_FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-19", 150, "EBAY_FR")
    series = db.get_ebay_snapshot_series(conn, kid)
    assert series == [("2026-08-18", 120), ("2026-08-19", 150)]
    conn.close()


def test_insert_ebay_snapshot_ignores_duplicate_date(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "led face mask", "gadgets")
    db.insert_ebay_snapshot(conn, kid, "2026-08-18", 120, "EBAY_FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-18", 999, "EBAY_FR")
    series = db.get_ebay_snapshot_series(conn, kid)
    assert series == [("2026-08-18", 120)]
    conn.close()
