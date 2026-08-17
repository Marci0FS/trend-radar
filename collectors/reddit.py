"""Collecteur Reddit via PRAW (API officielle Reddit, gratuite).

Necessite des credentials d'app Reddit type "script" :
https://www.reddit.com/prefs/apps -> variables d'environnement
REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT (voir .env.example).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import praw


def get_client() -> praw.Reddit:
    """Leve KeyError si les credentials ne sont pas definis en env."""
    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "trend-radar/0.1"),
    )


def search_keyword(
    reddit: praw.Reddit,
    keyword: str,
    subreddits: list[str],
    time_filter: str = "month",
    limit: int = 25,
) -> list[dict]:
    """Cherche `keyword` dans une liste de subreddits (ou tout Reddit si vide)."""
    subreddit_query = "+".join(subreddits) if subreddits else "all"
    posts = []
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
    return posts


if __name__ == "__main__":
    import sys

    kw = sys.argv[1] if len(sys.argv) > 1 else "test"
    client = get_client()
    for p in search_keyword(client, kw, subreddits=[]):
        print(p["score"], p["title"])
