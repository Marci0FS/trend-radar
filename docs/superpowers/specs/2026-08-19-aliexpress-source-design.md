# AliExpress comme 4e source de convergence — design

## Contexte

trend-radar croise aujourd'hui Google Trends + Reddit + eBay pour son
scoring de convergence (`scoring/convergence.py`), avec un signal marqué
"FORT" si `sources_count >= 2`. Reddit reste inaccessible (karma quasi
nul, 2 refus). eBay ne capte que l'offre (nombre d'annonces actives) —
pas un vrai signal de demande.

Objectif : ajouter AliExpress comme 4e source, via l'Affiliate API
officielle et gratuite d'AliExpress Open Platform, dont les résultats de
recherche produit incluent un compteur de ventes récentes par produit —
un signal de demande direct, plus fort que le proxy d'offre utilisé par
eBay.

Portée : uniquement le mode watchlist (`cli.py scan`), comme eBay —
AliExpress n'a pas de notion de "hot/rising" utilisable pour le mode
discovery.

## Signal choisi

Somme du compteur de ventes récentes (`volume` / `lastest_volume` selon
la doc — nom exact à confirmer à l'implémentation, avec fallback vers le
nom réellement observé dans la réponse) sur les **10 premiers produits**
retournés par une recherche par mot-clé (`aliexpress.affiliate.product.query`).

**Pourquoi un agrégat sur 10 résultats plutôt qu'un seul produit** : un
seul produit best-seller peut exploser sans que le mot-clé soit vraiment
tendance (effet "produit viral isolé"). L'agrégat lisse ce bruit et colle
mieux à l'esprit "convergence" du projet (on cherche un mot-clé qui monte,
pas un produit qui monte).

Ciblage géographique/langue, cohérent avec les autres sources
(`trends_geo`, `ebay_marketplace: EBAY_FR`) : `ship_to_country=FR`,
`target_currency=EUR`, `target_language=fr`.

## Authentification — notablement différente d'eBay

eBay utilise un flux OAuth2 client-credentials simple (une requête
serveur-à-serveur, sans interaction utilisateur après création de l'app).
AliExpress utilise un flux OAuth par code d'autorisation :

1. **Étape manuelle unique** (l'utilisateur, dans un navigateur) : autorise
   l'app AliExpress → obtient un `refresh_token`. Ce refresh_token est
   stocké dans `.env` (`ALIEXPRESS_REFRESH_TOKEN`), jamais collé dans le
   chat, au même titre que `ALIEXPRESS_APP_SECRET`.
2. **À chaque scan** : le collector échange le `refresh_token` contre un
   `access_token` frais (valable ~10h — largement suffisant pour un scan
   quotidien, pas besoin de le persister entre deux runs).
3. **Signature de chaque requête** : `MD5(app_secret + paramètres_triés +
   app_secret)`, format spécifique à l'API AliExpress (pas un simple
   header Bearer comme eBay).

**Point d'attention documenté (pas géré automatiquement)** : le
`refresh_token` peut lui-même expirer après plusieurs mois. Quand ça
arrive, le collector échoue proprement (voir Gestion d'erreurs) et il
faut refaire l'étape 1 manuellement. Pas de renouvellement automatique
dans cette version.

## Architecture

Nouveau `collectors/aliexpress.py`, même structure que
`collectors/ebay.py` :

```python
def get_access_token() -> str:
    """Echange ALIEXPRESS_REFRESH_TOKEN contre un access_token frais
    (~10h de validite). Pas de cache disque : un nouveau token est
    demande a chaque scan (frequence quotidienne, pas besoin de
    persister entre deux runs)."""

def fetch_sales_volume(keyword: str, ship_to: str = "FR", currency: str = "EUR", language: str = "fr") -> int:
    """Appelle aliexpress.affiliate.product.query avec le mot-cle,
    recupere les 10 premiers resultats, retourne la somme de leur
    compteur de ventes recentes."""

def _sign_request(params: dict, app_secret: str) -> str:
    """MD5(app_secret + parametres_tries + app_secret)."""
```

Credentials via `.env` : `ALIEXPRESS_APP_KEY`, `ALIEXPRESS_APP_SECRET`,
`ALIEXPRESS_REFRESH_TOKEN`.

## Stockage

Nouvelle table `aliexpress_snapshots`, historisée comme les 3 autres :

```sql
CREATE TABLE aliexpress_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    date TEXT NOT NULL,
    sales_volume INTEGER NOT NULL,
    marketplace TEXT,
    collected_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(keyword_id, date, marketplace)
);
```

Nouvelles fonctions dans `storage/db.py` :

```python
def insert_aliexpress_snapshot(conn: sqlite3.Connection, keyword_id: int, date: str, sales_volume: int, marketplace: str) -> None:
    """Un seul point par scan (comme eBay), INSERT OR IGNORE."""

def get_aliexpress_snapshot_series(conn: sqlite3.Connection, keyword_id: int) -> list[tuple[str, int]]:
    """Retourne [(date, sales_volume), ...] trie par date, pour reutiliser growth_pct."""
```

## Point important — fenêtre de comparaison

Comme eBay, AliExpress ne donne qu'un total du jour courant — un seul
point de donnée par `scan`. `growth_pct` (déjà générique) est appelé avec
`window_days=1`. Il faut donc **au moins 2 scans à des jours différents**
avant d'avoir un signal AliExpress non nul.

## Scoring (scoring/convergence.py)

`compute_convergence` gagne une 4e branche, même style que les
précédentes :

```python
aliexpress_rows = conn.execute(
    "SELECT date, sales_volume FROM aliexpress_snapshots WHERE keyword_id = ? ORDER BY date",
    (keyword_id,),
).fetchall()
aliexpress_snapshots = [(r["date"], r["sales_volume"]) for r in aliexpress_rows]
aliexpress_growth = growth_pct(aliexpress_snapshots, window_days=1)
signals_detected["aliexpress"] = aliexpress_growth >= thresholds["aliexpress_growth_pct"]
```

`sources_count = sum(...)` passe naturellement de `/3` à `/4` (aucun
changement de logique, juste une clé de plus dans `signals_detected`).

**Changement de seuil FORT — s'applique à toutes les sources, pas
seulement AliExpress** : avec 4 sources possibles, `sources_count >= 2`
perd de son sens (n'importe quelle paire sur 4 suffirait, y compris deux
sources faibles alors que les deux autres contredisent). Le seuil FORT
passe à **`sources_count >= 3`** (majorité). Les tests existants de
`scoring/convergence.py` qui vérifient le seuil à 2 doivent être mis à
jour dans le cadre de ce plan (tâche dédiée, pas un effet de bord silencieux).

## Configuration (config/watchlist.yaml)

```yaml
aliexpress_ship_to: "FR"
aliexpress_currency: "EUR"
aliexpress_language: "fr"

thresholds:
  trends_growth_pct: 20
  reddit_min_posts: 3
  reddit_min_avg_score: 10
  ebay_growth_pct: 20
  aliexpress_growth_pct: 20   # nouveau, valeur de depart a calibrer plus tard
```

## Intégration cli.py (cmd_scan)

Après le bloc eBay existant, même pattern de gestion des credentials
manquantes (essai de récupération d'un access_token une fois avant la
boucle, skip propre si `KeyError` ou si le refresh échoue), puis dans la
boucle par mot-clé : appel `fetch_sales_volume`, insertion via
`insert_aliexpress_snapshot`. `signal_entries` gagne le champ
`aliexpress_growth_pct` — présent dans `signals.json`, mais
`web/public/index.html` n'est **pas** modifié dans ce spec : la page
ignore ce champ supplémentaire sans erreur, exactement comme pour eBay.
Ajouter une colonne AliExpress visible sur le dashboard reste un suivi
séparé.

## Gestion d'erreurs

- **Credentials manquantes** (`ALIEXPRESS_APP_KEY`/`APP_SECRET`/
  `REFRESH_TOKEN` absents) : skip propre avec message clair, même pattern
  que Reddit/eBay (`KeyError` → scan continue sans AliExpress).
- **Échec du refresh du token** (refresh_token expiré/invalide) :
  AliExpress désactivé pour tout le scan, message explicite invitant à
  refaire le consentement manuel (étape 1 de l'auth).
- **Échec API par mot-clé** (réseau, timeout, réponse malformée) : ne
  doit JAMAIS faire planter tout le scan (même leçon que Trends et eBay).
  `try/except` autour de l'appel dans la boucle, ce mot-clé continue sans
  AliExpress, les autres sources et les autres mot-clés ne sont pas
  affectés.
- **Champ volume absent/invalide dans la réponse** : ne jamais traiter un
  champ manquant comme un zéro implicite (même précaution que le fix
  final eBay — un zéro fabriqué pourrait produire un faux signal FORT
  publié sur le dashboard). Lever une erreur explicite (`AliExpressError`),
  jamais une exception Python brute qui échapperait au `except` du
  `cli.py`.

## Tests

- `collectors/aliexpress.py` : génération de signature MD5 (valeurs
  connues), refresh du token (mock `requests.post`, cas succès et échec),
  agrégation du volume sur 10 résultats (mock `requests.get`), gestion
  des réponses malformées (champ absent → `AliExpressError`, jamais un
  zéro silencieux).
- `storage/db.py` : `insert_aliexpress_snapshot` +
  `get_aliexpress_snapshot_series` (mêmes patterns que les fonctions eBay
  existantes).
- `scoring/convergence.py` : mise à jour des scénarios existants pour le
  nouveau seuil `>=3` ; nouveaux cas 4 sources (aucune, 1, 2, 3, 4 en
  accord), vérifie que FORT n'est atteignable qu'à partir de 3 sources
  d'accord.
- `cli.py` / `cmd_scan` : credentials manquantes → skip propre ; échec
  refresh token → skip propre ; échec API sur un mot-clé → ce mot-clé
  continue sans AliExpress, le scan ne plante pas, les autres mot-clés et
  les autres sources ne sont pas affectés.

## Hors scope (pour cette version)

- Mode discovery : AliExpress n'est pas intégré au scan Reddit
  hot/rising.
- Dashboard web : la colonne AliExpress n'est pas ajoutée à
  `web/public/index.html` dans ce spec (le JSON contiendra la donnée,
  l'affichage est un suivi séparé).
- Renouvellement automatique du refresh_token expiré : documenté (README)
  mais pas codé — nécessite un nouveau consentement manuel de
  l'utilisateur dans un navigateur.
- Fenêtres de comparaison configurables par source : reste en dur dans le
  code (`window_days=1` pour AliExpress, comme eBay), pas exposé en
  config pour cette version.
