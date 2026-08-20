# Google Trends Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Google Trends "realtime trending searches" as a 2nd
discovery source in `cli.py discover` — a Reddit-independent way to
surface candidate products, no new credentials required.

**Architecture:** A new standalone module `discovery/trends_scan.py`
fetches Google's realtime trending searches (top 20), then filters them
down to product-relevant candidates by cross-checking each term against
the already-connected eBay and YouTube collectors — a term is a
"confirmed candidate" only if at least one of those two returns a
non-zero signal. `cli.py cmd_discover` is restructured so Reddit and
Google Trends each run independently (mirroring `cmd_scan`'s existing
per-source resilience pattern): a Reddit failure no longer aborts the
whole discovery run, and both sources' candidates are merged into one
report/JSON output, tagged with a `source` field.

**Tech Stack:** Python, `pytrends` (already a dependency, already used
by `collectors/google_trends.py` — no new library), SQLite (historized,
INSERT-only).

## Global Constraints

- Free, self-hosted, official API only — no scraping.
- SQLite storage is append-only: every insert function uses
  `INSERT OR IGNORE`, never `UPDATE`/`DELETE`.
- No new credentials of any kind — `pytrends` runs unauthenticated
  (same as the existing `collectors/google_trends.py`), and eBay/YouTube
  are reused via their existing collector functions exactly as they are.
- Only the **first 20** trending terms returned by Google are checked
  against eBay/YouTube — checking all (up to 300) would blow YouTube's
  100-calls/day `search.list` quota, of which 16 are already used by the
  daily watchlist scan.
- A candidate is "confirmed" when **at least one** of eBay/YouTube
  returns a non-zero signal for that term — not both required.
- Never let a single source's failure abort the whole `cmd_discover` run
  — this applies to Reddit (already partially resilient, being
  strengthened here) and to the new Google Trends block equally. A
  failure on ONE trending term (eBay/YouTube error) must not abort
  checking the other 19 terms either.
- Follow the exact patterns of `collectors/google_trends.py` (retry/backoff
  on failure, wrap into `RuntimeError`, not a new exception class) and
  `discovery/velocity.py` (candidate dict shape) as they exist today.

---

### Task 1: Storage — `trends_discovery_candidates` table

**Files:**
- Modify: `storage/schema.sql`
- Modify: `storage/db.py`
- Test: `tests/test_trends_discovery_storage.py`

**Interfaces:**
- Produces: `db.insert_trends_discovery_candidate(conn, term: str, date: str, ebay_signal: bool, youtube_signal: bool) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_trends_discovery_storage.py`:

```python
from storage import db


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def test_insert_trends_discovery_candidate(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    db.insert_trends_discovery_candidate(conn, "led face mask", "2026-08-20", True, False)
    row = conn.execute(
        "SELECT term, date, ebay_signal, youtube_signal FROM trends_discovery_candidates"
    ).fetchone()
    assert row["term"] == "led face mask"
    assert row["date"] == "2026-08-20"
    assert row["ebay_signal"] == 1
    assert row["youtube_signal"] == 0
    conn.close()


def test_insert_trends_discovery_candidate_ignores_duplicate_term_and_date(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    db.insert_trends_discovery_candidate(conn, "led face mask", "2026-08-20", True, False)
    db.insert_trends_discovery_candidate(conn, "led face mask", "2026-08-20", False, True)
    rows = conn.execute("SELECT * FROM trends_discovery_candidates").fetchall()
    assert len(rows) == 1
    assert rows[0]["ebay_signal"] == 1  # la 1ere insertion gagne, INSERT OR IGNORE
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_trends_discovery_storage.py -v`
Expected: FAIL — `sqlite3.OperationalError: no such table: trends_discovery_candidates`

- [ ] **Step 3: Add the table to the schema**

In `storage/schema.sql`, add this table right after the existing
`youtube_snapshots` table definition (before the `CREATE INDEX` block at
the bottom of the file):

```sql
CREATE TABLE IF NOT EXISTS trends_discovery_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL,
    date TEXT NOT NULL,
    ebay_signal INTEGER NOT NULL,
    youtube_signal INTEGER NOT NULL,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(term, date)
);
```

No index is needed on this table for this plan — nothing queries it by
a non-primary-key column yet (see the spec's "Hors scope" section: this
table is a historical journal, not read back by `cmd_discover` in the
same run).

- [ ] **Step 4: Implement the storage function**

In `storage/db.py`, add after the last existing insert function (after
`insert_youtube_snapshot`/`get_youtube_snapshot_series`):

```python
def insert_trends_discovery_candidate(
    conn: sqlite3.Connection, term: str, date: str, ebay_signal: bool, youtube_signal: bool
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO trends_discovery_candidates (term, date, ebay_signal, youtube_signal)
           VALUES (?, ?, ?, ?)""",
        (term, date, int(ebay_signal), int(youtube_signal)),
    )
    conn.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_trends_discovery_storage.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add storage/schema.sql storage/db.py tests/test_trends_discovery_storage.py
git commit -m "feat: add trends_discovery_candidates storage"
```

---

### Task 2: Collector — `discovery/trends_scan.py`

**Files:**
- Create: `discovery/trends_scan.py`
- Test: `tests/test_trends_scan.py`

**Interfaces:**
- Consumes: `collectors.ebay.fetch_listing_count(keyword: str, marketplace: str = "EBAY_FR") -> int`
  (raises `ebay.EbayError` on failure; also raises `KeyError` internally
  via `get_app_token()` if eBay credentials are missing — both must be
  handled)
- Consumes: `collectors.youtube.fetch_recent_view_count(keyword: str) -> int`
  (raises `youtube.YouTubeError` on failure; also raises `KeyError`
  internally if `YOUTUBE_API_KEY` is missing — both must be handled)
- Produces: `trends_scan.fetch_trending_candidates(geo: str = "FR", limit: int = 20) -> list[dict]`,
  where each dict is
  `{"phrase": str, "source": "google_trends", "mention_count": 0, "growth_pct": 0, "ebay_signal": bool, "youtube_signal": bool}`.
  Raises `RuntimeError` if the Google Trends call itself fails (after
  retries) — never for a single term's eBay/YouTube check failing.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_trends_scan.py`:

```python
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from collectors import ebay, youtube
from discovery import trends_scan


def _fake_trending_df(titles):
    return pd.DataFrame({"title": titles})


def test_fetch_trending_candidates_confirms_term_with_ebay_signal(monkeypatch):
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.return_value = _fake_trending_df(["led face mask"])

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
        monkeypatch.setattr(ebay, "fetch_listing_count", lambda term, **kwargs: 42)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 0)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert len(candidates) == 1
    assert candidates[0] == {
        "phrase": "led face mask",
        "source": "google_trends",
        "mention_count": 0,
        "growth_pct": 0,
        "ebay_signal": True,
        "youtube_signal": False,
    }


def test_fetch_trending_candidates_confirms_term_with_youtube_signal_only(monkeypatch):
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.return_value = _fake_trending_df(["mini projecteur"])

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
        monkeypatch.setattr(ebay, "fetch_listing_count", lambda term, **kwargs: 0)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 1500)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert len(candidates) == 1
    assert candidates[0]["ebay_signal"] is False
    assert candidates[0]["youtube_signal"] is True


def test_fetch_trending_candidates_discards_term_with_no_signal(monkeypatch):
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.return_value = _fake_trending_df(["celebrity gossip"])

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
        monkeypatch.setattr(ebay, "fetch_listing_count", lambda term, **kwargs: 0)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 0)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert candidates == []


def test_fetch_trending_candidates_limits_to_first_n_terms(monkeypatch):
    titles = [f"term {i}" for i in range(30)]
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.return_value = _fake_trending_df(titles)

    call_count = {"ebay": 0}

    def _counting_ebay(term, **kwargs):
        call_count["ebay"] += 1
        return 1

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
        monkeypatch.setattr(ebay, "fetch_listing_count", _counting_ebay)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 0)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert call_count["ebay"] == 20
    assert len(candidates) == 20


def test_fetch_trending_candidates_one_term_failure_does_not_affect_others(monkeypatch):
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.return_value = _fake_trending_df(
        ["flaky term", "good term"]
    )

    def _flaky_ebay(term, **kwargs):
        if term == "flaky term":
            raise ebay.EbayError("simulated failure")
        return 5

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
        monkeypatch.setattr(ebay, "fetch_listing_count", _flaky_ebay)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 0)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    phrases = [c["phrase"] for c in candidates]
    assert "good term" in phrases
    assert "flaky term" not in phrases


def test_fetch_trending_candidates_treats_missing_ebay_credentials_as_no_signal(monkeypatch):
    """KeyError (credentials manquantes) doit etre traite comme 'pas de
    signal', pas comme une erreur qui remonte — coherent avec le reste du
    projet ou une source sans credentials est silencieusement desactivee."""
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.return_value = _fake_trending_df(["led face mask"])

    def _raise_key_error(term, **kwargs):
        raise KeyError("EBAY_CLIENT_ID")

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
        monkeypatch.setattr(ebay, "fetch_listing_count", _raise_key_error)
        monkeypatch.setattr(youtube, "fetch_recent_view_count", lambda term: 100)

        candidates = trends_scan.fetch_trending_candidates(geo="FR", limit=20)

    assert len(candidates) == 1
    assert candidates[0]["ebay_signal"] is False
    assert candidates[0]["youtube_signal"] is True


def test_fetch_trending_candidates_raises_runtime_error_on_google_trends_failure(monkeypatch):
    mock_pytrends = MagicMock()
    mock_pytrends.realtime_trending_searches.side_effect = RuntimeError("boom")

    with patch("discovery.trends_scan.TrendReq", return_value=mock_pytrends):
        monkeypatch.setattr(trends_scan.time, "sleep", lambda seconds: None)
        with pytest.raises(RuntimeError):
            trends_scan.fetch_trending_candidates(geo="FR", limit=20)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_trends_scan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'discovery.trends_scan'`

- [ ] **Step 3: Implement the collector**

Create `discovery/trends_scan.py`:

```python
"""Detection de recherches en tendance sur Google, sans mot-cle fourni a
l'avance (contrairement a collectors/google_trends.py, qui suit un
mot-cle donne dans le temps).

Google a deja fait le travail de detection de tendance : ce module ne
calcule aucune croissance, il recupere un instantane des N recherches
les plus en tendance actuellement (realtime_trending_searches), puis
filtre celles qui ont aussi un signal produit (eBay et/ou YouTube) pour
ecarter l'actualite generaliste (celebrites, sport, meteo...) que
pytrends renvoie sans distinction — meme logique de "convergence" que le
reste du projet, plutot qu'une couche NLP de filtrage supplementaire.

Note d'implementation : le nom exact de la colonne portant le terme de
recherche dans la reponse de realtime_trending_searches ('title') est
notre meilleure lecture de la lib pytrends au moment de l'ecriture — a
confirmer au premier run reel (voir aussi la note du module sur pytrends
etant archive depuis avril 2025, non bloquant pour l'instant).
"""
from __future__ import annotations

import time

from pytrends.request import TrendReq

from collectors import ebay
from collectors import youtube

_RESULTS_LIMIT = 20


def fetch_trending_candidates(geo: str = "FR", limit: int = _RESULTS_LIMIT) -> list[dict]:
    """Retourne les candidats confirmes parmi les `limit` premieres
    recherches en tendance sur Google (pn=geo) : ceux dont au moins un
    signal eBay ou YouTube est non-nul.

    Leve RuntimeError si l'appel Google Trends echoue (meme convention
    que collectors/google_trends.py). Un echec eBay/YouTube sur UN terme
    precis (EbayError/YouTubeError/KeyError pour credentials manquantes)
    exclut juste ce terme des signaux confirmes pour cette source, ne
    fait jamais planter le reste de la fonction."""
    terms = _fetch_trending_terms(geo)
    candidates = []
    for term in terms[:limit]:
        ebay_signal = _check_ebay_signal(term)
        youtube_signal = _check_youtube_signal(term)
        if ebay_signal or youtube_signal:
            candidates.append(
                {
                    "phrase": term,
                    "source": "google_trends",
                    "mention_count": 0,
                    "growth_pct": 0,
                    "ebay_signal": ebay_signal,
                    "youtube_signal": youtube_signal,
                }
            )
    return candidates


def _fetch_trending_terms(geo: str, retries: int = 2) -> list[str]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            pytrends = TrendReq(hl="fr-FR", tz=60)
            df = pytrends.realtime_trending_searches(pn=geo)
            if df is None or df.empty:
                return []
            return [str(t) for t in df["title"].tolist()]
        except Exception as exc:  # pytrends leve des exceptions requests generiques
            last_error = exc
            if attempt < retries:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(
        f"Echec fetch Google Trends realtime_trending_searches (geo={geo})"
    ) from last_error


def _check_ebay_signal(term: str) -> bool:
    try:
        return ebay.fetch_listing_count(term) > 0
    except (KeyError, ebay.EbayError):
        return False


def _check_youtube_signal(term: str) -> bool:
    try:
        return youtube.fetch_recent_view_count(term) > 0
    except (KeyError, youtube.YouTubeError):
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_trends_scan.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add discovery/trends_scan.py tests/test_trends_scan.py
git commit -m "feat: add Google Trends discovery collector with eBay/YouTube cross-validation"
```

---

### Task 3: CLI integration — `cmd_discover` resilience + merge

**Files:**
- Modify: `cli.py`
- Modify: `tests/test_cli_discover.py`
- Test: additions to `tests/test_cli_discover.py`

**Interfaces:**
- Consumes: `trends_scan.fetch_trending_candidates(geo, limit)` (Task 2)
- Consumes: `db.insert_trends_discovery_candidate(conn, term, date, ebay_signal, youtube_signal)` (Task 1)
- Consumes: `velocity.find_candidates(...)` (existing, returns `list[dict]`
  with `phrase`/`mention_count`/`growth_pct` keys — unchanged)

- [ ] **Step 1: Fix the existing test that will otherwise hit the real network**

`tests/test_cli_discover.py::test_cmd_discover_skips_without_reddit_credentials`
currently calls `cli.cmd_discover(...)` with Reddit credentials missing
and asserts on the printed message, relying on `cmd_discover` returning
immediately after the Reddit failure. After this task, `cmd_discover`
will continue past a Reddit failure and attempt Google Trends discovery
instead — which would make this existing test perform a **real network
call** to Google Trends unless it's also mocked. Fix this first, before
writing new tests, so nothing regresses silently:

In `tests/test_cli_discover.py`, add the import:
```python
from discovery import trends_scan
```

Update `test_cmd_discover_skips_without_reddit_credentials`:
```python
def test_cmd_discover_skips_without_reddit_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(trends_scan, "fetch_trending_candidates", lambda **kwargs: [])

    def _raise_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_key_error)

    cli.cmd_discover({"discovery": {"subreddits": ["gadgets"]}})

    captured = capsys.readouterr()
    assert "credentials manquants" in captured.out
```

Also update `test_cmd_discover_writes_report` the same way — add
`monkeypatch.setattr(trends_scan, "fetch_trending_candidates", lambda **kwargs: [])`
right after its existing `monkeypatch.setattr(storage_db, "DB_PATH", ...)`
line, so it doesn't hit the network either (this test currently succeeds
with real Reddit credentials mocked, but Google Trends is a brand-new,
separately-unmocked code path it will now also execute).

Run: `python3 -m pytest tests/test_cli_discover.py -v`
Expected: PASS (both existing tests, now hermetic against the network)

- [ ] **Step 2: Write the new failing tests**

In `tests/test_cli_discover.py`, add at the end:

```python
def test_cmd_discover_includes_google_trends_candidates_when_reddit_unavailable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", tmp_path / "discovery_report.md")

    def _raise_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_key_error)

    fake_candidate = {
        "phrase": "led face mask",
        "source": "google_trends",
        "mention_count": 0,
        "growth_pct": 0,
        "ebay_signal": True,
        "youtube_signal": False,
    }
    monkeypatch.setattr(trends_scan, "fetch_trending_candidates", lambda **kwargs: [fake_candidate])

    cli.cmd_discover({"discovery": {"subreddits": []}})

    import json

    data = json.loads((tmp_path / "signals.json").read_text())
    phrases = [c["phrase"] for c in data["discovery"]]
    assert "led face mask" in phrases
    sources = {c["phrase"]: c["source"] for c in data["discovery"]}
    assert sources["led face mask"] == "google_trends"


def test_cmd_discover_continues_when_google_trends_fails(tmp_path, monkeypatch):
    """Un echec Google Trends ne doit pas empecher les candidats Reddit
    d'apparaitre dans le meme run (independance des deux sources de
    decouverte, meme principe que cmd_scan)."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", tmp_path / "discovery_report.md")

    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())
    monkeypatch.setattr(
        reddit_scan,
        "scan_subreddits",
        lambda reddit, subreddits, post_limit: [
            {"subreddit": "gadgets", "title": "This LED face mask is amazing"},
            {"subreddit": "gadgets", "title": "I love my LED face mask so much"},
        ],
    )

    def _raise_runtime_error(**kwargs):
        raise RuntimeError("simulated Google Trends failure")

    monkeypatch.setattr(trends_scan, "fetch_trending_candidates", _raise_runtime_error)

    watchlist = {
        "discovery": {
            "subreddits": ["gadgets"],
            "post_limit": 10,
            "min_mentions": 1,
            "min_growth_pct": 0,
        }
    }

    cli.cmd_discover(watchlist)  # ne doit pas lever d'exception

    assert "led face mask" in (tmp_path / "discovery_report.md").read_text()


def test_cmd_discover_one_trending_term_failure_does_not_lose_reddit_candidates(
    tmp_path, monkeypatch
):
    """Verifie que la fusion des deux listes garde les candidats Reddit
    meme quand Google Trends renvoie une liste vide (aucun candidat
    confirme, sans que ce soit une erreur)."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", tmp_path / "discovery_report.md")

    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())
    monkeypatch.setattr(
        reddit_scan,
        "scan_subreddits",
        lambda reddit, subreddits, post_limit: [
            {"subreddit": "gadgets", "title": "This LED face mask is amazing"},
            {"subreddit": "gadgets", "title": "I love my LED face mask so much"},
        ],
    )
    monkeypatch.setattr(trends_scan, "fetch_trending_candidates", lambda **kwargs: [])

    watchlist = {
        "discovery": {
            "subreddits": ["gadgets"],
            "post_limit": 10,
            "min_mentions": 1,
            "min_growth_pct": 0,
        }
    }

    cli.cmd_discover(watchlist)

    import json

    data = json.loads((tmp_path / "signals.json").read_text())
    phrases = [c["phrase"] for c in data["discovery"]]
    assert "led face mask" in phrases
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cli_discover.py -v`
Expected: FAIL — `ModuleNotFoundError` on the `from discovery import trends_scan`
import in the test file is NOT expected (Task 2 already created that
module), but `AttributeError`-style failures ARE expected since
`cli.py`'s `cmd_discover` doesn't call `trends_scan.fetch_trending_candidates`
yet, and the new tests' assertions about `source` fields in `signals.json`
will fail against the current (Reddit-only) output shape.

- [ ] **Step 4: Restructure `cmd_discover`**

In `cli.py`, add the import near the other `discovery` imports:

```python
from discovery import extract, promote, reddit_scan, trends_scan, velocity
```

Replace the entire body of `cmd_discover` with:

```python
def cmd_discover(watchlist: dict, publish_after: bool = False) -> None:
    """Discovery : detecte des candidats emergents sans mots-cles, via Reddit et/ou Google Trends."""
    db.init_db()
    conn = db.get_connection()
    discovery_cfg = watchlist.get("discovery", {})
    subreddits = discovery_cfg.get("subreddits", [])
    post_limit = discovery_cfg.get("post_limit", 50)
    min_mentions = discovery_cfg.get("min_mentions", 5)
    min_growth = discovery_cfg.get("min_growth_pct", 30)

    reddit_candidates: list[dict] = []
    try:
        reddit_client = reddit_collector.get_client()
    except KeyError:
        reddit_client = None
        print("Reddit : credentials manquants, discovery Reddit desactivee pour ce run")

    if reddit_client:
        try:
            # Echoue vite si le modele spaCy manque, avant de consommer le budget
            # d'appels Reddit sur un scan complet (voir discovery.extract.ensure_model).
            extract.ensure_model()

            print(f"Discovery : scan de {len(subreddits)} subreddits...")
            posts = reddit_scan.scan_subreddits(reddit_client, subreddits, post_limit=post_limit)

            titles_by_subreddit: dict[str, list[str]] = {}
            for p in posts:
                titles_by_subreddit.setdefault(p["subreddit"], []).append(p["title"])

            now = datetime.now(timezone.utc).isoformat()
            mentions = []
            for subreddit, titles in titles_by_subreddit.items():
                phrase_counts = extract.extract_phrases(titles)
                for phrase, count in phrase_counts.items():
                    mentions.append({
                        "phrase": phrase,
                        "subreddit": subreddit,
                        "mention_count": count,
                        "window_start": now,
                        "window_end": now,
                    })
            db.insert_phrase_mentions(conn, mentions)

            found = velocity.find_candidates(
                conn, min_mentions=min_mentions, min_growth_pct=min_growth, current_window=now
            )
            reddit_candidates = [{**c, "source": "reddit"} for c in found]
        except Exception as exc:
            print(f"Discovery Reddit : echec, continue sans ces candidats : {exc}")

    trends_candidates: list[dict] = []
    try:
        trends_geo = watchlist.get("trends_geo", "FR")
        found = trends_scan.fetch_trending_candidates(geo=trends_geo, limit=20)
        today = datetime.now(timezone.utc).date().isoformat()
        for c in found:
            db.insert_trends_discovery_candidate(
                conn, c["phrase"], today, c["ebay_signal"], c["youtube_signal"]
            )
        trends_candidates = found
    except RuntimeError as exc:
        print(f"Discovery Google Trends : echec, continue sans ces candidats : {exc}")

    conn.close()

    candidates = reddit_candidates + trends_candidates
    write_discovery_report(candidates)
    signal_entries = [
        {
            "phrase": c["phrase"],
            "source": c.get("source", "reddit"),
            "mention_count": c["mention_count"],
            "growth_pct": c["growth_pct"],
            "ebay_signal": c.get("ebay_signal", False),
            "youtube_signal": c.get("youtube_signal", False),
        }
        for c in candidates
    ]
    write_signals_json("discovery", signal_entries)
    if publish_after:
        publish.publish_json(
            Path(__file__).parent, os.path.relpath(SIGNALS_JSON_PATH, Path(__file__).parent)
        )
```

- [ ] **Step 5: Update `write_discovery_report` to render each source appropriately**

In `cli.py`, replace `write_discovery_report`:

```python
def write_discovery_report(candidates: list[dict]) -> None:
    """Genere un rapport Markdown des candidats discovery, trie par croissance."""
    lines = ["# Rapport discovery — trend-radar", ""]
    if not candidates:
        lines.append("Aucun candidat au-dessus des seuils pour ce scan.")
    for c in candidates:
        source = c.get("source", "reddit")
        lines.append(f"## {c['phrase']} ({source})")
        if source == "google_trends":
            lines.append(f"- Signal eBay : {'oui' if c.get('ebay_signal') else 'non'}")
            lines.append(f"- Signal YouTube : {'oui' if c.get('youtube_signal') else 'non'}")
        else:
            lines.append(f"- Mentions cette fenetre : {c['mention_count']}")
            lines.append(f"- Croissance : {c['growth_pct']}%")
        lines.append(f"- Pour suivre ce candidat : `python cli.py promote \"{c['phrase']}\" <categorie>`")
        lines.append("")
    DISCOVERY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Rapport discovery ecrit : {DISCOVERY_REPORT_PATH}")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cli_discover.py -v`
Expected: PASS (5 tests: 2 fixed existing + 3 new)

Run the full suite to confirm nothing else broke:
Run: `python3 -m pytest -v`
Expected: PASS (all tests, no regressions)

- [ ] **Step 7: Commit**

```bash
git add cli.py tests/test_cli_discover.py
git commit -m "feat: run Reddit and Google Trends discovery independently, merge candidates"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:** None — documentation only, no code.

- [ ] **Step 1: Document the new discovery source**

In `README.md`, find the section describing the discovery mode (search
for "discover" or "mode discovery" in the file to locate it). Add a
short paragraph after the existing discovery description:

```markdown
Depuis peu, `discover` combine deux sources independantes :
- **Reddit** (hot/rising sur les subreddits configures) — necessite
  REDDIT_CLIENT_ID/SECRET.
- **Google Trends** (recherches en tendance en temps reel, filtrees via
  eBay/YouTube pour ne garder que les candidats plausiblement produits)
  — aucune credential requise, fonctionne meme si Reddit est bloque.

Les deux sources tournent independamment : si l'une echoue, l'autre
continue de produire des candidats normalement.
```

- [ ] **Step 2: Verify the full suite still passes**

Run: `python3 -m pytest -v`
Expected: PASS (all tests — sanity check, this task doesn't touch code)

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document Google Trends discovery source"
```
