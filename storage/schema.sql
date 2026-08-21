-- Schema SQLite trend-radar.
-- Historique dans le temps : ces tables ne sont jamais UPDATE/DELETE,
-- seulement des INSERT (meme logique que le tracker collector-arbitrage).

CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL UNIQUE,
    category TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS google_trends_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    date TEXT NOT NULL,
    interest_score INTEGER NOT NULL,
    region TEXT,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(keyword_id, date, region)
);

CREATE TABLE IF NOT EXISTS reddit_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    post_id TEXT NOT NULL UNIQUE,
    subreddit TEXT NOT NULL,
    title TEXT NOT NULL,
    score INTEGER NOT NULL,
    num_comments INTEGER NOT NULL,
    created_utc TEXT NOT NULL,
    url TEXT,
    collected_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    sources_count INTEGER NOT NULL,
    convergence_score REAL NOT NULL,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS phrase_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase TEXT NOT NULL,
    subreddit TEXT NOT NULL,
    mention_count INTEGER NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    scanned_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ebay_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    date TEXT NOT NULL,
    listing_count INTEGER NOT NULL,
    marketplace TEXT,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(keyword_id, date, marketplace)
);

CREATE TABLE IF NOT EXISTS aliexpress_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    date TEXT NOT NULL,
    sales_volume INTEGER NOT NULL,
    marketplace TEXT,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(keyword_id, date, marketplace)
);

CREATE TABLE IF NOT EXISTS youtube_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    date TEXT NOT NULL,
    view_count INTEGER NOT NULL,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(keyword_id, date)
);

CREATE TABLE IF NOT EXISTS trends_discovery_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL,
    date TEXT NOT NULL,
    ebay_signal INTEGER NOT NULL,
    youtube_signal INTEGER NOT NULL,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(term, date)
);

CREATE INDEX IF NOT EXISTS idx_trends_keyword ON google_trends_snapshots(keyword_id);
CREATE INDEX IF NOT EXISTS idx_reddit_keyword ON reddit_signals(keyword_id);
CREATE INDEX IF NOT EXISTS idx_signals_keyword ON signals(keyword_id);
CREATE INDEX IF NOT EXISTS idx_phrase_mentions_phrase ON phrase_mentions(phrase);
CREATE INDEX IF NOT EXISTS idx_ebay_keyword ON ebay_snapshots(keyword_id);
CREATE INDEX IF NOT EXISTS idx_aliexpress_keyword ON aliexpress_snapshots(keyword_id);
CREATE INDEX IF NOT EXISTS idx_youtube_keyword ON youtube_snapshots(keyword_id);
