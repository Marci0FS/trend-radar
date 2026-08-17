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


def test_add_keyword_to_existing_category():
    result = add_keyword_to_yaml_text(EXISTING_YAML, "chargeur solaire portable", "gadgets")
    lines = result.splitlines()
    idx = lines.index("    keywords:")
    assert lines[idx + 1] == '      - "chargeur solaire portable"'


def test_add_keyword_creates_new_category():
    result = add_keyword_to_yaml_text(EXISTING_YAML, "fontaine a eau chat", "animaux")
    assert "  animaux:" in result
    assert '      - "fontaine a eau chat"' in result
    assert "trends_timeframe:" in result  # le reste du fichier est preserve


def test_add_keyword_preserves_comments():
    yaml_with_comment = "# commentaire important\n" + EXISTING_YAML
    result = add_keyword_to_yaml_text(yaml_with_comment, "chargeur solaire portable", "gadgets")
    assert "# commentaire important" in result


def test_is_duplicate_detects_existing_keyword():
    assert is_duplicate(EXISTING_YAML, "mini projecteur", "gadgets") is True
    assert is_duplicate(EXISTING_YAML, "nouveau produit", "gadgets") is False
    assert is_duplicate(EXISTING_YAML, "mini projecteur", "beaute") is False
