"""Ajout d'un candidat discovery a config/watchlist.yaml.

Manipulation textuelle plutot que yaml.safe_load + yaml.dump : preserve
les commentaires du fichier (PyYAML ne les garde pas lors d'un round-trip).
yaml.safe_load reste utilise pour la detection de doublons (lecture seule,
aucun risque de perte de formatage).
"""
from __future__ import annotations

import json

import yaml


def is_duplicate(yaml_text: str, phrase: str, category: str) -> bool:
    data = yaml.safe_load(yaml_text) or {}
    categories = data.get("categories", {})
    cat = categories.get(category)
    if not cat:
        return False
    return phrase in (cat.get("keywords") or [])


def add_keyword_to_yaml_text(yaml_text: str, phrase: str, category: str) -> str:
    lines = yaml_text.splitlines(keepends=True)
    category_header = f"  {category}:\n"

    category_start_idx = None
    keywords_line_idx = None
    for i, line in enumerate(lines):
        if line == category_header:
            category_start_idx = i
        elif category_start_idx is not None and line.strip() == "keywords:":
            keywords_line_idx = i
            break

    # json.dumps produit un scalaire double-quote valide en YAML tout en
    # echappant correctement les guillemets et antislashs eventuels dans
    # la phrase (extraite par spaCy, donc non fiable telle quelle).
    new_item = f"      - {json.dumps(phrase)}\n"

    if keywords_line_idx is not None:
        lines.insert(keywords_line_idx + 1, new_item)
        return "".join(lines)

    # Categorie absente : ajouter un nouveau bloc juste avant la fin du bloc "categories:"
    insert_idx = None
    in_categories = False
    for i, line in enumerate(lines):
        if line.strip() == "categories:":
            in_categories = True
            continue
        if in_categories and line.strip() != "" and not line.startswith(" "):
            insert_idx = i
            break
    if insert_idx is None:
        insert_idx = len(lines)

    new_block = (
        f"  {category}:\n"
        f"    keywords:\n"
        f"      - {json.dumps(phrase)}\n"
        f"    subreddits: []\n"
        f"\n"
    )
    lines.insert(insert_idx, new_block)
    return "".join(lines)
