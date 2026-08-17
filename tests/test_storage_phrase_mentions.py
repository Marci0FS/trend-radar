from pathlib import Path

from storage import db


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def test_insert_and_get_distinct_phrases(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    db.insert_phrase_mentions(conn, [
        {"phrase": "led face mask", "subreddit": "gadgets", "mention_count": 3,
         "window_start": "2026-08-01T00:00:00", "window_end": "2026-08-01T00:00:00"},
        {"phrase": "posture corrector", "subreddit": "gadgets", "mention_count": 1,
         "window_start": "2026-08-01T00:00:00", "window_end": "2026-08-01T00:00:00"},
    ])
    phrases = db.get_distinct_phrases(conn)
    assert sorted(phrases) == ["led face mask", "posture corrector"]
    conn.close()


def test_get_phrase_mention_series_aggregates_by_window(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    db.insert_phrase_mentions(conn, [
        {"phrase": "led face mask", "subreddit": "gadgets", "mention_count": 3,
         "window_start": "2026-08-01T00:00:00", "window_end": "2026-08-01T00:00:00"},
        {"phrase": "led face mask", "subreddit": "shutupandtakemymoney", "mention_count": 2,
         "window_start": "2026-08-01T00:00:00", "window_end": "2026-08-01T00:00:00"},
        {"phrase": "led face mask", "subreddit": "gadgets", "mention_count": 9,
         "window_start": "2026-08-08T00:00:00", "window_end": "2026-08-08T00:00:00"},
    ])
    series = db.get_phrase_mention_series(conn, "led face mask")
    assert series == [
        ("2026-08-01T00:00:00", 5),
        ("2026-08-08T00:00:00", 9),
    ]
    conn.close()
