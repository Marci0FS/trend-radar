"""Collecteur YouTube Data API v3 (somme des vues sur les 10 videos les
plus vues publiees dans les 7 derniers jours pour un mot-cle).

API officielle et gratuite. Authentification la plus simple des sources
de trend-radar : une seule cle API passee en parametre d'URL, pas
d'OAuth, pas de secret separe, pas de rafraichissement de token.

Deux appels par mot-cle :
1. search.list (100 unites de quota sur les 10 000/jour, plafonne aussi
   a 100 appels search.list/jour independamment du reste) : trouve les
   10 videos les plus vues publiees dans les 7 derniers jours.
2. videos.list (1 unite de quota) : recupere le viewCount exact de ces
   10 videos — search.list seul ne le fournit pas.

pageInfo.totalResults de search.list n'est PAS utilise comme signal :
Google le documente comme une estimation approximative, pas un compte
exact, trop bruite pour la convergence (voir doc officielle search.list).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import requests

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_RESULTS_PER_KEYWORD = 10
_WINDOW_DAYS = 7


class YouTubeError(RuntimeError):
    pass


def fetch_recent_view_count(keyword: str) -> int:
    """Retourne la somme des vues sur les 10 videos les plus vues publiees
    dans les 7 derniers jours pour ce mot-cle. Leve KeyError si
    YOUTUBE_API_KEY n'est pas definie en env (meme convention que
    collectors.ebay.get_app_token). Un resultat de recherche vide est une
    observation legitime (0 vue) ; une video presente mais avec un champ
    manquant/invalide est une erreur (voir YouTubeError), jamais traitee
    comme 0."""
    key = os.environ["YOUTUBE_API_KEY"]

    published_after = (
        datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        search_resp = requests.get(
            _SEARCH_URL,
            params={
                "key": key,
                "q": keyword,
                "part": "id",
                "type": "video",
                "order": "viewCount",
                "publishedAfter": published_after,
                "maxResults": _RESULTS_PER_KEYWORD,
            },
            timeout=15,
        )
        search_resp.raise_for_status()
        video_ids = _extract_video_ids(search_resp.json())
    except requests.RequestException as exc:
        raise YouTubeError(f"Echec recherche YouTube pour '{keyword}' : {exc}") from exc
    except (TypeError, AttributeError, ValueError) as exc:
        raise YouTubeError(
            f"Reponse de recherche YouTube invalide pour '{keyword}' : {exc}"
        ) from exc

    if not video_ids:
        return 0

    try:
        videos_resp = requests.get(
            _VIDEOS_URL,
            params={"key": key, "id": ",".join(video_ids), "part": "statistics"},
            timeout=15,
        )
        videos_resp.raise_for_status()
        return _sum_view_counts(videos_resp.json(), keyword)
    except requests.RequestException as exc:
        raise YouTubeError(
            f"Echec recuperation des vues YouTube pour '{keyword}' : {exc}"
        ) from exc
    except (TypeError, AttributeError, ValueError) as exc:
        raise YouTubeError(
            f"Reponse de statistiques YouTube invalide pour '{keyword}' : {exc}"
        ) from exc


def _extract_video_ids(data) -> list[str]:
    try:
        items = data["items"]
    except (KeyError, TypeError) as exc:
        raise YouTubeError(
            f"Structure de reponse search.list inattendue : {repr(data)[:200]}"
        ) from exc
    if not isinstance(items, list):
        raise YouTubeError(f"Champ 'items' n'est pas une liste : {repr(items)[:200]}")
    ids = []
    for item in items:
        try:
            ids.append(item["id"]["videoId"])
        except (KeyError, TypeError) as exc:
            raise YouTubeError(
                f"Element de recherche sans videoId : {repr(item)[:200]}"
            ) from exc
    return ids


def _sum_view_counts(data, keyword: str) -> int:
    try:
        items = data["items"]
    except (KeyError, TypeError) as exc:
        raise YouTubeError(
            f"Structure de reponse videos.list inattendue : {repr(data)[:200]}"
        ) from exc
    if not isinstance(items, list):
        raise YouTubeError(f"Champ 'items' n'est pas une liste : {repr(items)[:200]}")
    total = 0
    for item in items:
        try:
            view_count = item["statistics"]["viewCount"]
        except (KeyError, TypeError) as exc:
            raise YouTubeError(
                f"Video YouTube sans champ viewCount pour '{keyword}' : {repr(item)[:200]}"
            ) from exc
        try:
            total += int(view_count)
        except (TypeError, ValueError) as exc:
            raise YouTubeError(
                f"Valeur de viewCount non numerique pour '{keyword}' : {view_count!r}"
            ) from exc
    return total
