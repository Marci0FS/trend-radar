import yaml

from discovery.promote import add_keyword_to_yaml_text, is_duplicate

EXISTING_YAML = """categories:
  gadgets:
    keywords:
      - "purificateur d'air portable"
      - "mini projecteur"
    subreddits:
      - gadgets
      - shutupandtakemymoney

trends_timeframe: "today 3-m"
trends_geo: "FR"
"""

MULTI_CATEGORY_YAML = """categories:
  gadgets:
    keywords:
      - "purificateur d'air portable"
    subreddits:
      - gadgets
  beaute:
    keywords:
      - "masque facial"
    subreddits:
      - beaute

trends_timeframe: "today 3-m"
trends_geo: "FR"
"""


def test_add_keyword_to_existing_category():
    result = add_keyword_to_yaml_text(EXISTING_YAML, "chargeur solaire portable", "gadgets")
    lines = result.splitlines()
    idx = lines.index("    keywords:")
    assert lines[idx + 1] == '      - "chargeur solaire portable"'


def test_add_keyword_creates_new_category():
    result = add_keyword_to_yaml_text(EXISTING_YAML, "fontaine a eau chat", "animaux")
    lines = result.splitlines()

    # Assert category header exists
    assert "  animaux:" in result

    # Assert the category block structure is correct with positional checks
    animaux_idx = lines.index("  animaux:")
    assert lines[animaux_idx + 1] == "    keywords:"
    assert lines[animaux_idx + 2] == '      - "fontaine a eau chat"'

    # Assert rest of file is preserved
    assert "trends_timeframe:" in result


def test_add_keyword_preserves_comments():
    yaml_with_comment = "# commentaire important\n" + EXISTING_YAML
    result = add_keyword_to_yaml_text(yaml_with_comment, "chargeur solaire portable", "gadgets")
    assert "# commentaire important" in result


def test_add_keyword_to_second_category_in_multi_category():
    """Ensure keyword is added to the correct category when multiple exist."""
    result = add_keyword_to_yaml_text(MULTI_CATEGORY_YAML, "rouge a levres", "beaute")
    lines = result.splitlines()

    # Find the beaute category
    beaute_idx = lines.index("  beaute:")
    # The next line should be "    keywords:"
    assert lines[beaute_idx + 1] == "    keywords:"
    # The next line should be the new keyword (inserted first)
    assert lines[beaute_idx + 2] == '      - "rouge a levres"'
    # Verify the original keyword is still there
    assert '      - "masque facial"' in result
    # Verify gadgets category is unchanged
    assert "  gadgets:" in result


def test_is_duplicate_detects_existing_keyword():
    assert is_duplicate(EXISTING_YAML, "mini projecteur") is True
    assert is_duplicate(EXISTING_YAML, "nouveau produit") is False


def test_is_duplicate_detects_keyword_in_a_different_category():
    """Un meme produit ne doit pas pouvoir etre promu deux fois sous deux
    categories differentes : is_duplicate doit chercher dans TOUTES les
    categories, pas seulement celle visee par le promote en cours."""
    assert is_duplicate(MULTI_CATEGORY_YAML, "masque facial") is True
    assert is_duplicate(MULTI_CATEGORY_YAML, "produit inconnu") is False


def test_add_keyword_with_double_quote_produces_valid_yaml():
    """spaCy peut extraire des phrases contenant des guillemets (ex: 'smart' mug).
    Sans echappement, ca cassait le YAML genere (discovery finding #1)."""
    phrase = '"smart" mug'
    result = add_keyword_to_yaml_text(EXISTING_YAML, phrase, "gadgets")
    data = yaml.safe_load(result)
    assert phrase in data["categories"]["gadgets"]["keywords"]


def test_add_keyword_with_backslash_produces_valid_yaml():
    """spaCy peut extraire des phrases avec antislash (ex: mesures fractionnaires
    '3\\4 inch hose adapter'). Sans echappement, ca cassait le YAML genere."""
    phrase = "3\\4 inch hose adapter"
    result = add_keyword_to_yaml_text(EXISTING_YAML, phrase, "gadgets")
    data = yaml.safe_load(result)
    assert phrase in data["categories"]["gadgets"]["keywords"]


def test_add_keyword_with_special_chars_in_new_category_produces_valid_yaml():
    """Meme garantie que ci-dessus, mais sur le chemin 'nouvelle categorie'."""
    phrase = '"smart" mug'
    result = add_keyword_to_yaml_text(EXISTING_YAML, phrase, "cuisine")
    data = yaml.safe_load(result)
    assert phrase in data["categories"]["cuisine"]["keywords"]
    assert isinstance(data["categories"]["cuisine"].get("subreddits"), list)


REAL_SHAPED_YAML = """categories:
  gadgets:
    keywords:
      - "purificateur d'air portable"
      - "mini projecteur"
    subreddits:
      - gadgets
      - shutupandtakemymoney
  beaute:
    keywords:
      - "masque LED visage"
    subreddits:
      - SkincareAddiction
      - beauty

trends_timeframe: "today 3-m"
trends_geo: "FR"
thresholds:
  trends_growth_pct: 20
  reddit_min_posts: 3
  reddit_min_avg_score: 10
"""


def test_promote_into_existing_category_produces_scan_ready_config():
    """Regression pour discovery finding #1 et #8 : le YAML produit par promote
    doit rester chargeable et correctement structure pour que `scan` puisse
    ensuite lire keywords/subreddits sans erreur."""
    result = add_keyword_to_yaml_text(REAL_SHAPED_YAML, "chargeur solaire portable", "gadgets")
    data = yaml.safe_load(result)
    assert "chargeur solaire portable" in data["categories"]["gadgets"]["keywords"]
    assert isinstance(data["categories"]["gadgets"].get("subreddits"), list)
    assert data["categories"]["gadgets"]["subreddits"] == ["gadgets", "shutupandtakemymoney"]


def test_promote_into_new_category_produces_scan_ready_config():
    """Meme garantie que ci-dessus, mais pour une categorie qui n'existait pas
    encore dans le fichier : `scan` doit pouvoir iterer keywords/subreddits
    sans planter sur un type inattendu (None au lieu d'une liste, etc.)."""
    result = add_keyword_to_yaml_text(REAL_SHAPED_YAML, "fontaine a eau chat", "animaux")
    data = yaml.safe_load(result)
    assert "fontaine a eau chat" in data["categories"]["animaux"]["keywords"]
    assert isinstance(data["categories"]["animaux"].get("subreddits"), list)
    # Les autres categories doivent rester intactes et toujours chargeables.
    assert "mini projecteur" in data["categories"]["gadgets"]["keywords"]
    assert isinstance(data["categories"]["beaute"].get("subreddits"), list)


def test_is_duplicate_handles_null_keywords():
    """Ensure is_duplicate doesn't crash when keywords field is None/null."""
    yaml_with_null_keywords = """categories:
  gadgets:
    keywords:
    subreddits: []
"""
    # Should not crash and should return False
    assert is_duplicate(yaml_with_null_keywords, "test") is False
