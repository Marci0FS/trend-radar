"""Phase 4 du plan de correction : filtre semantique 'produit physique
vendable' via Claude, place avant la confirmation eBay/YouTube existante
dans discovery/trends_scan.py. Remplace la piste spaCy NER testee et
rejetee le 2026-08-21 (echouait dans les deux sens sur des requetes
courtes hors contexte) - un jugement de sens plutot qu'un type d'entite.

Ces tests ne font jamais d'appel reseau reel : `_call_claude` est
systematiquement monkeypatche pour retourner un objet reponse minimal."""
import json

import anthropic
import pytest

from discovery import product_filter


class _FakeBlock:
    def __init__(self, type_, text=None):
        self.type = type_
        self.text = text


class _FakeResponse:
    def __init__(self, content):
        self.content = content


def _fake_response(payload) -> _FakeResponse:
    return _FakeResponse([_FakeBlock("text", json.dumps(payload, ensure_ascii=False))])


def test_filter_product_terms_keeps_only_accepted(monkeypatch):
    monkeypatch.setattr(
        product_filter, "_call_claude", lambda terms: _fake_response(["masque LED visage"])
    )
    result = product_filter.filter_product_terms(["masque LED visage", "chaleur"])
    assert result == ["masque LED visage"]


def test_filter_product_terms_empty_list_returns_empty_without_calling_api(monkeypatch):
    def _fail_if_called(terms):
        raise AssertionError("_call_claude ne doit pas etre appele pour une liste vide")

    monkeypatch.setattr(product_filter, "_call_claude", _fail_if_called)
    assert product_filter.filter_product_terms([]) == []


def test_filter_product_terms_ignores_hallucinated_terms_not_in_input(monkeypatch):
    """Si Claude renvoie un terme absent de la liste d'origine (halluciné ou
    reformule), il ne doit jamais atterrir dans le resultat : seuls les
    termes reellement presents en entree peuvent survivre."""
    monkeypatch.setattr(
        product_filter,
        "_call_claude",
        lambda terms: _fake_response(["masque LED visage", "terme invente"]),
    )
    result = product_filter.filter_product_terms(["masque LED visage", "chaleur"])
    assert result == ["masque LED visage"]


def test_filter_product_terms_strips_markdown_code_fence(monkeypatch):
    monkeypatch.setattr(
        product_filter,
        "_call_claude",
        lambda terms: _FakeResponse(
            [_FakeBlock("text", '```json\n["masque LED visage"]\n```')]
        ),
    )
    result = product_filter.filter_product_terms(["masque LED visage", "chaleur"])
    assert result == ["masque LED visage"]


def test_filter_product_terms_raises_on_invalid_json(monkeypatch):
    monkeypatch.setattr(
        product_filter,
        "_call_claude",
        lambda terms: _FakeResponse([_FakeBlock("text", "reponse en texte libre, pas du JSON")]),
    )
    with pytest.raises(product_filter.ProductFilterError):
        product_filter.filter_product_terms(["masque LED visage"])


def test_filter_product_terms_raises_on_non_list_json(monkeypatch):
    monkeypatch.setattr(
        product_filter, "_call_claude", lambda terms: _fake_response({"not": "a list"})
    )
    with pytest.raises(product_filter.ProductFilterError):
        product_filter.filter_product_terms(["masque LED visage"])


def test_filter_product_terms_raises_on_response_without_text_block(monkeypatch):
    monkeypatch.setattr(product_filter, "_call_claude", lambda terms: _FakeResponse([]))
    with pytest.raises(product_filter.ProductFilterError):
        product_filter.filter_product_terms(["masque LED visage"])


def test_filter_product_terms_wraps_api_error(monkeypatch):
    def _raise_api_error(terms):
        raise anthropic.APIConnectionError(request=None)

    monkeypatch.setattr(product_filter, "_call_claude", _raise_api_error)
    with pytest.raises(product_filter.ProductFilterError):
        product_filter.filter_product_terms(["masque LED visage"])
