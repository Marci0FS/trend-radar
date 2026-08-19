# YouTube comme 5e source de convergence — design

## Contexte

trend-radar croise aujourd'hui Google Trends + Reddit + eBay + AliExpress
pour son scoring de convergence (`scoring/convergence.py`), avec un signal
marqué "FORT" si `sources_count >= 3`. Reddit reste inaccessible (karma
quasi nul, 2 refus). AliExpress est mergé mais ses credentials réelles ne
sont pas encore obtenues (inscription au programme d'affiliation en cours
de review).

Objectif : ajouter YouTube comme 5e source, via l'API officielle et
gratuite YouTube Data API v3, dont l'authentification est nettement plus
simple que toutes les sources existantes (une seule clé API, pas d'OAuth,
pas de secret séparé). Le signal capte l'attention/le buzz vidéo autour
d'un mot-clé — complémentaire à Reddit (qui capte les discussions/posts)
plutôt qu'un doublon, utile en particulier tant que Reddit reste bloqué.

Portée : uniquement le mode watchlist (`cli.py scan`), comme eBay et
AliExpress — pas d'intégration au mode discovery dans cette version.

## Signal choisi

Somme des vues sur les **10 vidéos les plus vues publiées dans les 7
derniers jours** pour un mot-clé donné :

1. `search.list` avec `q=<mot-clé>`, `publishedAfter=<il y a 7 jours>`,
   `order=viewCount`, `maxResults=10`, `type=video` → renvoie les 10
   vidéos les plus vues de la fenêtre (mais sans le compteur de vues
   exact dans la réponse de recherche elle-même)
2. `videos.list` avec les 10 `videoId` obtenus, `part=statistics` → donne
   le `viewCount` exact de chacune
3. Somme des `viewCount` des 10 vidéos = le signal stocké

**Pourquoi pas `pageInfo.totalResults` de `search.list` seul** (plus
simple, un seul appel) : Google documente ce champ comme une estimation
approximative, pas un compte exact, particulièrement peu fiable sur des
requêtes à fort volume — un signal trop bruité pour une convergence
fiable. La somme des vues sur les vidéos réellement les plus populaires
est un signal de "buzz" plus significatif qu'un décompte approximatif de
publications, et cohérent avec le choix déjà fait pour AliExpress
(agrégat sur le top 10 plutôt qu'une métrique unique bruitée).

**Pourquoi une fenêtre glissante de 7 jours plutôt que 30** : capte un
vrai pic de buzz récent sans le diluer sur un mois entier ; les mots-clés
du watchlist sont des produits assez génériques (pas ultra-niche), donc
le risque de résultats vides sur 7 jours reste faible.

## Authentification — la plus simple des 5 sources

Une seule clé API (`YOUTUBE_API_KEY`), générée en quelques minutes dans
Google Cloud Console (pas de carte bancaire requise), passée en paramètre
de chaque requête. Pas d'OAuth, pas de secret séparé, pas de consentement
navigateur, pas de signature de requête — contrairement à eBay
(client-credentials) et surtout AliExpress (refresh-token + signature
MD5).

**Coût en quota** (quota gratuit : 10 000 unités/jour au total, plus un
plafond spécifique de 100 appels `search.list`/jour) :
- `search.list` : 100 unités par appel
- `videos.list` : 1 unité par appel
- Total : 101 unités × 16 mots-clés = ~1616 unités/scan — largement dans
  le quota général, et 16 appels `search.list` sur les 100/jour permis

## Architecture

Nouveau `collectors/youtube.py`, même structure que `collectors/ebay.py`
(un `*Error`, une fonction de fetch — pas de fonction de token puisqu'il
n'y a pas d'auth à rafraîchir) :

```python
def fetch_recent_view_count(keyword: str, api_key: str | None = None) -> int:
    """Appelle search.list (7 derniers jours, order=viewCount, top 10)
    puis videos.list sur les IDs obtenus, retourne la somme des viewCount.
    Leve KeyError si YOUTUBE_API_KEY absente de l'environnement (si
    api_key n'est pas fourni explicitement), meme convention que les
    autres collecteurs."""
```

## Stockage

Nouvelle table `youtube_snapshots`, historisée comme les 3 autres sources
à un point par scan :

```sql
CREATE TABLE youtube_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    date TEXT NOT NULL,
    view_count INTEGER NOT NULL,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(keyword_id, date)
);
```

Pas de colonne "marketplace"/région ici (contrairement à eBay/AliExpress)
— YouTube n'a pas de notion de marché géographique dans cet usage.

Nouvelles fonctions dans `storage/db.py` :

```python
def insert_youtube_snapshot(conn: sqlite3.Connection, keyword_id: int, date: str, view_count: int) -> None:
    """Un seul point par scan, INSERT OR IGNORE."""

def get_youtube_snapshot_series(conn: sqlite3.Connection, keyword_id: int) -> list[tuple[str, int]]:
    """Retourne [(date, view_count), ...] trie par date."""
```

## Point important — fenêtre de comparaison

Comme eBay et AliExpress, YouTube ne donne qu'un point par `scan` (la
somme de vues sur la fenêtre glissante de 7 jours au moment du scan) — un
seul point de donnée, pas un historique. `growth_pct` (déjà générique)
est appelé avec `window_days=1` : compare le point du scan actuel à celui
du scan précédent. Il faut donc **au moins 2 scans à des jours
différents** avant d'avoir un signal YouTube non nul.

## Scoring (scoring/convergence.py)

`compute_convergence` gagne une 5e branche, même style que les 4
précédentes :

```python
youtube_rows = conn.execute(
    "SELECT date, view_count FROM youtube_snapshots WHERE keyword_id = ? ORDER BY date",
    (keyword_id,),
).fetchall()
youtube_snapshots = [(r["date"], r["view_count"]) for r in youtube_rows]
youtube_growth = growth_pct(youtube_snapshots, window_days=1)
signals_detected["youtube"] = youtube_growth >= thresholds["youtube_growth_pct"]
```

`sources_count = sum(...)` passe naturellement de `/4` à `/5`.

**Pas de nouveau changement du seuil FORT** : `sources_count >= 3` reste
inchangé (déjà relevé de `>=2` à `>=3` lors de l'ajout d'AliExpress).
Avec 5 sources possibles, `>=3` reste une vraie majorité qui converge —
pas besoin de le remonter davantage pour cette version. Seul le
dénominateur affiché change (`/4` → `/5`), dans `cli.py write_report` et
`web/public/index.html`.

## Configuration (config/watchlist.yaml)

```yaml
thresholds:
  trends_growth_pct: 20
  reddit_min_posts: 3
  reddit_min_avg_score: 10
  ebay_growth_pct: 20
  aliexpress_growth_pct: 20
  youtube_growth_pct: 20   # nouveau, valeur de depart a calibrer plus tard
```

Pas de nouvelle clé de config géographique/marketplace nécessaire (à la
différence d'eBay/AliExpress) — YouTube n'utilise que le mot-clé et la
fenêtre temporelle, tous deux déjà couverts par le code, sans paramètre
supplémentaire à exposer.

## Intégration cli.py (cmd_scan)

Après le bloc AliExpress existant, même pattern de gestion des
credentials manquantes (vérification de `YOUTUBE_API_KEY` une fois avant
la boucle, skip propre si absente), puis dans la boucle par mot-clé :
appel `fetch_recent_view_count`, insertion via `insert_youtube_snapshot`.
`signal_entries` gagne le champ `youtube_growth_pct` — présent dans
`signals.json`, mais `web/public/index.html` n'affiche pas de nouvelle
colonne (le JSON contient la donnée, l'affichage reste un suivi séparé,
comme pour eBay et AliExpress). Seuls le dénominateur `/5` du dashboard
et de `write_report`, et le nombre de points dans la fonction `dots()`
JS, sont mis à jour pour rester cohérents (même type de correction
mineure que celle appliquée lors de l'ajout d'AliExpress).

## Gestion d'erreurs

- **Clé API manquante** (`YOUTUBE_API_KEY` absente) : skip propre avec
  message clair, même pattern que les autres sources (`KeyError` → scan
  continue sans YouTube).
- **Échec API par mot-clé** (réseau, timeout, quota dépassé, réponse
  malformée) : ne doit JAMAIS faire planter tout le scan. `try/except`
  autour de l'appel dans la boucle, ce mot-clé continue sans YouTube, les
  autres sources et les autres mot-clés ne sont pas affectés.
- **Champ `viewCount` absent/invalide dans une réponse `videos.list`** :
  ne jamais traiter un champ manquant comme un zéro implicite (même
  précaution que pour eBay/AliExpress) — lever `YouTubeError`, jamais une
  exception Python brute qui échapperait au `except` du `cli.py`.
- **Aucune vidéo trouvée dans la fenêtre de 7 jours** : cas légitime,
  distinct d'une erreur — retourne `0` (pas d'exception), comme le cas
  "liste de produits vide" déjà géré pour AliExpress.

## Tests

- `collectors/youtube.py` : `fetch_recent_view_count` (mock
  `requests.get` pour les deux appels `search.list`/`videos.list`),
  agrégation des vues sur 10 vidéos, cas 0 résultat (retourne 0, pas
  d'erreur), cas champ `viewCount` manquant sur une vidéo (lève
  `YouTubeError`), cas échec HTTP sur l'un ou l'autre appel (lève
  `YouTubeError`), clé API manquante (lève `KeyError`).
- `storage/db.py` : `insert_youtube_snapshot` + `get_youtube_snapshot_series`
  (mêmes patterns que les fonctions eBay/AliExpress existantes).
- `scoring/convergence.py` : cas 5 sources (aucune, 1, 3 en accord — pas
  besoin de re-tester exhaustivement 0 à 5, les tests existants couvrent
  déjà le mécanisme générique de `sources_count`), vérifie que le seuil
  FORT reste `>=3` et n'a pas besoin d'être re-testé pour changement (il
  ne change pas dans cette version).
- `cli.py` / `cmd_scan` : clé API manquante → skip propre ; échec API sur
  un mot-clé → ce mot-clé continue sans YouTube, le scan ne plante pas,
  les autres mot-clés et les autres sources ne sont pas affectés
  (indépendance testée comme pour la paire eBay/AliExpress).

## Hors scope (pour cette version)

- Mode discovery : YouTube n'est pas intégré au scan Reddit hot/rising.
- Dashboard web : pas de nouvelle colonne visible pour YouTube (le JSON
  contiendra la donnée, l'affichage est un suivi séparé) — seuls le
  dénominateur et le nombre de points de l'indicateur de convergence sont
  mis à jour pour rester exacts.
- Nouveau changement du seuil FORT : reste à `>=3` sur 5 sources
  possibles dans cette version.
- Fenêtre de comparaison configurable : reste en dur dans le code
  (`window_days=1`, fenêtre de recherche de 7 jours), pas exposée en
  config pour cette version.
