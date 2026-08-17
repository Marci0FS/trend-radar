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
