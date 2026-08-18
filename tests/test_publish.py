from unittest.mock import MagicMock, patch

import publish


def test_publish_json_noop_when_unchanged(tmp_path):
    with patch("publish.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = publish.publish_json(tmp_path, "web/public/data/signals.json")

    assert result is False
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[:2] == ["git", "status"]


def test_publish_json_commits_and_pushes_when_changed(tmp_path):
    status_result = MagicMock(returncode=0, stdout=" M web/public/data/signals.json\n", stderr="")
    ok_result = MagicMock(returncode=0, stdout="", stderr="")

    with patch("publish.subprocess.run") as mock_run:
        mock_run.side_effect = [status_result, ok_result, ok_result, ok_result]
        result = publish.publish_json(tmp_path, "web/public/data/signals.json")

    assert result is True
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert calls[0][:2] == ["git", "status"]
    assert calls[1] == ["git", "add", "web/public/data/signals.json"]
    assert calls[2] == ["git", "commit", "-m", "chore: update signals.json", "--", "web/public/data/signals.json"]
    assert calls[3] == ["git", "push"]


def test_publish_json_handles_push_failure(tmp_path):
    status_result = MagicMock(returncode=0, stdout=" M web/public/data/signals.json\n", stderr="")
    ok_result = MagicMock(returncode=0, stdout="", stderr="")
    push_fail = MagicMock(returncode=1, stdout="", stderr="fatal: could not read from remote")

    with patch("publish.subprocess.run") as mock_run:
        mock_run.side_effect = [status_result, ok_result, ok_result, push_fail]
        result = publish.publish_json(tmp_path, "web/public/data/signals.json")

    assert result is False


def test_publish_json_handles_status_failure(tmp_path):
    with patch("publish.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="fatal: not a git repository")
        result = publish.publish_json(tmp_path, "web/public/data/signals.json")

    assert result is False
