# eBay Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add eBay (Browse API active-listing count) as a 3rd convergence source in trend-radar, so a strong signal (2+ sources) is reachable via Trends+eBay without depending on Reddit.

**Architecture:** A new `collectors/ebay.py` (OAuth2 client-credentials via `requests`) mirrors the existing `collectors/google_trends.py` shape. A new `ebay_snapshots` table stores one listing-count data point per scan (unlike Trends, which returns a full history in one call). `scoring/convergence.py` gains a 3rd branch reusing the existing `growth_pct` helper. `cli.py`'s `cmd_scan` wires it in with the same resilience conventions already established for Trends/Reddit failures.

**Tech Stack:** Python, `requests` (new direct dependency, already present transitively via `pytrends`), SQLite (historized, same convention as the rest of the project).

## Global Constraints

- Gratuit et self-hosted : eBay Browse API officielle, OAuth2 client-credentials, aucune dependance payante (spec: contraintes projet).
- Un echec eBay (credentials manquantes OU erreur API sur un mot-cle) ne doit **jamais** faire planter tout le scan (spec: Gestion d'erreurs) — meme convention que le correctif deja applique a Google Trends dans ce projet.
- Interfaces exactes attendues (des taches futures en dependent) :
  - `collectors.ebay.get_app_token() -> str` (leve `KeyError` si credentials manquantes)
  - `collectors.ebay.fetch_listing_count(keyword: str, marketplace: str = "EBAY_FR") -> int` (leve `collectors.ebay.EbayError` sur echec API)
  - `storage.db.insert_ebay_snapshot(conn, keyword_id: int, date: str, listing_count: int, marketplace: str) -> None`
  - `storage.db.get_ebay_snapshot_series(conn, keyword_id: int) -> list[tuple[str, int]]`
- `growth_pct` (deja existant dans `collectors/google_trends.py`) est reutilise tel quel pour eBay, avec `window_days=1` (un seul point de donnee par scan, contrairement a Trends) — ne pas dupliquer cette logique.
- `sources_count` passe naturellement de `/2` a `/3` ; le seuil "signal FORT" reste `sources_count >= 2` (pas de changement de ce seuil).

---

## File Structure

**Create:**
- `collectors/ebay.py` — auth OAuth2 + recherche du nombre d'annonces actives
- `tests/test_ebay.py`
- `tests/test_ebay_storage.py`
- `tests/test_convergence.py` (le fichier `scoring/convergence.py` n'a actuellement aucun test dedie — cette tache comble ce trou en meme temps qu'elle ajoute la 3e source)
- `tests/test_cli_scan_ebay.py`

**Modify:**
- `storage/schema.sql` — ajoute la table `ebay_snapshots` + index
- `storage/db.py` — ajoute `insert_ebay_snapshot`, `get_ebay_snapshot_series`
- `scoring/convergence.py` — ajoute la branche eBay
- `cli.py` — integre eBay dans `cmd_scan` (credentials + boucle par mot-cle + `signal_entries`)
- `config/watchlist.yaml` — ajoute `ebay_marketplace` et `thresholds.ebay_growth_pct`
- `requirements.txt` — ajoute `requests`
- `.env.example` — ajoute `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET`/`EBAY_ENVIRONMENT`
- `README.md` — documente la configuration eBay

---

### Task 1: Table `ebay_snapshots` + helpers storage

**Files:**
- Modify: `storage/schema.sql`
- Modify: `storage/db.py`
- Test: `tests/test_ebay_storage.py`

**Interfaces:**
- Consumes: rien (premiere tache)
- Produces:
  - `storage.db.insert_ebay_snapshot(conn: sqlite3.Connection, keyword_id: int, date: str, listing_count: int, marketplace: str) -> None`
  - `storage.db.get_ebay_snapshot_series(conn: sqlite3.Connection, keyword_id: int) -> list[tuple[str, int]]`

- [ ] **Step 1: Ecrire le test qui echoue**

Creer `tests/test_ebay_storage.py` :

```python
from storage import db


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def test_insert_and_get_ebay_snapshot_series(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "led face mask", "gadgets")
    db.insert_ebay_snapshot(conn, kid, "2026-08-18", 120, "EBAY_FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-19", 150, "EBAY_FR")
    series = db.get_ebay_snapshot_series(conn, kid)
    assert series == [("2026-08-18", 120), ("2026-08-19", 150)]
    conn.close()


def test_insert_ebay_snapshot_ignores_duplicate_date(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "led face mask", "gadgets")
    db.insert_ebay_snapshot(conn, kid, "2026-08-18", 120, "EBAY_FR")
    db.insert_ebay_snapshot(conn, kid, "2026-08-18", 999, "EBAY_FR")
    series = db.get_ebay_snapshot_series(conn, kid)
    assert series == [("2026-08-18", 120)]
    conn.close()
```

- [ ] **Step 2: Lancer les tests pour verifier qu'ils echouent**

Run: `pytest tests/test_ebay_storage.py -v`
Expected: FAIL avec `AttributeError: module 'storage.db' has no attribute 'insert_ebay_snapshot'`

- [ ] **Step 3: Ajouter la table au schema**

Dans `storage/schema.sql`, ajouter apres la table `phrase_mentions` (avant la section des index) :

```sql
CREATE TABLE IF NOT EXISTS ebay_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    date TEXT NOT NULL,
    listing_count INTEGER NOT NULL,
    marketplace TEXT,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(keyword_id, date, marketplace)
);
```

Et ajouter l'index avec les autres :

```sql
CREATE INDEX IF NOT EXISTS idx_ebay_keyword ON ebay_snapshots(keyword_id);
```

- [ ] **Step 4: Implementer les helpers dans `storage/db.py`**

Ajouter a la fin du fichier :

```python
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
```

- [ ] **Step 5: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_ebay_storage.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add storage/schema.sql storage/db.py tests/test_ebay_storage.py
git commit -m "feat: add ebay_snapshots table and storage helpers"
```

---

### Task 2: Collecteur eBay (`collectors/ebay.py`)

**Files:**
- Create: `collectors/ebay.py`
- Test: `tests/test_ebay.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: rien
- Produces:
  - `collectors.ebay.get_app_token() -> str` (leve `KeyError` si `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET` absentes)
  - `collectors.ebay.fetch_listing_count(keyword: str, marketplace: str = "EBAY_FR") -> int`
  - `collectors.ebay.EbayError` (sous-classe de `RuntimeError`)

- [ ] **Step 1: Ajouter `requests` aux dependances**

Ajouter une ligne `requests` dans `requirements.txt` (deja present en dependance transitive via `pytrends`, mais doit etre declare explicitement puisqu'on l'importe directement).

- [ ] **Step 2: Ecrire le test qui echoue**

Creer `tests/test_ebay.py` :

```python
import time
from unittest.mock import MagicMock, patch

import pytest

from collectors import ebay


def test_get_app_token_caches_token(monkeypatch):
    monkeypatch.setenv("EBAY_CLIENT_ID", "test-id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("EBAY_ENVIRONMENT", "PRODUCTION")
    ebay._token_cache.clear()

    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "tok123", "expires_in": 7200}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.ebay.requests.post", return_value=mock_response) as mock_post:
        token1 = ebay.get_app_token()
        token2 = ebay.get_app_token()

    assert token1 == "tok123"
    assert token2 == "tok123"
    mock_post.assert_called_once()


def test_get_app_token_missing_credentials_raises_key_error(monkeypatch):
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("EBAY_ENVIRONMENT", "PRODUCTION")
    ebay._token_cache.clear()

    with pytest.raises(KeyError):
        ebay.get_app_token()


def test_fetch_listing_count_parses_total(monkeypatch):
    ebay._token_cache["PRODUCTION"] = ("cached-token", time.time() + 999)

    mock_response = MagicMock()
    mock_response.json.return_value = {"total": 4213, "itemSummaries": []}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.ebay.requests.get", return_value=mock_response) as mock_get:
        count = ebay.fetch_listing_count("led face mask")

    assert count == 4213
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs["params"]["q"] == "led face mask"
    assert call_kwargs["params"]["limit"] == 1


def test_fetch_listing_count_raises_ebay_error_on_http_failure(monkeypatch):
    ebay._token_cache["PRODUCTION"] = ("cached-token", time.time() + 999)

    import requests as requests_module

    with patch(
        "collectors.ebay.requests.get",
        side_effect=requests_module.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(ebay.EbayError):
            ebay.fetch_listing_count("led face mask")
```

- [ ] **Step 3: Lancer les tests pour verifier qu'ils echouent**

Run: `pip install -r requirements.txt && pytest tests/test_ebay.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'collectors.ebay'`

- [ ] **Step 4: Implementer `collectors/ebay.py`**

```python
"""Collecteur eBay Browse API (annonces actives, OAuth2 client-credentials).

API officielle et gratuite. Suit le nombre d'annonces actives correspondant
a une recherche comme signal de demande indirect — les ventes conclues ne
sont pas exposees par une API officielle gratuite (meme constat que le
connecteur eBay de collector-arbitrage, un autre projet de l'utilisateur).
"""
from __future__ import annotations

import base64
import os
import time

import requests

_ENDPOINTS = {
    "PRODUCTION": {
        "token": "https://api.ebay.com/identity/v1/oauth2/token",
        "browse": "https://api.ebay.com/buy/browse/v1/item_summary/search",
    },
    "SANDBOX": {
        "token": "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
        "browse": "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search",
    },
}

# Cache memoire simple du token d'application (valable ~2h cote eBay)
_token_cache: dict[str, tuple[str, float]] = {}


class EbayError(RuntimeError):
    pass


def get_app_token() -> str:
    """OAuth2 client-credentials. Leve KeyError si EBAY_CLIENT_ID/EBAY_CLIENT_SECRET
    ne sont pas definies en env (meme convention que collectors.reddit.get_client)."""
    env = os.environ.get("EBAY_ENVIRONMENT", "PRODUCTION")
    cached = _token_cache.get(env)
    if cached and cached[1] > time.time() + 30:
        return cached[0]

    client_id = os.environ["EBAY_CLIENT_ID"]
    client_secret = os.environ["EBAY_CLIENT_SECRET"]

    endpoints = _ENDPOINTS[env]
    basic_auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")

    try:
        resp = requests.post(
            endpoints["token"],
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            headers={
                "Authorization": f"Basic {basic_auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise EbayError(f"Echec authentification eBay : {exc}") from exc

    data = resp.json()
    token = data["access_token"]
    expires_at = time.time() + int(data.get("expires_in", 7200))
    _token_cache[env] = (token, expires_at)
    return token


def fetch_listing_count(keyword: str, marketplace: str = "EBAY_FR") -> int:
    """Retourne le nombre total d'annonces actives correspondant a la
    recherche (champ 'total' de la reponse Browse API, limit=1 pour
    economiser la bande passante : on ne lit pas les annonces elles-memes)."""
    env = os.environ.get("EBAY_ENVIRONMENT", "PRODUCTION")
    endpoints = _ENDPOINTS[env]
    token = get_app_token()

    try:
        resp = requests.get(
            endpoints["browse"],
            params={"q": keyword, "limit": 1},
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": marketplace,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise EbayError(f"Echec recherche eBay pour '{keyword}' : {exc}") from exc

    data = resp.json()
    return int(data.get("total", 0))
```

- [ ] **Step 5: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_ebay.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add collectors/ebay.py tests/test_ebay.py requirements.txt
git commit -m "feat: add eBay Browse API collector (OAuth2 client-credentials)"
```

---

### Task 3: Scoring — 3e source (`scoring/convergence.py`)

**Files:**
- Modify: `scoring/convergence.py`
- Test: `tests/test_convergence.py`

**Interfaces:**
- Consumes: `collectors.google_trends.growth_pct` (existant, deja importe dans ce fichier). Note : la requete des snapshots eBay se fait en SQL inline directement dans cette fonction, comme pour `trends_rows`/`reddit_rows` juste au-dessus dans le meme fichier — pas d'appel a `storage.db.get_ebay_snapshot_series` (Task 1), qui reste un helper public teste et reutilisable mais que `compute_convergence` n'utilise pas, par coherence avec le style deja en place dans cette fonction (aucune des deux autres sources n'y passe par `storage/db.py` non plus).
- Produces: `compute_convergence` inchange en signature, mais `details` gagne la cle `ebay_growth_pct`, `signals_detected` gagne la cle `ebay`, et `sources_count` peut maintenant valoir 0 a 3

**Note** : `scoring/convergence.py` n'a actuellement aucun test dedie dans le projet — cette tache en ajoute pour la premiere fois, en meme temps qu'elle ajoute la 3e source.

- [ ] **Step 1: Ecrire le test qui echoue**

Creer `tests/test_convergence.py` :

```python
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
```

- [ ] **Step 2: Lancer les tests pour verifier qu'ils echouent**

Run: `pytest tests/test_convergence.py -v`
Expected: FAIL — `KeyError: 'ebay_growth_pct'` (thresholds dict n'est pas encore lu pour eBay) ou `AssertionError` sur `sources_count`

- [ ] **Step 3: Modifier `scoring/convergence.py`**

Remplacer :

```python
    reddit_rows = conn.execute(
        "SELECT score FROM reddit_signals WHERE keyword_id = ? AND created_utc >= ?",
        (keyword_id, window_start),
    ).fetchall()
    reddit_count = len(reddit_rows)
    reddit_avg_score = sum(r["score"] for r in reddit_rows) / reddit_count if reddit_count else 0
    signals_detected["reddit"] = (
        reddit_count >= thresholds["reddit_min_posts"]
        and reddit_avg_score >= thresholds["reddit_min_avg_score"]
    )

    sources_count = sum(1 for v in signals_detected.values() if v)
    # Score = 10 points par source en convergence + bonus intensite (croissance trends, volume reddit)
    convergence_score = sources_count * 10 + max(trends_growth, 0) * 0.1 + reddit_count * 0.5

    return {
        "keyword_id": keyword_id,
        "window_start": window_start,
        "window_end": window_end,
        "sources_count": sources_count,
        "convergence_score": round(convergence_score, 2),
        "details": {
            "trends_growth_pct": round(trends_growth, 1),
            "reddit_post_count": reddit_count,
            "reddit_avg_score": round(reddit_avg_score, 1),
            "signals_detected": signals_detected,
        },
    }
```

par :

```python
    reddit_rows = conn.execute(
        "SELECT score FROM reddit_signals WHERE keyword_id = ? AND created_utc >= ?",
        (keyword_id, window_start),
    ).fetchall()
    reddit_count = len(reddit_rows)
    reddit_avg_score = sum(r["score"] for r in reddit_rows) / reddit_count if reddit_count else 0
    signals_detected["reddit"] = (
        reddit_count >= thresholds["reddit_min_posts"]
        and reddit_avg_score >= thresholds["reddit_min_avg_score"]
    )

    ebay_rows = conn.execute(
        "SELECT date, listing_count FROM ebay_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    ebay_snapshots = [(r["date"], r["listing_count"]) for r in ebay_rows]
    ebay_growth = growth_pct(ebay_snapshots, window_days=1)
    signals_detected["ebay"] = ebay_growth >= thresholds["ebay_growth_pct"]

    sources_count = sum(1 for v in signals_detected.values() if v)
    # Score = 10 points par source en convergence + bonus intensite (croissance trends, volume reddit, croissance eBay)
    convergence_score = (
        sources_count * 10
        + max(trends_growth, 0) * 0.1
        + reddit_count * 0.5
        + max(ebay_growth, 0) * 0.1
    )

    return {
        "keyword_id": keyword_id,
        "window_start": window_start,
        "window_end": window_end,
        "sources_count": sources_count,
        "convergence_score": round(convergence_score, 2),
        "details": {
            "trends_growth_pct": round(trends_growth, 1),
            "reddit_post_count": reddit_count,
            "reddit_avg_score": round(reddit_avg_score, 1),
            "ebay_growth_pct": round(ebay_growth, 1),
            "signals_detected": signals_detected,
        },
    }
```

- [ ] **Step 4: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_convergence.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lancer toute la suite de tests**

Run: `pytest -v`
Expected: PASS (tous les tests, Tasks 1-3 incluses)

- [ ] **Step 6: Commit**

```bash
git add scoring/convergence.py tests/test_convergence.py
git commit -m "feat: add eBay as 3rd convergence source in scoring"
```

---

### Task 4: Integration CLI (`cli.py`)

**Files:**
- Modify: `cli.py`
- Test: `tests/test_cli_scan_ebay.py`

**Interfaces:**
- Consumes: `collectors.ebay.get_app_token`, `collectors.ebay.fetch_listing_count`, `collectors.ebay.EbayError` (Task 2) ; `storage.db.insert_ebay_snapshot` (Task 1)
- Produces: rien de nouveau — `cmd_scan` gagne un comportement, signature inchangee

- [ ] **Step 1: Ecrire le test qui echoue**

Creer `tests/test_cli_scan_ebay.py` :

```python
import json

from collectors import ebay
from collectors import google_trends
from collectors import reddit as reddit_collector
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
        },
    }


def _patch_common(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(google_trends, "fetch_interest_over_time", lambda *a, **k: [])

    def _raise_reddit_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_reddit_key_error)


def test_cmd_scan_skips_ebay_when_credentials_missing(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    def _raise_ebay_key_error():
        raise KeyError("EBAY_CLIENT_ID")

    monkeypatch.setattr(ebay, "get_app_token", _raise_ebay_key_error)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    assert data["watchlist"][0]["ebay_growth_pct"] == 0.0


def test_cmd_scan_continues_when_ebay_fails_for_one_keyword(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    monkeypatch.setattr(ebay, "get_app_token", lambda: "fake-token")

    def _flaky_fetch(keyword, **kwargs):
        raise ebay.EbayError("simulated failure")

    monkeypatch.setattr(ebay, "fetch_listing_count", _flaky_fetch)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    assert len(data["watchlist"]) == 1
    assert data["watchlist"][0]["keyword"] == "test kw"


def test_cmd_scan_stores_ebay_snapshot_when_available(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    monkeypatch.setattr(ebay, "get_app_token", lambda: "fake-token")
    monkeypatch.setattr(ebay, "fetch_listing_count", lambda keyword, **kwargs: 4213)

    cli.cmd_scan(_base_watchlist())

    conn = storage_db.get_connection()
    kid = storage_db.get_or_create_keyword(conn, "test kw", "gadgets")
    series = storage_db.get_ebay_snapshot_series(conn, kid)
    conn.close()
    assert series[-1][1] == 4213
```

- [ ] **Step 2: Lancer les tests pour verifier qu'ils echouent**

Run: `pytest tests/test_cli_scan_ebay.py -v`
Expected: FAIL — `KeyError: 'ebay_growth_pct'` (le champ n'existe pas encore dans `signal_entries`) ou comportement de crash au lieu de skip propre

- [ ] **Step 3: Modifier `cli.py`**

Ajouter aux imports, a cote de `from collectors import google_trends` :

```python
from collectors import ebay
```

Remplacer le bloc de detection Reddit (avant la boucle `for category, cat_data in ...`) :

```python
    try:
        reddit_client = reddit_collector.get_client()
    except KeyError:
        reddit_client = None
        print("Reddit : credentials manquants, collecte Reddit desactivee pour ce scan")
```

par (ajoute le meme bloc pour eBay juste apres) :

```python
    try:
        reddit_client = reddit_collector.get_client()
    except KeyError:
        reddit_client = None
        print("Reddit : credentials manquants, collecte Reddit desactivee pour ce scan")

    try:
        ebay.get_app_token()
        ebay_available = True
    except KeyError:
        ebay_available = False
        print("eBay : credentials manquantes, collecte eBay desactivee pour ce scan")
    except ebay.EbayError as exc:
        ebay_available = False
        print(f"eBay : authentification impossible, collecte eBay desactivee pour ce scan : {exc}")
```

Remplacer, dans la boucle par mot-cle, juste apres le bloc `if reddit_client: ...` :

```python
            if reddit_client:
                posts = reddit_collector.search_keyword(
                    reddit_client,
                    keyword,
                    subreddits,
                    time_filter=watchlist.get("reddit_time_filter", "month"),
                    limit=watchlist.get("reddit_post_limit", 25),
                )
                db.insert_reddit_posts(conn, keyword_id, posts)

            result = compute_convergence(conn, keyword_id, thresholds)
```

par :

```python
            if reddit_client:
                posts = reddit_collector.search_keyword(
                    reddit_client,
                    keyword,
                    subreddits,
                    time_filter=watchlist.get("reddit_time_filter", "month"),
                    limit=watchlist.get("reddit_post_limit", 25),
                )
                db.insert_reddit_posts(conn, keyword_id, posts)

            if ebay_available:
                marketplace = watchlist.get("ebay_marketplace", "EBAY_FR")
                try:
                    listing_count = ebay.fetch_listing_count(keyword, marketplace=marketplace)
                    today = datetime.now(timezone.utc).date().isoformat()
                    db.insert_ebay_snapshot(conn, keyword_id, today, listing_count, marketplace)
                except ebay.EbayError as exc:
                    print(f"  Echec eBay pour '{keyword}', continue sans ce signal : {exc}")

            result = compute_convergence(conn, keyword_id, thresholds)
```

Modifier `signal_entries` (dans le bloc apres `write_report(results)`) — remplacer :

```python
    signal_entries = [
        {
            "keyword": r["keyword"],
            "category": r["category"],
            "convergence_score": r["convergence_score"],
            "sources_count": r["sources_count"],
            "trends_growth_pct": r["details"]["trends_growth_pct"],
            "reddit_post_count": r["details"]["reddit_post_count"],
            "reddit_avg_score": r["details"]["reddit_avg_score"],
        }
        for r in results
    ]
```

par :

```python
    signal_entries = [
        {
            "keyword": r["keyword"],
            "category": r["category"],
            "convergence_score": r["convergence_score"],
            "sources_count": r["sources_count"],
            "trends_growth_pct": r["details"]["trends_growth_pct"],
            "reddit_post_count": r["details"]["reddit_post_count"],
            "reddit_avg_score": r["details"]["reddit_avg_score"],
            "ebay_growth_pct": r["details"]["ebay_growth_pct"],
        }
        for r in results
    ]
```

- [ ] **Step 4: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_cli_scan_ebay.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lancer toute la suite de tests**

Run: `pytest -v`
Expected: PASS (tous les tests, Tasks 1-4 incluses)

- [ ] **Step 6: Commit**

```bash
git add cli.py tests/test_cli_scan_ebay.py
git commit -m "feat: wire eBay collector into cmd_scan"
```

---

### Task 5: Configuration reelle, `.env.example`, documentation, verification finale

**Files:**
- Modify: `config/watchlist.yaml`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: rien (configuration et documentation, pas de nouveau code)
- Produces: rien de nouveau — cloture le plan

- [ ] **Step 1: Ajouter la configuration eBay a `config/watchlist.yaml`**

Ajouter `ebay_marketplace: "EBAY_FR"` juste apres la ligne `trends_geo: "FR"` existante.

Ajouter `ebay_growth_pct: 20` a la fin du bloc `thresholds:` existant (a cote de `trends_growth_pct`, `reddit_min_posts`, `reddit_min_avg_score`).

- [ ] **Step 2: Documenter les credentials dans `.env.example`**

Ajouter a la fin du fichier :

```
EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=
EBAY_ENVIRONMENT=PRODUCTION
```

- [ ] **Step 3: Documenter dans `README.md`**

Ajouter apres la section existante qui documente les credentials Reddit :

```markdown
### eBay (optionnel, 3e source de convergence)

Cree une "application" sur https://developer.ebay.com/my/keys (environnement
**Production**, pas Sandbox), recupere l'App ID et le Cert ID, ajoute-les a
`.env` :

```
EBAY_CLIENT_ID=ton_app_id
EBAY_CLIENT_SECRET=ton_cert_id
EBAY_ENVIRONMENT=PRODUCTION
```

Ta cle Production doit etre "compliant" (section Alerts & Notifications de
la page Application Keys) — si tu n'utilises pas d'endpoint de notification,
demande l'exemption "Marketplace Account Deletion", gratuite et immediate
pour un usage en lecture seule comme celui-ci.

Sans credentials, `scan` continue de fonctionner normalement, eBay est juste
desactive pour cette source.
```

- [ ] **Step 4: Verification finale complete**

Run: `pytest -v`
Expected: PASS (tous les tests)

Run: `python3 -m py_compile cli.py collectors/*.py discovery/*.py storage/*.py scoring/*.py publish.py`
Expected: aucune erreur

Run: `python3 -c "import yaml; yaml.safe_load(open('config/watchlist.yaml'))"`
Expected: aucune erreur (YAML valide)

- [ ] **Step 5: Commit**

```bash
git add config/watchlist.yaml .env.example README.md
git commit -m "docs: document eBay setup, configure real thresholds"
```

---

## Notes d'execution

- Les credentials eBay Production sont deja configurees par l'utilisateur
  dans `~/trend-radar/.env` (verifie avant de commencer l'implementation)
  et dans `~/collector-arbitrage/.env` — aucune action de creation de
  compte necessaire pour ce plan.
- Le tout premier `scan` reel apres ce plan ne produira pas encore de
  signal eBay non nul (un seul point de donnee, `growth_pct` retourne 0.0
  tant qu'il n'y a pas 2 points) — c'est le comportement attendu, pas un
  bug. Un 2e `scan` un autre jour calendaire fera apparaitre le premier
  signal eBay reel.
