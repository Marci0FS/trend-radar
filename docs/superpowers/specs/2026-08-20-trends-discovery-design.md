# Découverte via Google Trends — design

## Contexte

Le mode discovery existant de trend-radar (`discovery/extract.py`,
`discovery/velocity.py`, `discovery/reddit_scan.py`) détecte des
candidats produits sans mots-clés fournis à l'avance, en scannant les
posts hot/rising de subreddits ciblés, extrayant des phrases nominales
via spaCy, et calculant une croissance de mentions (`growth_pct`,
`window_days=1`). Il ne fonctionne qu'avec Reddit, actuellement bloqué
(karma insuffisant, 2 refus d'accès Data API).

Objectif : ajouter une 2e source de découverte, via Google Trends
"recherches en tendance" (`pytrends.realtime_trending_searches`), qui ne
dépend pas de Reddit et ne nécessite aucune nouvelle credential (pytrends
est déjà utilisé sans clé API pour le mode watchlist).

Portée : mode discovery uniquement (`cli.py discover`). Ne touche pas au
mode watchlist (`cli.py scan`).

## Signal choisi

`pytrends.realtime_trending_searches(pn='FR', cat='all')` retourne
jusqu'à 300 recherches actuellement en tendance sur Google en France.
Contrairement à Reddit (où on calcule nous-mêmes une vélocité de
mentions), Google a déjà fait le travail de détection de tendance — ce
signal est un instantané "voici ce qui buzz maintenant", pas une série
temporelle à suivre dans le temps. Aucun calcul de croissance
supplémentaire n'est nécessaire côté trend-radar pour ce signal.

**Limite à 20 termes** : vérifier les 300 termes retournés contre eBay et
YouTube serait bien trop coûteux en quota (YouTube est plafonné à 100
appels `search.list`/jour au total, dont 16 déjà utilisés par le scan
watchlist quotidien). On ne garde que les **20 premiers** termes remontés
par Google (les plus "chauds"), laissant une marge confortable de quota
(20 + 16 = 36 appels YouTube/jour sur 100 autorisés).

## Filtrage — convergence plutôt que catégorie Google

La liste brute de "recherches en tendance" Google est généraliste
(actualités, célébrités, sport, météo...), pas filtrée sur des produits.
Deux approches étaient possibles :

- **Catégorie Google Trends** (`cat=` du endpoint) : rejetée — les
  valeurs de catégorie valides ne sont pas documentées de façon fiable
  pour cet endpoint precis, risque de découvrir en cours de route que ça
  ne filtre pas grand-chose.
- **Filtrage a posteriori via les sources déjà connectées** (choisi) :
  pour chacun des 20 termes, on vérifie eBay (`fetch_listing_count`) et
  YouTube (`fetch_recent_view_count`, collecteurs déjà existants et
  réutilisés tels quels). Si l'un des deux renvoie un signal non-nul, le
  terme devient un **candidat confirmé**. Un terme "trending" sur Google
  qui a AUSSI un signal e-commerce/vidéo est probablement un vrai
  produit ; sans aucun des deux, c'est très probablement une actualité,
  une célébrité ou un événement sportif, écarté.

Ce choix reste dans l'esprit "convergence" déjà central au projet, sans
ajouter de couche NLP de filtrage supplémentaire.

## Point d'attention — pytrends non maintenu

`pytrends` est officiellement archivé depuis avril 2025 (plus de mises à
jour). Pas un bloquant immédiat (fonctionne toujours pour l'usage actuel
du projet, y compris `realtime_trending_searches`), mais un risque à
moyen terme si Google modifie son backend. Des forks maintenus (ex.
`trendspyg`) existent comme solution de repli si `pytrends` casse un
jour — pas d'action requise dans ce spec, juste documenté.

## Architecture

Nouveau module `discovery/trends_scan.py` :

```python
def fetch_trending_candidates(geo: str = "FR", limit: int = 20) -> list[dict]:
    """Recupere les `limit` premieres recherches en tendance sur Google
    (pn=geo), verifie chacune contre eBay et YouTube, retourne uniquement
    les candidats confirmes (au moins un signal non-nul).

    Chaque candidat : {"term": str, "ebay_signal": bool, "youtube_signal": bool}.

    Erreurs : un echec de l'appel Google Trends leve RuntimeError (meme
    convention que collectors/google_trends.py, pas de nouvelle classe
    d'exception). Un echec eBay/YouTube sur UN terme precis exclut juste
    ce terme des candidats confirmes, ne fait jamais planter le reste de
    la fonction."""
```

Reutilise `collectors.ebay.fetch_listing_count` et
`collectors.youtube.fetch_recent_view_count` tels quels — aucune
modification de ces collecteurs necessaire.

## Stockage

Nouvelle table `trends_discovery_candidates`, historisée comme le reste
du projet (jamais d'UPDATE/DELETE) :

```sql
CREATE TABLE trends_discovery_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL,
    date TEXT NOT NULL,
    ebay_signal INTEGER NOT NULL,
    youtube_signal INTEGER NOT NULL,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(term, date)
);
```

Nouvelles fonctions dans `storage/db.py` :

```python
def insert_trends_discovery_candidate(
    conn: sqlite3.Connection, term: str, date: str, ebay_signal: bool, youtube_signal: bool
) -> None:
    """Un candidat confirme par run, INSERT OR IGNORE."""
```

Pas de fonction de lecture dediee necessaire pour ce spec : `cmd_discover`
consomme directement la liste retournee par `fetch_trending_candidates`
dans le meme run (comme pour Reddit, qui ne relit pas non plus
`phrase_mentions` immediatement apres l'avoir ecrit pour construire son
rapport — `velocity.find_candidates` fait la lecture separement). La
table sert de journal historique consultable manuellement, pas de source
de lecture pour le rapport du run courant.

## Intégration cli.py (cmd_discover)

`cmd_discover` est restructuré pour que Reddit et Google Trends tournent
chacun independamment, meme lecon de resilience que `cmd_scan` — un
echec sur l'un ne doit jamais empecher l'autre :

- **Reddit** : comportement actuel conserve (scan des subreddits,
  extraction de phrases, `velocity.find_candidates`), mais au lieu d'un
  `return` immediat si les credentials manquent, on continue avec une
  liste de candidats Reddit vide. Le bloc de scan Reddit est aussi
  enveloppe dans un `try/except` large pour la meme raison que le
  correctif applique cette nuit a `collectors/reddit.py` — un probleme
  d'authentification en cours de scan Reddit ne doit pas empecher Google
  Trends de produire ses propres candidats dans le meme run.
- **Google Trends** : nouveau bloc independant, appelle
  `trends_scan.fetch_trending_candidates(geo=watchlist.get("trends_geo", "FR"), limit=20)`,
  insere chaque candidat confirme via `insert_trends_discovery_candidate`.

Les deux listes de candidats sont **fusionnees** dans le meme rapport et
la meme section `discovery` de `signals.json`. Chaque candidat porte un
champ `source` (`"reddit"` ou `"google_trends"`) :

```python
# Candidat Reddit (forme existante, gagne juste "source")
{"phrase": str, "source": "reddit", "mention_count": int, "growth_pct": float}

# Candidat Google Trends (nouvelle forme)
{"phrase": str, "source": "google_trends", "mention_count": 0, "growth_pct": 0,
 "ebay_signal": bool, "youtube_signal": bool}
```

`mention_count`/`growth_pct` sont mis a `0` pour les candidats Trends
(pas de notion de velocite calculee pour cette source) — meme convention
deja utilisee ailleurs dans le projet pour une source sans signal
disponible (ex. `ebay_growth_pct: 0.0` quand eBay est desactive).

Le flux `promote` (`cli.py promote`, ajout d'un candidat a la watchlist)
fonctionne a l'identique, peu importe la source du candidat — il ne lit
que le champ `phrase`, deja present dans les deux formes.

## Gestion d'erreurs

- **Echec Google Trends** (quota, reseau) : `RuntimeError` remonte de
  `fetch_trending_candidates`, capture dans `cmd_discover`, le run
  continue avec une liste de candidats Trends vide — meme message
  d'esprit que `cli.py`'s gestion existante des echecs Google Trends en
  mode watchlist.
- **Echec eBay/YouTube sur un terme precis** : ce terme est simplement
  exclu des candidats confirmes (pas de signal), ne fait jamais planter
  le reste de `fetch_trending_candidates`.
- **Echec Reddit** : comportement resilient deja etabli, renforce par ce
  spec (plus de `return` premature, `try/except` large autour du bloc de
  scan).

## Tests

- `discovery/trends_scan.py` : `fetch_trending_candidates` avec mock
  pytrends + eBay + YouTube — cas 0 candidat confirme (aucun signal
  eBay/YouTube), cas candidats confirmes (au moins un signal), cas echec
  sur un terme precis n'affecte pas les autres, cas echec Google Trends
  leve `RuntimeError`.
- `storage/db.py` : `insert_trends_discovery_candidate` (insertion,
  ignore des doublons meme jour/terme).
- `cli.py` / `cmd_discover` : Reddit indisponible + Trends disponible
  produit quand meme des candidats (et vice-versa) ; candidats des deux
  sources correctement fusionnes avec le bon champ `source` dans
  `signals.json`.

## Hors scope (pour cette version)

- Dashboard web : les nouveaux champs (`source`, `ebay_signal`,
  `youtube_signal`) sont presents dans le JSON mais pas affiches
  specifiquement — meme precedent que pour eBay/AliExpress/YouTube en
  mode watchlist.
- Parametre `cat` de Google Trends (piste de filtrage par categorie) :
  abandonnee au profit du filtrage par convergence.
- Migration vers un fork maintenu de `pytrends` (ex. `trendspyg`) : a
  surveiller si `pytrends` casse un jour, pas d'action dans ce spec.
- Historique/lecture de `trends_discovery_candidates` au-dela du run
  courant : la table sert de journal, pas encore de source de calcul de
  tendance dans le temps.
