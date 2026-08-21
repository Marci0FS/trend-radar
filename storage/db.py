"""Connexion SQLite et helpers d'insertion pour trend-radar.

Historique dans le temps : chaque scan ajoute des lignes, jamais
d'UPDATE destructif sur les series temporelles (meme logique que le
tracker collector-arbitrage existant).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "trends.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    conn.close()


def get_or_create_keyword(conn: sqlite3.Connection, term: str, category: str | None = None) -> int:
    row = conn.execute("SELECT id FROM keywords WHERE term = ?", (term,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO keywords (term, category) VALUES (?, ?)", (term, category)
    )
    conn.commit()
    return cur.lastrowid


def insert_trends_snapshots(
    conn: sqlite3.Connection, keyword_id: int, snapshots: list[tuple[str, int]], region: str
) -> None:
    conn.executemany(
        """INSERT OR IGNORE INTO google_trends_snapshots (keyword_id, date, interest_score, region)
           VALUES (?, ?, ?, ?)""",
        [(keyword_id, date, score, region) for date, score in snapshots],
    )
    conn.commit()


def insert_reddit_posts(conn: sqlite3.Connection, keyword_id: int, posts: list[dict]) -> None:
    conn.executemany(
        """INSERT OR IGNORE INTO reddit_signals
           (keyword_id, post_id, subreddit, title, score, num_comments, created_utc, url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                keyword_id, p["post_id"], p["subreddit"], p["title"], p["score"],
                p["num_comments"], p["created_utc"], p["url"],
            )
            for p in posts
        ],
    )
    conn.commit()


def insert_signal(
    conn: sqlite3.Connection,
    keyword_id: int,
    window_start: str,
    window_end: str,
    sources_count: int,
    convergence_score: float,
    details: dict,
) -> None:
    conn.execute(
        """INSERT INTO signals
           (keyword_id, window_start, window_end, sources_count, convergence_score, details_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (keyword_id, window_start, window_end, sources_count, convergence_score,
         json.dumps(details, ensure_ascii=False)),
    )
    conn.commit()


def insert_phrase_mentions(conn: sqlite3.Connection, mentions: list[dict]) -> None:
    conn.executemany(
        """INSERT INTO phrase_mentions (phrase, subreddit, mention_count, window_start, window_end)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (m["phrase"], m["subreddit"], m["mention_count"], m["window_start"], m["window_end"])
            for m in mentions
        ],
    )
    conn.commit()


def get_distinct_phrases(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT phrase FROM phrase_mentions").fetchall()
    return [r["phrase"] for r in rows]


def get_phrases_in_window(conn: sqlite3.Connection, window_start: str) -> list[str]:
    """Phrases mentionnees dans une fenetre (run de scan) donnee.

    Utilise par find_candidates pour borner sa recherche aux phrases vues
    lors du run courant, plutot que d'iterer sur toutes les phrases jamais
    enregistrees (requete non bornee, de plus en plus couteuse au fil du temps).
    """
    rows = conn.execute(
        "SELECT DISTINCT phrase FROM phrase_mentions WHERE window_start = ?",
        (window_start,),
    ).fetchall()
    return [r["phrase"] for r in rows]


def get_phrase_mention_series(conn: sqlite3.Connection, phrase: str) -> list[tuple[str, int]]:
    rows = conn.execute(
        """SELECT window_start, SUM(mention_count) as total
           FROM phrase_mentions
           WHERE phrase = ?
           GROUP BY window_start
           ORDER BY window_start""",
        (phrase,),
    ).fetchall()
    return [(r["window_start"], r["total"]) for r in rows]


def insert_ebay_snapshot(
    conn: sqlite3.Connection, keyword_id: int, date: str, listing_count: int, marketplace: str
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO ebay_snapshots (keyword_id, date, listing_count, marketplace)
           VALUES (?, ?, ?, ?)""",
        (keyword_id, date, listing_count, marketplace),
    )
    conn.commit()


def get_ebay_snapshot_series(conn: sqlite3.Connection, keyword_id: int) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT date, listing_count FROM ebay_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    return [(r["date"], r["listing_count"]) for r in rows]


def insert_aliexpress_snapshot(
    conn: sqlite3.Connection, keyword_id: int, date: str, sales_volume: int, marketplace: str
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO aliexpress_snapshots (keyword_id, date, sales_volume, marketplace)
           VALUES (?, ?, ?, ?)""",
        (keyword_id, date, sales_volume, marketplace),
    )
    conn.commit()


def get_aliexpress_snapshot_series(conn: sqlite3.Connection, keyword_id: int) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT date, sales_volume FROM aliexpress_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    return [(r["date"], r["sales_volume"]) for r in rows]


def insert_youtube_snapshot(
    conn: sqlite3.Connection, keyword_id: int, date: str, view_count: int
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO youtube_snapshots (keyword_id, date, view_count)
           VALUES (?, ?, ?)""",
        (keyword_id, date, view_count),
    )
    conn.commit()


def get_youtube_snapshot_series(conn: sqlite3.Connection, keyword_id: int) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT date, view_count FROM youtube_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    return [(r["date"], r["view_count"]) for r in rows]


def insert_trends_discovery_candidate(
    conn: sqlite3.Connection, term: str, date: str, ebay_signal: bool, youtube_signal: bool
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO trends_discovery_candidates (term, date, ebay_signal, youtube_signal)
           VALUES (?, ?, ?, ?)""",
        (term, date, int(ebay_signal), int(youtube_signal)),
    )
    conn.commit()
