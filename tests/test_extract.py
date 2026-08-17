from discovery.extract import extract_phrases


def test_extract_phrases_counts_repeated_mentions():
    titles = [
        "This LED face mask changed my skincare routine",
        "I bought a LED face mask and love it",
        "Anyone else using a LED face mask daily?",
    ]
    counts = extract_phrases(titles)
    assert counts["led face mask"] == 3


def test_extract_phrases_filters_noise():
    titles = [
        "Update: my post got removed",
        "it",
        "ok",
    ]
    counts = extract_phrases(titles)
    assert "post" not in counts
    assert "update" not in counts
    assert "it" not in counts
    assert "ok" not in counts


def test_extract_phrases_empty_input_returns_empty_dict():
    assert extract_phrases([]) == {}


def test_extract_phrases_merges_adjacent_noun_chunks():
    """Test that adjacent noun chunks (with no gap) are merged into a single phrase.

    This verifies the fix for spaCy's inconsistent chunking of compound nouns:
    in certain sentence structures, spaCy splits "LED face mask" into separate
    chunks "a LED face" and "mask", which must be recombined before counting.
    """
    # "Anyone using a LED face mask" causes spaCy to create adjacent chunks
    # "a LED face" and "mask" that should merge to "a LED face mask"
    titles = [
        "Anyone else using a LED face mask daily?",
    ]
    counts = extract_phrases(titles)
    assert counts["led face mask"] == 1
    # Confirm that the split chunks "led face" and "mask" are NOT counted separately
    assert "led face" not in counts, "Adjacent chunks should be merged, not split"
    assert counts.get("mask") is None, "Final noun should not be counted as standalone"


def test_extract_phrases_does_not_merge_non_adjacent_chunks():
    """Test that noun chunks with gaps between them are NOT merged.

    Non-adjacent chunks (separated by verbs, prepositions, or other tokens)
    should remain separate and be counted independently.
    """
    # "colorful bags inside beautiful boxes" creates non-adjacent chunks
    # separated by the verb/preposition "inside", so they should not merge
    titles = [
        "I found colorful bags inside beautiful boxes",
    ]
    counts = extract_phrases(titles)
    # Both phrases should be extracted separately
    assert "colorful bags" in counts
    assert "beautiful boxes" in counts
    # They should not be merged into a single long phrase
    assert "colorful bags inside beautiful boxes" not in counts
