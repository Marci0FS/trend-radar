# eBay comme 3e source de convergence — design

## Contexte

trend-radar croise aujourd'hui Google Trends + Reddit pour son scoring de
convergence (`scoring/convergence.py`) : un signal n'est marqué "FORT" que
si `sources_count >= 2`. Reddit est actuellement inaccessible (compte avec
karma quasi nul, accès Data API refusé deux fois) — donc plus aucun signal
FORT n'est atteignable tant que Reddit reste bloqué (Trends seul plafonne
à `1/2`).

Objectif : ajouter eBay comme 3e source possible, via l'API Browse
officielle (OAuth2 client-credentials, gratuite), pour redonner un vrai
chemin vers un signal FORT (Trends + eBay = 2/3) sans dépendre de Reddit.
Connecteur eBay déjà existant et éprouvé dans `~/collector-arbitrage`
(`tracker/connectors/ebay.py`) à utiliser comme référence pour le pattern
d'auth.

Portée : uniquement le mode watchlist (`cli.py scan`) — eBay n'a pas de
notion de "hot/rising" utilisable pour le mode discovery, seulement de la
recherche par mot-clé, hors scope de ce spec.

## Signal choisi

Le nombre total d'annonces actives correspondant à une recherche (champ
`total` de la réponse Browse API, obtenu avec `limit=1` pour économiser la
bande passante — on n'a besoin que du compte, pas des annonces). Suivi
dans le temps comme un signal de croissance, exactement comme Trends.

**Pourquoi pas les ventes conclues** : pas d'API officielle gratuite pour
ça (confirmé par le commentaire du connecteur `collector-arbitrage` :
"jamais scrapées"). Le volume d'annonces actives est un signal de demande
indirect (plus de vendeurs listent un produit = signe qu'il devient
recherché) mais c'est le seul exploitable légalement et gratuitement.

## Architecture

Nouveau `collectors/ebay.py`, même structure que `collectors/google_trends.py` :

```python
def get_app_token() -> str:
    """OAuth2 client-credentials. Cache memoire simple (token valable ~2h),
    meme pattern que collector-arbitrage/tracker/connectors/ebay.py."""

def fetch_listing_count(keyword: str, marketplace: str = "EBAY_FR") -> int:
    """Appelle Browse API avec limit=1, retourne le champ 'total' de la
    reponse (nombre total d'annonces actives correspondant a la recherche,
    pas seulement la page retournee)."""
```

Utilise `requests` (déjà présent en dépendance transitive via `pytrends`,
ajouté explicitement à `requirements.txt` comme dépendance directe) plutôt
que l'`urllib` bas-niveau de `collector-arbitrage` — trend-radar n'a jamais
eu la contrainte "stdlib uniquement" de cet autre projet, et `requests`
donne un code plus lisible.

Credentials via variables d'environnement (`.env`, comme Reddit) :
`EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_ENVIRONMENT` (défaut
`PRODUCTION`).

## Stockage

Nouvelle table `ebay_snapshots`, historisée comme `google_trends_snapshots` :

```sql
CREATE TABLE ebay_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    date TEXT NOT NULL,
    listing_count INTEGER NOT NULL,
    marketplace TEXT,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(keyword_id, date, marketplace)
);
```

Nouvelles fonctions dans `storage/db.py` :

```python
def insert_ebay_snapshot(conn: sqlite3.Connection, keyword_id: int, date: str, listing_count: int, marketplace: str) -> None:
    """Un seul point par scan (contrairement a Trends qui donne un historique
    complet en un appel), donc pas de liste ici — un INSERT OR IGNORE par appel."""

def get_ebay_snapshot_series(conn: sqlite3.Connection, keyword_id: int) -> list[tuple[str, int]]:
    """Retourne [(date, listing_count), ...] trie par date, pour reutiliser growth_pct."""
```

## Point important — fenêtre de comparaison

Contrairement à Trends (90 jours d'historique en un seul appel API), eBay
ne donne que le total du jour courant — **un seul point de donnée par
`scan`**. `growth_pct` (déjà générique, réutilisé tel quel) est appelé
avec `window_days=1` pour eBay — compare juste le dernier scan au
précédent, même choix déjà fait pour `discovery/velocity.py`. Ça implique
qu'il faut **au moins 2 scans à des jours différents** avant d'avoir un
signal eBay non nul — le premier scan pose juste la base (même garde-fou
déjà en place dans `growth_pct` pour historique insuffisant, rien à coder
en plus).

## Scoring (scoring/convergence.py)

`compute_convergence` gagne une 3e branche, même style que
`google_trends`/`reddit` :

```python
ebay_rows = conn.execute(
    "SELECT date, listing_count FROM ebay_snapshots WHERE keyword_id = ? ORDER BY date",
    (keyword_id,),
).fetchall()
ebay_snapshots = [(r["date"], r["listing_count"]) for r in ebay_rows]
ebay_growth = growth_pct(ebay_snapshots, window_days=1)
signals_detected["ebay"] = ebay_growth >= thresholds["ebay_growth_pct"]
```

`sources_count = sum(...)` passe naturellement de `/2` à `/3` (aucun
changement de logique, juste une clé de plus dans `signals_detected`). Le
seuil "FORT" reste `sources_count >= 2` — Trends+eBay suffit à un signal
fort sans Reddit, ce qui est exactement l'objectif.

## Configuration (config/watchlist.yaml)

```yaml
ebay_marketplace: "EBAY_FR"

thresholds:
  trends_growth_pct: 20
  reddit_min_posts: 3
  reddit_min_avg_score: 10
  ebay_growth_pct: 20   # nouveau
```

## Intégration cli.py (cmd_scan)

Après le bloc Trends existant, ajouter le même pattern que Reddit pour la
gestion des credentials manquantes (essai de récupération du client eBay
une fois avant la boucle, skip propre si `KeyError`), puis dans la boucle
par mot-clé : appel `fetch_listing_count`, insertion via
`insert_ebay_snapshot`. `signal_entries` (la projection whitelist déjà
construite dans `cmd_scan` pour le JSON dashboard) gagne le champ
`ebay_growth_pct` — le champ sera donc présent dans `signals.json`, mais
`web/public/index.html` n'est PAS modifié dans ce spec : la page ignorera
simplement ce champ supplémentaire (elle ne lit que les clés qu'elle
connaît déjà, aucune erreur). Ajouter une colonne eBay visible sur le
dashboard est un suivi séparé si souhaité plus tard.

## Gestion d'erreurs

- **Credentials eBay manquantes** (`EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET`
  absents) : skip propre avec message clair, même pattern que Reddit
  (`KeyError` → `ebay_client = None` → scan continue sans eBay).
- **Échec API par mot-clé** (auth invalide, réseau, timeout) : ne doit
  JAMAIS faire planter tout le scan — leçon du bug Trends corrigé plus tôt
  dans ce projet (`cli.py`, `cmd_scan`). `try/except` autour de l'appel
  eBay dans la boucle, message d'erreur, `continue` vers la suite du
  traitement de CE mot-clé (Trends/Reddit continuent normalement, seul
  eBay est skippé pour ce mot-clé) — contrairement à Trends où un échec
  saute tout le mot-clé, ici seul le morceau eBay est optionnel donc on
  peut continuer le reste du traitement du même mot-clé sans lui.
- **Token OAuth2 expiré/invalide en cours de scan** : `get_app_token`
  gère son propre cache et rafraîchissement, transparent pour l'appelant.

## Tests

- `collectors/ebay.py` : `get_app_token` (mock `requests.post`, vérifie le
  cache et son expiration), `fetch_listing_count` (mock `requests.get`,
  vérifie le parsing du champ `total`).
- `storage/db.py` : `insert_ebay_snapshot` + `get_ebay_snapshot_series`
  (mêmes patterns de test que les fonctions Trends existantes).
- `scoring/convergence.py` : cas 3 sources (aucune, 1, 2, 3 en accord),
  vérifie que le seuil FORT (`>=2`) est atteignable via Trends+eBay sans
  Reddit.
- `cli.py` / `cmd_scan` : credentials eBay manquantes → skip propre ;
  échec API sur un mot-clé → ce mot-clé continue sans eBay, le scan ne
  plante pas, les autres mot-clés ne sont pas affectés.

## Hors scope (pour cette version)

- Mode discovery : eBay n'est pas intégré au scan Reddit hot/rising.
- Dashboard web : la colonne eBay n'est pas ajoutée à `web/public/index.html`
  dans ce spec (le JSON contiendra la donnée, l'affichage est un suivi
  séparé).
- Fenêtres de comparaison configurables par source (actuellement
  `window_days=7` pour Trends, `window_days=1` pour eBay, en dur dans le
  code — pas exposé en config pour cette version).
