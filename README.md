# trend-radar

Veille de tendances autonome (produits/services en ligne à forte croissance),
100% gratuite et self-hosted. Croise Google Trends, Reddit, eBay,
AliExpress et YouTube (3e, 4e et 5e sources optionnelles), ne remonte un
signal fort que si au moins 3 des 5 sources convergent sur la même
fenêtre de temps.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm  # modele requis par le mode discovery
cp .env.example .env  # renseigner REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET
```

Créer une app Reddit (type "script") sur https://www.reddit.com/prefs/apps
pour obtenir les credentials.

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

**Premiere verification apres obtention des credentials reelles** : plusieurs
details de l'integration (nom exact du champ de volume de ventes retourne
par l'API — `volume` vs `lastest_volume` —, mais aussi l'URL de la gateway,
le format du `timestamp` de signature, l'algorithme `sign_method` et le nom
du parametre `session` portant l'access token, voir la docstring de
`collectors/aliexpress.py` pour le detail complet) n'ont pas pu etre
confirmes avant que le compte affilie existe. `python cli.py check` ne
touche pas AliExpress (seulement Trends/Reddit) : lance plutot
`python cli.py scan` apres avoir configure les credentials, et surveille la
sortie standard pour une ligne du type `Echec AliExpress pour '<mot-cle>' ...`
suivie d'un message `AliExpressError` (par ex. "sans champ
'volume'/'lastest_volume'", "authentification impossible", etc.) — c'est le
chemin de code qui exerce reellement le collecteur AliExpress et revele une
hypothese fausse. Si un tel message apparait, inspecte la reponse reelle de
l'API et ajuste `collectors/aliexpress.py` en consequence.

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

Le fichier `.env` est chargé automatiquement au démarrage de la CLI
(via `python-dotenv`).

## Usage

```bash
# Requête ponctuelle : état actuel d'un mot-clé, sans toucher la watchlist
python cli.py check "led face mask"

# Veille continue : scanne toute la watchlist (config/watchlist.yaml),
# stocke en SQLite, calcule le score de convergence, écrit data/report.md
python cli.py scan
```

Pour automatiser `scan` en tâche de fond, ajouter une entrée cron/launchd
locale (pas de process Vercel — voir note architecture ci-dessous).

### Mode discovery (sans mots-clés)

```bash
# Detecte des candidats emergents sur Reddit (config/watchlist.yaml -> discovery)
python cli.py discover

# Lit data/discovery_report.md, puis fait entrer un candidat dans le pipeline standard
python cli.py promote "nom du produit" gadgets
```

`discover` ne consulte jamais Google Trends automatiquement — seul `promote`
suivi de `scan` valide un candidat via Trends + convergence. Ca evite de
gaspiller le budget de requetes Trends sur du bruit d'extraction.

### Dashboard web (Vercel)

```bash
# Met a jour web/public/data/signals.json et le pousse sur GitHub
# (declenche un redeploy automatique si le projet Vercel est branche sur ce repo)
python cli.py scan --publish
python cli.py discover --publish
```

Sans `--publish`, `signals.json` est mis a jour localement mais rien n'est
pousse — tu restes maitre de quand publier.

Attention : l'integration Git de Vercel ne produit un deploiement de
*production* que depuis la branche de production configuree sur le projet
(en general `main`) — pousser `--publish` depuis une autre branche declenche
un deploiement preview, pas la mise a jour du site en production.

**Premier deploiement** : depuis `web/public/`, lancer `vercel --prod` (CLI
deja authentifiee) pour creer le projet et obtenir une URL. Pour activer le
redeploiement automatique a chaque `--publish`, relier le projet Vercel a ce
repo GitHub et regler son "Root Directory" sur `web/public` dans les
parametres du projet (Settings → General → Root Directory).

## Stockage

SQLite (`data/trends.db`), historique dans le temps : chaque scan ajoute des
lignes, rien n'est jamais écrasé.

## Architecture

Collecte 100% locale (pytrends + PRAW en direct, pas de MCP — inadapté à un
cron headless). Le dashboard web est déployé sur Vercel en lecture seule sur
un export JSON, car les fonctions Vercel sont éphémères et incompatibles
avec une persistance SQLite.
