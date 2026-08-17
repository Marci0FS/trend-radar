# Discovery mode — design

## Contexte

trend-radar tourne aujourd'hui en mode "watchlist" : l'utilisateur fournit
une liste de mots-clés dans `config/watchlist.yaml`, et le pipeline
(Google Trends + Reddit + scoring de convergence) confirme ou infirme si
ça monte. Limite structurelle : l'outil ne peut jamais faire remonter un
produit auquel l'utilisateur n'a pas déjà pensé.

Objectif de ce pivot : ajouter un mode "discovery" qui détecte des
candidats produits/niches directement depuis l'activité Reddit, sans
liste de mots-clés fournie à l'avance — pour repérer des tendances
avant qu'elles soient connues, cohérent avec l'objectif initial du
projet ("avant saturation").

Le mode watchlist existant n'est pas remplacé : discovery devient une
source additionnelle de mots-clés candidats, qui rejoignent ensuite le
même pipeline de scoring (Trends + convergence) une fois promus.

Contrainte non négociable : gratuit, self-hosted, cohérent avec la stack
existante (Python, SQLite historisé, pas de dépendance API payante).

## Architecture & flux de données

Nouveau module `discovery/`, à côté de `collectors/` :

- **`discovery/reddit_scan.py`** — scanne une liste de subreddits en
  listing `rising` + `hot` (pas de recherche par mot-clé, contrairement
  au watchlist mode) via PRAW, récupère les titres de posts récents.
- **`discovery/extract.py`** — utilise spaCy (modèle anglais
  `en_core_web_sm`, local, gratuit) pour extraire les groupes nominaux
  (noun phrases) des titres, normalise (minuscule, singulier), filtre le
  bruit (stopwords, longueur minimale, blocklist de termes génériques
  Reddit : "update", "post", "thread", noms de subreddits, etc.).

**Note langue** : les subreddits ciblés sont anglophones (écosystème
Reddit), donc l'extraction se fait en anglais même si les mots-clés
Trends restent en français — cohérent avec la langue naturelle de
chaque source.

Nouvelle table SQLite `phrase_mentions` (historisée, append-only comme
le reste du schema) :

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

**Commandes CLI ajoutées** :

- `cli.py discover` — lance scan + extraction sur la liste de subreddits
  discovery (voir `config/watchlist.yaml`), compare la fenêtre courante
  aux fenêtres précédentes pour calculer une croissance de mentions
  (même logique que `growth_pct` existant dans `collectors/google_trends.py`),
  filtre par seuils configurables (nb mentions min, % croissance min),
  écrit `data/discovery_report.md` trié par croissance décroissante.
- `cli.py promote "<phrase>" <categorie>` — ajoute un candidat choisi par
  l'utilisateur à `config/watchlist.yaml` sous la catégorie donnée (créée
  si elle n'existe pas). Vérifie l'absence de doublon avant ajout. Le
  candidat entre alors dans le pipeline watchlist standard (Trends +
  Reddit + convergence) au prochain `cli.py scan`.

**Workflow utilisateur (semi-automatique, humain dans la boucle)** :

1. `cli.py discover` (manuel pour l'instant, cron plus tard comme `scan`)
2. Lecture de `data/discovery_report.md` par l'utilisateur
3. `cli.py promote "<phrase>" <categorie>` pour les candidats intéressants
4. `cli.py scan` classique valide via Trends + convergence

Ce choix (semi-auto plutôt que 100% auto) évite de gaspiller le budget
de requêtes Google Trends (ressource fragile, rate-limitée) sur du bruit
d'extraction — spaCy ne sera jamais parfait, l'humain filtre avant que
Trends soit sollicité.

## Subreddits discovery

Dans `config/watchlist.yaml`, nouvelle clé `discovery` :

```yaml
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

## Gestion d'erreurs

- **Reddit credentials manquants** : `discover` skip proprement avec
  message clair, même pattern que le reste du projet (pas de crash).
- **Modèle spaCy absent** : erreur explicite au démarrage indiquant la
  commande d'installation (`python -m spacy download en_core_web_sm`) —
  pas de fallback silencieux vers une extraction dégradée.
- **Historique insuffisant** (premier `discover`, pas de fenêtre
  précédente) : retourne "pas de signal" plutôt que planter, comme le
  garde-fou déjà présent dans `growth_pct`. Le premier scan pose juste
  la baseline.
- **Doublon dans watchlist** : `promote` vérifie avant d'ajouter.

## Tests

- Test unitaire de `discovery/extract.py` sur des titres de posts
  synthétiques (pas de réseau) — vérifie que les bonnes phrases sortent
  et que stopwords/bruit sont filtrés.
- Test de la logique de vélocité (fenêtre actuelle vs précédente) avec
  des lignes `phrase_mentions` synthétiques insérées en base — même
  pattern que le smoke test déjà fait sur `compute_convergence` lors du
  MVP watchlist.
- Pas de test réseau réel (Reddit live) dans la suite automatisée —
  validation manuelle via `cli.py discover` une fois les credentials
  Reddit débloqués (en attente d'approbation côté Reddit au moment de ce
  design).

## Hors scope (pour l'instant)

- Automatisation cron du `discover` (viendra avec le reste de
  l'automatisation, pas prioritaire tant que Reddit n'est pas débloqué).
- Dashboard web de consultation des candidats (le rapport Markdown
  suffit pour l'instant).
- Pondération/catégorisation automatique des candidats par spaCy (la
  catégorie est choisie manuellement au moment du `promote`).
