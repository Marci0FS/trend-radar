"""Extraction de phrases candidates depuis des titres de posts Reddit.

Utilise spaCy (modele anglais, local, gratuit) pour extraire les groupes
nominaux (noun chunks) des titres, plutot qu'un simple comptage de n-grams :
meilleure comprehension grammaticale, moins de bruit qu'un decoupage brut.
"""
from __future__ import annotations

import spacy

_NLP = None

MIN_PHRASE_LENGTH = 4

STOPWORD_PHRASES = {
    "update", "post", "thread", "amazon", "reddit", "op", "edit",
    "it", "ok", "this", "that", "these", "those", "anyone", "someone",
}

LEADING_DETERMINERS = ("a ", "an ", "the ", "my ", "this ", "these ", "those ", "your ", "our ")


def _get_nlp():
    global _NLP
    if _NLP is None:
        try:
            _NLP = spacy.load("en_core_web_sm")
        except OSError as exc:
            raise RuntimeError(
                "Modele spaCy manquant. Installer avec : python -m spacy download en_core_web_sm"
            ) from exc
    return _NLP


def _normalize(phrase: str) -> str:
    phrase = phrase.lower().strip()
    for article in LEADING_DETERMINERS:
        if phrase.startswith(article):
            phrase = phrase[len(article):]
    return phrase.strip()


def _is_noise(phrase: str) -> bool:
    if len(phrase) < MIN_PHRASE_LENGTH:
        return True
    if phrase in STOPWORD_PHRASES:
        return True
    if phrase.replace(" ", "").isdigit():
        return True
    return False


def extract_phrases(titles: list[str]) -> dict[str, int]:
    """Retourne {phrase_normalisee: nb_occurrences} a partir d'une liste de titres."""
    if not titles:
        return {}
    nlp = _get_nlp()
    counts: dict[str, int] = {}
    for doc in nlp.pipe(titles):
        # Extract noun chunks and merge adjacent ones if needed
        chunks = list(doc.noun_chunks)
        i = 0
        while i < len(chunks):
            chunk = chunks[i]
            # Look ahead to see if we should merge with following chunk
            merged_text = chunk.text
            j = i + 1
            while j < len(chunks):
                next_chunk = chunks[j]
                # Check if chunks are adjacent (no gap between them)
                if chunk.end == next_chunk.start:
                    merged_text += " " + next_chunk.text
                    chunk = next_chunk
                    j += 1
                else:
                    break

            phrase = _normalize(merged_text)
            if _is_noise(phrase):
                i = j
                continue
            counts[phrase] = counts.get(phrase, 0) + 1
            i = j
    return counts
