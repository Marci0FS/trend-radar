from storage import db
from discovery import velocity


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def test_find_candidates_detects_rising_phrase(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    db.insert_phrase_mentions(conn, [
        {"phrase": "led face mask", "subreddit": "gadgets", "mention_count": 3,
         "window_start": "2026-08-01T00:00:00", "window_end": "2026-08-01T00:00:00"},
    ])
    db.insert_phrase_mentions(conn, [
        {"phrase": "led face mask", "subreddit": "gadgets", "mention_count": 9,
         "window_start": "2026-08-08T00:00:00", "window_end": "2026-08-08T00:00:00"},
    ])
    candidates = velocity.find_candidates(
        conn, min_mentions=5, min_growth_pct=50, current_window="2026-08-08T00:00:00"
    )
    assert len(candidates) == 1
    assert candidates[0]["phrase"] == "led face mask"
    assert candidates[0]["mention_count"] == 9
    assert candidates[0]["growth_pct"] == 200.0
    conn.close()


def test_find_candidates_filters_below_threshold(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    db.insert_phrase_mentions(conn, [
        {"phrase": "random phrase", "subreddit": "gadgets", "mention_count": 2,
         "window_start": "2026-08-01T00:00:00", "window_end": "2026-08-01T00:00:00"},
    ])
    candidates = velocity.find_candidates(
        conn, min_mentions=5, min_growth_pct=30, current_window="2026-08-01T00:00:00"
    )
    assert candidates == []
    conn.close()


def test_find_candidates_sorted_by_growth_desc(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    for phrase, counts in [("phrase a", [4, 20]), ("phrase b", [4, 8])]:
        db.insert_phrase_mentions(conn, [
            {"phrase": phrase, "subreddit": "gadgets", "mention_count": counts[0],
             "window_start": "2026-08-01T00:00:00", "window_end": "2026-08-01T00:00:00"},
        ])
        db.insert_phrase_mentions(conn, [
            {"phrase": phrase, "subreddit": "gadgets", "mention_count": counts[1],
             "window_start": "2026-08-08T00:00:00", "window_end": "2026-08-08T00:00:00"},
        ])
    candidates = velocity.find_candidates(
        conn, min_mentions=1, min_growth_pct=0, current_window="2026-08-08T00:00:00"
    )
    assert [c["phrase"] for c in candidates] == ["phrase a", "phrase b"]
    conn.close()


def test_find_candidates_ignores_phrase_not_seen_in_current_window(tmp_path, monkeypatch):
    """Une phrase dont la derniere mention est dans une ancienne fenetre ne doit
    pas apparaitre, meme si elle passerait les seuils de mentions/croissance :
    elle n'a simplement pas ete revue lors du run courant (discovery finding #2)."""
    conn = _make_conn(tmp_path, monkeypatch)
    db.insert_phrase_mentions(conn, [
        {"phrase": "old stale phrase", "subreddit": "gadgets", "mention_count": 3,
         "window_start": "2026-08-01T00:00:00", "window_end": "2026-08-01T00:00:00"},
    ])
    db.insert_phrase_mentions(conn, [
        {"phrase": "old stale phrase", "subreddit": "gadgets", "mention_count": 9,
         "window_start": "2026-08-08T00:00:00", "window_end": "2026-08-08T00:00:00"},
    ])
    # current_window est un run plus recent que toute mention de "old stale phrase"
    candidates = velocity.find_candidates(
        conn, min_mentions=1, min_growth_pct=0, current_window="2026-08-15T00:00:00"
    )
    assert candidates == []
    conn.close()


def test_find_candidates_single_window_with_zero_growth_threshold(tmp_path, monkeypatch):
    """Une phrase avec un seul point de donnees (premiere fois vue) a une
    croissance mesuree de 0.0 (garde-fou 'historique insuffisant' de growth_pct).
    Avec min_growth_pct=0, elle est donc rapportee comme candidate des lors
    qu'elle est vue dans la fenetre courante et depasse min_mentions -- ce n'est
    pas une vraie croissance mesuree, juste la valeur par defaut du garde-fou."""
    conn = _make_conn(tmp_path, monkeypatch)
    db.insert_phrase_mentions(conn, [
        {"phrase": "brand new phrase", "subreddit": "gadgets", "mention_count": 7,
         "window_start": "2026-08-01T00:00:00", "window_end": "2026-08-01T00:00:00"},
    ])
    candidates = velocity.find_candidates(
        conn, min_mentions=5, min_growth_pct=0, current_window="2026-08-01T00:00:00"
    )
    assert len(candidates) == 1
    assert candidates[0]["phrase"] == "brand new phrase"
    assert candidates[0]["mention_count"] == 7
    assert candidates[0]["growth_pct"] == 0.0
    conn.close()
