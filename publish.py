"""Publication de signals.json vers GitHub (declenche le redeploy Vercel).

Ne committe/pousse QUE web/public/data/signals.json, jamais `git add -A` :
on ne veut pas embarquer d'autres changements en cours de l'utilisateur
dans un commit automatique. Toute erreur (reseau, remote absent, conflit)
est affichee clairement, sans exception non geree.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def publish_json(repo_root: Path, relative_path: str) -> bool:
    """Commit + push le fichier signals.json (donne en chemin relatif a
    repo_root) s'il a change. Retourne True si un push a eu lieu, False si
    rien n'avait change ou en cas d'erreur."""
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", relative_path],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        print(f"Erreur git status : {status.stderr.strip()}")
        return False
    if not status.stdout.strip():
        print("Rien a publier (signals.json inchange)")
        return False

    add = subprocess.run(
        ["git", "add", relative_path], cwd=repo_root, capture_output=True, text=True
    )
    if add.returncode != 0:
        print(f"Erreur git add : {add.stderr.strip()}")
        return False

    commit = subprocess.run(
        ["git", "commit", "-m", "chore: update signals.json", "--", relative_path],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        print(f"Erreur git commit : {commit.stderr.strip()}")
        return False

    push = subprocess.run(["git", "push"], cwd=repo_root, capture_output=True, text=True)
    if push.returncode != 0:
        print(f"Erreur git push : {push.stderr.strip()}")
        return False

    print("signals.json publie (commit + push)")
    return True
