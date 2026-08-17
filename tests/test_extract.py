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
