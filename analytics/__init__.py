"""Module d'analyse historique des tendances e-commerce - Phase 6.

Fonctionnalités:
- Identification des catégories les plus performantes
- Analyse de croissance temporelle
- Détection de patterns saisonniers
- Calcul du taux de succès discovery
- Export CSV/JSON pour analyse externe
"""
from .history_analysis import (
    export_to_csv,
    export_to_json,
    get_discovery_success_rate,
    get_growth_timeline,
    get_seasonal_patterns,
    get_top_categories,
)

__all__ = [
    "get_top_categories",
    "get_growth_timeline",
    "get_seasonal_patterns",
    "get_discovery_success_rate",
    "export_to_csv",
    "export_to_json",
]
