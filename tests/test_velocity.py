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
    candidates = velocity.find_candidates(conn, min_mentions=5, min_growth_pct=50)
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
    candidates = velocity.find_candidates(conn, min_mentions=5, min_growth_pct=30)
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
    candidates = velocity.find_candidates(conn, min_mentions=1, min_growth_pct=0)
    assert [c["phrase"] for c in candidates] == ["phrase a", "phrase b"]
    conn.close()
