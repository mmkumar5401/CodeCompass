"""Suite-wide isolation: init_project registers every repo it touches into the
global registry (~/.codecompass/repos). Redirect it per-test so a test run
never pollutes the developer's real registry."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_repos_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("CODECOMPASS_REPOS", str(tmp_path / "repos"))
