from unittest.mock import MagicMock

from discovery import reddit_scan


def test_scan_subreddits_collects_hot_and_rising_titles():
    fake_post_hot = MagicMock(title="Hot post about gadgets")
    fake_post_rising = MagicMock(title="Rising post about gadgets")
    fake_subreddit = MagicMock()
    fake_subreddit.hot.return_value = [fake_post_hot]
    fake_subreddit.rising.return_value = [fake_post_rising]
    fake_reddit = MagicMock()
    fake_reddit.subreddit.return_value = fake_subreddit

    posts = reddit_scan.scan_subreddits(fake_reddit, ["gadgets"], post_limit=10)

    assert posts == [
        {"subreddit": "gadgets", "title": "Hot post about gadgets"},
        {"subreddit": "gadgets", "title": "Rising post about gadgets"},
    ]
    fake_reddit.subreddit.assert_called_once_with("gadgets")
    fake_subreddit.hot.assert_called_once_with(limit=10)
    fake_subreddit.rising.assert_called_once_with(limit=10)


def test_scan_subreddits_handles_multiple_subreddits():
    fake_subreddit = MagicMock()
    fake_subreddit.hot.return_value = []
    fake_subreddit.rising.return_value = []
    fake_reddit = MagicMock()
    fake_reddit.subreddit.return_value = fake_subreddit

    reddit_scan.scan_subreddits(fake_reddit, ["gadgets", "beauty"], post_limit=5)

    assert fake_reddit.subreddit.call_count == 2


def test_scan_subreddits_skips_failing_subreddit_and_keeps_others(capsys):
    """Un subreddit prive/banni/en erreur ne doit pas faire perdre les donnees
    deja collectees sur les autres subreddits (discovery finding #6)."""
    fake_post_hot = MagicMock(title="Hot post about gadgets")
    fake_post_rising = MagicMock(title="Rising post about gadgets")
    good_subreddit = MagicMock()
    good_subreddit.hot.return_value = [fake_post_hot]
    good_subreddit.rising.return_value = [fake_post_rising]

    bad_subreddit = MagicMock()
    bad_subreddit.hot.side_effect = Exception("403 Forbidden (private subreddit)")

    fake_reddit = MagicMock()

    def _subreddit(name):
        return bad_subreddit if name == "privatesubforbidden" else good_subreddit

    fake_reddit.subreddit.side_effect = _subreddit

    posts = reddit_scan.scan_subreddits(
        fake_reddit, ["privatesubforbidden", "gadgets"], post_limit=10
    )

    assert posts == [
        {"subreddit": "gadgets", "title": "Hot post about gadgets"},
        {"subreddit": "gadgets", "title": "Rising post about gadgets"},
    ]
    captured = capsys.readouterr()
    assert "privatesubforbidden" in captured.out
