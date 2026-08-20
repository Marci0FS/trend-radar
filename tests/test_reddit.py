from unittest.mock import MagicMock

import pytest

from collectors import reddit


def test_get_client_missing_credentials_raises_key_error(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

    with pytest.raises(KeyError):
        reddit.get_client()


def test_get_client_empty_string_credential_raises_key_error(monkeypatch):
    """Meme bug deja corrige pour AliExpress/YouTube : une variable
    presente mais vide (etat par defaut de .env.example, ou Reddit reste
    bloque en pratique) ne doit pas etre traitee comme une vraie
    credential — sinon praw.Reddit() se construit sans erreur et un vrai
    appel API voue a l'echec (401) est tente au milieu du scan au lieu
    d'un skip propre en amont."""
    monkeypatch.setenv("REDDIT_CLIENT_ID", "")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "")

    with pytest.raises(KeyError):
        reddit.get_client()


def test_search_keyword_wraps_iteration_error_in_reddit_error():
    """PRAW execute la vraie requete HTTP paresseusement, au moment de
    l'iteration sur le generateur — pas au moment de l'appel .search()
    lui-meme. Un scenario reel (401 d'authentification invalide) leve
    l'exception depuis l'interieur de la boucle for ; ce test le simule
    en faisant lever l'exception directement par le mock d'iteration."""
    fake_reddit = MagicMock()

    def _raise(*args, **kwargs):
        raise RuntimeError("received 401 HTTP response")

    fake_reddit.subreddit.return_value.search.side_effect = _raise

    with pytest.raises(reddit.RedditError):
        reddit.search_keyword(fake_reddit, "led face mask", subreddits=[])


def test_search_keyword_returns_posts_on_success():
    fake_submission = MagicMock()
    fake_submission.id = "abc123"
    fake_submission.subreddit = "gadgets"
    fake_submission.title = "cool gadget"
    fake_submission.score = 42
    fake_submission.num_comments = 3
    fake_submission.created_utc = 1755000000
    fake_submission.permalink = "/r/gadgets/comments/abc123"

    fake_reddit = MagicMock()
    fake_reddit.subreddit.return_value.search.return_value = [fake_submission]

    posts = reddit.search_keyword(fake_reddit, "led face mask", subreddits=["gadgets"])

    assert len(posts) == 1
    assert posts[0]["post_id"] == "abc123"
    assert posts[0]["score"] == 42
