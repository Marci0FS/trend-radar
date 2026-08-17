"""CLI trend-radar : mode requete ponctuelle et mode veille continue.

Usage:
  python cli.py check "mot-cle"   # etat actuel en live, sans toucher la watchlist
  python cli.py scan              # scanne toute la watchlist, stocke, score, rapport
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

from collectors import google_trends
from collectors import reddit as reddit_collector
from discovery import extract, promote, reddit_scan, velocity
from scoring.convergence import compute_convergence
from storage import db

WATCHLIST_PATH = Path(__file__).parent / "config" / "watchlist.yaml"
REPORT_PATH = Path(__file__).parent / "data" / "report.md"
DISCOVERY_REPORT_PATH = Path(__file__).parent / "data" / "discovery_report.md"


def load_watchlist() -> dict:
    return yaml.safe_load(WATCHLIST_PATH.read_text())


def cmd_check(keyword: str, watchlist: dict) -> None:
    """Requete ponctuelle : interroge les sources en live, pas de stockage watchlist."""
    print(f"--- Check : {keyword} ---")

    trends_data = google_trends.fetch_interest_over_time(
        keyword,
        timeframe=watchlist.get("trends_timeframe", "today 3-m"),
        geo=watchlist.get("trends_geo", "FR"),
    )
    growth = google_trends.growth_pct(trends_data)
    print(f"Google Trends : croissance {round(growth, 1)}% sur la fenetre")

    try:
        reddit_client = reddit_collector.get_client()
    except KeyError:
        print("Reddit : credentials manquants (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET), skip")
        return

    posts = reddit_collector.search_keyword(reddit_client, keyword, subreddits=[])
    avg_score = sum(p["score"] for p in posts) / len(posts) if posts else 0
    print(f"Reddit : {len(posts)} posts trouves, score moyen {round(avg_score, 1)}")
    for p in posts[:5]:
        print(f"  [{p['score']:>4}] {p['title']} ({p['subreddit']})")


def cmd_scan(watchlist: dict) -> None:
    """Veille continue : scanne tous les mots-cles actifs de la watchlist, stocke, score."""
    db.init_db()
    conn = db.get_connection()
    thresholds = watchlist["thresholds"]
    results = []

    try:
        reddit_client = reddit_collector.get_client()
    except KeyError:
        reddit_client = None
        print("Reddit : credentials manquants, collecte Reddit desactivee pour ce scan")

    for category, cat_data in watchlist["categories"].items():
        subreddits = cat_data.get("subreddits", [])
        for keyword in cat_data["keywords"]:
            print(f"Scan : {keyword} ({category})")
            keyword_id = db.get_or_create_keyword(conn, keyword, category)

            trends_data = google_trends.fetch_interest_over_time(
                keyword,
                timeframe=watchlist.get("trends_timeframe", "today 3-m"),
                geo=watchlist.get("trends_geo", "FR"),
            )
            db.insert_trends_snapshots(conn, keyword_id, trends_data, watchlist.get("trends_geo", "FR"))
            time.sleep(2)  # limite le risque de 429 pytrends sur un scan a beaucoup de mots-cles

            if reddit_client:
                posts = reddit_collector.search_keyword(
                    reddit_client,
                    keyword,
                    subreddits,
                    time_filter=watchlist.get("reddit_time_filter", "month"),
                    limit=watchlist.get("reddit_post_limit", 25),
                )
                db.insert_reddit_posts(conn, keyword_id, posts)

            result = compute_convergence(conn, keyword_id, thresholds)
            db.insert_signal(
                conn,
                keyword_id=result["keyword_id"],
                window_start=result["window_start"],
                window_end=result["window_end"],
                sources_count=result["sources_count"],
                convergence_score=result["convergence_score"],
                details=result["details"],
            )
            results.append({"keyword": keyword, "category": category, **result})

    conn.close()
    write_report(results)


def cmd_discover(watchlist: dict) -> None:
    """Discovery : scanne Reddit sans mots-cles, detecte des candidats emergents."""
    db.init_db()
    conn = db.get_connection()
    discovery_cfg = watchlist.get("discovery", {})
    subreddits = discovery_cfg.get("subreddits", [])
    post_limit = discovery_cfg.get("post_limit", 50)
    min_mentions = discovery_cfg.get("min_mentions", 5)
    min_growth = discovery_cfg.get("min_growth_pct", 30)

    try:
        reddit_client = reddit_collector.get_client()
    except KeyError:
        print("Reddit : credentials manquants, discovery impossible sans acces Reddit")
        conn.close()
        return

    print(f"Discovery : scan de {len(subreddits)} subreddits...")
    posts = reddit_scan.scan_subreddits(reddit_client, subreddits, post_limit=post_limit)

    titles_by_subreddit: dict[str, list[str]] = {}
    for p in posts:
        titles_by_subreddit.setdefault(p["subreddit"], []).append(p["title"])

    now = datetime.now(timezone.utc).isoformat()
    mentions = []
    for subreddit, titles in titles_by_subreddit.items():
        phrase_counts = extract.extract_phrases(titles)
        for phrase, count in phrase_counts.items():
            mentions.append({
                "phrase": phrase,
                "subreddit": subreddit,
                "mention_count": count,
                "window_start": now,
                "window_end": now,
            })
    db.insert_phrase_mentions(conn, mentions)

    candidates = velocity.find_candidates(conn, min_mentions=min_mentions, min_growth_pct=min_growth)
    conn.close()
    write_discovery_report(candidates)


def cmd_promote(phrase: str, category: str) -> None:
    """Ajoute un candidat discovery a la watchlist, sous la categorie donnee."""
    yaml_text = WATCHLIST_PATH.read_text()
    if promote.is_duplicate(yaml_text, phrase, category):
        print(f"'{phrase}' est deja dans la categorie '{category}', rien a faire")
        return
    updated = promote.add_keyword_to_yaml_text(yaml_text, phrase, category)
    WATCHLIST_PATH.write_text(updated)
    print(f"'{phrase}' ajoute a la categorie '{category}' dans {WATCHLIST_PATH}")


def write_report(results: list[dict]) -> None:
    """Genere un rapport Markdown trie par force de convergence."""
    results_sorted = sorted(results, key=lambda r: r["convergence_score"], reverse=True)
    lines = ["# Rapport de veille — trend-radar", ""]
    for r in results_sorted:
        marker = "FORT" if r["sources_count"] >= 2 else "faible"
        lines.append(f"## [{marker}] {r['keyword']} ({r['category']})")
        lines.append(f"- Score convergence : **{r['convergence_score']}**")
        lines.append(f"- Sources en accord : {r['sources_count']}/2")
        d = r["details"]
        lines.append(f"- Google Trends : {d['trends_growth_pct']}% de croissance")
        lines.append(f"- Reddit : {d['reddit_post_count']} posts, score moyen {d['reddit_avg_score']}")
        lines.append("")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Rapport ecrit : {REPORT_PATH}")


def write_discovery_report(candidates: list[dict]) -> None:
    """Genere un rapport Markdown des candidats discovery, trie par croissance."""
    lines = ["# Rapport discovery — trend-radar", ""]
    if not candidates:
        lines.append("Aucun candidat au-dessus des seuils pour ce scan.")
    for c in candidates:
        lines.append(f"## {c['phrase']}")
        lines.append(f"- Mentions cette fenetre : {c['mention_count']}")
        lines.append(f"- Croissance : {c['growth_pct']}%")
        lines.append(f"- Pour suivre ce candidat : `python cli.py promote \"{c['phrase']}\" <categorie>`")
        lines.append("")
    DISCOVERY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Rapport discovery ecrit : {DISCOVERY_REPORT_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="trend-radar : veille de tendances multi-source")
    sub = parser.add_subparsers(dest="command", required=True)

    check_parser = sub.add_parser("check", help="requete ponctuelle sur un mot-cle")
    check_parser.add_argument("keyword")

    sub.add_parser("scan", help="veille continue sur la watchlist")

    sub.add_parser("discover", help="detecte des candidats emergents sur Reddit, sans mots-cles")

    promote_parser = sub.add_parser("promote", help="ajoute un candidat discovery a la watchlist")
    promote_parser.add_argument("phrase")
    promote_parser.add_argument("category")

    args = parser.parse_args()
    watchlist = load_watchlist()

    if args.command == "check":
        cmd_check(args.keyword, watchlist)
    elif args.command == "scan":
        cmd_scan(watchlist)
    elif args.command == "discover":
        cmd_discover(watchlist)
    elif args.command == "promote":
        cmd_promote(args.phrase, args.category)


if __name__ == "__main__":
    main()
