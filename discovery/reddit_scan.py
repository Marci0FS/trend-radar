"""Scan de subreddits pour le mode discovery.

Contrairement au mode watchlist (recherche par mot-cle via search_keyword,
voir collectors/reddit.py), discovery n'a pas de mot-cle a chercher : on
recupere les listings "hot" et "rising" tels quels pour en extraire les
phrases candidates ensuite (discovery/extract.py).
"""
from __future__ import annotations

import praw


def scan_subreddits(reddit: praw.Reddit, subreddits: list[str], post_limit: int = 50) -> list[dict]:
    """Retourne les titres des posts hot + rising pour chaque subreddit donne.

    Un subreddit prive, banni, mal orthographie ou en erreur transitoire
    (rate-limit PRAW, etc.) est signale et saute, plutot que de faire
    perdre toutes les donnees deja collectees sur les autres subreddits.
    """
    posts = []
    for name in subreddits:
        try:
            sub = reddit.subreddit(name)
            for submission in sub.hot(limit=post_limit):
                posts.append({"subreddit": name, "title": submission.title})
            for submission in sub.rising(limit=post_limit):
                posts.append({"subreddit": name, "title": submission.title})
        except Exception as exc:
            print(f"Discovery : echec du scan de r/{name} ({exc}), on continue avec les autres")
            continue
    return posts
