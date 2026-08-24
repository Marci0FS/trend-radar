"""Filtre semantique 'produit physique vendable' via Claude, place avant la
confirmation eBay/YouTube existante dans discovery/trends_scan.py.

Remplace la piste spaCy NER testee et rejetee le 2026-08-21 (echouait dans
les deux sens sur des requetes courtes hors contexte : ratait des non-produits
sans entite nommee comme "chaleur", faux positifs sur de vrais produits comme
"masque LED visage") - NER ne juge que le TYPE d'entite, jamais si un objet
est un produit vendable. Verifie avant implementation sur les 26 candidats
historiques reels (table trends_discovery_candidates) : 100% juges bruit par
ce meme jugement, coherent avec le fait qu'aucun n'a jamais ete promu.
"""
from __future__ import annotations

import json

import anthropic

_MODEL = "claude-opus-5"

_SYSTEM_PROMPT = (
    "Tu recois une liste de termes en tendance sur Google Trends France, au "
    "format JSON. Pour chacun, determine s'il designe un PRODUIT PHYSIQUE "
    "VENDABLE en ligne (gadget, beaute, maison, fitness, animalerie, "
    "puericulture, electronique grand public...).\n\n"
    "Exclus : actualite, sport (equipe/match/tournoi/athlete), "
    "personnalites/celebrites, meteo, politique, dates, lieux/aeroports, "
    "emissions ou oeuvres (TV/cinema/livre), actifs financiers "
    "(crypto/bourse), noms propres d'etablissements (ecole/hopital/rue), "
    "mots abstraits generiques (economie, education...).\n\n"
    "Renvoie les termes retenus dans le champ `products`, copies EXACTEMENT "
    "depuis la liste recue (aucune reformulation). Si aucun terme ne "
    "convient, renvoie une liste vide."
)

# Schema impose a la reponse (output_config.format) plutot qu'une consigne
# de formatage en langage naturel. Un premier essai en "reponds uniquement
# avec un tableau JSON" a produit en conditions reelles une reponse
# invalide : guillemet typographique (”) puis auto-correction du modele
# ("Wait — I must output exact JSON.") suivie du vrai tableau. Le schema
# rend ce cas structurellement impossible.
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "products": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["products"],
    "additionalProperties": False,
}


class ProductFilterError(RuntimeError):
    pass


def filter_product_terms(terms: list[str]) -> list[str]:
    """Garde uniquement les elements de `terms` juges "produit physique
    vendable" par Claude, dans leur ordre d'origine. Leve ProductFilterError
    si l'appel echoue (cle API manquante y compris - meme convention que les
    autres collecteurs : l'appelant decide s'il degrade) ou si la reponse
    n'est pas exploitable. Ne fait aucun appel pour une liste vide."""
    if not terms:
        return []

    try:
        response = _call_claude(terms)
    except anthropic.APIError as exc:
        raise ProductFilterError(f"Appel Claude echoue : {exc}") from exc

    text = _extract_text(response).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProductFilterError(
            f"Reponse Claude non parsable en JSON : {text[:200]!r}"
        ) from exc

    accepted = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(accepted, list):
        raise ProductFilterError(
            f"Reponse Claude sans champ 'products' exploitable : {text[:200]!r}"
        )

    # Filtrer depuis `terms` (et non renvoyer `accepted` tel quel) preserve
    # l'ordre d'origine ET ecarte tout terme reformule ou hallucine.
    accepted_set = set(accepted)
    return [t for t in terms if t in accepted_set]


def _call_claude(terms: list[str]):
    client = anthropic.Anthropic()
    return client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA},
        },
        messages=[{"role": "user", "content": json.dumps(terms, ensure_ascii=False)}],
    )


def _extract_text(response) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text
    raise ProductFilterError("Reponse Claude sans bloc texte")
