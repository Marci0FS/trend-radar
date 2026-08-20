"""Collecteur Reddit via PRAW (API officielle Reddit, gratuite).

Necessite des credentials d'app Reddit type "script" :
https://www.reddit.com/prefs/apps -> variables d'environnement
REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT (voir .env.example).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import praw


class RedditError(RuntimeError):
    pass


def get_client() -> praw.Reddit:
    """Leve KeyError si les credentials ne sont pas definies en env, OU
    sont definies mais vides (meme etat par defaut que .env.example, qui
    ne doit jamais etre traite comme des credentials presentes — meme
    bug deja corrige pour ALIEXPRESS_APP_KEY/YOUTUBE_API_KEY)."""
    client_id = os.environ["REDDIT_CLIENT_ID"]
    client_secret = os.environ["REDDIT_CLIENT_SECRET"]
    if not (client_id and client_secret):
        raise KeyError("REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET")
    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=os.environ.get("REDDIT_USER_AGENT", "trend-radar/0.1"),
    )


def search_keyword(
    reddit: praw.Reddit,
    keyword: str,
    subreddits: list[str],
    time_filter: str = "month",
    limit: int = 25,
) -> list[dict]:
    """Cherche `keyword` dans une liste de subreddits (ou tout Reddit si vide).

    PRAW execute la vraie requete HTTP paresseusement, au moment de
    l'iteration sur le generateur retourne par .search() — pas au moment
    de l'appel lui-meme. Toute erreur (auth invalide, quota, reseau) doit
    donc etre capturee autour de la boucle for, pas seulement autour de
    l'appel, sous peine de laisser une exception brute de PRAW/prawcore
    remonter jusqu'a l'appelant et planter tout le scan.
    """
    subreddit_query = "+".join(subreddits) if subreddits else "all"
    posts = []
    try:
        for submission in reddit.subreddit(subreddit_query).search(
            keyword, sort="top", time_filter=time_filter, limit=limit
        ):
            posts.append(
                {
                    "post_id": submission.id,
                    "subreddit": str(submission.subreddit),
                    "title": submission.title,
                    "score": submission.score,
                    "num_comments": submission.num_comments,
                    "created_utc": datetime.fromtimestamp(
                        submission.created_utc, tz=timezone.utc
                    ).isoformat(),
                    "url": f"https://reddit.com{submission.permalink}",
                }
            )
    except Exception as exc:
        raise RedditError(f"Echec recherche Reddit pour '{keyword}' : {exc}") from exc
    return posts


if __name__ == "__main__":
    import sys

    kw = sys.argv[1] if len(sys.argv) > 1 else "test"
    client = get_client()
    for p in search_keyword(client, kw, subreddits=[]):
        print(p["score"], p["title"])
