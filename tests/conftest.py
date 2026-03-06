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
        "_http",
        "embedding",
        "hbk_container",
        "indexer",
        "memory",
        "parse_fastcode",
        "parse_its_v8std",
        "standards_loader",
        "toc_parser",
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


def _nosync_root() -> Path:
    """Root of .nosync / nosync project (crypto library). Env NOSYNC_DIR overrides."""
    root = Path(__file__).resolve().parent.parent
    env_path = __import__("os").environ.get("NOSYNC_DIR")
    if env_path:
        return Path(env_path).resolve()
    for name in (".nosync", "nosync"):
        p = root / name
        if p.is_dir():
            return p
    return root / ".nosync"


@pytest.fixture
def nosync_root() -> Path:
    """Path to .nosync (or nosync) project root for crypto library tests."""
    return _nosync_root()


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
