import os

from dotenv import load_dotenv


def test_load_dotenv_reads_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_TREND_RADAR_VAR=hello\n")
    monkeypatch.delenv("TEST_TREND_RADAR_VAR", raising=False)
    load_dotenv(env_file)
    assert os.environ["TEST_TREND_RADAR_VAR"] == "hello"
