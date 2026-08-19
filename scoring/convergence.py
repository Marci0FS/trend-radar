"""Calcul du score de convergence multi-source.

Une tendance ne remonte comme "signal fort" que si elle apparait sur
au moins 2 sources distinctes dans la fenetre de temps consideree.
Seuils et ponderation volontairement simples pour le MVP (config/watchlist.yaml) ;
a affiner une fois qu'on a du recul sur des cas reels.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from collectors.google_trends import growth_pct


def compute_convergence(
    conn: sqlite3.Connection, keyword_id: int, thresholds: dict, window_days: int = 7
) -> dict:
    """Calcule le score de convergence pour un mot-cle sur la fenetre donnee."""
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(days=window_days)).isoformat()
    window_end = now.isoformat()

    signals_detected = {}

    trends_rows = conn.execute(
        "SELECT date, interest_score FROM google_trends_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    trends_snapshots = [(r["date"], r["interest_score"]) for r in trends_rows]
    trends_growth = growth_pct(trends_snapshots, window_days=window_days)
    signals_detected["google_trends"] = trends_growth >= thresholds["trends_growth_pct"]

    reddit_rows = conn.execute(
        "SELECT score FROM reddit_signals WHERE keyword_id = ? AND created_utc >= ?",
        (keyword_id, window_start),
    ).fetchall()
    reddit_count = len(reddit_rows)
    reddit_avg_score = sum(r["score"] for r in reddit_rows) / reddit_count if reddit_count else 0
    signals_detected["reddit"] = (
        reddit_count >= thresholds["reddit_min_posts"]
        and reddit_avg_score >= thresholds["reddit_min_avg_score"]
    )

    ebay_rows = conn.execute(
        "SELECT date, listing_count FROM ebay_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    ebay_snapshots = [(r["date"], r["listing_count"]) for r in ebay_rows]
    ebay_growth = growth_pct(ebay_snapshots, window_days=1)
    signals_detected["ebay"] = ebay_growth >= thresholds["ebay_growth_pct"]

    aliexpress_rows = conn.execute(
        "SELECT date, sales_volume FROM aliexpress_snapshots WHERE keyword_id = ? ORDER BY date",
        (keyword_id,),
    ).fetchall()
    aliexpress_snapshots = [(r["date"], r["sales_volume"]) for r in aliexpress_rows]
    aliexpress_growth = growth_pct(aliexpress_snapshots, window_days=1)
    signals_detected["aliexpress"] = aliexpress_growth >= thresholds["aliexpress_growth_pct"]

    sources_count = sum(1 for v in signals_detected.values() if v)
    # Score = 10 points par source en convergence + bonus intensite (croissance trends, volume reddit, croissance eBay, croissance AliExpress)
    convergence_score = (
        sources_count * 10
        + max(trends_growth, 0) * 0.1
        + reddit_count * 0.5
        + max(ebay_growth, 0) * 0.1
        + max(aliexpress_growth, 0) * 0.1
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
            "signals_detected": signals_detected,
        },
    }
