"""Collecteur Google Trends via pytrends.

Google n'expose pas d'API officielle pour Trends ; pytrends interroge
les memes endpoints que le site public. Pas de wrapper MCP ici (Phase 0) :
overhead inutile pour un script cron headless. Sujet a des 429 si appele
trop souvent -> un retry simple est prevu.
"""
from __future__ import annotations

import time

from pytrends.request import TrendReq


def fetch_interest_over_time(
    keyword: str, timeframe: str = "today 3-m", geo: str = "FR", retries: int = 2
) -> list[tuple[str, int]]:
    """Retourne [(date_iso, score_interet), ...] pour un mot-cle donne.

    Reessaie avec un backoff court en cas de 429 (rate limit Google).
    """
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            pytrends = TrendReq(hl="fr-FR", tz=60)
            pytrends.build_payload([keyword], timeframe=timeframe, geo=geo)
            df = pytrends.interest_over_time()
            if df.empty:
                return []
            return [(date.strftime("%Y-%m-%d"), int(row[keyword])) for date, row in df.iterrows()]
        except Exception as exc:  # pytrends leve des exceptions requests generiques
            last_error = exc
            if attempt < retries:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Echec fetch Google Trends pour '{keyword}'") from last_error


def growth_pct(snapshots: list[tuple[str, int]], window_days: int = 7) -> float:
    """Compare la moyenne des `window_days` derniers points a la fenetre precedente.

    Retourne un pourcentage de croissance (peut etre negatif). 0.0 si pas
    assez d'historique pour comparer deux fenetres completes.
    """
    if len(snapshots) < window_days * 2:
        return 0.0
    values = [v for _, v in snapshots]
    recent = values[-window_days:]
    previous = values[-window_days * 2 : -window_days]
    avg_recent = sum(recent) / len(recent)
    avg_previous = sum(previous) / len(previous) if previous else 0
    if avg_previous == 0:
        return 100.0 if avg_recent > 0 else 0.0
    return ((avg_recent - avg_previous) / avg_previous) * 100


if __name__ == "__main__":
    import sys

    kw = sys.argv[1] if len(sys.argv) > 1 else "test"
    data = fetch_interest_over_time(kw)
    for date, score in data[-10:]:
        print(date, score)
    print("Croissance:", round(growth_pct(data), 1), "%")
