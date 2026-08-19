import cli


def _result(sources_count: int, convergence_score: float = 10.0) -> dict:
    """Construit un dict resultat au format que cli.py::cmd_scan assemble pour
    chaque mot-cle (voir cli.py, boucle for keyword dans cmd_scan : {"keyword",
    "category", **result} ou result vient de scoring.convergence.compute_convergence)."""
    return {
        "keyword": "test kw",
        "category": "gadgets",
        "convergence_score": convergence_score,
        "sources_count": sources_count,
        "details": {
            "trends_growth_pct": 15.0,
            "reddit_post_count": 4,
            "reddit_avg_score": 12.5,
            "ebay_growth_pct": 5.0,
            "aliexpress_growth_pct": 8.0,
        },
    }


def test_write_report_marks_two_sources_as_faible(tmp_path, monkeypatch):
    """Le seuil FORT a ete releve de >= 2 a >= 3 sources sur 4 (branche
    'wire aliexpress' du feature). Un resultat avec sources_count == 2 ne
    doit plus jamais produire [FORT] : c'est la regression que ce test
    protege contre un retour silencieux a l'ancien seuil."""
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")

    cli.write_report([_result(sources_count=2)])

    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "[faible]" in text
    assert "[FORT]" not in text


def test_write_report_marks_three_sources_as_fort_with_four_denominator(tmp_path, monkeypatch):
    """Un resultat avec sources_count == 3 doit produire [FORT] et la ligne
    'Sources en accord : 3/4' (denominateur passe de /3 a /4 avec l'ajout
    d'AliExpress comme 4e source)."""
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")

    cli.write_report([_result(sources_count=3)])

    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "[FORT]" in text
    assert "Sources en accord : 3/4" in text


def test_write_report_includes_aliexpress_line(tmp_path, monkeypatch):
    """La ligne de rapport AliExpress (nouvelle avec cette source) doit bien
    apparaitre dans le Markdown genere, avec le pourcentage de croissance."""
    monkeypatch.setattr(cli, "REPORT_PATH", tmp_path / "report.md")

    cli.write_report([_result(sources_count=4)])

    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "AliExpress : 8.0% de croissance" in text
