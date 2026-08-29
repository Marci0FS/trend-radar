"""Tests pour analytics/history_analysis.py - Phase 6"""
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from analytics.history_analysis import (
    export_to_csv,
    export_to_json,
    get_discovery_success_rate,
    get_growth_timeline,
    get_seasonal_patterns,
    get_top_categories,
)
from storage.db import get_connection, get_or_create_keyword, init_db, insert_signal, mark_promoted


@pytest.fixture
def populated_db(tmp_path, monkeypatch):
    """Crée une base SQLite temporaire avec des données de test."""
    test_db = tmp_path / "test_trends.db"
    monkeypatch.setattr("storage.db.DB_PATH", test_db)
    init_db()

    conn = get_connection()

    # Créer des keywords avec catégories
    kw1 = get_or_create_keyword(conn, "lego star wars", "toys")
    kw2 = get_or_create_keyword(conn, "nintendo switch", "gaming")
    kw3 = get_or_create_keyword(conn, "pokemon cards", "collectibles")
    kw4 = get_or_create_keyword(conn, "funko pop", "collectibles")

    # Insérer des signaux avec différents scores
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    last_week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    last_month = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # Keyword 1: forte tendance
    insert_signal(conn, kw1, last_month, yesterday, 4, 4.5, {"test": "data"})
    insert_signal(conn, kw1, last_week, today, 5, 5.2, {"test": "data"})

    # Keyword 2: tendance moyenne
    insert_signal(conn, kw2, last_week, yesterday, 3, 3.1, {"test": "data"})
    insert_signal(conn, kw2, yesterday, today, 3, 3.3, {"test": "data"})

    # Keyword 3: faible tendance
    insert_signal(conn, kw3, last_month, yesterday, 2, 2.0, {"test": "data"})

    # Keyword 4: très forte tendance
    insert_signal(conn, kw4, last_month, yesterday, 4, 4.0, {"test": "data"})
    insert_signal(conn, kw4, yesterday, today, 5, 6.0, {"test": "data"})

    # Marquer kw4 comme promu
    mark_promoted(conn, "funko pop")

    # Insérer des snapshots pour timeline
    conn.execute(
        "INSERT INTO google_trends_snapshots (keyword_id, date, interest_score, region) VALUES (?, ?, ?, ?)",
        (kw1, last_month, 50, "FR"),
    )
    conn.execute(
        "INSERT INTO google_trends_snapshots (keyword_id, date, interest_score, region) VALUES (?, ?, ?, ?)",
        (kw1, yesterday, 75, "FR"),
    )
    conn.execute(
        "INSERT INTO ebay_snapshots (keyword_id, date, listing_count) VALUES (?, ?, ?)",
        (kw1, yesterday, 1200),
    )
    conn.execute(
        "INSERT INTO youtube_snapshots (keyword_id, date, view_count) VALUES (?, ?, ?)",
        (kw1, yesterday, 50000),
    )

    # Insérer des candidats discovery
    conn.execute(
        "INSERT INTO trends_discovery_candidates (term, date, ebay_signal, youtube_signal) VALUES (?, ?, ?, ?)",
        ("test product 1", today, 1, 1),
    )
    conn.execute(
        "INSERT INTO trends_discovery_candidates (term, date, ebay_signal, youtube_signal) VALUES (?, ?, ?, ?)",
        ("test product 2", today, 1, 0),
    )

    conn.commit()
    conn.close()

    yield test_db


def test_get_top_categories(populated_db):
    """Vérifie que get_top_categories retourne les bonnes catégories triées."""
    categories = get_top_categories(limit=3, min_convergence=2.0)

    assert len(categories) > 0
    # Les catégories sont triées par avg_score DESC
    # toys: (4.5 + 5.2) / 2 = 4.85
    # collectibles: (4.0 + 6.0) / 2 = 5.0 pour funko, 2.0 pour pokemon = (5.0 + 2.0) / 2 = 3.5
    # gaming: (3.1 + 3.3) / 2 = 3.2
    # Donc ordre: toys > collectibles > gaming
    assert categories[0]["category"] == "toys"
    assert categories[0]["avg_score"] > 4.0
    assert categories[0]["keywords_count"] == 1

    # Vérifier que collectibles est présent
    collectibles = next((c for c in categories if c["category"] == "collectibles"), None)
    assert collectibles is not None
    assert collectibles["keywords_count"] == 2


def test_get_top_categories_filters_by_min_convergence(populated_db):
    """Vérifie que le filtre min_convergence fonctionne."""
    categories = get_top_categories(limit=10, min_convergence=5.0)

    # kw1 (toys) a un signal de 5.2, kw4 (collectibles) a un signal de 6.0
    assert len(categories) == 2
    # Vérifier que les deux catégories sont présentes
    category_names = [c["category"] for c in categories]
    assert "toys" in category_names
    assert "collectibles" in category_names


def test_get_growth_timeline_returns_timeline(populated_db):
    """Vérifie que get_growth_timeline retourne la timeline complète."""
    timeline = get_growth_timeline("lego star wars", days=60)

    assert timeline["term"] == "lego star wars"
    assert timeline["category"] == "toys"
    assert timeline["period_days"] == 60
    assert len(timeline["timeline"]) == 2  # 2 signaux insérés

    # Vérifier croissance
    assert timeline["growth_rate_percent"] is not None
    assert timeline["growth_rate_percent"] > 0  # Score a augmenté

    # Vérifier sources_evolution
    assert "google_trends" in timeline["sources_evolution"]
    assert len(timeline["sources_evolution"]["google_trends"]) == 2
    assert "ebay" in timeline["sources_evolution"]
    assert "youtube" in timeline["sources_evolution"]


def test_get_growth_timeline_unknown_term(populated_db):
    """Vérifie que get_growth_timeline gère un terme inconnu."""
    timeline = get_growth_timeline("unknown term", days=30)

    assert "error" in timeline
    assert "not found" in timeline["error"]


def test_get_seasonal_patterns_all_categories(populated_db):
    """Vérifie que get_seasonal_patterns retourne la distribution mensuelle."""
    patterns = get_seasonal_patterns()

    assert patterns["category"] == "all"
    assert "monthly_distribution" in patterns
    assert len(patterns["monthly_distribution"]) > 0
    assert "best_months" in patterns
    assert "worst_months" in patterns

    # Vérifier structure monthly_distribution
    month = patterns["monthly_distribution"][0]
    assert "month" in month
    assert "month_name" in month
    assert "signal_count" in month
    assert "avg_score" in month


def test_get_seasonal_patterns_specific_category(populated_db):
    """Vérifie que get_seasonal_patterns filtre par catégorie."""
    patterns = get_seasonal_patterns(category="collectibles")

    assert patterns["category"] == "collectibles"
    assert len(patterns["monthly_distribution"]) > 0

    # Vérifier que les signaux toys ne sont pas inclus
    # (difficile à tester sans contrôler les dates exactement, mais on vérifie la structure)


def test_get_discovery_success_rate(populated_db):
    """Vérifie le calcul du taux de succès des découvertes."""
    success = get_discovery_success_rate(days=90)

    assert success["period_days"] == 90
    assert success["promoted_count"] == 1  # Seul kw4 est promu
    assert success["total_discovered"] == 2  # 2 candidats discovery
    assert success["success_rate_percent"] == 50.0  # 1/2 = 50%
    assert len(success["top_performers"]) == 1

    top = success["top_performers"][0]
    assert top["term"] == "funko pop"
    assert top["category"] == "collectibles"
    assert top["avg_score"] == 5.0  # (4.0 + 6.0) / 2


def test_export_to_csv_creates_file(populated_db, tmp_path):
    """Vérifie que export_to_csv crée un fichier CSV valide."""
    output = tmp_path / "export.csv"
    export_to_csv(output, days=90)

    assert output.exists()

    # Vérifier contenu
    content = output.read_text()
    assert "term,category,date,convergence_score,sources_count,details" in content
    assert "lego star wars" in content
    assert "nintendo switch" in content
    assert "funko pop" in content


def test_export_to_json_creates_file(populated_db, tmp_path):
    """Vérifie que export_to_json crée un fichier JSON valide."""
    output = tmp_path / "report.json"
    export_to_json(output)

    assert output.exists()

    # Vérifier structure JSON
    data = json.loads(output.read_text())
    assert "generated_at" in data
    assert "top_categories" in data
    assert "seasonal_patterns" in data
    assert "discovery_success" in data

    # Vérifier que top_categories contient des données
    assert len(data["top_categories"]) > 0
    # La première catégorie doit être celle avec le meilleur avg_score
    assert data["top_categories"][0]["category"] in ["toys", "collectibles"]
