"""Permet aux tests d'importer les modules du projet (cli, storage, discovery, collectors)
sans installation en mode package."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
