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
    assert is_duplicate(EXISTING_YAML, "mini projecteur", "gadgets") is True
    assert is_duplicate(EXISTING_YAML, "nouveau produit", "gadgets") is False
    assert is_duplicate(EXISTING_YAML, "mini projecteur", "beaute") is False


def test_is_duplicate_handles_null_keywords():
    """Ensure is_duplicate doesn't crash when keywords field is None/null."""
    yaml_with_null_keywords = """categories:
  gadgets:
    keywords:
    subreddits: []
"""
    # Should not crash and should return False
    assert is_duplicate(yaml_with_null_keywords, "test", "gadgets") is False
