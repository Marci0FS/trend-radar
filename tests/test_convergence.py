from storage import db
from scoring.convergence import compute_convergence

THRESHOLDS = {
    "trends_growth_pct": 20,
    "reddit_min_posts": 3,
    "reddit_min_avg_score": 10,
    "ebay_growth_pct": 20,
}


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def test_compute_convergence_zero_sources(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit calme", "test")
    result = compute_convergence(conn, kid, THRESHOLDS)
    assert result["sources_count"] == 0
    conn.close()


def test_compute_convergence_trends_and_ebay_reach_fort_without_reddit(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit tendance", "test")

    trends_points = [(f"2026-08-{d:02d}", 10 if d <= 7 else 50) for d in range(1, 15)]
    db.insert_trends_snapshots(conn, kid, trends_points, "FR")

    db.insert_ebay_snapshot(conn, kid, "2026-08-13", 100, "EBAY_FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-14", 200, "EBAY_FR")

    result = compute_convergence(conn, kid, THRESHOLDS)

    assert result["sources_count"] == 2
    assert result["details"]["signals_detected"]["google_trends"] is True
    assert result["details"]["signals_detected"]["ebay"] is True
    assert result["details"]["signals_detected"]["reddit"] is False
    conn.close()


def test_compute_convergence_ebay_below_threshold_not_counted(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit stable", "test")
    db.insert_ebay_snapshot(conn, kid, "2026-08-13", 100, "EBAY_FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-14", 105, "EBAY_FR")
    result = compute_convergence(conn, kid, THRESHOLDS)
    assert result["details"]["signals_detected"]["ebay"] is False
    conn.close()
