# Phase 6 : Analyse Historique des Tendances

Module d'analyse exploitant l'historique SQLite accumulé par trend-radar pour identifier les patterns, prédire les tendances futures et exporter les données.

## 🎯 Fonctionnalités

### 1. **Top Catégories** 
Identifie les catégories e-commerce les plus performantes basées sur le score de convergence moyen.

```bash
python cli.py analyze categories
```

**Sortie** :
```
📊 Top Categories by Average Convergence Score:

1. fitness
   Avg Score: 29.7 | Max: 39.84
   Keywords: 2 | Signals: 13

2. maison
   Avg Score: 20.15 | Max: 27.29
   Keywords: 3 | Signals: 17
```

---

### 2. **Timeline de Croissance**
Analyse la croissance d'un terme spécifique sur une période donnée.

```bash
python cli.py analyze timeline "lego star wars" 90
```

**Sortie** : JSON avec timeline, taux de croissance, évolution par source (Google Trends, eBay, YouTube, AliExpress).

```json
{
  "term": "lego star wars",
  "category": "toys",
  "period_days": 90,
  "growth_rate_percent": 45.2,
  "timeline": [
    {"date": "2026-08-01", "convergence_score": 4.5, "sources_count": 4},
    {"date": "2026-08-15", "convergence_score": 5.2, "sources_count": 5}
  ],
  "sources_evolution": {
    "google_trends": [{"date": "2026-08-01", "score": 50}],
    "ebay": [{"date": "2026-08-01", "count": 1200}],
    "youtube": [{"date": "2026-08-01", "views": 50000}]
  }
}
```

---

### 3. **Patterns Saisonniers**
Détecte les patterns saisonniers dans les tendances e-commerce.

```bash
# Toutes catégories
python cli.py analyze seasonal

# Catégorie spécifique
python cli.py analyze seasonal toys
```

**Sortie** : Distribution mensuelle des signaux forts (convergence ≥ 3), meilleurs/pires mois.

```json
{
  "category": "toys",
  "monthly_distribution": [
    {"month": 11, "month_name": "November", "signal_count": 42, "avg_score": 5.8},
    {"month": 12, "month_name": "December", "signal_count": 89, "avg_score": 6.2}
  ],
  "best_months": [
    {"month": 12, "month_name": "December", "signal_count": 89, "avg_score": 6.2}
  ],
  "worst_months": [
    {"month": 3, "month_name": "March", "signal_count": 12, "avg_score": 3.5}
  ]
}
```

---

### 4. **Taux de Succès Discovery**
Calcule le taux de succès des découvertes automatiques (keywords promus).

```bash
python cli.py analyze discovery 90
```

**Sortie** :
```json
{
  "period_days": 90,
  "promoted_count": 15,
  "total_discovered": 120,
  "success_rate_percent": 12.5,
  "top_performers": [
    {
      "term": "fidget spinner",
      "category": "toys",
      "promoted_at": "2026-07-15T10:30:00",
      "avg_score": 8.5,
      "max_score": 12.3
    }
  ]
}
```

---

### 5. **Export CSV**
Exporte l'historique complet en CSV pour analyse externe (Excel, Google Sheets).

```bash
python cli.py analyze export-csv data/trends_export.csv 90
```

**Colonnes** : `term`, `category`, `date`, `convergence_score`, `sources_count`, `details`

---

### 6. **Export JSON**
Exporte un rapport complet en JSON (top catégories + patterns saisonniers + success rate).

```bash
python cli.py analyze export-json data/trends_report.json
```

---

## 📊 Utilisation Programmatique

```python
from analytics.history_analysis import (
    get_top_categories,
    get_growth_timeline,
    get_seasonal_patterns,
    get_discovery_success_rate,
    export_to_csv,
    export_to_json
)

# Top 5 catégories
categories = get_top_categories(limit=5, min_convergence=3.0)

# Timeline d'un produit
timeline = get_growth_timeline("lego star wars", days=90)

# Patterns saisonniers
patterns = get_seasonal_patterns(category="toys")

# Taux de succès discovery
success = get_discovery_success_rate(days=90)

# Exports
export_to_csv("output.csv", days=90)
export_to_json("report.json")
```

---

## 🧪 Tests

La suite de tests complète valide toutes les fonctionnalités :

```bash
pytest tests/test_history_analysis.py -v
```

**Coverage** : 9 tests, toutes les fonctions publiques couvertes.

---

## 🗄️ Schéma Base de Données

Le module exploite ces tables SQLite (voir `storage/schema.sql`) :

- `keywords` : mots-clés suivis + catégories + date de promotion
- `signals` : scores de convergence historiques
- `google_trends_snapshots` : historique Google Trends
- `ebay_snapshots` : historique eBay
- `youtube_snapshots` : historique YouTube
- `aliexpress_snapshots` : historique AliExpress
- `trends_discovery_candidates` : candidats détectés automatiquement

---

## 📈 Cas d'Usage

### 1. **Identifier les catégories rentables**
```bash
python cli.py analyze categories
```
→ Focus marketing sur les catégories avec le meilleur avg_score

### 2. **Timing saisonnier**
```bash
python cli.py analyze seasonal toys
```
→ Planifier les campagnes selon les meilleurs mois

### 3. **ROI de la discovery**
```bash
python cli.py analyze discovery 30
```
→ Mesurer l'efficacité de la détection automatique

### 4. **Analyse approfondie externe**
```bash
python cli.py analyze export-csv trends_full.csv 180
```
→ Pivot tables Excel, visualisations custom

---

## 🚀 Prochaines Améliorations

- [ ] Prédictions ML basées sur l'historique
- [ ] Alertes automatiques sur nouveaux patterns détectés
- [ ] Dashboard interactif Streamlit/Plotly
- [ ] API REST pour intégration externe
- [ ] Export Parquet pour analyse Big Data

---

**Auteur** : Claude Code + trend-radar  
**Date** : 2026-08-29  
**Version** : Phase 6 - Analyse Historique  
