"""Suite-wide isolation: init_project registers every repo it touches into the
global registry (~/.codecompass/repos). Redirect it per-test so a test run
never pollutes the developer's real registry. Also stub the vector index
rebuild: ingest builds it by default, and tests must not download the
embedding model or spend seconds embedding."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_repos_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("CODECOMPASS_REPOS", str(tmp_path / "repos"))


@pytest.fixture(autouse=True)
def _stub_vector_index(monkeypatch):
    monkeypatch.setattr("graph.vector_store.index_entities", lambda _: 0)
