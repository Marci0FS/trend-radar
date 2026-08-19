# AliExpress Convergence Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add AliExpress as a 4th convergence source (sales-volume demand
signal, aggregated over the top 10 search results per keyword), and raise
the "FORT" convergence threshold from `sources_count >= 2` to
`sources_count >= 3` project-wide now that 4 sources exist.

**Architecture:** New `collectors/aliexpress.py` mirrors the shape of
`collectors/ebay.py` (an `*Error` exception class, a token-fetch function,
a fetch function) but implements a refresh-token OAuth flow and a
TOP-style MD5 request signature instead of eBay's simple client-credentials
flow. A new `aliexpress_snapshots` table stores one sales-volume snapshot
per keyword per scan day. `scoring/convergence.py` gains a 4th branch
following the exact pattern of its `google_trends`/`reddit`/`ebay`
branches. `cli.py cmd_scan` wires AliExpress in with the same
credentials-missing/per-keyword-failure resilience pattern already used
for Reddit and eBay.

**Tech Stack:** Python, `requests` (already a dependency), SQLite
(historized, INSERT-only), `hashlib` (stdlib, for MD5 signing).

## Global Constraints

- Free, self-hosted, official API only — no scraping against AliExpress's
  ToS.
- SQLite storage is append-only: every insert function uses
  `INSERT OR IGNORE`, never `UPDATE`/`DELETE`.
- Follow the exact patterns of `collectors/ebay.py`, `storage/db.py`, and
  `scoring/convergence.py` as they exist today (post-eBay-merge) — do not
  restructure unrelated code.
- **The FORT threshold change (`sources_count >= 2` → `>= 3`) applies to
  ALL sources, not just AliExpress.** Every existing test that asserts on
  the FORT label, the `/3` denominator string, or that treats 2 agreeing
  sources as sufficient must be updated as part of this plan — not left
  broken as a side effect.
- Never fabricate a zero when a response field is missing — always raise
  `AliExpressError` instead (same lesson already applied to
  `collectors/ebay.py`'s handling of a missing `total` field). A silently
  fabricated zero could produce a false "FORT" signal on the public
  dashboard (`growth_pct` treats a `0`-average previous window as +100%
  growth).
- `ALIEXPRESS_APP_KEY` / `ALIEXPRESS_APP_SECRET` / `ALIEXPRESS_REFRESH_TOKEN`
  are **not yet available** — the user has not created an AliExpress
  affiliate account or obtained a refresh token yet (unlike eBay, where
  credentials existed before implementation). This entire plan is
  implemented and tested against mocked HTTP calls only. Do not attempt
  any real network call to AliExpress's API. Getting real credentials is
  a separate, out-of-band step the user does themselves in a browser (never
  enter a password on their behalf) — not a task in this plan.
- The exact response field name for sales volume (`volume` vs
  `lastest_volume`) and the exact refresh-token method name
  (`taobao.top.auth.token.refresh`) are the implementation's best-effort
  reading of publicly documented AliExpress Open Platform conventions —
  they have **not** been verified against a live account (none exists
  yet). This is called out explicitly in code comments and in the README
  (Task 5) as a first-real-scan smoke test item, not silently assumed.

---

### Task 1: Storage — `aliexpress_snapshots` table

**Files:**
- Modify: `storage/schema.sql`
- Modify: `storage/db.py`
- Test: `tests/test_aliexpress_storage.py`

**Interfaces:**
- Produces: `db.insert_aliexpress_snapshot(conn, keyword_id: int, date: str, sales_volume: int, marketplace: str) -> None`
- Produces: `db.get_aliexpress_snapshot_series(conn, keyword_id: int) -> list[tuple[str, int]]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_aliexpress_storage.py`:

```python
from storage import db


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def test_insert_and_get_aliexpress_snapshot_series(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "led face mask", "gadgets")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-18", 1200, "FR")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-19", 1500, "FR")
    series = db.get_aliexpress_snapshot_series(conn, kid)
    assert series == [("2026-08-18", 1200), ("2026-08-19", 1500)]
    conn.close()


def test_insert_aliexpress_snapshot_ignores_duplicate_date(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    kid = db.get_or_create_keyword(conn, "led face mask", "gadgets")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-18", 1200, "FR")
    db.insert_aliexpress_snapshot(conn, kid, "2026-08-18", 9999, "FR")
    series = db.get_aliexpress_snapshot_series(conn, kid)
    assert series == [("2026-08-18", 1200)]
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_aliexpress_storage.py -v`
Expected: FAIL — `AttributeError: module 'storage.db' has no attribute
'insert_aliexpress_snapshot'` (table doesn't exist yet either, but the
missing function fails first).

- [ ] **Step 3: Add the table to the schema**

In `storage/schema.sql`, add this table right after the existing
`ebay_snapshots` table definition (before the `CREATE INDEX` block at the
bottom of the file):

```sql
CREATE TABLE IF NOT EXISTS aliexpress_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    date TEXT NOT NULL,
    sales_volume INTEGER NOT NULL,
    marketplace TEXT,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(keyword_id, date, marketplace)
);
```

Then add an index alongside the existing `idx_ebay_keyword` line:

```sql
CREATE INDEX IF NOT EXISTS idx_aliexpress_keyword ON aliexpress_snapshots(keyword_id);
```

- [ ] **Step 4: Implement the storage functions**

In `storage/db.py`, add after `get_ebay_snapshot_series`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_aliexpress_storage.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add storage/schema.sql storage/db.py tests/test_aliexpress_storage.py
git commit -m "feat: add aliexpress_snapshots storage"
```

---

### Task 2: Collector — `collectors/aliexpress.py`

**Files:**
- Create: `collectors/aliexpress.py`
- Test: `tests/test_aliexpress.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone module, same as `collectors/ebay.py`).
- Produces: `aliexpress.AliExpressError(RuntimeError)`
- Produces: `aliexpress.get_access_token() -> str` (raises `KeyError` if
  `ALIEXPRESS_APP_KEY`/`ALIEXPRESS_APP_SECRET`/`ALIEXPRESS_REFRESH_TOKEN`
  are missing from the environment; raises `AliExpressError` on HTTP
  failure or a malformed response)
- Produces: `aliexpress.fetch_sales_volume(keyword: str, ship_to: str = "FR", currency: str = "EUR", language: str = "fr") -> int`
  (raises `AliExpressError` on HTTP failure or malformed response; never
  returns a fabricated zero for a missing field)
- Produces (private, used only by tests and internally): `aliexpress._sign_request(params: dict, app_secret: str) -> str`
- Produces (module state, reset in tests via `monkeypatch.setattr(aliexpress, "_cached_access_token", None)`): `aliexpress._cached_access_token: str | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_aliexpress.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from collectors import aliexpress


def test_sign_request_produces_expected_md5():
    """Fixture verifiee independamment : MD5('shhh' + 'a1b2sign_methodmd5' +
    'shhh') = 498B7905B62F5C10A1544F20A06F8FE2 (parametres tries par cle :
    a, b, sign_method ; concatenation cle+valeur sans separateur)."""
    params = {"b": "2", "a": "1", "sign_method": "md5"}
    assert aliexpress._sign_request(params, "shhh") == "498B7905B62F5C10A1544F20A06F8FE2"


def test_get_access_token_missing_credentials_raises_key_error(monkeypatch):
    monkeypatch.delenv("ALIEXPRESS_APP_KEY", raising=False)
    monkeypatch.delenv("ALIEXPRESS_APP_SECRET", raising=False)
    monkeypatch.delenv("ALIEXPRESS_REFRESH_TOKEN", raising=False)
    monkeypatch.setattr(aliexpress, "_cached_access_token", None)

    with pytest.raises(KeyError):
        aliexpress.get_access_token()


def test_get_access_token_caches_within_process(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setenv("ALIEXPRESS_REFRESH_TOKEN", "test-refresh")
    monkeypatch.setattr(aliexpress, "_cached_access_token", None)

    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "tok123"}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response) as mock_get:
        token1 = aliexpress.get_access_token()
        token2 = aliexpress.get_access_token()

    assert token1 == "tok123"
    assert token2 == "tok123"
    mock_get.assert_called_once()


def test_get_access_token_raises_aliexpress_error_on_http_failure(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setenv("ALIEXPRESS_REFRESH_TOKEN", "test-refresh")
    monkeypatch.setattr(aliexpress, "_cached_access_token", None)

    import requests as requests_module

    with patch(
        "collectors.aliexpress.requests.get",
        side_effect=requests_module.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(aliexpress.AliExpressError):
            aliexpress.get_access_token()


def test_get_access_token_raises_aliexpress_error_on_missing_access_token_field(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setenv("ALIEXPRESS_REFRESH_TOKEN", "test-refresh")
    monkeypatch.setattr(aliexpress, "_cached_access_token", None)

    mock_response = MagicMock()
    mock_response.json.return_value = {"error": "invalid refresh token"}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response):
        with pytest.raises(aliexpress.AliExpressError):
            aliexpress.get_access_token()


def _query_response(products):
    return {
        "aliexpress_affiliate_product_query_response": {
            "resp_result": {"result": {"products": {"product": products}}}
        }
    }


def test_fetch_sales_volume_sums_volume_across_products(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    mock_response = MagicMock()
    mock_response.json.return_value = _query_response(
        [{"volume": 100}, {"volume": 250}, {"volume": 30}]
    )
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response) as mock_get:
        total = aliexpress.fetch_sales_volume("led face mask")

    assert total == 380
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs["params"]["keywords"] == "led face mask"
    assert call_kwargs["params"]["page_size"] == 10
    assert call_kwargs["params"]["ship_to_country"] == "FR"


def test_fetch_sales_volume_falls_back_to_lastest_volume_field(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    mock_response = MagicMock()
    mock_response.json.return_value = _query_response([{"lastest_volume": 42}])
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response):
        total = aliexpress.fetch_sales_volume("led face mask")

    assert total == 42


def test_fetch_sales_volume_returns_zero_for_empty_results(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    mock_response = MagicMock()
    mock_response.json.return_value = _query_response([])
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response):
        total = aliexpress.fetch_sales_volume("very obscure keyword")

    assert total == 0


def test_fetch_sales_volume_raises_aliexpress_error_when_product_missing_volume(monkeypatch):
    """Un produit sans champ 'volume' ni 'lastest_volume' doit lever
    AliExpressError plutot que d'etre silencieusement traite comme 0 —
    un faux 0 stocke en snapshot fabriquerait un faux signal de convergence
    au prochain scan (meme precaution que collectors/ebay.py)."""
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    mock_response = MagicMock()
    mock_response.json.return_value = _query_response([{"productId": 123}])
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response):
        with pytest.raises(aliexpress.AliExpressError):
            aliexpress.fetch_sales_volume("led face mask")


def test_fetch_sales_volume_raises_aliexpress_error_on_malformed_structure(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    mock_response = MagicMock()
    mock_response.json.return_value = {"error_response": {"msg": "Invalid session"}}
    mock_response.raise_for_status.return_value = None

    with patch("collectors.aliexpress.requests.get", return_value=mock_response):
        with pytest.raises(aliexpress.AliExpressError):
            aliexpress.fetch_sales_volume("led face mask")


def test_fetch_sales_volume_raises_aliexpress_error_on_http_failure(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")
    monkeypatch.setattr(aliexpress, "_cached_access_token", "cached-token")

    import requests as requests_module

    with patch(
        "collectors.aliexpress.requests.get",
        side_effect=requests_module.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(aliexpress.AliExpressError):
            aliexpress.fetch_sales_volume("led face mask")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_aliexpress.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'collectors.aliexpress'`

- [ ] **Step 3: Implement the collector**

Create `collectors/aliexpress.py`:

```python
"""Collecteur AliExpress Affiliate API (volume de ventes agrege sur les
10 premiers resultats d'une recherche par mot-cle, OAuth par refresh
token + requetes signees).

API officielle et gratuite (programme d'affiliation AliExpress Open
Platform). Contrairement a eBay (OAuth2 client-credentials simple, une
seule requete serveur-a-serveur), cette API utilise un flux par
refresh_token : l'utilisateur autorise l'app une fois dans un navigateur
pour obtenir ALIEXPRESS_REFRESH_TOKEN (stocke en .env), et ce module
echange ce refresh_token contre un access_token frais a chaque scan
(valable ~10h, largement suffisant pour un run quotidien). Le cache
ci-dessous est en memoire pour la duree du process (evite un refresh par
mot-cle au sein d'un meme scan) — pas de persistance disque entre deux
runs, conformement au design.

Chaque requete est signee : MD5(app_secret + parametres_tries_concatenes
+ app_secret), convention de signature de l'AliExpress Open Platform
gateway (heritee des API TOP-style historiques).

Note d'implementation : le nom exact du champ de volume ('volume' vs
'lastest_volume') et le nom exact de la methode de refresh de token
('taobao.top.auth.token.refresh') sont notre meilleure lecture de la doc
publique — aucun compte reel n'existe encore pour verifier. A confirmer
lors du premier scan reel une fois les credentials obtenues.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

import requests

_GATEWAY_URL = "https://api-sg.aliexpress.com/sync"
_METHOD_REFRESH_TOKEN = "taobao.top.auth.token.refresh"
_METHOD_PRODUCT_QUERY = "aliexpress.affiliate.product.query"
_RESULTS_PER_KEYWORD = 10

# Cache memoire du access_token pour la duree du process (voir docstring).
_cached_access_token: str | None = None


class AliExpressError(RuntimeError):
    pass


def _sign_request(params: dict, app_secret: str) -> str:
    """MD5(app_secret + cles_triees_concatenees_avec_valeurs + app_secret)."""
    sorted_items = sorted(params.items())
    concatenated = "".join(f"{key}{value}" for key, value in sorted_items)
    to_sign = f"{app_secret}{concatenated}{app_secret}"
    return hashlib.md5(to_sign.encode("utf-8")).hexdigest().upper()


def _system_params(app_key: str, method: str) -> dict:
    return {
        "app_key": app_key,
        "method": method,
        "sign_method": "md5",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "format": "json",
        "v": "2.0",
    }


def get_access_token() -> str:
    """Echange ALIEXPRESS_REFRESH_TOKEN contre un access_token frais.
    Leve KeyError si ALIEXPRESS_APP_KEY/ALIEXPRESS_APP_SECRET/
    ALIEXPRESS_REFRESH_TOKEN ne sont pas definies en env (meme convention
    que collectors.reddit.get_client / collectors.ebay.get_app_token)."""
    global _cached_access_token
    if _cached_access_token is not None:
        return _cached_access_token

    app_key = os.environ["ALIEXPRESS_APP_KEY"]
    app_secret = os.environ["ALIEXPRESS_APP_SECRET"]
    refresh_token = os.environ["ALIEXPRESS_REFRESH_TOKEN"]

    params = _system_params(app_key, _METHOD_REFRESH_TOKEN)
    params["refresh_token"] = refresh_token
    params["sign"] = _sign_request(params, app_secret)

    try:
        resp = requests.get(_GATEWAY_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or "access_token" not in data:
            raise AliExpressError(
                f"Reponse AliExpress sans champ 'access_token' au refresh : {data!r}"
            )
        token = str(data["access_token"])
    except requests.RequestException as exc:
        raise AliExpressError(f"Echec rafraichissement du token AliExpress : {exc}") from exc
    except (TypeError, AttributeError, ValueError) as exc:
        raise AliExpressError(f"Reponse invalide du serveur AliExpress au refresh : {exc}") from exc

    _cached_access_token = token
    return token


def fetch_sales_volume(
    keyword: str,
    ship_to: str = "FR",
    currency: str = "EUR",
    language: str = "fr",
) -> int:
    """Retourne la somme du volume de ventes recentes sur les 10 premiers
    produits retournes pour ce mot-cle. Une liste de resultats vide est
    une observation legitime (0 vente) ; un produit present mais sans
    champ de volume est une erreur (voir AliExpressError), jamais traite
    comme 0."""
    app_key = os.environ["ALIEXPRESS_APP_KEY"]
    app_secret = os.environ["ALIEXPRESS_APP_SECRET"]
    access_token = get_access_token()

    params = _system_params(app_key, _METHOD_PRODUCT_QUERY)
    params["session"] = access_token
    params["keywords"] = keyword
    params["page_size"] = _RESULTS_PER_KEYWORD
    params["ship_to_country"] = ship_to
    params["target_currency"] = currency
    params["target_language"] = language
    params["sign"] = _sign_request(params, app_secret)

    try:
        resp = requests.get(_GATEWAY_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        products = _extract_products(data)
    except requests.RequestException as exc:
        raise AliExpressError(f"Echec recherche AliExpress pour '{keyword}' : {exc}") from exc
    except (TypeError, AttributeError, ValueError) as exc:
        raise AliExpressError(f"Reponse invalide du serveur AliExpress pour '{keyword}' : {exc}") from exc

    return _sum_volume(products, keyword)


def _extract_products(data) -> list[dict]:
    """Navigue la structure de reponse imbriquee (style TOP gateway) pour
    atteindre la liste de produits. Leve AliExpressError si la structure
    ne correspond pas a ce qui est attendu."""
    try:
        result = data["aliexpress_affiliate_product_query_response"]["resp_result"]["result"]
        products = result["products"]["product"]
    except (KeyError, TypeError) as exc:
        raise AliExpressError(f"Structure de reponse AliExpress inattendue : {data!r}") from exc
    if not isinstance(products, list):
        raise AliExpressError(f"Champ 'product' n'est pas une liste : {products!r}")
    return products


def _sum_volume(products: list[dict], keyword: str) -> int:
    total = 0
    for product in products:
        volume = product.get("volume", product.get("lastest_volume"))
        if volume is None:
            raise AliExpressError(
                f"Produit AliExpress sans champ 'volume'/'lastest_volume' pour '{keyword}' : {product!r}"
            )
        try:
            total += int(volume)
        except (TypeError, ValueError) as exc:
            raise AliExpressError(
                f"Valeur de volume non numerique pour '{keyword}' : {volume!r}"
            ) from exc
    return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_aliexpress.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add collectors/aliexpress.py tests/test_aliexpress.py
git commit -m "feat: add AliExpress Affiliate API collector (refresh-token OAuth + MD5 signing)"
```

---

### Task 3: Scoring — 4th convergence branch + FORT threshold change

**Files:**
- Modify: `scoring/convergence.py`
- Modify: `tests/test_convergence.py`

**Interfaces:**
- Consumes: `db.get_aliexpress_snapshot_series` shape (from Task 1, though
  this task queries `aliexpress_snapshots` inline via SQL — same
  established style as the `trends`/`reddit`/`ebay` branches, which don't
  call the `get_*_series` helpers either).
- Consumes: `collectors.google_trends.growth_pct` (already imported in
  `scoring/convergence.py`).
- Produces: `compute_convergence(...)` result now includes
  `details["aliexpress_growth_pct"]` and `details["signals_detected"]["aliexpress"]`,
  and `sources_count` ranges 0–4 instead of 0–3.

- [ ] **Step 1: Write the failing tests**

In `tests/test_convergence.py`, replace the `THRESHOLDS` dict at the top
of the file:

```python
THRESHOLDS = {
    "trends_growth_pct": 20,
    "reddit_min_posts": 3,
    "reddit_min_avg_score": 10,
    "ebay_growth_pct": 20,
    "aliexpress_growth_pct": 20,
}
```

Rename `test_compute_convergence_trends_and_ebay_reach_fort_without_reddit`
to `test_compute_convergence_trends_and_ebay_agree_as_two_sources` (the
old name is misleading once FORT requires 3 sources — 2/4 agreeing is no
longer "FORT" on its own; the test's assertions on `sources_count == 2` and
the two `signals_detected` booleans stay valid and unchanged):

```python
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
```

Add new tests at the end of the file:

```python
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
            "num_comments": 1, "created_utc": "2026-08-14T00:00:00+00:00", "url": "https://x",
        }
        for i in range(5)
    ])

    result = compute_convergence(conn, kid, THRESHOLDS)

    assert result["sources_count"] == 4
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_convergence.py -v`
Expected: FAIL (5 of 7 tests) — the renamed test and the 4 new tests all
assert on `result["details"]["signals_detected"]["aliexpress"]` or
`result["details"]["aliexpress_growth_pct"]`, neither of which exists yet
in `compute_convergence`'s return value (raises `KeyError`). The other 2
original tests (`test_compute_convergence_zero_sources`,
`test_compute_convergence_ebay_below_threshold_not_counted`) still pass
unchanged.

- [ ] **Step 3: Implement the 4th branch**

In `scoring/convergence.py`, add after the existing `ebay` branch (after
the `signals_detected["ebay"] = ...` line) and before `sources_count = ...`:

```python
    aliexpress_rows = conn.execute(
        "SELECT date, sales_volume FROM aliexpress_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    aliexpress_snapshots = [(r["date"], r["sales_volume"]) for r in aliexpress_rows]
    aliexpress_growth = growth_pct(aliexpress_snapshots, window_days=1)
    signals_detected["aliexpress"] = aliexpress_growth >= thresholds["aliexpress_growth_pct"]
```

Update the `convergence_score` computation to add the AliExpress bonus term:

```python
    convergence_score = (
        sources_count * 10
        + max(trends_growth, 0) * 0.1
        + reddit_count * 0.5
        + max(ebay_growth, 0) * 0.1
        + max(aliexpress_growth, 0) * 0.1
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
            "signals_detected": signals_detected,
        },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_convergence.py -v`
Expected: PASS (7 tests: 3 original + 4 new/renamed)

- [ ] **Step 5: Commit**

```bash
git add scoring/convergence.py tests/test_convergence.py
git commit -m "feat: add AliExpress as 4th convergence source in scoring"
```

---

### Task 4: CLI integration — `cmd_scan`, `write_report`, dashboard text consistency

**Files:**
- Modify: `cli.py`
- Modify: `tests/test_cli_scan_ebay.py` (threshold dict needs the new key)
- Modify: `tests/test_cli_publish_flag.py` (threshold dict needs the new key)
- Modify: `tests/test_cli_scan_resilience.py` (threshold dict needs the new key)
- Modify: `web/public/index.html` (dot-indicator count and footer text — NOT
  a new visible column, just keeping the existing "N of M sources" and
  "signal fort" indicators honest now that M=4 and the threshold is 3)
- Test: `tests/test_cli_scan_aliexpress.py`

**Interfaces:**
- Consumes: `aliexpress.get_access_token`, `aliexpress.fetch_sales_volume`,
  `aliexpress.AliExpressError` (Task 2)
- Consumes: `db.insert_aliexpress_snapshot` (Task 1)
- Consumes: `compute_convergence` returning `details["aliexpress_growth_pct"]` (Task 3)

- [ ] **Step 1: Update the three existing threshold dicts that will otherwise KeyError**

`compute_convergence` now unconditionally reads
`thresholds["aliexpress_growth_pct"]` (added in Task 3). Any test that
builds a `watchlist["thresholds"]` dict without that key will now fail
with `KeyError: 'aliexpress_growth_pct'` as soon as `cmd_scan` runs. Fix
the three affected files before writing any new test, so the full suite
stays green throughout this task:

In `tests/test_cli_publish_flag.py:85`, change:
```python
"thresholds": {"trends_growth_pct": 20, "reddit_min_posts": 3, "reddit_min_avg_score": 10, "ebay_growth_pct": 20},
```
to:
```python
"thresholds": {"trends_growth_pct": 20, "reddit_min_posts": 3, "reddit_min_avg_score": 10, "ebay_growth_pct": 20, "aliexpress_growth_pct": 20},
```

In `tests/test_cli_scan_resilience.py:32`, apply the identical change.

In `tests/test_cli_scan_ebay.py`, in `_base_watchlist()`, change:
```python
        "thresholds": {
            "trends_growth_pct": 20,
            "reddit_min_posts": 3,
            "reddit_min_avg_score": 10,
            "ebay_growth_pct": 20,
        },
```
to:
```python
        "thresholds": {
            "trends_growth_pct": 20,
            "reddit_min_posts": 3,
            "reddit_min_avg_score": 10,
            "ebay_growth_pct": 20,
            "aliexpress_growth_pct": 20,
        },
```

Run: `python3 -m pytest tests/test_cli_publish_flag.py tests/test_cli_scan_resilience.py tests/test_cli_scan_ebay.py -v`
Expected: PASS (confirms these three files are green again before adding new code)

- [ ] **Step 2: Write the failing tests for AliExpress cli integration**

Create `tests/test_cli_scan_aliexpress.py`:

```python
import json
from datetime import datetime, timezone

from collectors import aliexpress
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
            "aliexpress_growth_pct": 20,
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

    def _raise_ebay_key_error():
        raise KeyError("EBAY_CLIENT_ID")

    monkeypatch.setattr(ebay, "get_app_token", _raise_ebay_key_error)


def test_cmd_scan_skips_aliexpress_when_credentials_missing(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    def _raise_aliexpress_key_error():
        raise KeyError("ALIEXPRESS_APP_KEY")

    monkeypatch.setattr(aliexpress, "get_access_token", _raise_aliexpress_key_error)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    assert data["watchlist"][0]["aliexpress_growth_pct"] == 0.0


def test_cmd_scan_continues_when_aliexpress_fails_for_one_keyword(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    monkeypatch.setattr(aliexpress, "get_access_token", lambda: "fake-token")

    def _flaky_fetch(keyword, **kwargs):
        raise aliexpress.AliExpressError("simulated failure")

    monkeypatch.setattr(aliexpress, "fetch_sales_volume", _flaky_fetch)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    assert len(data["watchlist"]) == 1
    entry = data["watchlist"][0]
    assert entry["keyword"] == "test kw"
    assert entry["trends_growth_pct"] == 0.0
    assert isinstance(entry["convergence_score"], (int, float))


def test_cmd_scan_ebay_succeeds_when_aliexpress_fails_for_one_keyword(tmp_path, monkeypatch):
    """eBay et AliExpress sont deux blocs independants dans la boucle par
    mot-cle : un echec AliExpress ne doit pas empecher eBay de tourner
    normalement pour ce meme mot-cle (meme preuve d'independance que
    test_cmd_scan_reddit_succeeds_when_ebay_fails_for_one_keyword pour la
    paire Reddit/eBay)."""
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(google_trends, "fetch_interest_over_time", lambda *a, **k: [])

    def _raise_reddit_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_reddit_key_error)

    monkeypatch.setattr(ebay, "get_app_token", lambda: "fake-ebay-token")
    monkeypatch.setattr(ebay, "fetch_listing_count", lambda keyword, **kwargs: 4213)

    monkeypatch.setattr(aliexpress, "get_access_token", lambda: "fake-token")

    def _flaky_fetch(keyword, **kwargs):
        raise aliexpress.AliExpressError("simulated failure")

    monkeypatch.setattr(aliexpress, "fetch_sales_volume", _flaky_fetch)

    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    entry = data["watchlist"][0]
    assert entry["aliexpress_growth_pct"] == 0.0

    conn = storage_db.get_connection()
    kid = storage_db.get_or_create_keyword(conn, "test kw", "gadgets")
    series = storage_db.get_ebay_snapshot_series(conn, kid)
    conn.close()
    assert series[-1][1] == 4213


def test_cmd_scan_stores_aliexpress_snapshot_when_available(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)

    monkeypatch.setattr(aliexpress, "get_access_token", lambda: "fake-token")
    monkeypatch.setattr(aliexpress, "fetch_sales_volume", lambda keyword, **kwargs: 1234)

    cli.cmd_scan(_base_watchlist())

    conn = storage_db.get_connection()
    kid = storage_db.get_or_create_keyword(conn, "test kw", "gadgets")
    series = storage_db.get_aliexpress_snapshot_series(conn, kid)
    conn.close()
    assert series[-1][1] == 1234


def test_cmd_scan_aliexpress_growth_survives_two_scans_into_signals_json(tmp_path, monkeypatch):
    _patch_common(tmp_path, monkeypatch)
    monkeypatch.setattr(aliexpress, "get_access_token", lambda: "fake-token")

    class _FrozenDatetime(datetime):
        _current = datetime(2026, 8, 18, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._current

    monkeypatch.setattr(cli, "datetime", _FrozenDatetime)

    _FrozenDatetime._current = datetime(2026, 8, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(aliexpress, "fetch_sales_volume", lambda keyword, **kwargs: 100)
    cli.cmd_scan(_base_watchlist())

    _FrozenDatetime._current = datetime(2026, 8, 19, tzinfo=timezone.utc)
    monkeypatch.setattr(aliexpress, "fetch_sales_volume", lambda keyword, **kwargs: 200)
    cli.cmd_scan(_base_watchlist())

    data = json.loads((tmp_path / "signals.json").read_text())
    entry = data["watchlist"][0]
    assert entry["aliexpress_growth_pct"] == 100.0
    assert entry["sources_count"] == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cli_scan_aliexpress.py -v`
Expected: FAIL — `KeyError: 'aliexpress_growth_pct'` (cli.py doesn't
produce this field in `signal_entries` yet) or `ModuleNotFoundError`-style
`AttributeError` for `aliexpress.get_access_token` not being called by
`cmd_scan`.

- [ ] **Step 4: Wire AliExpress into `cmd_scan`**

In `cli.py`, add the import near the other collector imports:

```python
from collectors import aliexpress
```

After the existing eBay availability check block (after the
`ebay_available = False` / `print(...)` lines for the `EbayError` case),
add:

```python
    try:
        aliexpress.get_access_token()
        aliexpress_available = True
    except KeyError:
        aliexpress_available = False
        print("AliExpress : credentials manquantes, collecte AliExpress desactivee pour ce scan")
    except aliexpress.AliExpressError as exc:
        aliexpress_available = False
        print(f"AliExpress : authentification impossible, collecte AliExpress desactivee pour ce scan : {exc}")
```

Inside the per-keyword loop, after the existing eBay block (`if
ebay_available: ... except ebay.EbayError as exc: print(...)`), add a new
independent block:

```python
            if aliexpress_available:
                ship_to = watchlist.get("aliexpress_ship_to", "FR")
                currency = watchlist.get("aliexpress_currency", "EUR")
                language = watchlist.get("aliexpress_language", "fr")
                try:
                    sales_volume = aliexpress.fetch_sales_volume(
                        keyword, ship_to=ship_to, currency=currency, language=language
                    )
                    today = datetime.now(timezone.utc).date().isoformat()
                    db.insert_aliexpress_snapshot(conn, keyword_id, today, sales_volume, ship_to)
                except aliexpress.AliExpressError as exc:
                    print(f"  Echec AliExpress pour '{keyword}', continue sans ce signal : {exc}")
```

In `signal_entries` (inside `cmd_scan`), add the new field after
`"ebay_growth_pct"`:

```python
            "ebay_growth_pct": r["details"]["ebay_growth_pct"],
            "aliexpress_growth_pct": r["details"]["aliexpress_growth_pct"],
```

- [ ] **Step 5: Update `write_report` for the new threshold and 4th source**

In `cli.py`, `write_report`, change:

```python
        marker = "FORT" if r["sources_count"] >= 2 else "faible"
```
to:
```python
        marker = "FORT" if r["sources_count"] >= 3 else "faible"
```

Change:
```python
        lines.append(f"- Sources en accord : {r['sources_count']}/3")
```
to:
```python
        lines.append(f"- Sources en accord : {r['sources_count']}/4")
```

Add a new line after the existing eBay line:
```python
        lines.append(f"- eBay : {d['ebay_growth_pct']}% de croissance")
        lines.append(f"- AliExpress : {d['aliexpress_growth_pct']}% de croissance")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cli_scan_aliexpress.py -v`
Expected: PASS (5 tests)

Run the full suite to confirm nothing else broke:
Run: `python3 -m pytest -v`
Expected: PASS (all tests, no regressions)

- [ ] **Step 7: Fix the dashboard's dot-indicator and footer text**

`web/public/index.html` hardcodes a 3-dot indicator and a footer sentence
naming exactly 3 sources and a "2 of 3" threshold — both are now
factually wrong (4 sources exist, FORT needs 3). This is a text/indicator
correctness fix, not the (still out-of-scope) addition of a new
AliExpress data column.

In `web/public/index.html`, change the `dots()` function's loop bound:
```javascript
    function dots(n) {
      let out = '<span class="dots">';
      for (let i = 0; i < 3; i++) {
```
to:
```javascript
    function dots(n) {
      let out = '<span class="dots">';
      for (let i = 0; i < 4; i++) {
```

Change the footer text:
```html
  <footer>signal fort = au moins deux des trois sources independantes (Trends, Reddit, eBay) en accord (&#9679;&#9679;&#9675;)</footer>
```
to:
```html
  <footer>signal fort = au moins trois des quatre sources independantes (Trends, Reddit, eBay, AliExpress) en accord (&#9679;&#9679;&#9679;&#9675;)</footer>
```

- [ ] **Step 8: Manually verify the dashboard renders correctly**

Run: `python3 -m http.server 8000 --directory web/public` and open
`http://localhost:8000` in a browser (or just read the file — no build
step exists for this static site). Confirm the footer text reads
correctly and no JavaScript console error appears (the `dots()` change is
a pure loop-bound edit, low risk, but the file has no automated test
coverage for its JS, so this manual check is the only verification
available — matches how the eBay dashboard fix was verified).

- [ ] **Step 9: Commit**

```bash
git add cli.py tests/test_cli_scan_aliexpress.py tests/test_cli_publish_flag.py tests/test_cli_scan_resilience.py tests/test_cli_scan_ebay.py web/public/index.html
git commit -m "feat: wire AliExpress into cmd_scan, raise FORT threshold to 3/4 sources"
```

---

### Task 5: Configuration & documentation

**Files:**
- Modify: `config/watchlist.yaml`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: `watchlist.get("aliexpress_ship_to", "FR")`,
  `watchlist.get("aliexpress_currency", "EUR")`,
  `watchlist.get("aliexpress_language", "fr")`,
  `watchlist["thresholds"]["aliexpress_growth_pct"]` (all read by `cli.py`
  and `scoring/convergence.py` in Tasks 3–4 with safe defaults via `.get`
  for the non-threshold keys — but `thresholds["aliexpress_growth_pct"]`
  is accessed with `[...]`, not `.get`, so it MUST exist in the real
  `config/watchlist.yaml` after this task, exactly like the other three
  threshold keys already there).

- [ ] **Step 1: Add AliExpress settings to the real watchlist config**

In `config/watchlist.yaml`, after the `ebay_marketplace: "EBAY_FR"` line, add:

```yaml
aliexpress_ship_to: "FR"
aliexpress_currency: "EUR"
aliexpress_language: "fr"
```

In the `thresholds:` block, after `ebay_growth_pct: 20`, add:

```yaml
  aliexpress_growth_pct: 20
```

- [ ] **Step 2: Verify the config loads and scan runs against it (mocked)**

Run: `python3 -m pytest -v`
Expected: PASS (all tests — this step doesn't add new tests, it just
confirms the real YAML file the app loads at runtime is well-formed and
consistent with what `cmd_scan` expects; the existing test suite already
exercises `compute_convergence`/`cmd_scan` against test-local threshold
dicts, so this is a manual sanity check, not a new automated test)

Run: `python3 -c "import yaml; d = yaml.safe_load(open('config/watchlist.yaml')); assert 'aliexpress_growth_pct' in d['thresholds']; assert d['aliexpress_ship_to'] == 'FR'; print('OK')"`
Expected: prints `OK`

- [ ] **Step 3: Add credentials placeholders to `.env.example`**

In `.env.example`, after the `EBAY_ENVIRONMENT=PRODUCTION` line, add:

```
ALIEXPRESS_APP_KEY=
ALIEXPRESS_APP_SECRET=
ALIEXPRESS_REFRESH_TOKEN=
```

- [ ] **Step 4: Document AliExpress setup in the README**

In `README.md`, update the intro paragraph. Change:
```
100% gratuite et self-hosted. Croise Google Trends, Reddit et eBay (3e source
optionnelle), ne remonte un signal fort que si au moins 2 sources convergent
sur la même fenêtre de temps.
```
to:
```
100% gratuite et self-hosted. Croise Google Trends, Reddit, eBay et
AliExpress (3e et 4e sources optionnelles), ne remonte un signal fort que
si au moins 3 des 4 sources convergent sur la même fenêtre de temps.
```

After the existing "### eBay (optionnel, 3e source de convergence)"
section, add a new section:

```markdown
### AliExpress (optionnel, 4e source de convergence)

Contrairement a eBay, l'authentification AliExpress demande une etape
manuelle unique dans un navigateur :

1. Cree un compte sur le [programme d'affiliation AliExpress](https://portals.aliexpress.com/)
   et une app sur l'Open Platform pour obtenir un `App Key` / `App Secret`.
2. Autorise l'app (consentement OAuth dans le navigateur) pour obtenir un
   `refresh_token` — cette etape ne se fait qu'une fois.
3. Ajoute les trois valeurs a `.env` :

```
ALIEXPRESS_APP_KEY=ton_app_key
ALIEXPRESS_APP_SECRET=ton_app_secret
ALIEXPRESS_REFRESH_TOKEN=le_refresh_token_obtenu_a_l_etape_2
```

Sans credentials, `scan` continue de fonctionner normalement, AliExpress
est juste desactive pour cette source (comme eBay et Reddit).

**Le refresh_token peut expirer** apres plusieurs mois d'inactivite —
si `scan` affiche "AliExpress : authentification impossible" de facon
persistante, refais l'etape 2.

**Premiere verification apres obtention des credentials reelles** : le
nom exact du champ de volume de ventes retourne par l'API
(`volume` vs `lastest_volume`) n'a pas pu etre confirme avant que le
compte affilie existe. Lance `python cli.py check "un mot-cle test"`
apres avoir configure les credentials et verifie dans les logs qu'aucune
`AliExpressError` de type "sans champ 'volume'/'lastest_volume'" n'apparait —
si c'est le cas, la reponse reelle de l'API doit etre inspectee et
`collectors/aliexpress.py::_sum_volume` ajuste au nom de champ reel.
```

- [ ] **Step 5: Commit**

```bash
git add config/watchlist.yaml .env.example README.md
git commit -m "docs: document AliExpress setup, configure real thresholds"
```

---

## Post-plan note (not a task, informational)

Once the user has real AliExpress credentials in `.env` and runs a real
`scan`, the very first real API response should be treated as a smoke
test for the two documented unknowns (exact volume field name, exact
refresh-token method name) — see the README section added in Task 5. If
either assumption is wrong, the fix is a small, isolated change to
`collectors/aliexpress.py` (constants `_METHOD_REFRESH_TOKEN` and the
`_sum_volume` field lookup), not a design change.
