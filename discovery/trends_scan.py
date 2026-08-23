"""Detection de recherches en tendance sur Google, sans mot-cle fourni a
l'avance (contrairement a collectors/google_trends.py, qui suit un
mot-cle donne dans le temps).

Google a deja fait le travail de detection de tendance : ce module ne
calcule aucune croissance, il recupere un instantane des N recherches
les plus en tendance actuellement, puis filtre celles qui ont aussi un
signal produit (eBay et/ou YouTube) pour ecarter l'actualite generaliste
(celebrites, sport, meteo...) que le flux renvoie sans distinction —
meme logique de "convergence" que le reste du projet.

Avant meme cette confirmation eBay/YouTube, un filtre semantique Claude
(product_filter.filter_product_terms, Phase 4 du plan de correction,
2026-08-24) ecarte les termes qui ne designent pas un produit physique
vendable. Verifie sur les 26 candidats historiques reels : le filtre
eBay/YouTube seul laissait passer 100% de bruit (actualite/sport/meteo),
car un terme generique a mecaniquement plus d'annonces/vues qu'un vrai
produit de niche — une piste NER locale avait deja ete testee et rejetee
avant (echoue dans les deux sens sur des requetes courtes). Si l'appel
Claude echoue (cle API manquante y compris), ce filtre se desactive
proprement pour le run et le comportement retombe sur eBay/YouTube seuls
(pas de blocage total de `discover`).

Utilise trendspyg (fork maintenu de pytrends, flux RSS Google Trends)
plutot que pytrends.realtime_trending_searches : ce dernier s'est avere
mort en production le 2026-08-21, le jour meme du premier run reel
(HTTP 404 confirme sur les 3 methodes de la famille "trending searches"
de pytrends — realtime_trending_searches, trending_searches,
today_searches — alors que pytrends.interest_over_time, utilise par
collectors/google_trends.py pour le mode watchlist, fonctionnait
toujours). trendspyg contourne le probleme en lisant le flux RSS public
de Google (https://trends.google.com/trending/rss), toujours actif.
"""
from __future__ import annotations

import time

from trendspyg import download_google_trends_rss

from collectors import ebay
from collectors import youtube
from discovery import product_filter

_RESULTS_LIMIT = 20


def fetch_trending_candidates(geo: str = "FR", limit: int = _RESULTS_LIMIT) -> list[dict]:
    """Retourne les candidats confirmes parmi les `limit` premieres
    recherches en tendance sur Google (pn=geo) : ceux dont au moins un
    signal eBay ou YouTube est non-nul.

    Leve RuntimeError si l'appel Google Trends echoue (meme convention
    que collectors/google_trends.py). Un echec eBay/YouTube sur UN terme
    precis (EbayError/YouTubeError/KeyError pour credentials manquantes)
    exclut juste ce terme des signaux confirmes pour cette source, ne
    fait jamais planter le reste de la fonction. Un echec du filtre produit
    Claude en amont (ProductFilterError) degrade silencieusement vers
    l'ancien comportement (eBay/YouTube seuls, aucun terme pre-filtre)."""
    terms = _fetch_trending_terms(geo)[:limit]
    try:
        terms = product_filter.filter_product_terms(terms)
    except product_filter.ProductFilterError as exc:
        print(f"Filtre produit Claude indisponible pour ce run, candidats non pre-filtres : {exc}")

    candidates = []
    for term in terms:
        ebay_count = _ebay_listing_count(term)
        youtube_views = _youtube_view_count(term)
        ebay_signal = ebay_count > 0
        youtube_signal = youtube_views > 0
        if ebay_signal or youtube_signal:
            candidates.append(
                {
                    "phrase": term,
                    "source": "google_trends",
                    "mention_count": 0,
                    "growth_pct": 0,
                    "ebay_signal": ebay_signal,
                    "youtube_signal": youtube_signal,
                    "ebay_count": ebay_count,
                    "youtube_views": youtube_views,
                }
            )
    return candidates


def _fetch_trending_terms(geo: str, retries: int = 2) -> list[str]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            results = download_google_trends_rss(
                geo=geo,
                output_format="dict",
                include_images=False,
                include_articles=False,
                cache=False,
            )
            return [str(r["trend"]) for r in results]
        except Exception as exc:  # trendspyg leve des TrendspygException typees
            last_error = exc
            if attempt < retries:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(
        f"Echec fetch Google Trends RSS trending (geo={geo}) : "
        f"{repr(last_error)[:500]}"
    ) from last_error


def _ebay_listing_count(term: str) -> int:
    try:
        return ebay.fetch_listing_count(term)
    except (KeyError, ebay.EbayError):
        return 0


def _youtube_view_count(term: str) -> int:
    try:
        return youtube.fetch_recent_view_count(term)
    except (KeyError, youtube.YouTubeError):
        return 0
