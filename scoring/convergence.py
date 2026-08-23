"""Calcul du score de convergence multi-source.

Une tendance ne remonte comme "signal fort" que si elle apparait sur
au moins 3 sources distinctes sur 5 dans la fenetre de temps consideree.
Seuils et ponderation volontairement simples pour le MVP (config/watchlist.yaml) ;
a affiner une fois qu'on a du recul sur des cas reels.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from collectors.google_trends import growth_pct

# Fenetre de comparaison par source pour growth_pct. Trends recupere ~90
# jours d'historique quotidien en un seul appel API (interest_over_time),
# donc une fenetre de 7 jours (alignee sur `window_days`) lisse le bruit
# jour-a-jour. eBay/AliExpress/YouTube n'ajoutent qu'UN SEUL point par
# `scan` (un scan = un snapshot) : une fenetre de 7 jours leur imposerait
# 14 scans reels avant tout signal non-nul (cf. growth_pct :
# len(snapshots) < window_days*2 => 0.0), ce qui les laisserait muets
# pendant deux semaines. window_days=1 (comparer le dernier scan au
# precedent) est donc le choix delibere pour ces 3 sources (voir
# docs/superpowers/specs/2026-08-18-ebay-source-design.md, section "Point
# important - fenetre de comparaison"). Rendu configurable ici (finding #2
# de la review Omniroute du 2026-08-22) plutot que fige en dur.
DEFAULT_GROWTH_WINDOWS = {"ebay": 1, "aliexpress": 1, "youtube": 1}


def compute_convergence(
    conn: sqlite3.Connection,
    keyword_id: int,
    thresholds: dict,
    window_days: int = 7,
    growth_windows: dict | None = None,
    source_availability: dict | None = None,
) -> dict:
    """Calcule le score de convergence pour un mot-cle sur la fenetre donnee.

    `growth_windows` (optionnel) permet de piloter par source la fenetre de
    comparaison passee a growth_pct (cles : trends/ebay/aliexpress/youtube).
    `trends` vaut `window_days` par defaut (comportement historique
    inchange) ; ebay/aliexpress/youtube valent DEFAULT_GROWTH_WINDOWS.

    `source_availability` (optionnel, cles parmi google_trends/reddit/
    ebay/aliexpress/youtube) : marque une source comme desactivee faute de
    credentials (`cmd_scan` le sait deja, `compute_convergence` ne peut pas
    le deviner depuis la seule DB). Absente d'une cle => source consideree
    disponible, comportement identique a avant l'ajout de ce parametre."""
    windows = {"trends": window_days, **DEFAULT_GROWTH_WINDOWS, **(growth_windows or {})}
    availability = {"google_trends": True, "reddit": True, "ebay": True, "aliexpress": True, "youtube": True}
    availability.update(source_availability or {})
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(days=window_days)).isoformat()
    window_end = now.isoformat()

    signals_detected = {}

    trends_rows = conn.execute(
        "SELECT date, interest_score FROM google_trends_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    trends_snapshots = [(r["date"], r["interest_score"]) for r in trends_rows]
    trends_growth = growth_pct(trends_snapshots, window_days=windows["trends"])
    signals_detected["google_trends"] = trends_growth >= thresholds["trends_growth_pct"]

    reddit_rows = conn.execute(
        "SELECT score, created_utc FROM reddit_signals WHERE keyword_id = ? AND created_utc >= ? ORDER BY created_utc",
        (keyword_id, window_start),
    ).fetchall()
    reddit_count = len(reddit_rows)
    reddit_avg_score = sum(r["score"] for r in reddit_rows) / reddit_count if reddit_count else 0
    reddit_last_date = reddit_rows[-1]["created_utc"][:10] if reddit_rows else None
    signals_detected["reddit"] = (
        reddit_count >= thresholds["reddit_min_posts"]
        and reddit_avg_score >= thresholds["reddit_min_avg_score"]
    )

    ebay_rows = conn.execute(
        "SELECT date, listing_count FROM ebay_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    ebay_snapshots = [(r["date"], r["listing_count"]) for r in ebay_rows]
    ebay_growth = growth_pct(ebay_snapshots, window_days=windows["ebay"])
    signals_detected["ebay"] = ebay_growth >= thresholds["ebay_growth_pct"]

    aliexpress_rows = conn.execute(
        "SELECT date, sales_volume FROM aliexpress_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    aliexpress_snapshots = [(r["date"], r["sales_volume"]) for r in aliexpress_rows]
    aliexpress_growth = growth_pct(aliexpress_snapshots, window_days=windows["aliexpress"])
    signals_detected["aliexpress"] = aliexpress_growth >= thresholds["aliexpress_growth_pct"]

    youtube_rows = conn.execute(
        "SELECT date, view_count FROM youtube_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    youtube_snapshots = [(r["date"], r["view_count"]) for r in youtube_rows]
    youtube_growth = growth_pct(youtube_snapshots, window_days=windows["youtube"])
    signals_detected["youtube"] = youtube_growth >= thresholds["youtube_growth_pct"]

    def _state(source: str, has_data: bool) -> str:
        if not availability[source]:
            return "unavailable"
        if not has_data:
            return "no_data"
        return "positive" if signals_detected[source] else "neutral"

    source_states = {
        "google_trends": _state("google_trends", len(trends_snapshots) >= windows["trends"] * 2),
        "reddit": _state("reddit", reddit_count > 0),
        "ebay": _state("ebay", len(ebay_snapshots) >= windows["ebay"] * 2),
        "aliexpress": _state("aliexpress", len(aliexpress_snapshots) >= windows["aliexpress"] * 2),
        "youtube": _state("youtube", len(youtube_snapshots) >= windows["youtube"] * 2),
    }
    source_freshness = {
        "google_trends": trends_snapshots[-1][0] if trends_snapshots else None,
        "reddit": reddit_last_date,
        "ebay": ebay_snapshots[-1][0] if ebay_snapshots else None,
        "aliexpress": aliexpress_snapshots[-1][0] if aliexpress_snapshots else None,
        "youtube": youtube_snapshots[-1][0] if youtube_snapshots else None,
    }

    sources_count = sum(1 for v in signals_detected.values() if v)
    # Score = 10 points par source en convergence + bonus intensite (croissance trends, volume reddit, croissance eBay, croissance AliExpress, croissance YouTube)
    convergence_score = (
        sources_count * 10
        + max(trends_growth, 0) * 0.1
        + reddit_count * 0.5
        + max(ebay_growth, 0) * 0.1
        + max(aliexpress_growth, 0) * 0.1
        + max(youtube_growth, 0) * 0.1
    )

    return {
        "keyword_id": keyword_id,
        "window_start": window_start,
        "window_end": window_end,
        "sources_count": sources_count,
        "convergence_score": round(convergence_score, 2),
        "details": {
            "trends_growth_pct": round(trends_growth, 1),
            "reddit_post_count": reddit_count,
            "reddit_avg_score": round(reddit_avg_score, 1),
            "ebay_growth_pct": round(ebay_growth, 1),
            "aliexpress_growth_pct": round(aliexpress_growth, 1),
            "youtube_growth_pct": round(youtube_growth, 1),
            "signals_detected": signals_detected,
            "source_states": source_states,
            "source_freshness": source_freshness,
        },
    }
