"""Analyse historique des tendances e-commerce - Phase 6.

Ce module exploite l'historique SQLite pour:
1. Identifier les catégories les plus performantes
2. Analyser la croissance temporelle des produits
3. Détecter les patterns saisonniers
4. Prédire les tendances futures
5. Export CSV/JSON pour analyse externe
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from storage.db import get_connection


def get_top_categories(limit: int = 10, min_convergence: float = 2.0) -> list[dict]:
    """Retourne les catégories les plus performantes basées sur le score de convergence moyen.

    Args:
        limit: Nombre de catégories à retourner
        min_convergence: Score minimum de convergence pour filtrer

    Returns:
        Liste de dicts avec category, avg_score, total_signals, keywords_count
    """
    conn = get_connection()
    query = """
        SELECT
            k.category,
            AVG(s.convergence_score) as avg_score,
            COUNT(s.id) as total_signals,
            COUNT(DISTINCT k.id) as keywords_count,
            MAX(s.convergence_score) as max_score
        FROM signals s
        JOIN keywords k ON s.keyword_id = k.id
        WHERE k.category IS NOT NULL
          AND s.convergence_score >= ?
        GROUP BY k.category
        ORDER BY avg_score DESC
        LIMIT ?
    """
    rows = conn.execute(query, (min_convergence, limit)).fetchall()
    conn.close()

    return [
        {
            "category": row["category"],
            "avg_score": round(row["avg_score"], 2),
            "total_signals": row["total_signals"],
            "keywords_count": row["keywords_count"],
            "max_score": round(row["max_score"], 2),
        }
        for row in rows
    ]


def get_growth_timeline(term: str, days: int = 90) -> dict[str, Any]:
    """Analyse la croissance d'un terme sur une période donnée.

    Args:
        term: Le mot-clé à analyser
        days: Nombre de jours d'historique à analyser

    Returns:
        Dict avec timeline (dates + scores), growth_rate, sources_evolution
    """
    conn = get_connection()

    # Récupérer le keyword_id
    keyword_row = conn.execute("SELECT id, category FROM keywords WHERE term = ?", (term,)).fetchone()
    if not keyword_row:
        conn.close()
        return {"error": f"Keyword '{term}' not found"}

    keyword_id = keyword_row["id"]
    category = keyword_row["category"]
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Timeline des scores de convergence
    signals_query = """
        SELECT
            date(window_end) as date,
            convergence_score,
            sources_count,
            details_json
        FROM signals
        WHERE keyword_id = ? AND date(window_end) >= ?
        ORDER BY window_end ASC
    """
    signals = conn.execute(signals_query, (keyword_id, cutoff_date)).fetchall()

    # Évolution par source
    sources_evolution = _get_sources_evolution(conn, keyword_id, cutoff_date)

    conn.close()

    # Calcul du taux de croissance
    growth_rate = None
    if len(signals) >= 2:
        first_score = signals[0]["convergence_score"]
        last_score = signals[-1]["convergence_score"]
        if first_score > 0:
            growth_rate = round(((last_score - first_score) / first_score) * 100, 2)

    return {
        "term": term,
        "category": category,
        "period_days": days,
        "timeline": [
            {
                "date": s["date"],
                "convergence_score": round(s["convergence_score"], 2),
                "sources_count": s["sources_count"],
            }
            for s in signals
        ],
        "growth_rate_percent": growth_rate,
        "sources_evolution": sources_evolution,
    }


def _get_sources_evolution(conn, keyword_id: int, cutoff_date: str) -> dict[str, list[dict]]:
    """Helper pour extraire l'évolution de chaque source (Google Trends, eBay, etc.)"""
    evolution = {}

    # Google Trends
    trends_query = """
        SELECT date, interest_score
        FROM google_trends_snapshots
        WHERE keyword_id = ? AND date >= ?
        ORDER BY date ASC
    """
    trends = conn.execute(trends_query, (keyword_id, cutoff_date)).fetchall()
    evolution["google_trends"] = [
        {"date": row["date"], "score": row["interest_score"]} for row in trends
    ]

    # eBay
    ebay_query = """
        SELECT date, listing_count
        FROM ebay_snapshots
        WHERE keyword_id = ? AND date >= ?
        ORDER BY date ASC
    """
    ebay = conn.execute(ebay_query, (keyword_id, cutoff_date)).fetchall()
    evolution["ebay"] = [
        {"date": row["date"], "count": row["listing_count"]} for row in ebay
    ]

    # YouTube
    youtube_query = """
        SELECT date, view_count
        FROM youtube_snapshots
        WHERE keyword_id = ? AND date >= ?
        ORDER BY date ASC
    """
    youtube = conn.execute(youtube_query, (keyword_id, cutoff_date)).fetchall()
    evolution["youtube"] = [
        {"date": row["date"], "views": row["view_count"]} for row in youtube
    ]

    # AliExpress
    aliexpress_query = """
        SELECT date, sales_volume
        FROM aliexpress_snapshots
        WHERE keyword_id = ? AND date >= ?
        ORDER BY date ASC
    """
    aliexpress = conn.execute(aliexpress_query, (keyword_id, cutoff_date)).fetchall()
    evolution["aliexpress"] = [
        {"date": row["date"], "sales": row["sales_volume"]} for row in aliexpress
    ]

    return evolution


def get_seasonal_patterns(category: str | None = None) -> dict[str, Any]:
    """Détecte les patterns saisonniers dans les tendances.

    Args:
        category: Catégorie à analyser (None = toutes)

    Returns:
        Dict avec monthly_distribution, best_months, worst_months
    """
    conn = get_connection()

    # Distribution mensuelle des signaux forts (convergence >= 3)
    query = """
        SELECT
            strftime('%m', s.window_end) as month,
            COUNT(s.id) as signal_count,
            AVG(s.convergence_score) as avg_score
        FROM signals s
        JOIN keywords k ON s.keyword_id = k.id
        WHERE s.convergence_score >= 3.0
    """
    params = []
    if category:
        query += " AND k.category = ?"
        params.append(category)

    query += " GROUP BY month ORDER BY month ASC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    monthly_data = [
        {
            "month": int(row["month"]),
            "month_name": datetime.strptime(row["month"], "%m").strftime("%B"),
            "signal_count": row["signal_count"],
            "avg_score": round(row["avg_score"], 2),
        }
        for row in rows
    ]

    if not monthly_data:
        return {"error": "No data available for seasonal analysis"}

    # Identifier les meilleurs/pires mois
    sorted_by_count = sorted(monthly_data, key=lambda x: x["signal_count"], reverse=True)

    return {
        "category": category or "all",
        "monthly_distribution": monthly_data,
        "best_months": sorted_by_count[:3],
        "worst_months": sorted_by_count[-3:],
    }


def get_discovery_success_rate(days: int = 90) -> dict[str, Any]:
    """Calcule le taux de succès des découvertes (promoted keywords).

    Args:
        days: Période d'analyse

    Returns:
        Dict avec promoted_count, total_discovered, success_rate, top_performers
    """
    conn = get_connection()
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Keywords promus dans la période
    promoted_query = """
        SELECT
            k.term,
            k.category,
            k.promoted_at,
            AVG(s.convergence_score) as avg_score,
            MAX(s.convergence_score) as max_score
        FROM keywords k
        LEFT JOIN signals s ON k.id = s.keyword_id
        WHERE k.promoted_at >= ?
        GROUP BY k.id
        ORDER BY avg_score DESC
    """
    promoted = conn.execute(promoted_query, (cutoff_date,)).fetchall()

    # Total de candidats découverts dans la période
    total_discovered = conn.execute(
        "SELECT COUNT(DISTINCT term) as count FROM trends_discovery_candidates WHERE date >= ?",
        (cutoff_date,),
    ).fetchone()["count"]

    conn.close()

    promoted_count = len(promoted)
    success_rate = round((promoted_count / total_discovered * 100), 2) if total_discovered > 0 else 0

    return {
        "period_days": days,
        "promoted_count": promoted_count,
        "total_discovered": total_discovered,
        "success_rate_percent": success_rate,
        "top_performers": [
            {
                "term": row["term"],
                "category": row["category"],
                "promoted_at": row["promoted_at"],
                "avg_score": round(row["avg_score"], 2) if row["avg_score"] else 0,
                "max_score": round(row["max_score"], 2) if row["max_score"] else 0,
            }
            for row in promoted[:10]
        ],
    }


def export_to_csv(output_path: str | Path, days: int = 90) -> None:
    """Exporte l'analyse historique complète en CSV.

    Args:
        output_path: Chemin du fichier CSV de sortie
        days: Période d'historique à exporter
    """
    conn = get_connection()
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    query = """
        SELECT
            k.term,
            k.category,
            s.window_end as date,
            s.convergence_score,
            s.sources_count,
            s.details_json
        FROM signals s
        JOIN keywords k ON s.keyword_id = k.id
        WHERE date(s.window_end) >= ?
        ORDER BY s.window_end DESC, s.convergence_score DESC
    """
    rows = conn.execute(query, (cutoff_date,)).fetchall()
    conn.close()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["term", "category", "date", "convergence_score", "sources_count", "details"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "term": row["term"],
                "category": row["category"] or "uncategorized",
                "date": row["date"],
                "convergence_score": round(row["convergence_score"], 2),
                "sources_count": row["sources_count"],
                "details": row["details_json"],
            })

    print(f"✅ Exported {len(rows)} records to {output_path}")


def export_to_json(output_path: str | Path) -> None:
    """Exporte un rapport complet en JSON.

    Args:
        output_path: Chemin du fichier JSON de sortie
    """
    report = {
        "generated_at": datetime.now().isoformat(),
        "top_categories": get_top_categories(limit=10),
        "seasonal_patterns": get_seasonal_patterns(),
        "discovery_success": get_discovery_success_rate(days=90),
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"✅ Exported report to {output_path}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m analytics.history_analysis categories")
        print("  python -m analytics.history_analysis timeline <term> [days]")
        print("  python -m analytics.history_analysis seasonal [category]")
        print("  python -m analytics.history_analysis discovery [days]")
        print("  python -m analytics.history_analysis export-csv <output.csv> [days]")
        print("  python -m analytics.history_analysis export-json <output.json>")
        sys.exit(1)

    command = sys.argv[1]

    if command == "categories":
        categories = get_top_categories()
        print("\n📊 Top Categories by Average Convergence Score:\n")
        for i, cat in enumerate(categories, 1):
            print(f"{i}. {cat['category']}")
            print(f"   Avg Score: {cat['avg_score']} | Max: {cat['max_score']}")
            print(f"   Keywords: {cat['keywords_count']} | Signals: {cat['total_signals']}\n")

    elif command == "timeline":
        if len(sys.argv) < 3:
            print("❌ Missing term argument")
            sys.exit(1)
        term = sys.argv[2]
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 90
        timeline = get_growth_timeline(term, days)
        print(json.dumps(timeline, indent=2, ensure_ascii=False))

    elif command == "seasonal":
        category = sys.argv[2] if len(sys.argv) > 2 else None
        patterns = get_seasonal_patterns(category)
        print(json.dumps(patterns, indent=2, ensure_ascii=False))

    elif command == "discovery":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 90
        success = get_discovery_success_rate(days)
        print(json.dumps(success, indent=2, ensure_ascii=False))

    elif command == "export-csv":
        if len(sys.argv) < 3:
            print("❌ Missing output path argument")
            sys.exit(1)
        output = sys.argv[2]
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 90
        export_to_csv(output, days)

    elif command == "export-json":
        if len(sys.argv) < 3:
            print("❌ Missing output path argument")
            sys.exit(1)
        output = sys.argv[2]
        export_to_json(output)

    else:
        print(f"❌ Unknown command: {command}")
        sys.exit(1)
