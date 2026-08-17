# trend-radar

Veille de tendances autonome (produits/services en ligne à forte croissance),
100% gratuite et self-hosted. Croise Google Trends et Reddit, ne remonte un
signal fort que si au moins 2 sources convergent sur la même fenêtre de temps.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # renseigner REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET
```

Créer une app Reddit (type "script") sur https://www.reddit.com/prefs/apps
pour obtenir les credentials.

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

## Stockage

SQLite (`data/trends.db`), historique dans le temps : chaque scan ajoute des
lignes, rien n'est jamais écrasé.

## Architecture

Collecte 100% locale (pytrends + PRAW en direct, pas de MCP — inadapté à un
cron headless). Le dashboard web (à venir) sera déployé sur Vercel en lecture
seule sur un export JSON, car les fonctions Vercel sont éphémères et
incompatibles avec une persistance SQLite.
