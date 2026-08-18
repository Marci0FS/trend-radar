# trend-radar

Veille de tendances autonome (produits/services en ligne à forte croissance),
100% gratuite et self-hosted. Croise Google Trends et Reddit, ne remonte un
signal fort que si au moins 2 sources convergent sur la même fenêtre de temps.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm  # modele requis par le mode discovery
cp .env.example .env  # renseigner REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET
```

Créer une app Reddit (type "script") sur https://www.reddit.com/prefs/apps
pour obtenir les credentials.

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
cron headless). Le dashboard web (à venir) sera déployé sur Vercel en lecture
seule sur un export JSON, car les fonctions Vercel sont éphémères et
incompatibles avec une persistance SQLite.
