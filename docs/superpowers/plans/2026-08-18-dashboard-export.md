# Dashboard Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a JSON export of scan/discover results and a static web dashboard, deployable on Vercel, so results are viewable without the terminal.

**Architecture:** `cli.py` gains `write_signals_json()` (writes `web/public/data/signals.json`, the file Vercel serves directly — no build step) and a `--publish` flag on `scan`/`discover` that calls a new `publish.py` module to git-commit-and-push just that file, triggering a Vercel redeploy. A single static `web/public/index.html` (vanilla JS, no framework) fetches and renders the JSON.

**Tech Stack:** Python (stdlib `json`, `subprocess`), vanilla HTML/CSS/JS, Vercel (static site, `vercel` CLI already authenticated locally).

## Global Constraints

- Gratuit et self-hosted : aucune dependance a une API payante (spec: contraintes projet).
- Zero build step pour le dashboard : `web/public/index.html` doit fonctionner tel quel, sans framework ni etape de compilation.
- `publish_json()` ne doit committer/pousser QUE `web/public/data/signals.json` — jamais `git add -A` — pour ne jamais embarquer d'autres changements en cours de l'utilisateur dans un commit automatique (spec: Publication).
- `write_signals_json` ne doit jamais effacer l'autre section (`scan` ne touche que `watchlist`, `discover` ne touche que `discovery`) et doit tolerer un fichier JSON corrompu existant sans planter (spec: Erreurs).
- Comportement par defaut inchange : sans `--publish`, seul le JSON local est mis a jour, rien n'est pousse (spec: Publication).

---

## File Structure

**Create:**
- `publish.py` — commit + push de `web/public/data/signals.json`
- `web/public/index.html` — dashboard statique
- `tests/test_signals_json.py`
- `tests/test_publish.py`
- `tests/test_cli_publish_flag.py`

**Modify:**
- `cli.py` — ajoute `write_signals_json`, le flag `--publish`, les appels dans `cmd_scan`/`cmd_discover`
- `README.md` — documente `--publish` et le deploiement Vercel
- `.gitignore` — retirer toute exclusion qui empecherait de committer `web/public/data/signals.json` (verifier qu'aucune regle ne matche ce chemin ; `data/*.db` etc. ne concernent que le dossier `data/` a la racine, pas `web/public/data/`, mais a verifier explicitement)

---

### Task 1: `write_signals_json` dans cli.py

**Files:**
- Modify: `cli.py`
- Test: `tests/test_signals_json.py`

**Interfaces:**
- Consumes: rien (nouvelle fonction independante)
- Produces: `cli.write_signals_json(section: str, entries: list[dict]) -> None`, constante `cli.SIGNALS_JSON_PATH: Path` — des taches futures (2, 3) en dependent

- [ ] **Step 1: Ecrire le test qui echoue**

Creer `tests/test_signals_json.py` :

```python
import json

import cli


def test_write_signals_json_creates_file(tmp_path, monkeypatch):
    json_path = tmp_path / "signals.json"
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", json_path)

    cli.write_signals_json("watchlist", [{"keyword": "test", "convergence_score": 5.0}])

    data = json.loads(json_path.read_text())
    assert data["watchlist"] == [{"keyword": "test", "convergence_score": 5.0}]
    assert data["discovery"] == []
    assert "last_updated" in data


def test_write_signals_json_preserves_other_section(tmp_path, monkeypatch):
    json_path = tmp_path / "signals.json"
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", json_path)

    cli.write_signals_json("watchlist", [{"keyword": "a"}])
    cli.write_signals_json("discovery", [{"phrase": "b"}])

    data = json.loads(json_path.read_text())
    assert data["watchlist"] == [{"keyword": "a"}]
    assert data["discovery"] == [{"phrase": "b"}]


def test_write_signals_json_tolerates_corrupted_file(tmp_path, monkeypatch):
    json_path = tmp_path / "signals.json"
    json_path.write_text("{not valid json")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", json_path)

    cli.write_signals_json("watchlist", [{"keyword": "a"}])

    data = json.loads(json_path.read_text())
    assert data["watchlist"] == [{"keyword": "a"}]
    assert data["discovery"] == []
```

- [ ] **Step 2: Lancer les tests pour verifier qu'ils echouent**

Run: `pytest tests/test_signals_json.py -v`
Expected: FAIL avec `AttributeError: module 'cli' has no attribute 'write_signals_json'` (ou `SIGNALS_JSON_PATH`)

- [ ] **Step 3: Implementer dans `cli.py`**

Ajouter `import json` aux imports en haut du fichier (a cote de `import argparse`).

Ajouter apres `DISCOVERY_REPORT_PATH = ...` :

```python
SIGNALS_JSON_PATH = Path(__file__).parent / "web" / "public" / "data" / "signals.json"
```

Ajouter la fonction (par exemple juste apres `write_discovery_report`) :

```python
def write_signals_json(section: str, entries: list[dict]) -> None:
    """Met a jour une section ('watchlist' ou 'discovery') de signals.json,
    en preservant l'autre section si le fichier existe deja. Tolere un
    fichier JSON corrompu en repartant d'un objet vide plutot que planter."""
    data: dict = {}
    if SIGNALS_JSON_PATH.exists():
        try:
            data = json.loads(SIGNALS_JSON_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    data.setdefault("watchlist", [])
    data.setdefault("discovery", [])
    data[section] = entries
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    SIGNALS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIGNALS_JSON_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"signals.json mis a jour : {SIGNALS_JSON_PATH}")
```

`datetime`/`timezone` sont deja importes en haut de `cli.py` (utilises par `cmd_discover`).

- [ ] **Step 4: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_signals_json.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add cli.py tests/test_signals_json.py
git commit -m "feat: add write_signals_json for dashboard export"
```

---

### Task 2: module `publish.py`

**Files:**
- Create: `publish.py`
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: rien (module independant, utilise `subprocess`)
- Produces: `publish.publish_json(repo_root: Path) -> bool` — la tache 3 en depend

- [ ] **Step 1: Ecrire le test qui echoue**

Creer `tests/test_publish.py` :

```python
from unittest.mock import MagicMock, patch

import publish


def test_publish_json_noop_when_unchanged(tmp_path):
    with patch("publish.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = publish.publish_json(tmp_path)

    assert result is False
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[:2] == ["git", "status"]


def test_publish_json_commits_and_pushes_when_changed(tmp_path):
    status_result = MagicMock(returncode=0, stdout=" M web/public/data/signals.json\n", stderr="")
    ok_result = MagicMock(returncode=0, stdout="", stderr="")

    with patch("publish.subprocess.run") as mock_run:
        mock_run.side_effect = [status_result, ok_result, ok_result, ok_result]
        result = publish.publish_json(tmp_path)

    assert result is True
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert calls[0][:2] == ["git", "status"]
    assert calls[1][:2] == ["git", "add"]
    assert calls[2][:2] == ["git", "commit"]
    assert calls[3] == ["git", "push"]


def test_publish_json_handles_push_failure(tmp_path):
    status_result = MagicMock(returncode=0, stdout=" M web/public/data/signals.json\n", stderr="")
    ok_result = MagicMock(returncode=0, stdout="", stderr="")
    push_fail = MagicMock(returncode=1, stdout="", stderr="fatal: could not read from remote")

    with patch("publish.subprocess.run") as mock_run:
        mock_run.side_effect = [status_result, ok_result, ok_result, push_fail]
        result = publish.publish_json(tmp_path)

    assert result is False


def test_publish_json_handles_status_failure(tmp_path):
    with patch("publish.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="fatal: not a git repository")
        result = publish.publish_json(tmp_path)

    assert result is False
```

- [ ] **Step 2: Lancer les tests pour verifier qu'ils echouent**

Run: `pytest tests/test_publish.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'publish'`

- [ ] **Step 3: Implementer `publish.py`**

```python
"""Publication de signals.json vers GitHub (declenche le redeploy Vercel).

Ne committe/pousse QUE web/public/data/signals.json, jamais `git add -A` :
on ne veut pas embarquer d'autres changements en cours de l'utilisateur
dans un commit automatique. Toute erreur (reseau, remote absent, conflit)
est affichee clairement, sans exception non geree.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

SIGNALS_JSON_RELATIVE_PATH = "web/public/data/signals.json"


def publish_json(repo_root: Path) -> bool:
    """Commit + push signals.json s'il a change. Retourne True si un push
    a eu lieu, False si rien n'avait change ou en cas d'erreur."""
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", SIGNALS_JSON_RELATIVE_PATH],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        print(f"Erreur git status : {status.stderr.strip()}")
        return False
    if not status.stdout.strip():
        print("Rien a publier (signals.json inchange)")
        return False

    add = subprocess.run(
        ["git", "add", SIGNALS_JSON_RELATIVE_PATH], cwd=repo_root, capture_output=True, text=True
    )
    if add.returncode != 0:
        print(f"Erreur git add : {add.stderr.strip()}")
        return False

    commit = subprocess.run(
        ["git", "commit", "-m", "chore: update signals.json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        print(f"Erreur git commit : {commit.stderr.strip()}")
        return False

    push = subprocess.run(["git", "push"], cwd=repo_root, capture_output=True, text=True)
    if push.returncode != 0:
        print(f"Erreur git push : {push.stderr.strip()}")
        return False

    print("signals.json publie (commit + push)")
    return True
```

- [ ] **Step 4: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_publish.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add publish.py tests/test_publish.py
git commit -m "feat: add publish.py to push signals.json to GitHub"
```

---

### Task 3: flag `--publish` et appels dans `cmd_scan`/`cmd_discover`

**Files:**
- Modify: `cli.py`
- Test: `tests/test_cli_publish_flag.py`

**Interfaces:**
- Consumes: `cli.write_signals_json` (Task 1), `publish.publish_json` (Task 2)
- Produces: `cmd_scan(watchlist: dict, publish_after: bool = False) -> None`, `cmd_discover(watchlist: dict, publish_after: bool = False) -> None` (signatures modifiees, parametre ajoute avec valeur par defaut — n'affecte aucun appelant existant)

- [ ] **Step 1: Ecrire le test qui echoue**

Creer `tests/test_cli_publish_flag.py` :

```python
import json
from unittest.mock import MagicMock

from collectors import google_trends
from collectors import reddit as reddit_collector
from discovery import reddit_scan
from storage import db as storage_db

import cli
import publish


def test_cmd_discover_writes_signals_json(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", tmp_path / "discovery_report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")

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
        "discovery": {"subreddits": ["gadgets"], "post_limit": 10, "min_mentions": 1, "min_growth_pct": 0}
    }
    cli.cmd_discover(watchlist)

    data = json.loads((tmp_path / "signals.json").read_text())
    assert any(c["phrase"] == "led face mask" for c in data["discovery"])


def test_cmd_discover_publishes_when_flag_set(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", tmp_path / "discovery_report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())
    monkeypatch.setattr(reddit_scan, "scan_subreddits", lambda reddit, subreddits, post_limit: [])

    mock_publish = MagicMock(return_value=True)
    monkeypatch.setattr(publish, "publish_json", mock_publish)

    cli.cmd_discover({"discovery": {"subreddits": []}}, publish_after=True)

    mock_publish.assert_called_once()


def test_cmd_discover_does_not_publish_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "DISCOVERY_REPORT_PATH", tmp_path / "discovery_report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(reddit_collector, "get_client", lambda: object())
    monkeypatch.setattr(reddit_scan, "scan_subreddits", lambda reddit, subreddits, post_limit: [])

    mock_publish = MagicMock()
    monkeypatch.setattr(publish, "publish_json", mock_publish)

    cli.cmd_discover({"discovery": {"subreddits": []}})

    mock_publish.assert_not_called()


def test_cmd_scan_writes_signals_json_and_publishes(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    monkeypatch.setattr(google_trends, "fetch_interest_over_time", lambda *a, **k: [])

    def _raise_key_error():
        raise KeyError("REDDIT_CLIENT_ID")

    monkeypatch.setattr(reddit_collector, "get_client", _raise_key_error)

    mock_publish = MagicMock(return_value=True)
    monkeypatch.setattr(publish, "publish_json", mock_publish)

    watchlist = {
        "categories": {"gadgets": {"keywords": ["test kw"], "subreddits": []}},
        "thresholds": {"trends_growth_pct": 20, "reddit_min_posts": 3, "reddit_min_avg_score": 10},
    }

    cli.cmd_scan(watchlist, publish_after=True)

    data = json.loads((tmp_path / "signals.json").read_text())
    assert data["watchlist"][0]["keyword"] == "test kw"
    mock_publish.assert_called_once()
```

- [ ] **Step 2: Lancer les tests pour verifier qu'ils echouent**

Run: `pytest tests/test_cli_publish_flag.py -v`
Expected: FAIL — `test_cmd_discover_writes_signals_json` echoue car `signals.json` n'est pas ecrit ; les tests avec `publish_after` echouent avec `TypeError: cmd_discover() got an unexpected keyword argument 'publish_after'`

- [ ] **Step 3: Modifier `cli.py`**

Ajouter `import publish` aux imports (a cote de `from discovery import ...`).

Modifier la signature et la fin de `cmd_discover` — remplacer :

```python
def cmd_discover(watchlist: dict) -> None:
```

par :

```python
def cmd_discover(watchlist: dict, publish_after: bool = False) -> None:
```

Et remplacer la derniere ligne de la fonction :

```python
    write_discovery_report(candidates)
```

par :

```python
    write_discovery_report(candidates)
    write_signals_json("discovery", candidates)
    if publish_after:
        publish.publish_json(Path(__file__).parent)
```

Modifier la signature et la fin de `cmd_scan` — remplacer :

```python
def cmd_scan(watchlist: dict) -> None:
```

par :

```python
def cmd_scan(watchlist: dict, publish_after: bool = False) -> None:
```

Et remplacer :

```python
    conn.close()
    write_report(results)
```

par :

```python
    conn.close()
    write_report(results)

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
    write_signals_json("watchlist", signal_entries)
    if publish_after:
        publish.publish_json(Path(__file__).parent)
```

Modifier `main()` — remplacer :

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

par :

```python
    scan_parser = sub.add_parser("scan", help="veille continue sur la watchlist")
    scan_parser.add_argument(
        "--publish", action="store_true", help="pousse signals.json vers GitHub apres le scan"
    )

    discover_parser = sub.add_parser(
        "discover", help="detecte des candidats emergents sur Reddit, sans mots-cles"
    )
    discover_parser.add_argument(
        "--publish", action="store_true", help="pousse signals.json vers GitHub apres le scan"
    )

    promote_parser = sub.add_parser("promote", help="ajoute un candidat discovery a la watchlist")
    promote_parser.add_argument("phrase")
    promote_parser.add_argument("category")

    args = parser.parse_args()
    watchlist = load_watchlist()

    if args.command == "check":
        cmd_check(args.keyword, watchlist)
    elif args.command == "scan":
        cmd_scan(watchlist, publish_after=args.publish)
    elif args.command == "discover":
        cmd_discover(watchlist, publish_after=args.publish)
    elif args.command == "promote":
        cmd_promote(args.phrase, args.category)
```

- [ ] **Step 4: Lancer les tests pour verifier qu'ils passent**

Run: `pytest tests/test_cli_publish_flag.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lancer toute la suite de tests**

Run: `pytest -v`
Expected: PASS (tous les tests, y compris les 35 deja existants)

- [ ] **Step 6: Commit**

```bash
git add cli.py tests/test_cli_publish_flag.py
git commit -m "feat: wire --publish flag into scan/discover commands"
```

---

### Task 4: dashboard statique `web/public/index.html`

**Files:**
- Create: `web/public/index.html`

**Interfaces:**
- Consumes: `web/public/data/signals.json` (produit par Task 1-3, format : `{last_updated, watchlist: [...], discovery: [...]}`)
- Produces: rien (page terminale, aucune autre tache n'en depend)

- [ ] **Step 1: Creer le fichier**

```html
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>trend-radar</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; background: #fafafa; color: #1a1a1a; }
  h1 { font-size: 1.5rem; }
  h2 { font-size: 1.1rem; margin-top: 2rem; }
  .updated { color: #666; font-size: 0.9rem; margin-bottom: 1rem; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; }
  th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #ddd; }
  th { font-size: 0.8rem; text-transform: uppercase; color: #666; }
  .score-fort { font-weight: bold; color: #0a7d2e; }
  .empty { color: #666; font-style: italic; padding: 1rem 0; }
  code { background: #eee; padding: 0.1rem 0.3rem; border-radius: 3px; }
</style>
</head>
<body>
  <h1>trend-radar</h1>
  <div class="updated" id="updated"></div>

  <h2>Watchlist</h2>
  <div id="watchlist-container"></div>

  <h2>Discovery</h2>
  <div id="discovery-container"></div>

  <script>
    async function loadSignals() {
      try {
        const res = await fetch('data/signals.json');
        if (!res.ok) throw new Error('not found');
        const data = await res.json();
        render(data);
      } catch (err) {
        showEmptyState();
      }
    }

    function showEmptyState() {
      const msg = '<p class="empty">Aucune donnee pour l\'instant &mdash; lance <code>python cli.py scan --publish</code>.</p>';
      document.getElementById('watchlist-container').innerHTML = msg;
      document.getElementById('discovery-container').innerHTML = '';
    }

    function render(data) {
      document.getElementById('updated').textContent = 'Derniere mise a jour : ' + (data.last_updated || 'inconnue');
      renderWatchlist(data.watchlist || []);
      renderDiscovery(data.discovery || []);
    }

    function renderWatchlist(items) {
      const container = document.getElementById('watchlist-container');
      if (items.length === 0) {
        container.innerHTML = '<p class="empty">Aucun resultat de scan pour l\'instant.</p>';
        return;
      }
      const sorted = [...items].sort((a, b) => b.convergence_score - a.convergence_score);
      let html = '<table><thead><tr><th>Mot-cle</th><th>Categorie</th><th>Score</th><th>Sources</th><th>Trends</th><th>Reddit</th></tr></thead><tbody>';
      for (const r of sorted) {
        const cls = r.sources_count >= 2 ? 'score-fort' : '';
        html += '<tr><td>' + escapeHtml(r.keyword) + '</td><td>' + escapeHtml(r.category) + '</td>' +
          '<td class="' + cls + '">' + r.convergence_score + '</td><td>' + r.sources_count + '/2</td>' +
          '<td>' + r.trends_growth_pct + '%</td><td>' + r.reddit_post_count + ' posts</td></tr>';
      }
      html += '</tbody></table>';
      container.innerHTML = html;
    }

    function renderDiscovery(items) {
      const container = document.getElementById('discovery-container');
      if (items.length === 0) {
        container.innerHTML = '<p class="empty">Aucun candidat discovery pour l\'instant.</p>';
        return;
      }
      const sorted = [...items].sort((a, b) => b.growth_pct - a.growth_pct);
      let html = '<table><thead><tr><th>Phrase</th><th>Mentions</th><th>Croissance</th></tr></thead><tbody>';
      for (const c of sorted) {
        html += '<tr><td>' + escapeHtml(c.phrase) + '</td><td>' + c.mention_count + '</td><td>' + c.growth_pct + '%</td></tr>';
      }
      html += '</tbody></table>';
      container.innerHTML = html;
    }

    function escapeHtml(str) {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    }

    loadSignals();
  </script>
</body>
</html>
```

`escapeHtml` passe toute donnee provenant du JSON (mots-cles, phrases discovery extraites par spaCy depuis du texte Reddit non fiable) par `textContent` avant de l'injecter dans le HTML — evite une injection XSS si une phrase contenait par accident des caracteres HTML.

- [ ] **Step 2: Verification manuelle (pas de test automatise pour cette page statique)**

Creer un fichier de donnees d'exemple et servir le dossier en local :

```bash
mkdir -p web/public/data
cat > web/public/data/signals.json << 'EOF'
{
  "last_updated": "2026-08-18T12:00:00+00:00",
  "watchlist": [
    {"keyword": "ceinture de sudation", "category": "fitness", "convergence_score": 13.88, "sources_count": 1, "trends_growth_pct": 38.8, "reddit_post_count": 0, "reddit_avg_score": 0}
  ],
  "discovery": []
}
EOF
python3 -m http.server 8000 --directory web/public &
sleep 1
curl -s http://localhost:8000/index.html | grep -q "trend-radar" && echo "index.html OK"
curl -s http://localhost:8000/data/signals.json | grep -q "ceinture de sudation" && echo "signals.json accessible OK"
kill %1
```

Expected: les deux `echo` s'affichent ("index.html OK" et "signals.json accessible OK"). Supprimer ensuite le fichier d'exemple :

```bash
rm web/public/data/signals.json
```

(le vrai `signals.json` sera regenere par `cli.py scan`/`discover`, pas besoin de garder cet exemple committe)

- [ ] **Step 3: Commit**

```bash
git add web/public/index.html
git commit -m "feat: add static dashboard for signals.json"
```

---

### Task 5: documentation et verification finale

**Files:**
- Modify: `README.md`
- Modify: `.gitignore` (verification, pas forcement de changement)

**Interfaces:**
- Consumes: rien (documentation, pas de nouveau code)
- Produces: rien de nouveau — cloture le plan

- [ ] **Step 1: Verifier que `.gitignore` n'exclut pas `web/public/data/signals.json`**

Lire `.gitignore` et confirmer qu'aucune regle ne matche ce chemin (les regles existantes `data/*.db`, `data/report.md`, `data/discovery_report.md` visent le dossier `data/` a la racine, pas `web/public/data/`). Si une regle trop large existait (ex: `data/` sans prefixe), l'ajuster pour ne cibler que le dossier racine. Verifier avec :

```bash
git check-ignore -v web/public/data/signals.json
```

Expected : aucune sortie (le fichier n'est pas ignore). Si une regle le matche, corriger `.gitignore` pour ne cibler que `/data/*.db` etc. (avec le `/` en tete pour ancrer a la racine du repo).

- [ ] **Step 2: Documenter dans `README.md`**

Ajouter apres la section "Mode discovery" existante :

```markdown
### Dashboard web (Vercel)

```bash
# Met a jour web/public/data/signals.json et le pousse sur GitHub
# (declenche un redeploy automatique si le projet Vercel est branche sur ce repo)
python cli.py scan --publish
python cli.py discover --publish
```

Sans `--publish`, `signals.json` est mis a jour localement mais rien n'est
pousse — tu restes maitre de quand publier.

**Premier deploiement** : depuis `web/public/`, lancer `vercel --prod` (CLI
deja authentifiee) pour creer le projet et obtenir une URL. Pour activer le
redeploiement automatique a chaque `--publish`, relier le projet Vercel a ce
repo GitHub et regler son "Root Directory" sur `web/public` dans les
parametres du projet (Settings → General → Root Directory).
```

- [ ] **Step 3: Verification finale complete**

Run: `pytest -v`
Expected: PASS (tous les tests, taches 1-3 incluses, plus les 35 tests existants)

Run: `python3 -m py_compile cli.py publish.py discovery/*.py storage/*.py collectors/*.py scoring/*.py`
Expected: aucune erreur

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document --publish and Vercel dashboard deployment"
```

---

## Notes d'execution

- Le premier `vercel --prod` reel (creation du projet, obtention d'une URL publique) n'est **pas** automatise par ce plan — c'est une action de publication qui doit rester une decision explicite de l'utilisateur, faite une fois le code merge et teste. Documente en Task 5, a executer manuellement (ou par l'agent avec confirmation explicite) apres la fin de ce plan.
- Aucune tache de ce plan ne depend de l'acces Reddit (Data API toujours en attente au moment de ce plan) — `write_signals_json`/`publish.py`/le dashboard sont testables entierement avec des mocks, comme le reste du projet.
