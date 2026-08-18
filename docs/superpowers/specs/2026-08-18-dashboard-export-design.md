# Export JSON + dashboard Vercel — design

## Contexte

trend-radar sort aujourd'hui ses résultats en Markdown (`data/report.md`,
`data/discovery_report.md`), consultables uniquement en local. Objectif :
un dashboard web pour consulter le dernier scan sans repasser par le
terminal, déployé sur Vercel — cohérent avec la décision d'architecture
prise plus tôt dans le projet (Vercel en lecture seule, aucune collecte
de données côté Vercel, toute la collecte reste locale).

Utilisateur non technique en frontend web (a toujours travaillé en
Python/CLI sur ce projet) → priorité à la simplicité de déploiement et de
maintenance sur la sophistication technique.

Portée de cette version : consultation du **dernier scan uniquement**,
pas d'historique/graphiques (ajoutable plus tard sans tout casser).

## Architecture

Site statique pur (`web/public/`), zéro framework, zéro build step :

- `web/public/index.html` — page unique, HTML + CSS inline + un peu de
  JS vanilla qui `fetch()` `data/signals.json` (chemin relatif, même
  dossier) et rend un tableau trié par score de convergence.
- `web/public/data/signals.json` — généré par `cli.py`, **c'est le
  fichier lui-même qui est servi statiquement par Vercel** (pas de copie,
  pas d'étape de build : écrire directement à cet emplacement est la
  source de vérité).

Déployé sur Vercel avec la racine du projet pointée sur `web/public`
(site 100% statique, pas de fonctions serverless nécessaires pour cette
version). `vercel` CLI déjà authentifié sur la machine de l'utilisateur.

## Génération du JSON

Nouvelle fonction dans `cli.py` :

```python
SIGNALS_JSON_PATH = Path(__file__).parent / "web" / "public" / "data" / "signals.json"

def write_signals_json(section: str, entries: list[dict]) -> None:
    """Met a jour une section ('watchlist' ou 'discovery') de signals.json,
    en preservant l'autre section si le fichier existe deja."""
```

Appelée à la fin de `cmd_scan` (`section="watchlist"`, les mêmes
`results` que `write_report`) et à la fin de `cmd_discover`
(`section="discovery"`, les mêmes `candidates` que
`write_discovery_report`). Comme `scan` et `discover` tournent
indépendamment, chacun ne doit toucher que sa propre section du JSON —
sinon un `discover` effacerait les résultats du dernier `scan` (et
inversement).

Structure du fichier :

```json
{
  "last_updated": "2026-08-18T14:32:00+00:00",
  "watchlist": [
    {
      "keyword": "ceinture de sudation",
      "category": "fitness",
      "convergence_score": 13.88,
      "sources_count": 1,
      "trends_growth_pct": 38.8,
      "reddit_post_count": 0,
      "reddit_avg_score": 0
    }
  ],
  "discovery": [
    {
      "phrase": "led face mask",
      "mention_count": 9,
      "growth_pct": 200.0
    }
  ]
}
```

`last_updated` est mis à jour à chaque écriture (par `scan` ou par
`discover`), quelle que soit la section modifiée.

## Publication (git push)

Nouveau module `publish.py` :

```python
def publish_json() -> bool:
    """Commit + push data/signals.json s'il a change. Retourne True si un
    push a eu lieu, False si rien n'avait change (no-op silencieux)."""
```

Implémentation : `git diff --quiet -- web/public/data/signals.json`
pour détecter un changement réel avant de committer (évite des commits
vides) ; puis `git add web/public/data/signals.json` (jamais `git add -A`
— on ne veut committer que ce fichier précis, pas d'autres changements
en cours dans le repo de l'utilisateur) ; `git commit -m "chore: update signals.json"` ;
`git push`. Toute erreur (réseau, conflit, remote non configuré) est
affichée clairement, sans crash.

Nouveau flag `--publish` sur les sous-commandes `scan` et `discover`
(argparse `store_true`, défaut `False`). Avec le flag, `cli.py` appelle
`publish_json()` après avoir écrit `signals.json`. Sans le flag
(comportement par défaut inchangé), le JSON est mis à jour localement
mais rien n'est poussé — l'utilisateur reste maître de quand publier.

## Dashboard (web/public/index.html)

Tableau simple, une ligne par mot-clé/candidat, trié par score
décroissant. Deux sections visuelles (Watchlist / Discovery) si les
deux existent dans le JSON. CSS inline minimal (pas de framework CSS).
Si `signals.json` n'existe pas encore (avant le premier
`scan --publish`), le `fetch()` échoue (404) et la page affiche un
message : *"Aucune donnée pour l'instant — lance `python cli.py scan --publish`."*

## Erreurs

- `signals.json` absent/vide → message clair côté dashboard (voir
  ci-dessus), pas d'erreur JS non gérée.
- `publish_json()` sans changement → no-op silencieux (juste un message
  console "rien à publier").
- `publish_json()` avec erreur git (réseau, remote absent, conflit) →
  message d'erreur clair, le script ne plante pas, la donnée reste
  écrite localement même si le push échoue.
- `write_signals_json` appelé sur un fichier JSON corrompu existant
  (édité à la main, cassé) → si le parse échoue, repartir d'un objet
  vide plutôt que planter (même logique de tolérance que le reste du
  projet).

## Tests

- `write_signals_json` : structure correcte, `last_updated` mis à jour,
  préservation de l'autre section (scan ne doit pas effacer discovery et
  vice versa), tolérance à un fichier JSON corrompu.
- `publish_json()` : mocker `subprocess.run` pour vérifier les commandes
  git exactes appelées ; vérifier le no-op quand `git diff --quiet`
  indique "rien à committer" ; vérifier qu'un échec de `git push` est
  géré proprement sans exception.
- Pas de test pour `index.html`/JS (page statique sans logique complexe,
  hors scope raisonnable).

## Hors scope (pour cette version)

- Historique / graphiques d'évolution dans le temps.
- Automatisation cron du `--publish` (viendra avec l'automatisation
  cron plus large du projet, pas traitée ici).
- Authentification/protection du dashboard (données non sensibles,
  public par design comme le repo GitHub).
