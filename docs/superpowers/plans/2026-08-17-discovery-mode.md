# Discovery Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "discovery" mode to trend-radar that detects emerging product candidates directly from Reddit activity (no pre-supplied keywords), surfaces them in a review report, and lets the user promote chosen candidates into the existing watchlist pipeline.

**Architecture:** A new `discovery/` package scans subreddits' hot+rising listings via PRAW, extracts noun phrases from post titles with spaCy, stores mention counts in a new historized SQLite table, and computes a growth signal by reusing the existing `growth_pct` function from `collectors/google_trends.py`. Two new CLI subcommands (`discover`, `promote`) wire this into `cli.py` alongside the existing `check`/`scan` commands. Nothing in the existing watchlist pipeline is modified in behavior — discovery is purely an additional keyword source.

**Tech Stack:** Python 3, spaCy (`en_core_web_sm`), PRAW (already a dependency), SQLite (already a dependency), pytest (new — project has no test suite yet).

## Global Constraints

- Gratuit et self-hosted : aucune dependance a une API payante (spec: contraintes non negociables).
- Extraction en anglais via spaCy local (`en_core_web_sm`) — les subreddits cibles sont anglophones, meme si les mots-cles Trends restent en francais (spec: note langue).
- Workflow semi-automatique, humain dans la boucle : `discover` ne doit **jamais** appeler Google Trends automatiquement ; la validation Trends se fait uniquement via `cli.py scan`, apres un `promote` explicite (spec: workflow utilisateur).
- SQLite historise, jamais d'UPDATE/DELETE sur les series temporelles — uniquement des INSERT (deja la convention du projet, `storage/schema.sql:2-3`).
- Schema exact de la nouvelle table (spec verbatim) :
  ```sql
  CREATE TABLE phrase_mentions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      phrase TEXT NOT NULL,
      subreddit TEXT NOT NULL,
      mention_count INTEGER NOT NULL,
      window_start TEXT NOT NULL,
      window_end TEXT NOT NULL,
      scanned_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
  ```
- Reddit credentials manquants -> skip propre avec message clair, jamais de crash (deja la convention, `cli.py:60-64`).

---

## File Structure

**Create:**
- `conftest.py` — ajoute la racine du projet au `sys.path` pour que les tests puissent `import cli`, `from storage import db`, etc.
- `discovery/__init__.py`
- `discovery/reddit_scan.py` — scan des subreddits (hot + rising), pas de recherche par mot-cle
- `discovery/extract.py` — extraction spaCy des groupes nominaux + filtrage bruit
- `discovery/velocity.py` — detection des candidats en croissance (reutilise `growth_pct`)
- `discovery/promote.py` — insertion textuelle d'un mot-cle dans `config/watchlist.yaml` (preserve les commentaires, pas de round-trip YAML)
- `tests/test_storage_phrase_mentions.py`
- `tests/test_extract.py`
- `tests/test_velocity.py`
- `tests/test_reddit_scan.py`
- `tests/test_promote.py`
- `tests/test_cli_discover.py`

**Modify:**
- `storage/schema.sql` — ajoute la table `phrase_mentions` + index
- `storage/db.py` — ajoute `insert_phrase_mentions`, `get_phrase_mention_series`, `get_distinct_phrases`
- `cli.py` — ajoute `cmd_discover`, `cmd_promote`, `write_discovery_report`, sous-commandes argparse `discover`/`promote`
- `config/watchlist.yaml` — ajoute la section `discovery:` (subreddits, seuils)
- `requirements.txt` — ajoute `spacy`, `pytest`
- `.gitignore` — ajoute `data/discovery_report.md`
- `README.md` — documente `discover`/`promote`

---

### Task 1: Table `phrase_mentions` + helpers storage + infra de tests

**Files:**
- Create: `conftest.py`
- Create: `tests/test_storage_phrase_mentions.py`
- Modify: `storage/schema.sql`
- Modify: `storage/db.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: rien (premiere tache)
- Produces:
  - `storage.db.insert_phrase_mentions(conn: sqlite3.Connection, mentions: list[dict]) -> None` — chaque dict a les cles `phrase`, `subreddit`, `mention_count`, `window_start`, `window_end`
  - `storage.db.get_phrase_mention_series(conn: sqlite3.Connection, phrase: str) -> list[tuple[str, int]]` — retourne `[(window_start, total_mentions), ...]` triees par `window_start`, agregees (SUM) sur tous les subreddits d'une meme fenetre
  - `storage.db.get_distinct_phrases(conn: sqlite3.Connection) -> list[str]`

- [ ] **Step 1: Ajouter pytest aux dependances**

Modifier `requirements.txt` :

```
pytrends
praw
PyYAML
spacy
pytest
```

- [ ] **Step 2: Creer `conftest.py` a la racine**

```python
"""Permet aux tests d'importer les modules du projet (cli, storage, discovery, collectors)
sans installation en mode package."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
```

- [ ] **Step 3: Ecrire le test qui echoue**

Creer `tests/test_storage_phrase_mentions.py` :

```python
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
```

- [ ] **Step 4: Lancer les tests pour verifier qu'ils echouent**

Run: `pip install -r requirements.txt && pytest tests/test_storage_phrase_mentions.py -v`
Expected: FAIL avec `AttributeError: module 'storage.db' has no attribute 'insert_phrase_mentions'`

- [ ] **Step 5: Ajouter la table au schema**

Dans `storage/schema.sql`, ajouter apres la table `signals` (avant la section des index) :

```sql
CREATE TABLE IF NOT EXISTS phrase_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase TEXT NOT NULL,
    subreddit TEXT NOT NULL,
    mention_count INTEGER NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    scanned_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Et ajouter l'index avec les autres :

```sql
CREATE INDEX IF NOT EXISTS idx_phrase_mentions_phrase ON phrase_mentions(phrase);
```

- [ ] **Step 6: Implementer les helpers dans `storage/db.py`**

Ajouter a la fin du fichier :

```python
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
```

- [ ] **Step 7: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_storage_phrase_mentions.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add conftest.py tests/test_storage_phrase_mentions.py storage/schema.sql storage/db.py requirements.txt
git commit -m "feat: add phrase_mentions table and storage helpers for discovery mode"
```

---

### Task 2: Extraction de phrases avec spaCy

**Files:**
- Create: `discovery/__init__.py`
- Create: `discovery/extract.py`
- Create: `tests/test_extract.py`
- Modify: `requirements.txt` (deja fait Task 1, rien a ajouter ici)

**Interfaces:**
- Consumes: rien
- Produces: `discovery.extract.extract_phrases(titles: list[str]) -> dict[str, int]` — retourne un dict phrase normalisee (minuscule) -> nombre d'occurrences

- [ ] **Step 1: Installer le modele spaCy**

Run: `python -m spacy download en_core_web_sm`
Expected: telechargement OK, message `Download and installation successful`

- [ ] **Step 2: Ecrire le test qui echoue**

Creer `discovery/__init__.py` (vide).

Creer `tests/test_extract.py` :

```python
from discovery.extract import extract_phrases


def test_extract_phrases_counts_repeated_mentions():
    titles = [
        "This LED face mask changed my skincare routine",
        "I bought a LED face mask and love it",
        "Anyone else using a LED face mask daily?",
    ]
    counts = extract_phrases(titles)
    assert counts["led face mask"] == 3


def test_extract_phrases_filters_noise():
    titles = [
        "Update: my post got removed",
        "it",
        "ok",
    ]
    counts = extract_phrases(titles)
    assert "post" not in counts
    assert "update" not in counts
    assert "it" not in counts
    assert "ok" not in counts


def test_extract_phrases_empty_input_returns_empty_dict():
    assert extract_phrases([]) == {}
```

- [ ] **Step 3: Lancer les tests pour verifier qu'ils echouent**

Run: `pytest tests/test_extract.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'discovery.extract'`

- [ ] **Step 4: Implementer `discovery/extract.py`**

```python
"""Extraction de phrases candidates depuis des titres de posts Reddit.

Utilise spaCy (modele anglais, local, gratuit) pour extraire les groupes
nominaux (noun chunks) des titres, plutot qu'un simple comptage de n-grams :
meilleure comprehension grammaticale, moins de bruit qu'un decoupage brut.
"""
from __future__ import annotations

import spacy

_NLP = None

MIN_PHRASE_LENGTH = 4

STOPWORD_PHRASES = {
    "update", "post", "thread", "amazon", "reddit", "op", "edit",
    "it", "ok", "this", "that", "these", "those", "anyone", "someone",
}

LEADING_DETERMINERS = ("a ", "an ", "the ", "my ", "this ", "these ", "those ", "your ", "our ")


def _get_nlp():
    global _NLP
    if _NLP is None:
        try:
            _NLP = spacy.load("en_core_web_sm")
        except OSError as exc:
            raise RuntimeError(
                "Modele spaCy manquant. Installer avec : python -m spacy download en_core_web_sm"
            ) from exc
    return _NLP


def _normalize(phrase: str) -> str:
    phrase = phrase.lower().strip()
    for article in LEADING_DETERMINERS:
        if phrase.startswith(article):
            phrase = phrase[len(article):]
    return phrase.strip()


def _is_noise(phrase: str) -> bool:
    if len(phrase) < MIN_PHRASE_LENGTH:
        return True
    if phrase in STOPWORD_PHRASES:
        return True
    if phrase.replace(" ", "").isdigit():
        return True
    return False


def extract_phrases(titles: list[str]) -> dict[str, int]:
    """Retourne {phrase_normalisee: nb_occurrences} a partir d'une liste de titres."""
    if not titles:
        return {}
    nlp = _get_nlp()
    counts: dict[str, int] = {}
    for doc in nlp.pipe(titles):
        for chunk in doc.noun_chunks:
            phrase = _normalize(chunk.text)
            if _is_noise(phrase):
                continue
            counts[phrase] = counts.get(phrase, 0) + 1
    return counts
```

- [ ] **Step 5: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_extract.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add discovery/__init__.py discovery/extract.py tests/test_extract.py
git commit -m "feat: spaCy-based phrase extraction for discovery mode"
```

---

### Task 3: Detection de vélocité (candidats en croissance)

**Files:**
- Create: `discovery/velocity.py`
- Create: `tests/test_velocity.py`

**Interfaces:**
- Consumes: `storage.db.get_distinct_phrases`, `storage.db.get_phrase_mention_series` (Task 1) ; `collectors.google_trends.growth_pct(snapshots: list[tuple[str,int]], window_days: int) -> float` (existant, `collectors/google_trends.py:38`)
- Produces: `discovery.velocity.find_candidates(conn: sqlite3.Connection, min_mentions: int, min_growth_pct: float) -> list[dict]` — chaque dict a les cles `phrase`, `mention_count`, `growth_pct`, trie par `growth_pct` decroissant

- [ ] **Step 1: Ecrire le test qui echoue**

Creer `tests/test_velocity.py` :

```python
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
```

- [ ] **Step 2: Lancer les tests pour verifier qu'ils echouent**

Run: `pytest tests/test_velocity.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'discovery.velocity'`

- [ ] **Step 3: Implementer `discovery/velocity.py`**

```python
"""Detection de candidats en croissance a partir des mentions de phrases.

Reutilise growth_pct (deja utilise pour Google Trends) plutot que de
dupliquer une logique de calcul de croissance : chaque run de `discover`
produit un point (une "fenetre"), et growth_pct(window_days=1) compare
simplement le dernier point au precedent.
"""
from __future__ import annotations

import sqlite3

from collectors.google_trends import growth_pct
from storage import db


def find_candidates(
    conn: sqlite3.Connection, min_mentions: int, min_growth_pct: float
) -> list[dict]:
    """Retourne les phrases dont la derniere fenetre depasse les deux seuils,
    triees par croissance decroissante."""
    candidates = []
    for phrase in db.get_distinct_phrases(conn):
        series = db.get_phrase_mention_series(conn, phrase)
        if not series:
            continue
        latest_count = series[-1][1]
        growth = growth_pct(series, window_days=1)
        if latest_count >= min_mentions and growth >= min_growth_pct:
            candidates.append({
                "phrase": phrase,
                "mention_count": latest_count,
                "growth_pct": round(growth, 1),
            })
    return sorted(candidates, key=lambda c: c["growth_pct"], reverse=True)
```

- [ ] **Step 4: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_velocity.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add discovery/velocity.py tests/test_velocity.py
git commit -m "feat: velocity detection for discovery candidates"
```

---

### Task 4: Scan des subreddits (hot + rising)

**Files:**
- Create: `discovery/reddit_scan.py`
- Create: `tests/test_reddit_scan.py`

**Interfaces:**
- Consumes: un objet `praw.Reddit` (deja fourni par `collectors.reddit.get_client()`, `collectors/reddit.py:15`)
- Produces: `discovery.reddit_scan.scan_subreddits(reddit, subreddits: list[str], post_limit: int = 50) -> list[dict]` — chaque dict a les cles `subreddit`, `title`

- [ ] **Step 1: Ecrire le test qui echoue**

Creer `tests/test_reddit_scan.py` :

```python
from unittest.mock import MagicMock

from discovery import reddit_scan


def test_scan_subreddits_collects_hot_and_rising_titles():
    fake_post_hot = MagicMock(title="Hot post about gadgets")
    fake_post_rising = MagicMock(title="Rising post about gadgets")
    fake_subreddit = MagicMock()
    fake_subreddit.hot.return_value = [fake_post_hot]
    fake_subreddit.rising.return_value = [fake_post_rising]
    fake_reddit = MagicMock()
    fake_reddit.subreddit.return_value = fake_subreddit

    posts = reddit_scan.scan_subreddits(fake_reddit, ["gadgets"], post_limit=10)

    assert posts == [
        {"subreddit": "gadgets", "title": "Hot post about gadgets"},
        {"subreddit": "gadgets", "title": "Rising post about gadgets"},
    ]
    fake_reddit.subreddit.assert_called_once_with("gadgets")
    fake_subreddit.hot.assert_called_once_with(limit=10)
    fake_subreddit.rising.assert_called_once_with(limit=10)


def test_scan_subreddits_handles_multiple_subreddits():
    fake_subreddit = MagicMock()
    fake_subreddit.hot.return_value = []
    fake_subreddit.rising.return_value = []
    fake_reddit = MagicMock()
    fake_reddit.subreddit.return_value = fake_subreddit

    reddit_scan.scan_subreddits(fake_reddit, ["gadgets", "beauty"], post_limit=5)

    assert fake_reddit.subreddit.call_count == 2
```

- [ ] **Step 2: Lancer les tests pour verifier qu'ils echouent**

Run: `pytest tests/test_reddit_scan.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'discovery.reddit_scan'`

- [ ] **Step 3: Implementer `discovery/reddit_scan.py`**

```python
"""Scan de subreddits pour le mode discovery.

Contrairement au mode watchlist (recherche par mot-cle via search_keyword,
voir collectors/reddit.py), discovery n'a pas de mot-cle a chercher : on
recupere les listings "hot" et "rising" tels quels pour en extraire les
phrases candidates ensuite (discovery/extract.py).
"""
from __future__ import annotations

import praw


def scan_subreddits(reddit: praw.Reddit, subreddits: list[str], post_limit: int = 50) -> list[dict]:
    """Retourne les titres des posts hot + rising pour chaque subreddit donne."""
    posts = []
    for name in subreddits:
        sub = reddit.subreddit(name)
        for submission in sub.hot(limit=post_limit):
            posts.append({"subreddit": name, "title": submission.title})
        for submission in sub.rising(limit=post_limit):
            posts.append({"subreddit": name, "title": submission.title})
    return posts
```

- [ ] **Step 4: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_reddit_scan.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add discovery/reddit_scan.py tests/test_reddit_scan.py
git commit -m "feat: hot+rising subreddit scanning for discovery mode"
```

---

### Task 5: Promotion d'un candidat vers la watchlist

**Files:**
- Create: `discovery/promote.py`
- Create: `tests/test_promote.py`

**Interfaces:**
- Consumes: rien (fonctions pures sur du texte YAML)
- Produces:
  - `discovery.promote.add_keyword_to_yaml_text(yaml_text: str, phrase: str, category: str) -> str`
  - `discovery.promote.is_duplicate(yaml_text: str, phrase: str, category: str) -> bool`

**Pourquoi du texte plutot que `yaml.dump`** : `config/watchlist.yaml` contient des commentaires utiles pour l'utilisateur ; PyYAML ne les preserve pas lors d'un round-trip `safe_load`/`dump`. `promote` est une action rare et manuelle (pas un chemin chaud) donc une insertion textuelle ciblee est preferable a l'ajout d'une dependance (`ruamel.yaml`) pour ce seul besoin.

- [ ] **Step 1: Ecrire le test qui echoue**

Creer `tests/test_promote.py` :

```python
from discovery.promote import add_keyword_to_yaml_text, is_duplicate

EXISTING_YAML = """categories:
  gadgets:
    keywords:
      - "purificateur d'air portable"
      - "mini projecteur"
    subreddits:
      - gadgets
      - shutupandtakemymoney

trends_timeframe: "today 3-m"
trends_geo: "FR"
"""


def test_add_keyword_to_existing_category():
    result = add_keyword_to_yaml_text(EXISTING_YAML, "chargeur solaire portable", "gadgets")
    lines = result.splitlines()
    idx = lines.index("    keywords:")
    assert lines[idx + 1] == '      - "chargeur solaire portable"'


def test_add_keyword_creates_new_category():
    result = add_keyword_to_yaml_text(EXISTING_YAML, "fontaine a eau chat", "animaux")
    assert "  animaux:" in result
    assert '      - "fontaine a eau chat"' in result
    assert "trends_timeframe:" in result  # le reste du fichier est preserve


def test_add_keyword_preserves_comments():
    yaml_with_comment = "# commentaire important\n" + EXISTING_YAML
    result = add_keyword_to_yaml_text(yaml_with_comment, "chargeur solaire portable", "gadgets")
    assert "# commentaire important" in result


def test_is_duplicate_detects_existing_keyword():
    assert is_duplicate(EXISTING_YAML, "mini projecteur", "gadgets") is True
    assert is_duplicate(EXISTING_YAML, "nouveau produit", "gadgets") is False
    assert is_duplicate(EXISTING_YAML, "mini projecteur", "beaute") is False
```

- [ ] **Step 2: Lancer les tests pour verifier qu'ils echouent**

Run: `pytest tests/test_promote.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'discovery.promote'`

- [ ] **Step 3: Implementer `discovery/promote.py`**

```python
"""Ajout d'un candidat discovery a config/watchlist.yaml.

Manipulation textuelle plutot que yaml.safe_load + yaml.dump : preserve
les commentaires du fichier (PyYAML ne les garde pas lors d'un round-trip).
yaml.safe_load reste utilise pour la detection de doublons (lecture seule,
aucun risque de perte de formatage).
"""
from __future__ import annotations

import yaml


def is_duplicate(yaml_text: str, phrase: str, category: str) -> bool:
    data = yaml.safe_load(yaml_text) or {}
    categories = data.get("categories", {})
    cat = categories.get(category)
    if not cat:
        return False
    return phrase in cat.get("keywords", [])


def add_keyword_to_yaml_text(yaml_text: str, phrase: str, category: str) -> str:
    lines = yaml_text.splitlines(keepends=True)
    category_header = f"  {category}:\n"

    category_start_idx = None
    keywords_line_idx = None
    for i, line in enumerate(lines):
        if line == category_header:
            category_start_idx = i
        elif category_start_idx is not None and line.strip() == "keywords:":
            keywords_line_idx = i
            break

    new_item = f'      - "{phrase}"\n'

    if keywords_line_idx is not None:
        lines.insert(keywords_line_idx + 1, new_item)
        return "".join(lines)

    # Categorie absente : ajouter un nouveau bloc juste avant la fin du bloc "categories:"
    insert_idx = None
    in_categories = False
    for i, line in enumerate(lines):
        if line.strip() == "categories:":
            in_categories = True
            continue
        if in_categories and line.strip() != "" and not line.startswith(" "):
            insert_idx = i
            break
    if insert_idx is None:
        insert_idx = len(lines)

    new_block = (
        f"  {category}:\n"
        f"    keywords:\n"
        f'      - "{phrase}"\n'
        f"    subreddits: []\n"
        f"\n"
    )
    lines.insert(insert_idx, new_block)
    return "".join(lines)
```

- [ ] **Step 4: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_promote.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add discovery/promote.py tests/test_promote.py
git commit -m "feat: promote discovery candidates into watchlist.yaml"
```

---

### Task 6: Commandes CLI `discover` et `promote`

**Files:**
- Modify: `cli.py`
- Create: `tests/test_cli_discover.py`

**Interfaces:**
- Consumes: `discovery.reddit_scan.scan_subreddits`, `discovery.extract.extract_phrases`, `discovery.velocity.find_candidates`, `discovery.promote.is_duplicate`, `discovery.promote.add_keyword_to_yaml_text` (Tasks 2-5) ; `storage.db.insert_phrase_mentions` (Task 1) ; `collectors.reddit.get_client` (existant)
- Produces: `cli.cmd_discover(watchlist: dict) -> None`, `cli.cmd_promote(phrase: str, category: str) -> None`, sous-commandes `discover`/`promote` en argparse

- [ ] **Step 1: Ecrire le test qui echoue**

Creer `tests/test_cli_discover.py` :

```python
from collectors import reddit as reddit_collector
from discovery import reddit_scan
from storage import db as storage_db

import cli


def test_cmd_discover_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    report_path = tmp_path / "discovery_report.md"
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", report_path)

    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())
    monkeypatch.setattr(
        reddit_scan,
        "scan_subreddits",
        lambda reddit, subreddits, post_limit: [
            {"subreddit": "gadgets", "title": "This LED face mask is amazing"},
            {"subreddit": "gadgets", "title": "I love my LED face mask so much"},
        ],
    )

    watchlist = {
        "discovery": {
            "subreddits": ["gadgets"],
            "post_limit": 10,
            "min_mentions": 1,
            "min_growth_pct": 0,
        }
    }

    cli.cmd_discover(watchlist)

    assert report_path.exists()
    assert "led face mask" in report_path.read_text()


def test_cmd_discover_skips_without_reddit_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")

    def _raise_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_key_error)

    cli.cmd_discover({"discovery": {"subreddits": ["gadgets"]}})

    captured = capsys.readouterr()
    assert "credentials manquants" in captured.out


def test_cmd_promote_adds_keyword_to_watchlist(tmp_path, monkeypatch):
    watchlist_file = tmp_path / "watchlist.yaml"
    watchlist_file.write_text(
        'categories:\n'
        '  gadgets:\n'
        '    keywords:\n'
        '      - "mini projecteur"\n'
        '    subreddits:\n'
        '      - gadgets\n'
    )
    monkeypatch.setattr(cli, "WATCHLIST_PATH", watchlist_file)

    cli.cmd_promote("chargeur solaire portable", "gadgets")

    content = watchlist_file.read_text()
    assert '"chargeur solaire portable"' in content


def test_cmd_promote_skips_duplicate(tmp_path, monkeypatch, capsys):
    watchlist_file = tmp_path / "watchlist.yaml"
    watchlist_file.write_text(
        'categories:\n'
        '  gadgets:\n'
        '    keywords:\n'
        '      - "mini projecteur"\n'
        '    subreddits:\n'
        '      - gadgets\n'
    )
    monkeypatch.setattr(cli, "WATCHLIST_PATH", watchlist_file)

    cli.cmd_promote("mini projecteur", "gadgets")

    captured = capsys.readouterr()
    assert "deja" in captured.out
    assert content_unchanged(watchlist_file)


def content_unchanged(path):
    return path.read_text().count("mini projecteur") == 1
```

- [ ] **Step 2: Lancer les tests pour verifier qu'ils echouent**

Run: `pytest tests/test_cli_discover.py -v`
Expected: FAIL avec `AttributeError: module 'cli' has no attribute 'cmd_discover'` (ou `DISCOVERY_REPORT_PATH`)

- [ ] **Step 3: Modifier `cli.py`**

Ajouter aux imports en haut du fichier :

```python
from datetime import datetime, timezone

from discovery import extract, promote, reddit_scan, velocity
```

Ajouter apres `REPORT_PATH = ...` :

```python
DISCOVERY_REPORT_PATH = Path(__file__).parent / "data" / "discovery_report.md"
```

Ajouter apres `cmd_scan` (avant `write_report`) :

```python
def cmd_discover(watchlist: dict) -> None:
    """Discovery : scanne Reddit sans mots-cles, detecte des candidats emergents."""
    db.init_db()
    conn = db.get_connection()
    discovery_cfg = watchlist.get("discovery", {})
    subreddits = discovery_cfg.get("subreddits", [])
    post_limit = discovery_cfg.get("post_limit", 50)
    min_mentions = discovery_cfg.get("min_mentions", 5)
    min_growth = discovery_cfg.get("min_growth_pct", 30)

    try:
        reddit_client = reddit_collector.get_client()
    except KeyError:
        print("Reddit : credentials manquants, discovery impossible sans acces Reddit")
        conn.close()
        return

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

    candidates = velocity.find_candidates(conn, min_mentions=min_mentions, min_growth_pct=min_growth)
    conn.close()
    write_discovery_report(candidates)


def cmd_promote(phrase: str, category: str) -> None:
    """Ajoute un candidat discovery a la watchlist, sous la categorie donnee."""
    yaml_text = WATCHLIST_PATH.read_text()
    if promote.is_duplicate(yaml_text, phrase, category):
        print(f"'{phrase}' est deja dans la categorie '{category}', rien a faire")
        return
    updated = promote.add_keyword_to_yaml_text(yaml_text, phrase, category)
    WATCHLIST_PATH.write_text(updated)
    print(f"'{phrase}' ajoute a la categorie '{category}' dans {WATCHLIST_PATH}")
```

Ajouter apres `write_report` :

```python
def write_discovery_report(candidates: list[dict]) -> None:
    """Genere un rapport Markdown des candidats discovery, trie par croissance."""
    lines = ["# Rapport discovery — trend-radar", ""]
    if not candidates:
        lines.append("Aucun candidat au-dessus des seuils pour ce scan.")
    for c in candidates:
        lines.append(f"## {c['phrase']}")
        lines.append(f"- Mentions cette fenetre : {c['mention_count']}")
        lines.append(f"- Croissance : {c['growth_pct']}%")
        lines.append(f"- Pour suivre ce candidat : `python cli.py promote \"{c['phrase']}\" <categorie>`")
        lines.append("")
    DISCOVERY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Rapport discovery ecrit : {DISCOVERY_REPORT_PATH}")
```

Modifier `main()` — remplacer :

```python
    sub.add_parser("scan", help="veille continue sur la watchlist")

    args = parser.parse_args()
    watchlist = load_watchlist()

    if args.command == "check":
        cmd_check(args.keyword, watchlist)
    elif args.command == "scan":
        cmd_scan(watchlist)
```

par :

```python
    sub.add_parser("scan", help="veille continue sur la watchlist")

    sub.add_parser("discover", help="detecte des candidats emergents sur Reddit, sans mots-cles")

    promote_parser = sub.add_parser("promote", help="ajoute un candidat discovery a la watchlist")
    promote_parser.add_argument("phrase")
    promote_parser.add_argument("category")

    args = parser.parse_args()
    watchlist = load_watchlist()

    if args.command == "check":
        cmd_check(args.keyword, watchlist)
    elif args.command == "scan":
        cmd_scan(watchlist)
    elif args.command == "discover":
        cmd_discover(watchlist)
    elif args.command == "promote":
        cmd_promote(args.phrase, args.category)
```

- [ ] **Step 4: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_cli_discover.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lancer toute la suite de tests**

Run: `pytest -v`
Expected: PASS (tous les tests, Tasks 1-6 inclus)

- [ ] **Step 6: Commit**

```bash
git add cli.py tests/test_cli_discover.py
git commit -m "feat: wire discover and promote CLI subcommands"
```

---

### Task 7: Configuration reelle, doc, verification finale

**Files:**
- Modify: `config/watchlist.yaml`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Consumes: rien (configuration et documentation, pas de nouveau code)
- Produces: rien de nouveau — cloture le plan

- [ ] **Step 1: Ajouter la section `discovery` a `config/watchlist.yaml`**

Ajouter a la fin du fichier :

```yaml

# Configuration du mode discovery (python cli.py discover) — detecte des
# candidats sans mots-cles fournis a l'avance, a partir de l'activite Reddit.
discovery:
  subreddits:
    # subreddits deja cibles par categorie (reutilises)
    - gadgets
    - shutupandtakemymoney
    - SkincareAddiction
    - beauty
    - BuyItForLife
    - HomeImprovement
    - fitness
    - xxfitness
    - cats
    - dogs
    - Mommit
    - beyondthebump
    # subreddits generalistes "produits tendance", hors categories
    - DidntKnowIWantedThat
    - InternetIsBeautiful
    - CoolGadgets
    - ProductPorn
  post_limit: 50
  min_mentions: 5
  min_growth_pct: 30
```

- [ ] **Step 2: Ignorer le rapport discovery genere**

Ajouter a `.gitignore` :

```
data/discovery_report.md
```

- [ ] **Step 3: Documenter dans `README.md`**

Ajouter apres la section `## Usage` existante :

```markdown
### Mode discovery (sans mots-cles)

```bash
# Detecte des candidats emergents sur Reddit (config/watchlist.yaml -> discovery)
python cli.py discover

# Lit data/discovery_report.md, puis fait entrer un candidat dans le pipeline standard
python cli.py promote "nom du produit" gadgets
```

`discover` ne consulte jamais Google Trends automatiquement — seul `promote`
suivi de `scan` valide un candidat via Trends + convergence. Ca evite de
gaspiller le budget de requetes Trends sur du bruit d'extraction.
```

- [ ] **Step 4: Verification finale complete**

Run: `pytest -v`
Expected: PASS (tous les tests)

Run: `python3 -m py_compile cli.py discovery/*.py storage/*.py collectors/*.py scoring/*.py`
Expected: aucune erreur

Run: `python3 -c "import yaml; yaml.safe_load(open('config/watchlist.yaml'))"`
Expected: aucune erreur (YAML valide)

- [ ] **Step 5: Commit**

```bash
git add config/watchlist.yaml .gitignore README.md
git commit -m "docs: document discovery mode, configure real subreddits and thresholds"
```

---

## Notes d'execution

- Les credentials Reddit ne sont toujours pas debloques au moment de ce plan (ticket "Data Access Request" en attente cote Reddit). Toutes les taches ci-dessus sont testables sans acces Reddit reel (mocks PRAW, DB isolee via `tmp_path`). Un test manuel bout-en-bout (`python cli.py discover` reel) reste a faire une fois l'acces debloque.
- `growth_pct` (Task 3) est reutilise tel quel depuis `collectors/google_trends.py` — ne pas dupliquer cette logique si un besoin different apparait plus tard (ex: fenetres glissantes sur plusieurs runs) ; l'etendre plutot sur place avec un parametre.
