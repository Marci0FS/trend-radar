"""Detection de recherches en tendance sur Google, sans mot-cle fourni a
l'avance (contrairement a collectors/google_trends.py, qui suit un
mot-cle donne dans le temps).

Google a deja fait le travail de detection de tendance : ce module ne
calcule aucune croissance, il recupere un instantane des N recherches
les plus en tendance actuellement (realtime_trending_searches), puis
filtre celles qui ont aussi un signal produit (eBay et/ou YouTube) pour
ecarter l'actualite generaliste (celebrites, sport, meteo...) que
pytrends renvoie sans distinction — meme logique de "convergence" que le
reste du projet, plutot qu'une couche NLP de filtrage supplementaire.

Note d'implementation : le nom exact de la colonne portant le terme de
recherche dans la reponse de realtime_trending_searches ('title') est
notre meilleure lecture de la lib pytrends au moment de l'ecriture — a
confirmer au premier run reel (voir aussi la note du module sur pytrends
etant archive depuis avril 2025, non bloquant pour l'instant).
"""
from __future__ import annotations

import time

from pytrends.request import TrendReq

from collectors import ebay
from collectors import youtube

_RESULTS_LIMIT = 20


def fetch_trending_candidates(geo: str = "FR", limit: int = _RESULTS_LIMIT) -> list[dict]:
    """Retourne les candidats confirmes parmi les `limit` premieres
    recherches en tendance sur Google (pn=geo) : ceux dont au moins un
    signal eBay ou YouTube est non-nul.

    Leve RuntimeError si l'appel Google Trends echoue (meme convention
    que collectors/google_trends.py). Un echec eBay/YouTube sur UN terme
    precis (EbayError/YouTubeError/KeyError pour credentials manquantes)
    exclut juste ce terme des signaux confirmes pour cette source, ne
    fait jamais planter le reste de la fonction."""
    terms = _fetch_trending_terms(geo)
    candidates = []
    for term in terms[:limit]:
        ebay_signal = _check_ebay_signal(term)
        youtube_signal = _check_youtube_signal(term)
        if ebay_signal or youtube_signal:
            candidates.append(
                {
                    "phrase": term,
                    "source": "google_trends",
                    "mention_count": 0,
                    "growth_pct": 0,
                    "ebay_signal": ebay_signal,
                    "youtube_signal": youtube_signal,
                }
            )
    return candidates


def _fetch_trending_terms(geo: str, retries: int = 2) -> list[str]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            pytrends = TrendReq(hl="fr-FR", tz=60)
            df = pytrends.realtime_trending_searches(pn=geo)
            if df is None or df.empty:
                return []
            return [str(t) for t in df["title"].tolist()]
        except Exception as exc:  # pytrends leve des exceptions requests generiques
            last_error = exc
            if attempt < retries:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(
        f"Echec fetch Google Trends realtime_trending_searches (geo={geo})"
    ) from last_error


def _check_ebay_signal(term: str) -> bool:
    try:
        return ebay.fetch_listing_count(term) > 0
    except (KeyError, ebay.EbayError):
        return False


def _check_youtube_signal(term: str) -> bool:
    try:
        return youtube.fetch_recent_view_count(term) > 0
    except (KeyError, youtube.YouTubeError):
        return False
