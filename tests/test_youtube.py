from unittest.mock import MagicMock, patch

import pytest

from collectors import youtube


def _search_response(video_ids):
    return {"items": [{"id": {"videoId": vid}} for vid in video_ids]}


def _videos_response(view_counts):
    return {"items": [{"statistics": {"viewCount": str(v)}} for v in view_counts]}


def test_fetch_recent_view_count_missing_api_key_raises_key_error(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    with pytest.raises(KeyError):
        youtube.fetch_recent_view_count("led face mask")


def test_fetch_recent_view_count_sums_views_across_videos(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    search_resp = MagicMock()
    search_resp.json.return_value = _search_response(["vid1", "vid2", "vid3"])
    search_resp.raise_for_status.return_value = None

    videos_resp = MagicMock()
    videos_resp.json.return_value = _videos_response([1000, 2500, 300])
    videos_resp.raise_for_status.return_value = None

    with patch(
        "collectors.youtube.requests.get", side_effect=[search_resp, videos_resp]
    ) as mock_get:
        total = youtube.fetch_recent_view_count("led face mask")

    assert total == 3800
    search_call_kwargs = mock_get.call_args_list[0].kwargs
    assert search_call_kwargs["params"]["q"] == "led face mask"
    assert search_call_kwargs["params"]["order"] == "viewCount"
    assert search_call_kwargs["params"]["type"] == "video"
    assert search_call_kwargs["params"]["maxResults"] == 10
    assert "publishedAfter" in search_call_kwargs["params"]

    videos_call_kwargs = mock_get.call_args_list[1].kwargs
    assert videos_call_kwargs["params"]["id"] == "vid1,vid2,vid3"


def test_fetch_recent_view_count_returns_zero_for_empty_search_results(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    search_resp = MagicMock()
    search_resp.json.return_value = _search_response([])
    search_resp.raise_for_status.return_value = None

    with patch("collectors.youtube.requests.get", side_effect=[search_resp]) as mock_get:
        total = youtube.fetch_recent_view_count("very obscure keyword")

    assert total == 0
    mock_get.assert_called_once()  # videos.list jamais appele si aucune video trouvee


def test_fetch_recent_view_count_raises_youtube_error_on_search_http_failure(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    import requests as requests_module

    with patch(
        "collectors.youtube.requests.get",
        side_effect=requests_module.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(youtube.YouTubeError):
            youtube.fetch_recent_view_count("led face mask")


def test_fetch_recent_view_count_raises_youtube_error_on_videos_http_failure(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    import requests as requests_module

    search_resp = MagicMock()
    search_resp.json.return_value = _search_response(["vid1"])
    search_resp.raise_for_status.return_value = None

    with patch(
        "collectors.youtube.requests.get",
        side_effect=[search_resp, requests_module.exceptions.ConnectionError("boom")],
    ):
        with pytest.raises(youtube.YouTubeError):
            youtube.fetch_recent_view_count("led face mask")


def test_fetch_recent_view_count_raises_youtube_error_when_video_missing_view_count(monkeypatch):
    """Une video presente dans la reponse mais sans champ viewCount doit
    lever YouTubeError plutot que d'etre silencieusement traitee comme 0 —
    un faux 0 fabriquerait un faux signal de convergence au prochain scan
    (meme precaution que collectors/ebay.py et collectors/aliexpress.py)."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    search_resp = MagicMock()
    search_resp.json.return_value = _search_response(["vid1"])
    search_resp.raise_for_status.return_value = None

    videos_resp = MagicMock()
    videos_resp.json.return_value = {"items": [{"statistics": {}}]}
    videos_resp.raise_for_status.return_value = None

    with patch("collectors.youtube.requests.get", side_effect=[search_resp, videos_resp]):
        with pytest.raises(youtube.YouTubeError):
            youtube.fetch_recent_view_count("led face mask")


def test_fetch_recent_view_count_raises_youtube_error_on_malformed_search_response(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    search_resp = MagicMock()
    search_resp.json.return_value = {"error": "quota exceeded"}
    search_resp.raise_for_status.return_value = None

    with patch("collectors.youtube.requests.get", side_effect=[search_resp]):
        with pytest.raises(youtube.YouTubeError):
            youtube.fetch_recent_view_count("led face mask")


def test_fetch_recent_view_count_redacts_api_key_from_error_message(monkeypatch):
    """requests integre l'URL complete (avec la query string, donc la cle
    API) dans le str() de RequestException. Le message YouTubeError qui en
    resulte est imprime tel quel sur stdout par cli.py::cmd_scan (voir
    README) : la cle ne doit donc jamais apparaitre dans str(YouTubeError),
    meme quand le message d'erreur brut de requests la contient."""
    fake_key = "AIzaSyREAL_SECRET_KEY"
    monkeypatch.setenv("YOUTUBE_API_KEY", fake_key)

    import requests as requests_module

    error_message = (
        f"HTTPSConnectionPool(host='www.googleapis.com', port=443): Max retries "
        f"exceeded with url: https://www.googleapis.com/youtube/v3/search?"
        f"key={fake_key}&q=test"
    )

    with patch(
        "collectors.youtube.requests.get",
        side_effect=requests_module.exceptions.ConnectionError(error_message),
    ):
        with pytest.raises(youtube.YouTubeError) as exc_info:
            youtube.fetch_recent_view_count("led face mask")

    assert fake_key not in str(exc_info.value)
    assert "Echec recherche YouTube" in str(exc_info.value)


def test_fetch_recent_view_count_raises_youtube_error_when_view_count_non_numeric(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    search_resp = MagicMock()
    search_resp.json.return_value = _search_response(["vid1"])
    search_resp.raise_for_status.return_value = None

    videos_resp = MagicMock()
    videos_resp.json.return_value = {"items": [{"statistics": {"viewCount": "not-a-number"}}]}
    videos_resp.raise_for_status.return_value = None

    with patch("collectors.youtube.requests.get", side_effect=[search_resp, videos_resp]):
        with pytest.raises(youtube.YouTubeError):
            youtube.fetch_recent_view_count("led face mask")
