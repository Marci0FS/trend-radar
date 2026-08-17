"""Detection de candidats en croissance a partir des mentions de phrases.

Reutilise growth_pct (deja utilise pour Google Trends) plutot que de
dupliquer une logique de calcul de croissance : chaque run de `discover`
produit un point (une "fenetre"), et growth_pct(window_days=1) compare
simplement le dernier point au precedent.
"""
from __future__ import annotations

import sqlite3

from collectors.google_trends import growth_pct
from storage import db


def find_candidates(
    conn: sqlite3.Connection,
    min_mentions: int,
    min_growth_pct: float,
    current_window: str,
) -> list[dict]:
    """Retourne les phrases vues dans `current_window` (le run de scan courant)
    dont la derniere fenetre depasse les deux seuils, triees par croissance
    decroissante.

    `current_window` borne la recherche aux phrases effectivement mentionnees
    lors de ce run : une phrase qui n'apparait plus sur Reddit disparait donc
    du rapport au lieu de rester indefiniment sur son dernier taux de
    croissance historique. Ca borne aussi le nombre de phrases interrogees a
    celles du run courant, plutot que toutes les phrases jamais enregistrees.
    """
    candidates = []
    for phrase in db.get_phrases_in_window(conn, current_window):
        series = db.get_phrase_mention_series(conn, phrase)
        if not series or series[-1][0] != current_window:
            continue
        latest_count = series[-1][1]
        growth = growth_pct(series, window_days=1)
        if latest_count >= min_mentions and growth >= min_growth_pct:
            candidates.append({
                "phrase": phrase,
                "mention_count": latest_count,
                "growth_pct": round(growth, 1),
            })
    return sorted(candidates, key=lambda c: c["growth_pct"], reverse=True)
