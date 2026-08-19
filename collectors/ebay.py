"""Collecteur eBay Browse API (annonces actives, OAuth2 client-credentials).

API officielle et gratuite. Suit le nombre d'annonces actives correspondant
a une recherche comme signal de demande indirect — les ventes conclues ne
sont pas exposees par une API officielle gratuite (meme constat que le
connecteur eBay de collector-arbitrage, un autre projet de l'utilisateur).
"""
from __future__ import annotations

import base64
import os
import time

import requests

_ENDPOINTS = {
    "PRODUCTION": {
        "token": "https://api.ebay.com/identity/v1/oauth2/token",
        "browse": "https://api.ebay.com/buy/browse/v1/item_summary/search",
    },
    "SANDBOX": {
        "token": "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
        "browse": "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search",
    },
}

# Cache memoire simple du token d'application (valable ~2h cote eBay)
_token_cache: dict[str, tuple[str, float]] = {}


class EbayError(RuntimeError):
    pass


def get_app_token() -> str:
    """OAuth2 client-credentials. Leve KeyError si EBAY_CLIENT_ID/EBAY_CLIENT_SECRET
    ne sont pas definies en env (meme convention que collectors.reddit.get_client)."""
    env = os.environ.get("EBAY_ENVIRONMENT", "PRODUCTION")
    cached = _token_cache.get(env)
    if cached and cached[1] > time.time() + 30:
        return cached[0]

    client_id = os.environ["EBAY_CLIENT_ID"]
    client_secret = os.environ["EBAY_CLIENT_SECRET"]

    endpoints = _ENDPOINTS[env]
    basic_auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")

    try:
        resp = requests.post(
            endpoints["token"],
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            headers={
                "Authorization": f"Basic {basic_auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        expires_at = time.time() + int(data.get("expires_in", 7200))
    except requests.RequestException as exc:
        raise EbayError(f"Echec authentification eBay : {exc}") from exc
    except (KeyError, ValueError) as exc:
        raise EbayError(f"Reponse invalide du serveur eBay : {exc}") from exc

    _token_cache[env] = (token, expires_at)
    return token


def fetch_listing_count(keyword: str, marketplace: str = "EBAY_FR") -> int:
    """Retourne le nombre total d'annonces actives correspondant a la
    recherche (champ 'total' de la reponse Browse API, limit=1 pour
    economiser la bande passante : on ne lit pas les annonces elles-memes)."""
    env = os.environ.get("EBAY_ENVIRONMENT", "PRODUCTION")
    endpoints = _ENDPOINTS[env]
    token = get_app_token()

    try:
        resp = requests.get(
            endpoints["browse"],
            params={"q": keyword, "limit": 1},
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": marketplace,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or "total" not in data:
            # Un champ 'total' absent (ex : reponse avec seulement 'warnings')
            # est une condition d'erreur, pas une observation legitime de zero
            # annonce — le distinguer evite de stocker un faux 0 qui ferait
            # remonter un faux signal "FORT" au prochain scan (growth_pct
            # traite avg_previous == 0 comme une croissance de +100%).
            raise EbayError(
                f"Reponse eBay sans champ 'total' pour '{keyword}' : {data!r}"
            )
        return int(data["total"])
    except requests.RequestException as exc:
        raise EbayError(f"Echec recherche eBay pour '{keyword}' : {exc}") from exc
    except (TypeError, AttributeError, ValueError) as exc:
        raise EbayError(f"Reponse invalide du serveur eBay pour '{keyword}' : {exc}") from exc
