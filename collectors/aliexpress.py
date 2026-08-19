"""Collecteur AliExpress Affiliate API (volume de ventes agrege sur les
10 premiers resultats d'une recherche par mot-cle, OAuth par refresh
token + requetes signees).

API officielle et gratuite (programme d'affiliation AliExpress Open
Platform). Contrairement a eBay (OAuth2 client-credentials simple, une
seule requete serveur-a-serveur), cette API utilise un flux par
refresh_token : l'utilisateur autorise l'app une fois dans un navigateur
pour obtenir ALIEXPRESS_REFRESH_TOKEN (stocke en .env), et ce module
echange ce refresh_token contre un access_token frais a chaque scan
(valable ~10h, largement suffisant pour un run quotidien). Le cache
ci-dessous est en memoire pour la duree du process (evite un refresh par
mot-cle au sein d'un meme scan) — pas de persistance disque entre deux
runs, conformement au design.

Chaque requete est signee : MD5(app_secret + parametres_tries_concatenes
+ app_secret), convention de signature de l'AliExpress Open Platform
gateway (heritee des API TOP-style historiques).

Note d'implementation : plusieurs details de ce module sont notre meilleure
lecture de la doc publique, non verifies contre un compte reel (aucun
compte affilie n'existait encore au moment de l'ecriture) — a confirmer
lors du premier scan reel une fois les credentials obtenues :
- le nom exact du champ de volume ('volume' vs 'lastest_volume') ;
- le nom exact de la methode de refresh de token
  ('taobao.top.auth.token.refresh') ;
- l'URL de la gateway ('api-sg.aliexpress.com/sync') ;
- le format du 'timestamp' utilise dans la signature
  ('%Y-%m-%d %H:%M:%S' ; certaines gateways de style TOP attendent un
  epoch en millisecondes a la place) ;
- l'algorithme de signature ('sign_method: md5' ; certaines gateways plus
  recentes attendent 'sha256') ;
- le nom du parametre portant l'access token ('session').

Si le premier scan reel echoue avec "authentification impossible" ou une
AliExpressError opaque, ce sont les points a verifier en premier contre la
reponse reelle de l'API.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

import requests

_GATEWAY_URL = "https://api-sg.aliexpress.com/sync"
_METHOD_REFRESH_TOKEN = "taobao.top.auth.token.refresh"
_METHOD_PRODUCT_QUERY = "aliexpress.affiliate.product.query"
_RESULTS_PER_KEYWORD = 10

# Cache memoire du access_token pour la duree du process (voir docstring).
_cached_access_token: str | None = None


class AliExpressError(RuntimeError):
    pass


def _sign_request(params: dict, app_secret: str) -> str:
    """MD5(app_secret + cles_triees_concatenees_avec_valeurs + app_secret)."""
    sorted_items = sorted(params.items())
    concatenated = "".join(f"{key}{value}" for key, value in sorted_items)
    to_sign = f"{app_secret}{concatenated}{app_secret}"
    return hashlib.md5(to_sign.encode("utf-8")).hexdigest().upper()


def _system_params(app_key: str, method: str) -> dict:
    return {
        "app_key": app_key,
        "method": method,
        "sign_method": "md5",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "format": "json",
        "v": "2.0",
    }


def get_access_token() -> str:
    """Echange ALIEXPRESS_REFRESH_TOKEN contre un access_token frais.
    Leve KeyError si ALIEXPRESS_APP_KEY/ALIEXPRESS_APP_SECRET/
    ALIEXPRESS_REFRESH_TOKEN ne sont pas definies en env (meme convention
    que collectors.reddit.get_client / collectors.ebay.get_app_token)."""
    global _cached_access_token
    if _cached_access_token is not None:
        return _cached_access_token

    app_key = os.environ["ALIEXPRESS_APP_KEY"]
    app_secret = os.environ["ALIEXPRESS_APP_SECRET"]
    refresh_token = os.environ["ALIEXPRESS_REFRESH_TOKEN"]

    params = _system_params(app_key, _METHOD_REFRESH_TOKEN)
    params["refresh_token"] = refresh_token
    params["sign"] = _sign_request(params, app_secret)

    try:
        resp = requests.get(_GATEWAY_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or "access_token" not in data:
            raise AliExpressError(
                f"Reponse AliExpress sans champ 'access_token' au refresh : {repr(data)[:200]}"
            )
        token = str(data["access_token"])
    except requests.RequestException as exc:
        raise AliExpressError(f"Echec rafraichissement du token AliExpress : {exc}") from exc
    except (TypeError, AttributeError, ValueError) as exc:
        raise AliExpressError(f"Reponse invalide du serveur AliExpress au refresh : {exc}") from exc

    _cached_access_token = token
    return token


def fetch_sales_volume(
    keyword: str,
    ship_to: str = "FR",
    currency: str = "EUR",
    language: str = "fr",
) -> int:
    """Retourne la somme du volume de ventes recentes sur les 10 premiers
    produits retournes pour ce mot-cle. Une liste de resultats vide est
    une observation legitime (0 vente) ; un produit present mais sans
    champ de volume est une erreur (voir AliExpressError), jamais traite
    comme 0."""
    app_key = os.environ["ALIEXPRESS_APP_KEY"]
    app_secret = os.environ["ALIEXPRESS_APP_SECRET"]
    access_token = get_access_token()

    params = _system_params(app_key, _METHOD_PRODUCT_QUERY)
    params["session"] = access_token
    params["keywords"] = keyword
    params["page_size"] = _RESULTS_PER_KEYWORD
    params["ship_to_country"] = ship_to
    params["target_currency"] = currency
    params["target_language"] = language
    params["sign"] = _sign_request(params, app_secret)

    try:
        resp = requests.get(_GATEWAY_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        products = _extract_products(data)
    except requests.RequestException as exc:
        raise AliExpressError(f"Echec recherche AliExpress pour '{keyword}' : {exc}") from exc
    except (TypeError, AttributeError, ValueError) as exc:
        raise AliExpressError(f"Reponse invalide du serveur AliExpress pour '{keyword}' : {exc}") from exc

    return _sum_volume(products, keyword)


def _extract_products(data) -> list[dict]:
    """Navigue la structure de reponse imbriquee (style TOP gateway) pour
    atteindre la liste de produits. Leve AliExpressError si la structure
    ne correspond pas a ce qui est attendu."""
    try:
        result = data["aliexpress_affiliate_product_query_response"]["resp_result"]["result"]
        products = result["products"]["product"]
    except (KeyError, TypeError) as exc:
        raise AliExpressError(
            f"Structure de reponse AliExpress inattendue : {repr(data)[:200]}"
        ) from exc
    if not isinstance(products, list):
        raise AliExpressError(f"Champ 'product' n'est pas une liste : {repr(products)[:200]}")
    return products


def _sum_volume(products: list[dict], keyword: str) -> int:
    total = 0
    for product in products:
        volume = product.get("volume", product.get("lastest_volume"))
        if volume is None:
            raise AliExpressError(
                f"Produit AliExpress sans champ 'volume'/'lastest_volume' pour "
                f"'{keyword}' : {repr(product)[:200]}"
            )
        try:
            total += int(volume)
        except (TypeError, ValueError) as exc:
            raise AliExpressError(
                f"Valeur de volume non numerique pour '{keyword}' : {volume!r}"
            ) from exc
    return total
