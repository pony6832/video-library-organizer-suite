import pytest


@pytest.fixture(autouse=True)
def _logs_stay_out_of_the_user_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_LIBRARY_ORGANIZER_LOG_DIR", str(tmp_path / "vlo-logs"))
