"""Permet aux tests d'importer les modules du projet (cli, storage, discovery, collectors)
sans installation en mode package."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest

import cli


@pytest.fixture(autouse=True)
def _isolate_signals_json(tmp_path, monkeypatch):
    """Empeche tout test (present ou futur) d'ecrire par omission dans le
    vrai web/public/data/signals.json, que --publish pourrait ensuite
    pousser publiquement. Les tests qui ont besoin d'un chemin specifique
    peuvent monkeypatcher SIGNALS_JSON_PATH eux-memes par dessus."""
    monkeypatch.setattr(cli, "SIGNALS_JSON_PATH", tmp_path / "signals.json")
