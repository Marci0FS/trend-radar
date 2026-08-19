# YouTube Convergence Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add YouTube as a 5th convergence source — a "buzz" signal
(sum of view counts on the 10 most-viewed videos published in the last 7
days per keyword) — using the YouTube Data API v3, the simplest
authentication of all five sources (a single API key, no OAuth).

**Architecture:** New `collectors/youtube.py` follows the shape of
`collectors/ebay.py` (one `*Error` class, one fetch function) but makes
two sequential HTTP calls per keyword: `search.list` to find candidate
videos, then `videos.list` to get their exact view counts (`search.list`
alone doesn't return view counts). A new `youtube_snapshots` table stores
one view-count snapshot per keyword per scan day. `scoring/convergence.py`
gains a 5th branch following the exact pattern of its four existing
branches. `cli.py cmd_scan` wires YouTube in with the same
credentials-missing/per-keyword-failure resilience pattern already used
for eBay and AliExpress. Unlike the AliExpress feature, this one does
**not** change the FORT threshold — `sources_count >= 3` stays as-is,
only the denominator display (`/4` → `/5`) changes.

**Tech Stack:** Python, `requests` (already a dependency), SQLite
(historized, INSERT-only).

## Global Constraints

- Free, self-hosted, official API only — no scraping against YouTube's
  ToS.
- SQLite storage is append-only: every insert function uses
  `INSERT OR IGNORE`, never `UPDATE`/`DELETE`.
- Follow the exact patterns of `collectors/ebay.py`,
  `collectors/aliexpress.py`, `storage/db.py`, and `scoring/convergence.py`
  as they exist today (post-AliExpress-merge) — do not restructure
  unrelated code.
- **The FORT threshold (`sources_count >= 3`) does NOT change in this
  plan.** Only the displayed denominator changes from `/4` to `/5`, in
  `cli.py write_report` and `web/public/index.html`. Do not touch the
  `>= 3` comparison anywhere.
- Never fabricate a zero when a response field is missing — always raise
  `YouTubeError` instead (same lesson already applied to
  `collectors/ebay.py` and `collectors/aliexpress.py`). An empty search
  result (no videos found in the 7-day window) IS a legitimate `0` —
  distinguish this from a malformed/incomplete response on a video that
  WAS returned, which is always an error, never a fabricated zero.
- Truncate any full API response body interpolated into an error message
  to ~200 characters (`repr(...)[:200]`) — established convention from
  the AliExpress feature's final review, to avoid ever echoing a large or
  sensitive payload into logs/stdout.
- `YOUTUBE_API_KEY` is **not yet available** — the user has not created a
  Google Cloud project or generated an API key yet. This entire plan is
  implemented and tested against mocked HTTP calls only. Do not attempt
  any real network call to the YouTube API. Getting a real key is a
  separate, out-of-band step the user does themselves in a browser (never
  enter a password on their behalf) — not a task in this plan.

---

### Task 1: Storage — `youtube_snapshots` table

**Files:**
- Modify: `storage/schema.sql`
- Modify: `storage/db.py`
- Test: `tests/test_youtube_storage.py`

**Interfaces:**
- Produces: `db.insert_youtube_snapshot(conn, keyword_id: int, date: str, view_count: int) -> None`
- Produces: `db.get_youtube_snapshot_series(conn, keyword_id: int) -> list[tuple[str, int]]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_youtube_storage.py`:

```python
from storage import db


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def test_insert_and_get_youtube_snapshot_series(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "led face mask", "gadgets")
    db.insert_youtube_snapshot(conn, kid, "2026-08-19", 15000)
    db.insert_youtube_snapshot(conn, kid, "2026-08-20", 22000)
    series = db.get_youtube_snapshot_series(conn, kid)
    assert series == [("2026-08-19", 15000), ("2026-08-20", 22000)]
    conn.close()


def test_insert_youtube_snapshot_ignores_duplicate_date(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "led face mask", "gadgets")
    db.insert_youtube_snapshot(conn, kid, "2026-08-19", 15000)
    db.insert_youtube_snapshot(conn, kid, "2026-08-19", 99999)
    series = db.get_youtube_snapshot_series(conn, kid)
    assert series == [("2026-08-19", 15000)]
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_youtube_storage.py -v`
Expected: FAIL — `AttributeError: module 'storage.db' has no attribute
'insert_youtube_snapshot'`

- [ ] **Step 3: Add the table to the schema**

In `storage/schema.sql`, add this table right after the existing
`aliexpress_snapshots` table definition (before the `CREATE INDEX` block
at the bottom of the file):

```sql
CREATE TABLE IF NOT EXISTS youtube_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    date TEXT NOT NULL,
    view_count INTEGER NOT NULL,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(keyword_id, date)
);
```

Then add an index alongside the existing `idx_aliexpress_keyword` line:

```sql
CREATE INDEX IF NOT EXISTS idx_youtube_keyword ON youtube_snapshots(keyword_id);
```

- [ ] **Step 4: Implement the storage functions**

In `storage/db.py`, add after `get_aliexpress_snapshot_series`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_youtube_storage.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add storage/schema.sql storage/db.py tests/test_youtube_storage.py
git commit -m "feat: add youtube_snapshots storage"
```

---

### Task 2: Collector — `collectors/youtube.py`

**Files:**
- Create: `collectors/youtube.py`
- Test: `tests/test_youtube.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone module).
- Produces: `youtube.YouTubeError(RuntimeError)`
- Produces: `youtube.fetch_recent_view_count(keyword: str) -> int` (raises
  `KeyError` if `YOUTUBE_API_KEY` is missing from the environment; raises
  `YouTubeError` on HTTP failure or a malformed response; returns `0` for
  a legitimate empty result set, never for a malformed one)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_youtube.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from collectors import youtube


def _search_response(video_ids):
    return {"items": [{"id": {"videoId": vid}} for vid in video_ids]}


def _videos_response(view_counts):
    return {"items": [{"statistics": {"viewCount": str(v)}} for v in view_counts]}


def test_fetch_recent_view_count_missing_api_key_raises_key_error(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    with pytest.raises(KeyError):
        youtube.fetch_recent_view_count("led face mask")


def test_fetch_recent_view_count_sums_views_across_videos(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    search_resp = MagicMock()
    search_resp.json.return_value = _search_response(["vid1", "vid2", "vid3"])
    search_resp.raise_for_status.return_value = None

    videos_resp = MagicMock()
    videos_resp.json.return_value = _videos_response([1000, 2500, 300])
    videos_resp.raise_for_status.return_value = None

    with patch(
        "collectors.youtube.requests.get", side_effect=[search_resp, videos_resp]
    ) as mock_get:
        total = youtube.fetch_recent_view_count("led face mask")

    assert total == 3800
    search_call_kwargs = mock_get.call_args_list[0].kwargs
    assert search_call_kwargs["params"]["q"] == "led face mask"
    assert search_call_kwargs["params"]["order"] == "viewCount"
    assert search_call_kwargs["params"]["type"] == "video"
    assert search_call_kwargs["params"]["maxResults"] == 10
    assert "publishedAfter" in search_call_kwargs["params"]

    videos_call_kwargs = mock_get.call_args_list[1].kwargs
    assert videos_call_kwargs["params"]["id"] == "vid1,vid2,vid3"


def test_fetch_recent_view_count_returns_zero_for_empty_search_results(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    search_resp = MagicMock()
    search_resp.json.return_value = _search_response([])
    search_resp.raise_for_status.return_value = None

    with patch("collectors.youtube.requests.get", side_effect=[search_resp]) as mock_get:
        total = youtube.fetch_recent_view_count("very obscure keyword")

    assert total == 0
    mock_get.assert_called_once()  # videos.list jamais appele si aucune video trouvee


def test_fetch_recent_view_count_raises_youtube_error_on_search_http_failure(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    import requests as requests_module

    with patch(
        "collectors.youtube.requests.get",
        side_effect=requests_module.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(youtube.YouTubeError):
            youtube.fetch_recent_view_count("led face mask")


def test_fetch_recent_view_count_raises_youtube_error_on_videos_http_failure(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    import requests as requests_module

    search_resp = MagicMock()
    search_resp.json.return_value = _search_response(["vid1"])
    search_resp.raise_for_status.return_value = None

    with patch(
        "collectors.youtube.requests.get",
        side_effect=[search_resp, requests_module.exceptions.ConnectionError("boom")],
    ):
        with pytest.raises(youtube.YouTubeError):
            youtube.fetch_recent_view_count("led face mask")


def test_fetch_recent_view_count_raises_youtube_error_when_video_missing_view_count(monkeypatch):
    """Une video presente dans la reponse mais sans champ viewCount doit
    lever YouTubeError plutot que d'etre silencieusement traitee comme 0 —
    un faux 0 fabriquerait un faux signal de convergence au prochain scan
    (meme precaution que collectors/ebay.py et collectors/aliexpress.py)."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    search_resp = MagicMock()
    search_resp.json.return_value = _search_response(["vid1"])
    search_resp.raise_for_status.return_value = None

    videos_resp = MagicMock()
    videos_resp.json.return_value = {"items": [{"statistics": {}}]}
    videos_resp.raise_for_status.return_value = None

    with patch("collectors.youtube.requests.get", side_effect=[search_resp, videos_resp]):
        with pytest.raises(youtube.YouTubeError):
            youtube.fetch_recent_view_count("led face mask")


def test_fetch_recent_view_count_raises_youtube_error_on_malformed_search_response(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    search_resp = MagicMock()
    search_resp.json.return_value = {"error": "quota exceeded"}
    search_resp.raise_for_status.return_value = None

    with patch("collectors.youtube.requests.get", side_effect=[search_resp]):
        with pytest.raises(youtube.YouTubeError):
            youtube.fetch_recent_view_count("led face mask")


def test_fetch_recent_view_count_raises_youtube_error_when_view_count_non_numeric(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    search_resp = MagicMock()
    search_resp.json.return_value = _search_response(["vid1"])
    search_resp.raise_for_status.return_value = None

    videos_resp = MagicMock()
    videos_resp.json.return_value = {"items": [{"statistics": {"viewCount": "not-a-number"}}]}
    videos_resp.raise_for_status.return_value = None

    with patch("collectors.youtube.requests.get", side_effect=[search_resp, videos_resp]):
        with pytest.raises(youtube.YouTubeError):
            youtube.fetch_recent_view_count("led face mask")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_youtube.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'collectors.youtube'`

- [ ] **Step 3: Implement the collector**

Create `collectors/youtube.py`:

```python
"""Collecteur YouTube Data API v3 (somme des vues sur les 10 videos les
plus vues publiees dans les 7 derniers jours pour un mot-cle).

API officielle et gratuite. Authentification la plus simple des sources
de trend-radar : une seule cle API passee en parametre d'URL, pas
d'OAuth, pas de secret separe, pas de rafraichissement de token.

Deux appels par mot-cle :
1. search.list (100 unites de quota sur les 10 000/jour, plafonne aussi
   a 100 appels search.list/jour independamment du reste) : trouve les
   10 videos les plus vues publiees dans les 7 derniers jours.
2. videos.list (1 unite de quota) : recupere le viewCount exact de ces
   10 videos — search.list seul ne le fournit pas.

pageInfo.totalResults de search.list n'est PAS utilise comme signal :
Google le documente comme une estimation approximative, pas un compte
exact, trop bruite pour la convergence (voir doc officielle search.list).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import requests

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_RESULTS_PER_KEYWORD = 10
_WINDOW_DAYS = 7


class YouTubeError(RuntimeError):
    pass


def fetch_recent_view_count(keyword: str) -> int:
    """Retourne la somme des vues sur les 10 videos les plus vues publiees
    dans les 7 derniers jours pour ce mot-cle. Leve KeyError si
    YOUTUBE_API_KEY n'est pas definie en env (meme convention que
    collectors.ebay.get_app_token). Un resultat de recherche vide est une
    observation legitime (0 vue) ; une video presente mais avec un champ
    manquant/invalide est une erreur (voir YouTubeError), jamais traitee
    comme 0."""
    key = os.environ["YOUTUBE_API_KEY"]

    published_after = (
        datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        search_resp = requests.get(
            _SEARCH_URL,
            params={
                "key": key,
                "q": keyword,
                "part": "id",
                "type": "video",
                "order": "viewCount",
                "publishedAfter": published_after,
                "maxResults": _RESULTS_PER_KEYWORD,
            },
            timeout=15,
        )
        search_resp.raise_for_status()
        video_ids = _extract_video_ids(search_resp.json())
    except requests.RequestException as exc:
        raise YouTubeError(f"Echec recherche YouTube pour '{keyword}' : {exc}") from exc
    except (TypeError, AttributeError, ValueError) as exc:
        raise YouTubeError(
            f"Reponse de recherche YouTube invalide pour '{keyword}' : {exc}"
        ) from exc

    if not video_ids:
        return 0

    try:
        videos_resp = requests.get(
            _VIDEOS_URL,
            params={"key": key, "id": ",".join(video_ids), "part": "statistics"},
            timeout=15,
        )
        videos_resp.raise_for_status()
        return _sum_view_counts(videos_resp.json(), keyword)
    except requests.RequestException as exc:
        raise YouTubeError(
            f"Echec recuperation des vues YouTube pour '{keyword}' : {exc}"
        ) from exc
    except (TypeError, AttributeError, ValueError) as exc:
        raise YouTubeError(
            f"Reponse de statistiques YouTube invalide pour '{keyword}' : {exc}"
        ) from exc


def _extract_video_ids(data) -> list[str]:
    try:
        items = data["items"]
    except (KeyError, TypeError) as exc:
        raise YouTubeError(
            f"Structure de reponse search.list inattendue : {repr(data)[:200]}"
        ) from exc
    if not isinstance(items, list):
        raise YouTubeError(f"Champ 'items' n'est pas une liste : {repr(items)[:200]}")
    ids = []
    for item in items:
        try:
            ids.append(item["id"]["videoId"])
        except (KeyError, TypeError) as exc:
            raise YouTubeError(
                f"Element de recherche sans videoId : {repr(item)[:200]}"
            ) from exc
    return ids


def _sum_view_counts(data, keyword: str) -> int:
    try:
        items = data["items"]
    except (KeyError, TypeError) as exc:
        raise YouTubeError(
            f"Structure de reponse videos.list inattendue : {repr(data)[:200]}"
        ) from exc
    if not isinstance(items, list):
        raise YouTubeError(f"Champ 'items' n'est pas une liste : {repr(items)[:200]}")
    total = 0
    for item in items:
        try:
            view_count = item["statistics"]["viewCount"]
        except (KeyError, TypeError) as exc:
            raise YouTubeError(
                f"Video YouTube sans champ viewCount pour '{keyword}' : {repr(item)[:200]}"
            ) from exc
        try:
            total += int(view_count)
        except (TypeError, ValueError) as exc:
            raise YouTubeError(
                f"Valeur de viewCount non numerique pour '{keyword}' : {view_count!r}"
            ) from exc
    return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_youtube.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add collectors/youtube.py tests/test_youtube.py
git commit -m "feat: add YouTube Data API v3 collector (search.list + videos.list)"
```

---

### Task 3: Scoring — 5th convergence branch

**Files:**
- Modify: `scoring/convergence.py`
- Modify: `tests/test_convergence.py`

**Interfaces:**
- Consumes: nothing new from earlier tasks beyond the `youtube_snapshots`
  table existing (queried inline via SQL, same established style as the
  other four branches — none of them call the `get_*_series` helpers
  either).
- Produces: `compute_convergence(...)` result now includes
  `details["youtube_growth_pct"]` and
  `details["signals_detected"]["youtube"]`, and `sources_count` ranges
  0–5 instead of 0–4.

- [ ] **Step 1: Write the failing tests**

In `tests/test_convergence.py`, add `"youtube_growth_pct": 20` to the
`THRESHOLDS` dict at the top of the file (after `"aliexpress_growth_pct": 20,`):

```python
THRESHOLDS = {
    "trends_growth_pct": 20,
    "reddit_min_posts": 3,
    "reddit_min_avg_score": 10,
    "ebay_growth_pct": 20,
    "aliexpress_growth_pct": 20,
    "youtube_growth_pct": 20,
}
```

Add new tests at the end of the file:

```python
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
            "num_comments": 1, "created_utc": "2026-08-14T00:00:00+00:00", "url": "https://x",
        }
        for i in range(5)
    ])

    result = compute_convergence(conn, kid, THRESHOLDS)

    assert result["sources_count"] == 5
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_convergence.py -v`
Expected: FAIL (3 new tests) — `sqlite3.OperationalError: no such table:
youtube_snapshots` is NOT expected here since Task 1 already created the
table; instead expect `KeyError: 'youtube'` on
`result["details"]["signals_detected"]["youtube"]` (the key doesn't
exist yet because `compute_convergence` doesn't have the branch). All
other existing tests in the file continue to pass unchanged (this task
adds a key to `THRESHOLDS` that nothing existing reads yet — a `dict`
gaining an unused key never breaks anything that indexes other keys).

- [ ] **Step 3: Implement the 5th branch**

In `scoring/convergence.py`, add after the existing `aliexpress` branch
(after the `signals_detected["aliexpress"] = ...` line) and before
`sources_count = ...`:

```python
    youtube_rows = conn.execute(
        "SELECT date, view_count FROM youtube_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    youtube_snapshots = [(r["date"], r["view_count"]) for r in youtube_rows]
    youtube_growth = growth_pct(youtube_snapshots, window_days=1)
    signals_detected["youtube"] = youtube_growth >= thresholds["youtube_growth_pct"]
```

Update the `convergence_score` computation to add the YouTube bonus term:

```python
    convergence_score = (
        sources_count * 10
        + max(trends_growth, 0) * 0.1
        + reddit_count * 0.5
        + max(ebay_growth, 0) * 0.1
        + max(aliexpress_growth, 0) * 0.1
        + max(youtube_growth, 0) * 0.1
    )
```

Update the returned `details` dict to include the new field:

```python
        "details": {
            "trends_growth_pct": round(trends_growth, 1),
            "reddit_post_count": reddit_count,
            "reddit_avg_score": round(reddit_avg_score, 1),
            "ebay_growth_pct": round(ebay_growth, 1),
            "aliexpress_growth_pct": round(aliexpress_growth, 1),
            "youtube_growth_pct": round(youtube_growth, 1),
            "signals_detected": signals_detected,
        },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_convergence.py -v`
Expected: PASS (all tests, including the 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add scoring/convergence.py tests/test_convergence.py
git commit -m "feat: add YouTube as 5th convergence source in scoring"
```

---

### Task 4: CLI integration — `cmd_scan`, `write_report`, dashboard denominator

**Files:**
- Modify: `cli.py`
- Modify: `tests/test_cli_scan_ebay.py` (threshold dict needs the new key)
- Modify: `tests/test_cli_scan_aliexpress.py` (threshold dict needs the new key)
- Modify: `tests/test_cli_publish_flag.py` (threshold dict needs the new key)
- Modify: `tests/test_cli_scan_resilience.py` (threshold dict needs the new key)
- Modify: `tests/test_cli_write_report.py` (helper dict needs the new
  field; denominator assertion updates from `/4` to `/5`)
- Modify: `web/public/index.html` (dot-indicator count and footer text —
  NOT a new visible column, same kind of text/indicator correctness fix
  already applied for AliExpress)
- Test: `tests/test_cli_scan_youtube.py`

**Interfaces:**
- Consumes: `youtube.fetch_recent_view_count`, `youtube.YouTubeError` (Task 2)
- Consumes: `db.insert_youtube_snapshot` (Task 1)
- Consumes: `compute_convergence` returning `details["youtube_growth_pct"]` (Task 3)

- [ ] **Step 1: Update the five existing threshold dicts / fixtures that will otherwise KeyError or fail an outdated assertion**

`compute_convergence` now unconditionally reads
`thresholds["youtube_growth_pct"]` (added in Task 3). Any test that
builds a `watchlist["thresholds"]` dict without that key will now fail
with `KeyError: 'youtube_growth_pct'` as soon as `cmd_scan` runs. Fix
these five files first, before writing any new test:

In `tests/test_cli_publish_flag.py`, find the line building the
`"thresholds"` dict (currently ending in `"aliexpress_growth_pct": 20},`)
and add `"youtube_growth_pct": 20` before the closing brace:
```python
"thresholds": {"trends_growth_pct": 20, "reddit_min_posts": 3, "reddit_min_avg_score": 10, "ebay_growth_pct": 20, "aliexpress_growth_pct": 20, "youtube_growth_pct": 20},
```

In `tests/test_cli_scan_resilience.py`, apply the identical change to
its matching `"thresholds"` dict line.

In `tests/test_cli_scan_ebay.py`, in `_base_watchlist()`, add
`"youtube_growth_pct": 20,` as a new line right after
`"aliexpress_growth_pct": 20,`.

In `tests/test_cli_scan_aliexpress.py`, in `_base_watchlist()`, apply the
identical addition.

In `tests/test_cli_write_report.py`, in the `_result()` helper's
`"details"` dict, add `"youtube_growth_pct": 3.0,` as a new line right
after `"aliexpress_growth_pct": 8.0,`. Then update
`test_write_report_marks_three_sources_as_fort_with_four_denominator`:
rename it to `test_write_report_marks_three_sources_as_fort_with_five_denominator`
and change its assertion from `"Sources en accord : 3/4"` to
`"Sources en accord : 3/5"` (both the docstring's `/4`→`/5` reference and
the assertion string itself).

Run: `python3 -m pytest tests/test_cli_publish_flag.py tests/test_cli_scan_resilience.py tests/test_cli_scan_ebay.py tests/test_cli_scan_aliexpress.py tests/test_cli_write_report.py -v`
Expected: 4 of the 5 files PASS as before. `tests/test_cli_write_report.py`
has one FAILING test at this point —
`test_write_report_marks_three_sources_as_fort_with_five_denominator`
still expects `/5` but `cli.py`'s `write_report` still hardcodes `/4`
(that's fixed in Step 3 below). This confirms you're on track: the other
four files are fully green, and this one file has exactly the expected,
not-yet-fixed failure.

- [ ] **Step 2: Write the failing tests for YouTube cli integration**

Create `tests/test_cli_scan_youtube.py`:

```python
import json
from datetime import datetime, timezone

from collectors import aliexpress
from collectors import ebay
from collectors import google_trends
from collectors import reddit as reddit_collector
from collectors import youtube
from storage import db as storage_db

import cli


def _base_watchlist():
    return {
        "categories": {"gadgets": {"keywords": ["test kw"], "subreddits": []}},
        "thresholds": {
            "trends_growth_pct": 20,
            "reddit_min_posts": 3,
            "reddit_min_avg_score": 10,
            "ebay_growth_pct": 20,
            "aliexpress_growth_pct": 20,
            "youtube_growth_pct": 20,
        },
    }


def _patch_common(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(google_trends, "fetch_interest_over_time", lambda *a, **k: [])
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    def _raise_reddit_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_reddit_key_error)

    def _raise_ebay_key_error():
        raise KeyError("EBAY_CLIENT_ID")

    monkeypatch.setattr(ebay, "get_app_token", _raise_ebay_key_error)

    def _raise_aliexpress_key_error():
        raise KeyError("ALIEXPRESS_APP_KEY")

    monkeypatch.setattr(aliexpress, "get_access_token", _raise_aliexpress_key_error)


def test_cmd_scan_skips_youtube_when_credentials_missing(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    assert data["watchlist"][0]["youtube_growth_pct"] == 0.0


def test_cmd_scan_continues_when_youtube_fails_for_one_keyword(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    def _flaky_fetch(keyword, **kwargs):
        raise youtube.YouTubeError("simulated failure")

    monkeypatch.setattr(youtube, "fetch_recent_view_count", _flaky_fetch)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    assert len(data["watchlist"]) == 1
    entry = data["watchlist"][0]
    assert entry["keyword"] == "test kw"
    assert entry["trends_growth_pct"] == 0.0
    assert isinstance(entry["convergence_score"], (int, float))


def test_cmd_scan_ebay_succeeds_when_youtube_fails_for_one_keyword(tmp_path, monkeypatch):
    """eBay et YouTube sont deux blocs independants dans la boucle par
    mot-cle : un echec YouTube ne doit pas empecher eBay de tourner
    normalement pour ce meme mot-cle (meme preuve d'independance que pour
    les paires Reddit/eBay et eBay/AliExpress deja testees)."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(google_trends, "fetch_interest_over_time", lambda *a, **k: [])
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    def _raise_reddit_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_reddit_key_error)

    def _raise_aliexpress_key_error():
        raise KeyError("ALIEXPRESS_APP_KEY")

    monkeypatch.setattr(aliexpress, "get_access_token", _raise_aliexpress_key_error)

    monkeypatch.setattr(ebay, "get_app_token", lambda: "fake-ebay-token")
    monkeypatch.setattr(ebay, "fetch_listing_count", lambda keyword, **kwargs: 4213)

    def _flaky_fetch(keyword, **kwargs):
        raise youtube.YouTubeError("simulated failure")

    monkeypatch.setattr(youtube, "fetch_recent_view_count", _flaky_fetch)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    entry = data["watchlist"][0]
    assert entry["youtube_growth_pct"] == 0.0

    conn = storage_db.get_connection()
    kid = storage_db.get_or_create_keyword(conn, "test kw", "gadgets")
    series = storage_db.get_ebay_snapshot_series(conn, kid)
    conn.close()
    assert series[-1][1] == 4213


def test_cmd_scan_stores_youtube_snapshot_when_available(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda keyword: 15000)

    cli.cmd_scan(_base_watchlist())

    conn = storage_db.get_connection()
    kid = storage_db.get_or_create_keyword(conn, "test kw", "gadgets")
    series = storage_db.get_youtube_snapshot_series(conn, kid)
    conn.close()
    assert series[-1][1] == 15000


def test_cmd_scan_youtube_growth_survives_two_scans_into_signals_json(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    class _FrozenDatetime(datetime):
        _current = datetime(2026, 8, 18, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._current

    monkeypatch.setattr(cli, "datetime", _FrozenDatetime)

    _FrozenDatetime._current = datetime(2026, 8, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda keyword: 10000)
    cli.cmd_scan(_base_watchlist())

    _FrozenDatetime._current = datetime(2026, 8, 19, tzinfo=timezone.utc)
    monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda keyword: 20000)
    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    entry = data["watchlist"][0]
    assert entry["youtube_growth_pct"] == 100.0
    assert entry["sources_count"] == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cli_scan_youtube.py -v`
Expected: FAIL — `KeyError: 'youtube_growth_pct'` (cli.py doesn't produce
this field in `signal_entries` yet) or an `AttributeError`-style failure
for `youtube.fetch_recent_view_count` not being called by `cmd_scan`.

- [ ] **Step 4: Wire YouTube into `cmd_scan`**

In `cli.py`, add the import near the other collector imports:

```python
from collectors import youtube
```

After the existing AliExpress availability check block (after the
`aliexpress_available = False` / `print(...)` lines for the
`AliExpressError` case), add the YouTube pre-check. Unlike eBay/AliExpress
there is no token-exchange call to make up front — YouTube's only
"credential" is a single API key read directly from the environment — so
the pre-check just confirms the key is present, without making any HTTP
request:

```python
    try:
        os.environ["YOUTUBE_API_KEY"]
        youtube_available = True
    except KeyError:
        youtube_available = False
        print("YouTube : cle API manquante, collecte YouTube desactivee pour ce scan")
```

Inside the per-keyword loop, after the existing AliExpress block (after
the `except aliexpress.AliExpressError as exc: print(...)` lines), add a
new independent block, following the exact `if <source>_available:`
shape already used for eBay and AliExpress:

```python
            if youtube_available:
                try:
                    view_count = youtube.fetch_recent_view_count(keyword)
                    today = datetime.now(timezone.utc).date().isoformat()
                    db.insert_youtube_snapshot(conn, keyword_id, today, view_count)
                except youtube.YouTubeError as exc:
                    print(f"  Echec YouTube pour '{keyword}', continue sans ce signal : {exc}")
```

In `signal_entries` (inside `cmd_scan`), add the new field after
`"aliexpress_growth_pct"`:

```python
            "aliexpress_growth_pct": r["details"]["aliexpress_growth_pct"],
            "youtube_growth_pct": r["details"]["youtube_growth_pct"],
```

- [ ] **Step 5: Update `write_report` for the new denominator**

In `cli.py`, `write_report`, change:

```python
        lines.append(f"- Sources en accord : {r['sources_count']}/4")
```
to:
```python
        lines.append(f"- Sources en accord : {r['sources_count']}/5")
```

Add a new line after the existing AliExpress line:
```python
        lines.append(f"- AliExpress : {d['aliexpress_growth_pct']}% de croissance")
        lines.append(f"- YouTube : {d['youtube_growth_pct']}% de croissance")
```

Do NOT change the `marker = "FORT" if r["sources_count"] >= 3 else "faible"`
line — the threshold itself does not change in this plan.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cli_scan_youtube.py tests/test_cli_write_report.py -v`
Expected: PASS (5 + 3 tests)

Run the full suite to confirm nothing else broke:
Run: `python3 -m pytest -v`
Expected: PASS (all tests, no regressions)

- [ ] **Step 7: Fix the dashboard's dot-indicator and footer text**

`web/public/index.html` hardcodes a 4-dot indicator and a footer sentence
naming exactly 4 sources — both are now factually wrong (5 sources
exist). The FORT threshold sentence itself ("au moins trois des...")
stays correct since the threshold doesn't change — only the source count
and dot total change.

In `web/public/index.html`, change the `dots()` function's loop bound:
```javascript
    function dots(n) {
      let out = '<span class="dots">';
      for (let i = 0; i < 4; i++) {
```
to:
```javascript
    function dots(n) {
      let out = '<span class="dots">';
      for (let i = 0; i < 5; i++) {
```

Change the footer text:
```html
  <footer>signal fort = au moins trois des quatre sources independantes (Trends, Reddit, eBay, AliExpress) en accord (&#9679;&#9679;&#9679;&#9675;)</footer>
```
to:
```html
  <footer>signal fort = au moins trois des cinq sources independantes (Trends, Reddit, eBay, AliExpress, YouTube) en accord (&#9679;&#9679;&#9679;&#9675;&#9675;)</footer>
```

- [ ] **Step 8: Manually verify the dashboard renders correctly**

Run: `python3 -m http.server 8000 --directory web/public` and open
`http://localhost:8000` in a browser (or read the file directly — no
build step exists for this static site). Confirm the footer text reads
correctly and no JavaScript console error appears — same manual check
already used for the eBay and AliExpress dashboard fixes, since this
file has no automated test coverage for its JS.

- [ ] **Step 9: Commit**

```bash
git add cli.py tests/test_cli_scan_youtube.py tests/test_cli_scan_ebay.py tests/test_cli_scan_aliexpress.py tests/test_cli_publish_flag.py tests/test_cli_scan_resilience.py tests/test_cli_write_report.py web/public/index.html
git commit -m "feat: wire YouTube into cmd_scan, update dashboard denominator to /5"
```

---

### Task 5: Configuration & documentation

**Files:**
- Modify: `config/watchlist.yaml`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: `watchlist["thresholds"]["youtube_growth_pct"]` (read by
  `scoring/convergence.py` in Task 3 with `[...]`, not `.get(...)` — it
  MUST exist in the real `config/watchlist.yaml` after this task, exactly
  like the other four threshold keys already there).

- [ ] **Step 1: Add the YouTube threshold to the real watchlist config**

In `config/watchlist.yaml`, in the `thresholds:` block, after
`aliexpress_growth_pct: 20`, add:

```yaml
  youtube_growth_pct: 20
```

No new top-level config key is needed (no geo/marketplace parameter for
YouTube, per the design spec).

- [ ] **Step 2: Verify the config loads correctly**

Run: `python3 -m pytest -v`
Expected: PASS (all tests — sanity check that the real YAML file the app
loads at runtime is well-formed)

Run: `python3 -c "import yaml; d = yaml.safe_load(open('config/watchlist.yaml')); assert 'youtube_growth_pct' in d['thresholds']; print('OK')"`
Expected: prints `OK`

- [ ] **Step 3: Add the credential placeholder to `.env.example`**

In `.env.example`, after the `ALIEXPRESS_REFRESH_TOKEN=` line, add:

```
YOUTUBE_API_KEY=
```

- [ ] **Step 4: Document YouTube setup in the README**

In `README.md`, update the intro paragraph. Change:
```
100% gratuite et self-hosted. Croise Google Trends, Reddit, eBay et
AliExpress (3e et 4e sources optionnelles), ne remonte un signal fort que
si au moins 3 des 4 sources convergent sur la même fenêtre de temps.
```
to:
```
100% gratuite et self-hosted. Croise Google Trends, Reddit, eBay,
AliExpress et YouTube (3e, 4e et 5e sources optionnelles), ne remonte un
signal fort que si au moins 3 des 5 sources convergent sur la même
fenêtre de temps.
```

After the existing AliExpress setup section, add a new section:

```markdown
### YouTube (optionnel, 5e source de convergence)

L'authentification la plus simple des 5 sources — une seule clé API,
pas d'OAuth :

1. Crée un projet sur la [Google Cloud Console](https://console.cloud.google.com/)
   (gratuit, pas de carte bancaire requise).
2. Active la "YouTube Data API v3" dans la bibliothèque d'API du projet.
3. Crée une clé API dans "Identifiants" (Credentials).
4. Ajoute-la à `.env` :

```
YOUTUBE_API_KEY=ta_cle_api
```

Sans credentials, `scan` continue de fonctionner normalement, YouTube est
juste désactivé pour cette source (comme les autres sources optionnelles).

**Quota** : le plan gratuit permet ~100 recherches par jour
(`search.list` coûte 100 unités sur un quota de 10 000/jour, plafonné à
100 appels/jour) — largement suffisant pour un scan quotidien de la
watchlist actuelle (16 mots-clés = 16 appels).
```

- [ ] **Step 5: Commit**

```bash
git add config/watchlist.yaml .env.example README.md
git commit -m "docs: document YouTube setup, configure real threshold"
```

---

## Post-plan note (not a task, informational)

Once the user has a real `YOUTUBE_API_KEY` and runs a real `scan`, the
first real API response is a natural sanity check — unlike AliExpress,
there are no unverified structural assumptions here (the YouTube Data
API v3's `search.list`/`videos.list` response shapes used in this plan
are directly from Google's current public documentation, not inferred
from third-party guides), so no dedicated smoke-test procedure is needed
beyond watching stdout for an unexpected `YouTubeError` on the first run.
