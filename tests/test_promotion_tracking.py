"""Instrumentation Phase 5 du plan de correction : enregistrer la date de
promotion d'un candidat discovery vers la watchlist, pour pouvoir un jour
mesurer si le score de convergence a continue a monter 30/60 jours apres
(pas assez d'historique reel aujourd'hui pour faire la mesure elle-meme,
mais rien ne peut etre mesure plus tard si la date n'est jamais posee)."""
from storage import db


def _make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db.get_connection()


def test_mark_promoted_sets_promoted_at(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    db.mark_promoted(conn, "corde a sauter connectee")
    row = conn.execute(
        "SELECT promoted_at FROM keywords WHERE term = ?", ("corde a sauter connectee",)
    ).fetchone()
    assert row["promoted_at"] is not None
    conn.close()


def test_mark_promoted_creates_keyword_if_absent(tmp_path, monkeypatch):
    """promote peut concerner un terme jamais vu par scan/discover (import
    manuel) : mark_promoted ne doit pas exiger que le mot-cle existe deja."""
    conn = _make_conn(tmp_path, monkeypatch)
    db.mark_promoted(conn, "nouveau produit jamais scanne")
    row = conn.execute(
        "SELECT id FROM keywords WHERE term = ?", ("nouveau produit jamais scanne",)
    ).fetchone()
    assert row is not None
    conn.close()


def test_mark_promoted_does_not_overwrite_earlier_date(tmp_path, monkeypatch):
    """Repromouvoir (ex: rejouer un `promote` par erreur) ne doit pas
    effacer la vraie date de premiere promotion."""
    conn = _make_conn(tmp_path, monkeypatch)
    db.mark_promoted(conn, "produit deja promu")
    first = conn.execute(
        "SELECT promoted_at FROM keywords WHERE term = ?", ("produit deja promu",)
    ).fetchone()["promoted_at"]

    db.mark_promoted(conn, "produit deja promu")
    second = conn.execute(
        "SELECT promoted_at FROM keywords WHERE term = ?", ("produit deja promu",)
    ).fetchone()["promoted_at"]

    assert first == second
    conn.close()


def test_init_db_migration_adds_promoted_at_to_pre_existing_database(tmp_path, monkeypatch):
    """data/trends.db existe deja en production (commite depuis PR #10) et
    a ete cree avant l'ajout de cette colonne : init_db() doit pouvoir
    l'ajouter a une base existante, pas seulement a une base neuve creee
    via CREATE TABLE IF NOT EXISTS (qui n'alterera jamais une table
    existante)."""
    import sqlite3

    db_path = tmp_path / "pre_existing.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    # Simule l'etat de production actuel : table keywords sans promoted_at.
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL UNIQUE,
            category TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.execute("INSERT INTO keywords (term) VALUES ('terme pre existant')")
    conn.commit()
    conn.close()

    db.init_db()  # doit migrer sans erreur ni perte de donnees
    conn = db.get_connection()
    row = conn.execute(
        "SELECT term, promoted_at FROM keywords WHERE term = 'terme pre existant'"
    ).fetchone()
    assert row["term"] == "terme pre existant"
    assert row["promoted_at"] is None
    conn.close()
