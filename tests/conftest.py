"""Pytest fixtures."""

import importlib
from pathlib import Path
from unittest.mock import patch

import pytest


# Pre-import submodules so patch("onec_help.<sub>.attr") works (CI Python 3.10 editable install)
def _ensure_onec_help_submodules():
    """Bind submodules to onec_help package (Python 3.10 editable install quirk)."""
    import onec_help

    for _name in (
        "embedding",
        "hbk_container",
        "indexer",
        "memory",
        "parse_fastcode",
        "standards_loader",
        "unpack",
        "watchdog",
    ):
        _mod = __import__(f"onec_help.{_name}", fromlist=[_name])
        setattr(onec_help, _name, _mod)


_ensure_onec_help_submodules()


@pytest.fixture(autouse=True)
def _ensure_onec_help_refs():
    """Re-bind submodules before each test (Python 3.10 patch target lookup)."""
    _ensure_onec_help_submodules()
    yield


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def help_sample_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "help_sample"


@pytest.fixture
def sample_html(help_sample_dir: Path) -> Path:
    return help_sample_dir / "field626.html"


@pytest.fixture
def categories_file(help_sample_dir: Path) -> Path:
    return help_sample_dir / "__categories__"


@pytest.fixture(autouse=True)
def embedding_backend_none_for_network_tests(request):
    """Use EMBEDDING_BACKEND=none in indexer/embedding tests to avoid HuggingFace download."""
    path = str(getattr(request, "fspath", None) or "")
    if "test_indexer" in path or "test_embedding" in path:
        with patch.dict("os.environ", {"EMBEDDING_BACKEND": "none"}, clear=False):
            import onec_help.embedding as emb

            importlib.reload(emb)
            _ensure_onec_help_submodules()
            yield
    else:
        yield


@pytest.fixture(autouse=True)
def isolate_bm25_vocab_for_indexer_tests(request, tmp_path):
    """Redirect BM25 vocab to tmp_path in indexer tests to avoid overwriting data/bm25_vocab."""
    path = str(getattr(request, "fspath", None) or "")
    if "test_indexer" in path:
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}, clear=False):
            yield
    else:
        yield
