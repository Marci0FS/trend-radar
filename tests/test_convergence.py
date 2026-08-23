from datetime import datetime, timedelta, timezone

from storage import db
from scoring.convergence import compute_convergence

THRESHOLDS = {
    "trends_growth_pct": 20,
    "reddit_min_posts": 3,
    "reddit_min_avg_score": 10,
    "ebay_growth_pct": 20,
    "aliexpress_growth_pct": 20,
    "youtube_growth_pct": 20,
}


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def _recent_utc() -> str:
    """Horodatage a l'interieur de la fenetre glissante de 7 jours de
    compute_convergence, quelle que soit la date d'execution du test
    (contrairement a une date codee en dur, qui finit par sortir de la
    fenetre au fil du temps reel)."""
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def test_compute_convergence_zero_sources(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit calme", "test")
    result = compute_convergence(conn, kid, THRESHOLDS)
    assert result["sources_count"] == 0
    conn.close()


def test_compute_convergence_trends_and_ebay_agree_as_two_sources(tmp_path, monkeypatch):
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
    assert result["details"]["signals_detected"]["aliexpress"] is False
    conn.close()


def test_compute_convergence_ebay_below_threshold_not_counted(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit stable", "test")
    db.insert_ebay_snapshot(conn, kid, "2026-08-13", 100, "EBAY_FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-14", 105, "EBAY_FR")
    result = compute_convergence(conn, kid, THRESHOLDS)
    assert result["details"]["signals_detected"]["ebay"] is False
    conn.close()


def test_compute_convergence_default_growth_windows_match_historical_hardcoded_values(tmp_path, monkeypatch):
    """Trends=7j, eBay/AliExpress/YouTube=1j par defaut, meme sans passer
    growth_windows explicitement : aucun changement de comportement pour
    les appelants existants (cli.py sans mise a jour, anciens tests)."""
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit tendance", "test")
    db.insert_ebay_snapshot(conn, kid, "2026-08-13", 100, "EBAY_FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-14", 200, "EBAY_FR")
    result = compute_convergence(conn, kid, THRESHOLDS)
    assert result["details"]["signals_detected"]["ebay"] is True
    conn.close()


def test_compute_convergence_growth_windows_are_configurable_per_source(tmp_path, monkeypatch):
    """La fenetre de comparaison par source doit etre pilotable via le
    parametre growth_windows, pas figee en dur dans le code (finding #2
    de la review Omniroute du 2026-08-22)."""
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit tendance", "test")
    # Seulement 2 snapshots eBay : suffisant pour window_days=1 (defaut),
    # insuffisant pour window_days=7 (il en faudrait 14, growth_pct renvoie
    # alors 0.0 faute d'historique).
    db.insert_ebay_snapshot(conn, kid, "2026-08-13", 100, "EBAY_FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-14", 200, "EBAY_FR")

    result = compute_convergence(conn, kid, THRESHOLDS, growth_windows={"ebay": 7})

    assert result["details"]["ebay_growth_pct"] == 0.0
    assert result["details"]["signals_detected"]["ebay"] is False
    conn.close()


def test_compute_convergence_aliexpress_growth_detected(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit aliexpress", "test")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-13", 100, "FR")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-14", 200, "FR")
    result = compute_convergence(conn, kid, THRESHOLDS)
    assert result["details"]["signals_detected"]["aliexpress"] is True
    assert result["details"]["aliexpress_growth_pct"] == 100.0
    conn.close()


def test_compute_convergence_aliexpress_below_threshold_not_counted(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit stable aliexpress", "test")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-13", 100, "FR")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-14", 105, "FR")
    result = compute_convergence(conn, kid, THRESHOLDS)
    assert result["details"]["signals_detected"]["aliexpress"] is False
    conn.close()


def test_compute_convergence_three_of_four_sources_agree(tmp_path, monkeypatch):
    """Verifie que sources_count peut atteindre 3 (le nouveau seuil FORT,
    verifie au niveau cli.py write_report dans Task 4) quand Trends, eBay
    et AliExpress sont tous les trois au-dessus de leur seuil, sans Reddit."""
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit triple signal", "test")

    trends_points = [(f"2026-08-{d:02d}", 10 if d <= 7 else 50) for d in range(1, 15)]
    db.insert_trends_snapshots(conn, kid, trends_points, "FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-13", 100, "EBAY_FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-14", 200, "EBAY_FR")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-13", 100, "FR")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-14", 200, "FR")

    result = compute_convergence(conn, kid, THRESHOLDS)

    assert result["sources_count"] == 3
    conn.close()


def test_compute_convergence_all_four_sources_agree(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit quadruple signal", "test")

    trends_points = [(f"2026-08-{d:02d}", 10 if d <= 7 else 50) for d in range(1, 15)]
    db.insert_trends_snapshots(conn, kid, trends_points, "FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-13", 100, "EBAY_FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-14", 200, "EBAY_FR")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-13", 100, "FR")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-14", 200, "FR")
    db.insert_reddit_posts(conn, kid, [
        {
            "post_id": f"p{i}", "subreddit": "test", "title": "t", "score": 50,
            "num_comments": 1, "created_utc": _recent_utc(), "url": "https://x",
        }
        for i in range(5)
    ])

    result = compute_convergence(conn, kid, THRESHOLDS)

    assert result["sources_count"] == 4
    conn.close()


def test_compute_convergence_youtube_growth_detected(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit youtube", "test")
    db.insert_youtube_snapshot(conn, kid, "2026-08-18", 10000)
    db.insert_youtube_snapshot(conn, kid, "2026-08-19", 20000)
    result = compute_convergence(conn, kid, THRESHOLDS)
    assert result["details"]["signals_detected"]["youtube"] is True
    assert result["details"]["youtube_growth_pct"] == 100.0
    conn.close()


def test_compute_convergence_youtube_below_threshold_not_counted(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit stable youtube", "test")
    db.insert_youtube_snapshot(conn, kid, "2026-08-18", 10000)
    db.insert_youtube_snapshot(conn, kid, "2026-08-19", 10500)
    result = compute_convergence(conn, kid, THRESHOLDS)
    assert result["details"]["signals_detected"]["youtube"] is False
    conn.close()


def test_compute_convergence_reddit_post_outside_window_not_counted(tmp_path, monkeypatch):
    """Regression : un post juste hors de la fenetre glissante de 7 jours
    (8 jours dans le passe) ne doit jamais compter dans reddit_count,
    contrairement a une date codee en dur qui finit par sortir de la
    fenetre au fil du temps reel sans que le test le detecte."""
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit reddit perime", "test")
    old_utc = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    db.insert_reddit_posts(conn, kid, [
        {
            "post_id": f"p{i}", "subreddit": "test", "title": "t", "score": 50,
            "num_comments": 1, "created_utc": old_utc, "url": "https://x",
        }
        for i in range(5)
    ])

    result = compute_convergence(conn, kid, THRESHOLDS)

    assert result["details"]["reddit_post_count"] == 0
    assert result["details"]["signals_detected"]["reddit"] is False
    conn.close()


def test_compute_convergence_all_five_sources_agree(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "produit cinq signaux", "test")

    trends_points = [(f"2026-08-{d:02d}", 10 if d <= 7 else 50) for d in range(1, 15)]
    db.insert_trends_snapshots(conn, kid, trends_points, "FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-13", 100, "EBAY_FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-14", 200, "EBAY_FR")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-13", 100, "FR")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-14", 200, "FR")
    db.insert_youtube_snapshot(conn, kid, "2026-08-13", 10000)
    db.insert_youtube_snapshot(conn, kid, "2026-08-14", 20000)
    db.insert_reddit_posts(conn, kid, [
        {
            "post_id": f"p{i}", "subreddit": "test", "title": "t", "score": 50,
            "num_comments": 1, "created_utc": _recent_utc(), "url": "https://x",
        }
        for i in range(5)
    ])

    result = compute_convergence(conn, kid, THRESHOLDS)

    assert result["sources_count"] == 5
    conn.close()
