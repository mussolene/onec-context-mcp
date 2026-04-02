"""Tests for CLI."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from onec_help.interfaces.cli import (
    _build_snippets_sources,
    _categorize_error,
    _env_path,
    _run_api_structured_pipeline,
    _short_error,
    cmd_add_bm25,
    cmd_build_api_structured,
    cmd_build_docs,
    cmd_build_index,
    cmd_build_kd2_snapshot,
    cmd_build_metadata_graph,
    cmd_dashboard,
    cmd_index_api_structured,
    cmd_ingest,
    cmd_ingest_from_unpacked,
    cmd_init,
    cmd_load_snippets,
    cmd_load_standards,
    cmd_mcp,
    cmd_parse_fastcode,
    cmd_parse_helpf,
    cmd_qdrant_backup,
    cmd_qdrant_restore,
    cmd_read_hbk_container,
    cmd_reinit,
    cmd_unpack,
    cmd_unpack_diag,
    cmd_unpack_dir,
    cmd_unpack_sync,
    cmd_watchdog,
    main,
)
from onec_help.knowledge.kd2_metadata import snapshot_dir_for_xml


def make_args(**kwargs) -> SimpleNamespace:
    """Create argparse.Namespace-like object for cmd_* tests."""
    return SimpleNamespace(**kwargs)


def test_cmd_build_docs(help_sample_dir: Path, tmp_path: Path) -> None:
    args = make_args(project_dir=str(help_sample_dir), output=str(tmp_path / "out_md"))
    assert cmd_build_docs(args) == 0
    assert (tmp_path / "out_md").exists()


def test_cmd_build_kd2_snapshot(tmp_path: Path) -> None:
    xml_path = tmp_path / "kd2.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<Конфигурация Имя="Cfg">
  <CatalogObject.Конфигурации><Ref>cfg</Ref><Description>Cfg</Description><Имя>Cfg</Имя><Синоним>Cfg</Синоним><Версия>1.0.0.1</Версия></CatalogObject.Конфигурации>
  <CatalogObject.Объекты><Ref>doc</Ref><IsFolder>false</IsFolder><Description>Sales</Description><Имя>Sales</Имя><Синоним>Sales</Синоним><Тип>Документ</Тип></CatalogObject.Объекты>
</Конфигурация>
""",
        encoding="utf-8",
    )
    out = tmp_path / "snapshot"
    args = make_args(xml_path=str(xml_path), output_dir=str(out))
    assert cmd_build_kd2_snapshot(args) == 0
    assert (out / "manifest.json").exists()


@patch("onec_help.help_core.html2md.build_docs")
def test_cmd_build_docs_error(mock_build_docs, tmp_path: Path) -> None:
    mock_build_docs.side_effect = RuntimeError("disk full")
    tmp_path.mkdir(exist_ok=True)
    args = make_args(project_dir=str(tmp_path), output=str(tmp_path / "out_md"))
    assert cmd_build_docs(args) == 1


def test_cmd_read_hbk_container_not_file() -> None:
    """read-hbk-container returns 1 when path is not a file."""
    args = make_args(file="/nonexistent.hbk", out_dir=None, toc_json=None)
    assert cmd_read_hbk_container(args) == 1


def test_cmd_read_hbk_container_empty_toc(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """read-hbk-container on minimal container (empty TOC) lists entities."""
    import struct

    header = struct.pack("<iiii", 0, 256, 0, 0)
    toc_header = b"\x0d\x0a00000000 00000000 FFFFFFFF \x0d\x0a"
    hbk = tmp_path / "empty.hbk"
    hbk.write_bytes(header + toc_header)
    args = make_args(file=str(hbk), out_dir=None, toc_json=None)
    assert cmd_read_hbk_container(args) == 0
    out = capsys.readouterr().out
    assert "Entities:" in out


def test_cmd_unpack_diag_success(tmp_path: Path) -> None:
    out = tmp_path / "diag_out"
    with patch("onec_help.help_core.unpack.unpack_diag"):
        args = make_args(archive="/nonexistent.hbk", output_dir=str(out))
        assert cmd_unpack_diag(args) == 0


def test_cmd_unpack_diag_error(tmp_path: Path) -> None:
    with patch("onec_help.help_core.unpack.unpack_diag", side_effect=RuntimeError("diag failed")):
        args = make_args(archive="/nonexistent.hbk", output_dir=str(tmp_path))
        assert cmd_unpack_diag(args) == 1


def test_cmd_add_bm25_success() -> None:
    with patch("onec_help.search_store.indexer.add_bm25_to_all_collections", return_value={"onec_help": 100}):
        args = make_args()
        with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
            assert cmd_add_bm25(args) == 0


def test_cmd_add_bm25_error() -> None:
    with patch(
        "onec_help.search_store.indexer.add_bm25_to_all_collections",
        side_effect=RuntimeError("Qdrant unavailable"),
    ):
        args = make_args()
        with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
            assert cmd_add_bm25(args) == 1


def test_cmd_add_bm25_with_collection() -> None:
    """add-bm25 with --collection calls add_bm25_to_collection for that collection only."""
    with patch("onec_help.search_store.indexer.add_bm25_to_collection", return_value=50) as m:
        args = make_args(collection="onec_config_metadata", batch_size=100)
        with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
            assert cmd_add_bm25(args) == 0
        m.assert_called_once()
        call_kw = m.call_args[1]
        assert call_kw["collection"] == "onec_config_metadata"
        assert call_kw["batch_size"] == 100


def test_categorize_error() -> None:
    assert _categorize_error("All unpack methods failed") == "unpack"
    assert _categorize_error("connection timeout") == "embed"
    assert _categorize_error("qdrant upsert failed") == "index"
    assert _categorize_error("html parse error") == "build"
    assert _categorize_error("something else") == "other"


def test_short_error() -> None:
    assert _short_error("All unpack methods failed") == "unpack failed"
    assert _short_error("unzip: No such file or directory") == "unzip not found"
    assert _short_error("invalid archive") == "7z/invalid archive"
    assert _short_error("Connection timeout") == "timeout"
    assert _short_error("429 rate limit") == "rate limit"
    assert _short_error("x" * 50) == "x" * 38 + "…"
    assert _short_error("short") == "short"


def test_cmd_unpack_fail() -> None:
    args = make_args(archive="/nonexistent.hbk", output_dir="/tmp/out")
    assert cmd_unpack(args) == 1


@patch("onec_help.help_core.unpack.unpack_hbk")
def test_cmd_unpack_success(mock_unpack, tmp_path: Path) -> None:
    (tmp_path / "fake.hbk").write_bytes(b"x")
    args = make_args(archive=str(tmp_path / "fake.hbk"), output_dir=str(tmp_path / "out"))
    assert cmd_unpack(args) == 0
    mock_unpack.assert_called_once()


@patch("onec_help.search_store.indexer.build_index")
def test_cmd_build_index(mock_build, help_sample_dir: Path) -> None:
    mock_build.return_value = 5
    args = make_args(directory=str(help_sample_dir), docs_dir=None, incremental=False, skip_api_structured=False)
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        with patch("onec_help.interfaces.cli._run_api_structured_pipeline", return_value=0) as mock_struct:
            assert cmd_build_index(args) == 0
    mock_struct.assert_called_once_with(recreate=True)


@patch("onec_help.search_store.indexer.build_index")
def test_cmd_build_index_error(mock_build, help_sample_dir: Path) -> None:
    mock_build.side_effect = RuntimeError("Qdrant unavailable")
    args = make_args(directory=str(help_sample_dir), docs_dir=None, skip_api_structured=False)
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_build_index(args) == 1


def test_cmd_build_api_structured() -> None:
    with patch(
        "onec_help.knowledge.help_structured.build_structured_api_snapshot",
        return_value={"objects": 3, "examples": 2},
    ) as mock_build:
        args = make_args(output_dir=None)
        assert cmd_build_api_structured(args) == 0
    mock_build.assert_called_once()


def test_cmd_index_api_structured() -> None:
    with patch(
        "onec_help.knowledge.help_structured.index_structured_api_objects",
        return_value=3,
    ) as mock_objects:
        with patch(
            "onec_help.knowledge.help_structured.index_structured_api_members",
            return_value=5,
        ) as mock_members:
            with patch(
            "onec_help.knowledge.help_structured.index_structured_api_examples",
            return_value=2,
            ) as mock_examples:
                with patch(
                    "onec_help.knowledge.help_structured.index_structured_api_links",
                    return_value=7,
                ) as mock_links:
                    with patch("onec_help.search_store.indexer.add_bm25_to_collection", return_value=3) as mock_bm25:
                        args = make_args(snapshot_dir=None, recreate=True)
                        assert cmd_index_api_structured(args) == 0
    mock_objects.assert_called_once()
    mock_members.assert_called_once()
    mock_examples.assert_called_once()
    mock_links.assert_called_once()
    assert mock_bm25.call_count == 2


def test_run_api_structured_pipeline_stops_on_snapshot_error() -> None:
    with patch("onec_help.interfaces.cli.cmd_build_api_structured", return_value=1) as mock_build:
        with patch("onec_help.interfaces.cli.cmd_index_api_structured", return_value=0) as mock_index:
            assert _run_api_structured_pipeline(recreate=False) == 1
    mock_build.assert_called_once()
    mock_index.assert_not_called()


@patch("onec_help.knowledge.kd2_metadata.crawl_kd2_xml")
@patch("onec_help.knowledge.kd2_metadata.write_kd2_snapshot")
@patch("onec_help.knowledge.metadata_graph.build_metadata_graph_from_crawl")
@patch("onec_help.search_store.indexer.add_bm25_to_collection", return_value=1)
@patch("onec_help.search_store.embedding.is_embedding_available", return_value=True)
@patch("onec_help.runtime.redis_cache.require_runtime_redis")
@patch("qdrant_client.QdrantClient")
def test_cmd_build_metadata_graph_kd2_xml(
    mock_client,
    _mock_redis,
    _mock_embed_available,
    _mock_add_bm25,
    mock_build_graph,
    mock_write_snapshot,
    mock_crawl_kd2,
    tmp_path: Path,
) -> None:
    from onec_help.knowledge.config_crawler import ConfigObject, CrawlResult

    xml_path = tmp_path / "kd2.xml"
    xml_path.write_text("<Конфигурация Имя='Cfg'/>", encoding="utf-8")
    mock_crawl_kd2.return_value = CrawlResult(
        root_dir=xml_path,
        config_name="Cfg",
        config_version="1.0.0.1",
        platform_version=None,
        objects=[ConfigObject(id="Document/Sales", object_type="Document", name="Sales", attributes={})],
        relations=[],
    )
    mock_build_graph.return_value = 1
    mock_write_snapshot.return_value = {
        "format": "onec_kd2_snapshot_v1",
        "objects": 1,
        "fields": 0,
    }
    args = make_args(source_dir=str(xml_path), source_format="kd2-xml", recreate=False)
    assert cmd_build_metadata_graph(args) == 0
    mock_crawl_kd2.assert_called_once()
    mock_write_snapshot.assert_called_once_with(
        mock_crawl_kd2.return_value, snapshot_dir_for_xml(xml_path.parent, xml_path)
    )


@patch("onec_help.knowledge.kd2_metadata.write_kd2_snapshot")
@patch("onec_help.knowledge.metadata_graph.build_metadata_graph_from_crawl")
@patch("onec_help.search_store.indexer.add_bm25_to_collection", return_value=1)
@patch("onec_help.search_store.embedding.is_embedding_available", return_value=True)
@patch("onec_help.runtime.redis_cache.require_runtime_redis")
@patch("qdrant_client.QdrantClient")
def test_cmd_build_metadata_graph_auto_merges_multiple_kd2_exports(
    mock_client,
    _mock_redis,
    _mock_embed_available,
    _mock_add_bm25,
    mock_build_graph,
    mock_write_snapshot,
    tmp_path: Path,
) -> None:
    from onec_help.knowledge.config_crawler import ConfigObject, CrawlResult

    work_dir = tmp_path / "kd2"
    work_dir.mkdir()
    first = work_dir / "Cfg1.xml"
    second = work_dir / "Cfg2.xml"
    first.write_text("<Конфигурация Имя='Cfg1'/>", encoding="utf-8")
    second.write_text("<Конфигурация Имя='Cfg2'/>", encoding="utf-8")
    with patch(
        "onec_help.knowledge.kd2_metadata.crawl_kd2_xml",
        side_effect=[
            CrawlResult(
                root_dir=first,
                config_name="Cfg1",
                config_version="1.0",
                platform_version=None,
                objects=[ConfigObject(id="Document/A", object_type="Document", name="A", attributes={"config_version": "1.0"})],
                relations=[],
            ),
            CrawlResult(
                root_dir=second,
                config_name="Cfg2",
                config_version="2.0",
                platform_version=None,
                objects=[ConfigObject(id="Document/B", object_type="Document", name="B", attributes={"config_version": "2.0"})],
                relations=[],
            ),
        ],
    ) as mock_crawl_xml:
        mock_build_graph.return_value = 2
        mock_write_snapshot.return_value = {
            "format": "onec_kd2_snapshot_v1",
            "objects": 2,
            "fields": 0,
        }
        args = make_args(source_dir=str(work_dir), source_format="auto", recreate=False)
        assert cmd_build_metadata_graph(args) == 0
    called_paths = [call.args[0] for call in mock_crawl_xml.call_args_list]
    assert called_paths == [first.resolve(), second.resolve()]
    assert mock_write_snapshot.call_count == 2


@patch("onec_help.knowledge.kd2_metadata.crawl_kd2_xml")
@patch("onec_help.knowledge.kd2_metadata.write_kd2_snapshot")
@patch("onec_help.knowledge.metadata_graph.build_metadata_graph_from_crawl")
@patch("onec_help.search_store.indexer.add_bm25_to_collection", return_value=1)
@patch("onec_help.search_store.embedding.is_embedding_available", return_value=True)
@patch("onec_help.runtime.redis_cache.require_runtime_redis")
@patch("qdrant_client.QdrantClient")
def test_cmd_build_metadata_graph_auto_refreshes_snapshot_from_workdir(
    mock_client,
    _mock_redis,
    _mock_embed_available,
    _mock_add_bm25,
    mock_build_graph,
    mock_write_snapshot,
    mock_crawl_kd2,
    tmp_path: Path,
) -> None:
    from onec_help.knowledge.config_crawler import ConfigObject, CrawlResult

    work_dir = tmp_path / "kd2"
    work_dir.mkdir()
    xml_path = work_dir / "Cfg.xml"
    xml_path.write_text("<Конфигурация Имя='Cfg'/>", encoding="utf-8")
    mock_crawl_kd2.return_value = CrawlResult(
        root_dir=xml_path,
        config_name="Cfg",
        config_version="1.0.0.1",
        platform_version=None,
        objects=[ConfigObject(id="Document/Sales", object_type="Document", name="Sales", attributes={})],
        relations=[],
    )
    mock_build_graph.return_value = 1
    mock_write_snapshot.return_value = {
        "format": "onec_kd2_snapshot_v1",
        "objects": 1,
        "fields": 0,
    }
    args = make_args(source_dir=str(work_dir), source_format="auto", recreate=False)
    assert cmd_build_metadata_graph(args) == 0
    mock_crawl_kd2.assert_called_once_with(xml_path)
    mock_write_snapshot.assert_called_once_with(
        mock_crawl_kd2.return_value, snapshot_dir_for_xml(work_dir, xml_path)
    )


def test_main_help() -> None:
    with patch("sys.argv", ["onec_help", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0


def test_main_unpack_usage() -> None:
    with patch("sys.argv", ["onec_help", "unpack", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0


@patch("onec_help.runtime.ingest.run_ingest")
def test_cmd_ingest_with_sources_env(mock_run_ingest, tmp_path: Path) -> None:
    mock_run_ingest.return_value = 10
    (tmp_path / "ver").mkdir()
    args = make_args(
        sources=None,
        sources_file=None,
        languages=None,
        temp_base=None,
        workers=2,
        max_tasks=None,
        quiet=False,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {
            "HELP_SOURCE_BASE": str(tmp_path),
            "QDRANT_HOST": "localhost",
            "QDRANT_PORT": "6333",
            "INGEST_USE_TEMP": "1",
        },
    ):
        with patch("onec_help.runtime.ingest.discover_version_dirs") as mock_disc:
            mock_disc.return_value = [(tmp_path / "ver", "ver")]
            assert cmd_ingest(args) == 0
    mock_run_ingest.assert_called_once()


@patch("onec_help.runtime.ingest.run_ingest")
def test_cmd_ingest_sources_arg(mock_run_ingest) -> None:
    mock_run_ingest.return_value = 5
    args = make_args(
        sources=["/path/to/1cv8:8.3"],
        sources_file=None,
        languages=None,
        temp_base="/tmp/t",
        workers=1,
        max_tasks=None,
        quiet=True,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333", "INGEST_USE_TEMP": "1"},
        clear=False,
    ):
        assert cmd_ingest(args) == 0
    mock_run_ingest.assert_called_once()
    call_kw = mock_run_ingest.call_args[1]
    assert call_kw["source_dirs_with_versions"] == [("/path/to/1cv8", "8.3")]


def test_env_path() -> None:
    assert _env_path("NONEXISTENT_VAR") is None
    with patch.dict("os.environ", {"TEST_VAR": "/path"}):
        assert _env_path("TEST_VAR") == "/path"
    with patch.dict("os.environ", {"PORT": "8080"}):
        assert _env_path("PORT", "5000") == "8080"
    assert _env_path("MISSING", "default") == "default"


def test_cmd_ingest_no_sources_returns_error() -> None:
    args = make_args(
        sources=None,
        sources_file=None,
        languages=None,
        temp_base=None,
        workers=1,
        max_tasks=None,
        quiet=False,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict("os.environ", {}, clear=True):
        assert cmd_ingest(args) == 1


@patch("onec_help.runtime.ingest.run_unpack_only")
def test_cmd_unpack_dir_sources_path_version(mock_run, tmp_path: Path) -> None:
    """cmd_unpack_dir parses sources as path:version."""
    mock_run.return_value = 1
    out = tmp_path / "out"
    out.mkdir()
    args = make_args(
        source_dir="",
        output_dir=str(out),
        sources=["/path/to/1cv8:8.3"],
        languages=None,
        workers=1,
    )
    assert cmd_unpack_dir(args) == 0
    call_kw = mock_run.call_args[1]
    assert call_kw["source_dirs_with_versions"] == [("/path/to/1cv8", "8.3")]


@patch("onec_help.runtime.ingest.run_unpack_only")
def test_cmd_unpack_dir_sources_path_only(mock_run, tmp_path: Path) -> None:
    """cmd_unpack_dir with single path (no colon) uses path name as version."""
    mock_run.return_value = 1
    out = tmp_path / "out"
    out.mkdir()
    args = make_args(
        source_dir="",
        output_dir=str(out),
        sources=["/single/path"],
        languages=None,
        workers=1,
    )
    assert cmd_unpack_dir(args) == 0
    call_kw = mock_run.call_args[1]
    assert len(call_kw["source_dirs_with_versions"]) == 1
    assert call_kw["source_dirs_with_versions"][0][0] == "/single/path"


def test_cmd_unpack_dir_no_sources_error(tmp_path: Path) -> None:
    """When no sources and no HELP_SOURCE_BASE, cmd_unpack_dir returns 1."""
    args = make_args(
        source_dir="",
        output_dir=str(tmp_path / "out"),
        sources=None,
        languages=None,
        workers=1,
    )
    with patch.dict("os.environ", {}, clear=True):
        assert cmd_unpack_dir(args) == 1


@patch("onec_help.runtime.ingest.run_unpack_only")
def test_cmd_unpack_dir_success(mock_run, tmp_path: Path) -> None:
    mock_run.return_value = 2
    args = make_args(
        source_dir=str(tmp_path),
        output_dir=str(tmp_path / "out"),
        sources=None,
        languages="ru",
        workers=1,
        quiet=True,
    )
    assert cmd_unpack_dir(args) == 0
    mock_run.assert_called_once()


@patch("onec_help.runtime.ingest.run_unpack_sync")
def test_cmd_unpack_sync_success(mock_run, tmp_path: Path) -> None:
    """cmd_unpack_sync calls run_unpack_sync with correct output dir."""
    mock_run.return_value = 1
    out = tmp_path / "unpacked"
    args = make_args(
        source_dir=str(tmp_path),
        output_dir=str(out),
        sources=None,
        languages="ru",
        workers=1,
        quiet=True,
    )
    assert cmd_unpack_sync(args) == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["output_dir"] == out


@patch("onec_help.runtime.ingest.run_unpack_sync")
def test_cmd_unpack_sync_no_sources_error(mock_run) -> None:
    """cmd_unpack_sync returns 1 when no sources."""
    args = make_args(
        source_dir="",
        output_dir=None,
        sources=None,
        languages=None,
        workers=1,
        quiet=True,
    )
    with patch.dict("os.environ", {}, clear=True):
        assert cmd_unpack_sync(args) == 1
    mock_run.assert_not_called()


@patch("onec_help.search_store.indexer.build_index")
def test_cmd_build_index_incremental_no_bm25(mock_build, help_sample_dir: Path) -> None:
    """cmd_build_index passes incremental and no_bm25 to build_index."""
    mock_build.return_value = 3
    args = make_args(
        directory=str(help_sample_dir),
        docs_dir=None,
        incremental=True,
        no_bm25=True,
    )
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_build_index(args) == 0
    call_kw = mock_build.call_args[1]
    assert call_kw["incremental"] is True
    assert call_kw["bm25"] is False


def test_cmd_load_snippets_path_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    """cmd_load_snippets returns 1 when snippets_file path does not exist."""
    args = make_args(snippets_file="/nonexistent/snippets.json", from_project=False)
    with patch.dict("os.environ", {}, clear=True):
        assert cmd_load_snippets(args) == 1
    assert "not found" in capsys.readouterr().err


@patch("onec_help.interfaces.cli._build_snippets_sources", return_value=[])
def test_cmd_load_snippets_no_source_returns_zero(
    mock_build, capsys: pytest.CaptureFixture[str]
) -> None:
    """cmd_load_snippets returns 0 when no source and SNIPPETS_DIR not set."""
    args = make_args(snippets_file=None, from_project=False)
    with patch.dict("os.environ", {"SNIPPETS_DIR": "", "SNIPPETS_JSON_PATH": ""}, clear=False):
        assert cmd_load_snippets(args) == 0
    err = capsys.readouterr().err
    assert "SNIPPETS_DIR" in err or "No source" in err or "not found" in err


def test_cmd_load_standards_path_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    """cmd_load_standards returns 1 when standards_path does not exist."""
    args = make_args(standards_path="/nonexistent/standards")
    with patch.dict("os.environ", {"STANDARDS_REPOS": ""}, clear=False):
        assert cmd_load_standards(args) == 1
    err = capsys.readouterr().err
    assert "not found" in err or "path" in err.lower() or "Error:" in err


@patch("onec_help.knowledge.loaders.parse_fastcode.run_parse", return_value=0)
def test_cmd_parse_fastcode_pages_range(mock_run, tmp_path: Path) -> None:
    """cmd_parse_fastcode parses pages '1-3' as range."""
    args = make_args(pages="1-3", out=str(tmp_path / "out.json"), delay=0)
    assert cmd_parse_fastcode(args) == 0
    call_kw = mock_run.call_args[1]
    assert call_kw["pages"] == [1, 2, 3]


@patch("onec_help.knowledge.loaders.parse_helpf.run_parse", return_value=0)
def test_cmd_parse_helpf_pages_list(mock_run, tmp_path: Path) -> None:
    """cmd_parse_helpf parses pages '1,2,5' as list."""
    args = make_args(
        pages="1,2,5",
        out=str(tmp_path / "helpf.json"),
        source="faq",
        delay=0,
        max_items=0,
    )
    assert cmd_parse_helpf(args) == 0
    call_kw = mock_run.call_args[1]
    assert call_kw["pages"] == [1, 2, 5]


@patch("urllib.request.urlopen")
def test_cmd_qdrant_backup_fails(
    mock_urlopen, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """cmd_qdrant_backup returns 1 when API raises."""
    mock_urlopen.side_effect = OSError("Connection refused")
    args = make_args(output_dir=str(tmp_path))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_backup(args) == 1
    assert "Error:" in capsys.readouterr().err


def test_cmd_qdrant_restore_file_not_found(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """cmd_qdrant_restore returns 1 when file path does not exist."""
    args = make_args(file=str(tmp_path / "missing.snapshot"), backup_dir=str(tmp_path))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_restore(args) == 1
    assert "not found" in capsys.readouterr().err or "Error:" in capsys.readouterr().err


@patch("onec_help.interfaces.cli._clear_before_reinit", return_value=True)
@patch("onec_help.interfaces.cli.cmd_load_standards", return_value=0)
@patch("onec_help.interfaces.cli.cmd_load_snippets", return_value=0)
@patch("onec_help.interfaces.cli.cmd_ingest", return_value=0)
def test_cmd_reinit_force(
    mock_ingest, mock_snippets, mock_standards, mock_clear_before_reinit, tmp_path: Path
) -> None:
    """cmd_reinit with force calls _clear_before_reinit (Qdrant+cache) then init; never touch real data."""
    args = make_args(force=True)
    with patch.dict(
        "os.environ",
        {"HELP_SOURCE_BASE": str(tmp_path), "QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"},
        clear=False,
    ):
        rc = cmd_reinit(args)
    assert rc == 0
    mock_clear_before_reinit.assert_called_once()
    mock_ingest.assert_called()
    mock_snippets.assert_called()
    mock_standards.assert_called()


@patch("onec_help.interfaces.mcp_server.run_mcp")
def test_cmd_mcp_runtime_error_fastmcp(mock_run_mcp, capsys: pytest.CaptureFixture[str]) -> None:
    """cmd_mcp returns 1 when run_mcp raises RuntimeError mentioning fastmcp."""
    mock_run_mcp.side_effect = RuntimeError("fastmcp not installed")
    args = make_args(directory="data", transport="stdio")
    assert cmd_mcp(args) == 1
    assert "fastmcp" in capsys.readouterr().err.lower()


@patch("onec_help.runtime.ingest.run_ingest_from_unpacked")
def test_cmd_ingest_from_unpacked_success(mock_run, tmp_path: Path) -> None:
    """cmd_ingest_from_unpacked calls run_ingest_from_unpacked with correct dir."""
    mock_run.return_value = 10
    (tmp_path / "8.3").mkdir()
    (tmp_path / "8.3" / "1cv8_ru").mkdir()
    (tmp_path / "8.3" / "1cv8_ru" / "a.html").write_text("<html>")
    args = make_args(
        dir=str(tmp_path),
        recreate=False,
        quiet=True,
        embedding_batch_size=None,
        embedding_workers=None,
        bm25=False,
        no_bm25=False,
    )
    assert cmd_ingest_from_unpacked(args) == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["unpacked_base"] == tmp_path.resolve()


@patch("onec_help.runtime.ingest.run_ingest_from_unpacked")
def test_cmd_ingest_from_unpacked_dir_missing(mock_run) -> None:
    """cmd_ingest_from_unpacked returns 1 when unpacked dir does not exist."""
    args = make_args(dir="/nonexistent/unpacked", recreate=False, quiet=True)
    with patch.dict("os.environ", {}, clear=True):
        assert cmd_ingest_from_unpacked(args) == 1
    mock_run.assert_not_called()


@patch("onec_help.runtime.ingest.run_ingest")
def test_cmd_ingest_sources_file(mock_run, tmp_path: Path) -> None:
    mock_run.return_value = 3
    sf = tmp_path / "sources.txt"
    sf.write_text("/path/1:ver1\n/path/2:ver2\n", encoding="utf-8")
    args = make_args(
        sources=None,
        sources_file=str(sf),
        languages=None,
        temp_base=None,
        workers=1,
        max_tasks=None,
        quiet=True,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333", "INGEST_USE_TEMP": "1"},
        clear=False,
    ):
        assert cmd_ingest(args) == 0
    call_kw = mock_run.call_args[1]
    assert len(call_kw["source_dirs_with_versions"]) == 2


@patch("onec_help.runtime.ingest.run_ingest")
def test_cmd_ingest_sources_file_path_only(mock_run, tmp_path: Path) -> None:
    """sources_file with lines without colon uses path name as version."""
    mock_run.return_value = 1
    sf = tmp_path / "list.txt"
    sf.write_text("/only/path\n", encoding="utf-8")
    args = make_args(
        sources=None,
        sources_file=str(sf),
        languages=None,
        temp_base=None,
        workers=1,
        max_tasks=None,
        quiet=True,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333", "INGEST_USE_TEMP": "1"},
        clear=False,
    ):
        assert cmd_ingest(args) == 0
    call_kw = mock_run.call_args[1]
    assert len(call_kw["source_dirs_with_versions"]) == 1
    assert call_kw["source_dirs_with_versions"][0][0] == "/only/path"


@patch("onec_help.runtime.ingest.run_ingest_from_unpacked")
@patch("onec_help.runtime.ingest.run_unpack_sync")
def test_cmd_ingest_default_unpacked(mock_unpack, mock_from_unpacked, tmp_path: Path) -> None:
    """By default cmd_ingest runs unpack-sync to data/unpacked + ingest-from-unpacked."""
    mock_unpack.return_value = 1
    mock_from_unpacked.return_value = 10
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "1cv8_ru.hbk").write_bytes(b"x")
    args = make_args(
        sources=[str(tmp_path) + ":v"],
        sources_file=None,
        languages="ru",
        temp_base=None,
        workers=1,
        max_tasks=None,
        quiet=True,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {
            "QDRANT_HOST": "localhost",
            "QDRANT_PORT": "6333",
            "DATA_UNPACKED_DIR": str(tmp_path / "unpacked"),
        },
        clear=False,
    ):
        assert cmd_ingest(args) == 0
    mock_unpack.assert_called_once()
    mock_from_unpacked.assert_called_once()
    assert mock_from_unpacked.call_args[1]["unpacked_base"] == (tmp_path / "unpacked").resolve()


@patch("onec_help.runtime.ingest.run_ingest")
def test_cmd_ingest_use_temp(mock_run_ingest, tmp_path: Path) -> None:
    """When INGEST_USE_TEMP=1, cmd_ingest uses temp dir and run_ingest (no unpack_sync)."""
    mock_run_ingest.return_value = 5
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "1cv8_ru.hbk").write_bytes(b"x")
    args = make_args(
        sources=[str(tmp_path) + ":v"],
        sources_file=None,
        languages="ru",
        temp_base=None,
        workers=1,
        max_tasks=None,
        quiet=True,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {
            "QDRANT_HOST": "localhost",
            "QDRANT_PORT": "6333",
            "INGEST_USE_TEMP": "1",
        },
        clear=False,
    ):
        assert cmd_ingest(args) == 0
    mock_run_ingest.assert_called_once()


@patch("onec_help.runtime.ingest.run_ingest")
def test_cmd_ingest_exception(mock_run) -> None:
    mock_run.side_effect = RuntimeError("Qdrant down")
    args = make_args(
        sources=["/x:v"],
        sources_file=None,
        languages=None,
        temp_base=None,
        workers=1,
        max_tasks=None,
        quiet=True,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333", "INGEST_USE_TEMP": "1"},
        clear=False,
    ):
        assert cmd_ingest(args) == 1


@patch("onec_help.runtime.watchdog.run_watchdog")
def test_cmd_watchdog_success(mock_run_watchdog) -> None:
    """cmd_watchdog calls run_watchdog with poll/pending intervals and returns 0."""
    args = make_args(poll_interval=120, pending_interval=300)
    assert cmd_watchdog(args) == 0
    mock_run_watchdog.assert_called_once_with(
        poll_interval_sec=120,
        pending_interval_sec=300,
        once=False,
    )


@patch("onec_help.runtime.watchdog.run_watchdog")
def test_cmd_watchdog_once(mock_run_watchdog) -> None:
    """cmd_watchdog with once=True calls run_watchdog with once=True."""
    args = make_args(poll_interval=60, pending_interval=60, once=True)
    assert cmd_watchdog(args) == 0
    mock_run_watchdog.assert_called_once_with(
        poll_interval_sec=60,
        pending_interval_sec=60,
        once=True,
    )


@patch("onec_help.runtime.watchdog.run_watchdog")
def test_cmd_watchdog_exception(mock_run_watchdog) -> None:
    """cmd_watchdog returns 1 when run_watchdog raises."""
    mock_run_watchdog.side_effect = RuntimeError("watchdog error")
    args = make_args(poll_interval=60, pending_interval=60)
    assert cmd_watchdog(args) == 1


@patch("onec_help.runtime.redis_cache.require_runtime_redis")
def test_cmd_watchdog_requires_redis(mock_require) -> None:
    """cmd_watchdog fails fast when Redis is unavailable."""
    mock_require.side_effect = RuntimeError("Redis is required for watchdog.")
    args = make_args(poll_interval=60, pending_interval=60)
    assert cmd_watchdog(args) == 1


@patch("onec_help.runtime.watchdog.run_watchdog")
def test_cmd_watchdog_keyboard_interrupt(mock_run_watchdog) -> None:
    """cmd_watchdog returns 0 on KeyboardInterrupt (graceful exit)."""
    mock_run_watchdog.side_effect = KeyboardInterrupt
    args = make_args(poll_interval=60, pending_interval=60)
    assert cmd_watchdog(args) == 0


@patch("onec_help.interfaces.mcp_server.run_mcp")
def test_cmd_mcp_run_raises(mock_run_mcp) -> None:
    """When run_mcp raises (e.g. fastmcp required), cmd_mcp returns 1."""
    mock_run_mcp.side_effect = RuntimeError("fastmcp required: pip install fastmcp")
    args = make_args(directory="/tmp", transport=None, host=None, port=None, path=None)
    assert cmd_mcp(args) == 1


def test_cmd_load_snippets_file_not_found() -> None:
    """cmd_load_snippets returns 1 when path does not exist."""
    args = make_args(snippets_file="/nonexistent/snippets.json")
    assert cmd_load_snippets(args) == 1


def test_cmd_load_snippets_no_source(capsys) -> None:
    """cmd_load_snippets returns 0 with message when no path and no SNIPPETS_DIR."""
    # Unset defaults: env_config uses data/snippets when SNIPPETS_DIR is empty
    with (
        patch.dict("os.environ", {"SNIPPETS_JSON_PATH": "", "SNIPPETS_DIR": ""}, clear=False),
        patch("onec_help.shared.env_config.get_snippets_dir", return_value=""),
        patch("onec_help.shared.env_config.get_snippets_json_path", return_value=""),
    ):
        args = make_args(snippets_file=None, from_project=False)
        assert cmd_load_snippets(args) == 0
    out = capsys.readouterr().err
    assert "No source" in out or "examples only" in out


def test_cmd_load_snippets_invalid_json(tmp_path: Path) -> None:
    """cmd_load_snippets returns 1 when JSON is invalid."""
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    args = make_args(snippets_file=str(bad))
    assert cmd_load_snippets(args) == 1


@patch("onec_help.runtime.redis_cache.require_runtime_redis")
def test_cmd_load_snippets_requires_redis(mock_require, tmp_path: Path) -> None:
    """cmd_load_snippets fails fast when Redis is unavailable."""
    mock_require.side_effect = RuntimeError("Redis is required for load-snippets.")
    snippet_file = tmp_path / "snippets.json"
    snippet_file.write_text("[]", encoding="utf-8")
    args = make_args(snippets_file=str(snippet_file))
    assert cmd_load_snippets(args) == 1


def test_cmd_load_snippets_not_array(tmp_path: Path) -> None:
    """cmd_load_snippets returns 1 when JSON is not an array."""
    bad = tmp_path / "bad.json"
    bad.write_text('{"title": "x"}')
    args = make_args(snippets_file=str(bad))
    assert cmd_load_snippets(args) == 1


@patch("onec_help.search_store.embedding.is_embedding_available", return_value=True)
@patch("onec_help.interfaces.cli._get_memory_store")
def test_cmd_load_snippets_success(mock_get_store, _mock_embed_avail, tmp_path: Path) -> None:
    """cmd_load_snippets loads snippets and prints count."""
    snippet_file = tmp_path / "snippets.json"
    snippet_file.write_text(
        '[{"title": "Test", "description": "desc", "code_snippet": "Сообщить(1);"}]',
        encoding="utf-8",
    )
    mock_store = MagicMock()
    mock_store.upsert_curated_snippets.return_value = 1
    mock_get_store.return_value = mock_store
    args = make_args(snippets_file=str(snippet_file))
    assert cmd_load_snippets(args) == 0
    mock_store.upsert_curated_snippets.assert_called_once()
    call_args = mock_store.upsert_curated_snippets.call_args[0][0]
    assert len(call_args) == 1
    assert call_args[0]["title"] == "Test"


def test_main_load_snippets(tmp_path: Path) -> None:
    """main() parses load-snippets and invokes cmd_load_snippets."""
    snippet_file = tmp_path / "snippets.json"
    snippet_file.write_text('[{"title": "X", "code_snippet": "x"}]', encoding="utf-8")
    with (
        patch("onec_help.search_store.embedding.is_embedding_available", return_value=True),
        patch("onec_help.interfaces.cli._get_memory_store") as mock_get,
    ):
        mock_store = MagicMock()
        mock_store.upsert_curated_snippets.return_value = 1
        mock_get.return_value = mock_store
        with patch("sys.argv", ["onec_help", "load-snippets", str(snippet_file)]):
            assert main() == 0
        mock_store.upsert_curated_snippets.assert_called_once()


def test_cmd_load_snippets_exception(tmp_path: Path) -> None:
    """cmd_load_snippets returns 1 when get_memory_store raises."""
    snippet_file = tmp_path / "snippets.json"
    snippet_file.write_text('[{"title": "X", "code_snippet": "x"}]', encoding="utf-8")
    with patch("onec_help.interfaces.cli._get_memory_store", side_effect=RuntimeError("no qdrant")):
        args = make_args(snippets_file=str(snippet_file))
        assert cmd_load_snippets(args) == 1


@patch("onec_help.search_store.embedding.is_embedding_available", return_value=True)
@patch("onec_help.interfaces.cli._get_memory_store")
def test_cmd_load_snippets_from_folder(mock_get_store, _mock_embed_avail, tmp_path: Path) -> None:
    """cmd_load_snippets loads from folder (*.bsl, *.1c, *.json) when path is directory."""
    (tmp_path / "example.bsl").write_text("Сообщить(1);", encoding="utf-8")
    (tmp_path / "other.1c").write_text("Возврат Истина;", encoding="utf-8")
    (tmp_path / "extra.json").write_text(
        '[{"title":"FromJSON","description":"","code_snippet":"Возврат;"}]', encoding="utf-8"
    )
    mock_store = MagicMock()
    mock_store.upsert_curated_snippets.return_value = 3
    mock_get_store.return_value = mock_store
    args = make_args(snippets_file=str(tmp_path))
    assert cmd_load_snippets(args) == 0
    mock_store.upsert_curated_snippets.assert_called_once()
    items = mock_store.upsert_curated_snippets.call_args[0][0]
    assert len(items) == 3
    titles = {it["title"] for it in items}
    assert titles == {"example", "other", "FromJSON"}


@patch("onec_help.search_store.embedding.is_embedding_available", return_value=True)
@patch("onec_help.interfaces.cli._get_memory_store")
def test_cmd_load_snippets_type_split(mock_get_store, _mock_embed_avail, tmp_path: Path) -> None:
    """cmd_load_snippets splits items by type into snippets and community_help domains."""
    mixed = tmp_path / "mixed.json"
    mixed.write_text(
        json.dumps(
            [
                {
                    "title": "Snippet1",
                    "code_snippet": "Процедура Х()\nКонецПроцедуры",
                    "type": "snippet",
                },
                {
                    "title": "Ref1",
                    "description": "Long text " * 50,
                    "code_snippet": "x",
                    "type": "reference",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    mock_store = MagicMock()
    mock_store.upsert_curated_snippets.return_value = 1
    mock_get_store.return_value = mock_store
    args = make_args(snippets_file=str(mixed))
    assert cmd_load_snippets(args) == 0
    assert mock_store.upsert_curated_snippets.call_count == 2
    calls = mock_store.upsert_curated_snippets.call_args_list
    domains = [c[1]["domain"] for c in calls]
    assert "snippets" in domains
    assert "community_help" in domains


@patch("urllib.request.urlopen")
def test_cmd_qdrant_backup_success(mock_urlopen, tmp_path: Path) -> None:
    """cmd_qdrant_backup creates snapshot and saves to output dir for all 3 collections."""
    import urllib.error

    def make_ctx_mock(data: bytes) -> MagicMock:
        m = MagicMock()
        m.read.return_value = data
        m.__enter__ = lambda self: self
        m.__exit__ = lambda *a: None
        return m

    # GET /collections → returns onec_help, onec_help_memory, onec_config_metadata
    list_resp = make_ctx_mock(
        b'{"result":{"collections":[{"name":"onec_help"},{"name":"onec_help_memory"},{"name":"onec_config_metadata"}]}}'
    )
    # onec_help: success (create + download)
    create_resp = make_ctx_mock(b'{"result":{"name":"abc-123.snapshot"}}')
    download_resp = make_ctx_mock(b"snapshot-data")
    # onec_help_memory and onec_config_metadata: not present → URLError on create
    mock_urlopen.side_effect = [
        list_resp,
        create_resp,
        download_resp,
        urllib.error.URLError("not found"),
        urllib.error.URLError("not found"),
    ]

    out_dir = tmp_path / "backup"
    args = make_args(output_dir=str(out_dir))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_backup(args) == 0

    assert mock_urlopen.call_count == 5
    snaps = list(out_dir.glob("onec_help-*.snapshot"))
    assert len(snaps) == 1
    assert snaps[0].read_bytes() == b"snapshot-data"


@patch("urllib.request.urlopen")
def test_cmd_qdrant_backup_no_name_in_response(mock_urlopen, tmp_path: Path) -> None:
    """cmd_qdrant_backup returns 1 when response has no snapshot name."""
    create_resp = MagicMock()
    create_resp.read.return_value = b'{"result":{}}'
    mock_urlopen.return_value = create_resp

    args = make_args(output_dir=str(tmp_path / "backup"))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_backup(args) == 1


@patch("urllib.request.urlopen")
def test_cmd_qdrant_backup_http_error(mock_urlopen, tmp_path: Path) -> None:
    """cmd_qdrant_backup returns 1 on HTTP/network error."""
    import urllib.error

    mock_urlopen.side_effect = urllib.error.URLError("connection refused")

    args = make_args(output_dir=str(tmp_path / "backup"))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_backup(args) == 1


@patch("urllib.request.urlopen")
def test_cmd_qdrant_restore_success(mock_urlopen, tmp_path: Path) -> None:
    """cmd_qdrant_restore restores from snapshot file."""
    snap = tmp_path / "onec_help-20260302-120000.snapshot"
    snap.write_bytes(b"snapshot-content")

    resp = MagicMock()
    resp.read.return_value = b'{"status":"ok"}'
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: None
    mock_urlopen.return_value = resp

    args = make_args(backup_dir=str(tmp_path), file=str(snap))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_restore(args) == 0

    mock_urlopen.assert_called_once()


@patch("urllib.request.urlopen")
def test_cmd_qdrant_restore_latest_from_dir(mock_urlopen, tmp_path: Path) -> None:
    """cmd_qdrant_restore uses latest snapshot when file not specified."""
    (tmp_path / "onec_help-20260301-100000.snapshot").write_bytes(b"old")
    (tmp_path / "onec_help-20260302-120000.snapshot").write_bytes(b"new")

    resp = MagicMock()
    resp.read.return_value = b'{"status":"ok"}'
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: None
    mock_urlopen.return_value = resp

    args = make_args(backup_dir=str(tmp_path), file=None)
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_restore(args) == 0

    # Should use latest (20260302)
    call_data = mock_urlopen.call_args[0][0].data
    assert b"new" in call_data
    assert b"old" not in call_data


def test_cmd_qdrant_restore_no_snapshots(tmp_path: Path) -> None:
    """cmd_qdrant_restore returns 1 when backup dir has no snapshots."""
    args = make_args(backup_dir=str(tmp_path), file=None)
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_restore(args) == 1


@patch("urllib.request.urlopen")
def test_cmd_qdrant_restore_http_error(mock_urlopen, tmp_path: Path) -> None:
    """cmd_qdrant_restore returns 1 on HTTP/network error."""
    import urllib.error

    snap = tmp_path / "onec_help-20260302.snapshot"
    snap.write_bytes(b"data")
    mock_urlopen.side_effect = urllib.error.URLError("connection refused")

    args = make_args(backup_dir=str(tmp_path), file=str(snap))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_restore(args) == 1


@patch("onec_help.knowledge.loaders.parse_fastcode.run_parse")
def test_cmd_parse_fastcode(mock_run, tmp_path: Path) -> None:
    """cmd_parse_fastcode delegates to run_parse with correct args."""
    mock_run.return_value = 0
    args = SimpleNamespace(
        out=str(tmp_path / "out.json"), pages="1-3", delay=0.5, no_fetch_detail=False
    )
    assert cmd_parse_fastcode(args) == 0
    mock_run.assert_called_once()
    call_kw = mock_run.call_args[1]
    assert list(call_kw["out"].parts)[-1] == "out.json"
    assert call_kw["pages"] == [1, 2, 3]
    assert call_kw["fetch_detail"] is True


@patch("onec_help.knowledge.loaders.parse_fastcode.run_parse")
def test_cmd_parse_fastcode_auto_pages(mock_run, tmp_path: Path) -> None:
    """cmd_parse_fastcode with pages=auto passes None."""
    mock_run.return_value = 0
    args = SimpleNamespace(
        out=str(tmp_path / "out.json"), pages="auto", delay=1.0, no_fetch_detail=True
    )
    assert cmd_parse_fastcode(args) == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["pages"] is None


@patch("onec_help.knowledge.loaders.parse_helpf.run_parse")
def test_cmd_parse_helpf(mock_run, tmp_path: Path) -> None:
    """cmd_parse_helpf delegates to run_parse."""
    mock_run.return_value = 0
    args = SimpleNamespace(
        out=str(tmp_path / "helpf.json"),
        pages="1",
        source="faq",
        max_items=10,
        delay=1.0,
        no_fetch_detail=True,
    )
    assert cmd_parse_helpf(args) == 0
    mock_run.assert_called_once()
    call_kw = mock_run.call_args[1]
    assert call_kw["source"] == "faq"
    assert call_kw["max_items"] == 10


def test_cmd_load_standards_no_source(capsys) -> None:
    """cmd_load_standards returns 0 when no path and no STANDARDS_* (default disabled)."""
    import onec_help.interfaces.cli as cli_mod

    args = make_args(standards_path=None)
    # Unset defaults: env_config uses data/standards when STANDARDS_DIR is empty
    with (
        patch.dict(
            "os.environ",
            {"STANDARDS_DIR": "", "STANDARDS_REPOS": ""},
            clear=False,
        ),
        patch.object(cli_mod, "_DEFAULT_STANDARDS_REPOS", ""),
        patch("onec_help.shared.env_config.get_standards_dir", return_value=""),
        patch("onec_help.shared.env_config.get_standards_repos", return_value=""),
    ):
        assert cmd_load_standards(args) == 0
    err = capsys.readouterr().err
    assert "No source" in err and ("STANDARDS_REPOS" in err or "STANDARDS_DIR" in err)


@patch("onec_help.search_store.embedding.is_embedding_available", return_value=True)
@patch("onec_help.interfaces.cli._get_memory_store")
def test_cmd_load_standards_success(mock_get_store, _mock_embed_avail, tmp_path: Path) -> None:
    """cmd_load_standards loads markdown and upserts with domain=standards."""
    (tmp_path / "rule.md").write_text("# Проверка\n\nОписание правила.", encoding="utf-8")
    mock_store = MagicMock()
    mock_store.upsert_curated_snippets.return_value = 1
    mock_get_store.return_value = mock_store
    args = make_args(standards_path=str(tmp_path))
    assert cmd_load_standards(args) == 0
    mock_store.upsert_curated_snippets.assert_called_once()
    call_kw = mock_store.upsert_curated_snippets.call_args[1]
    assert call_kw.get("domain") == "standards"


@patch("onec_help.search_store.embedding.is_embedding_available", return_value=True)
@patch("onec_help.interfaces.cli._get_memory_store")
@patch("onec_help.knowledge.loaders.standards_loader.fetch_repo_archive")
def test_cmd_load_standards_from_repo(
    mock_fetch, mock_get_store, _mock_embed_avail, tmp_path: Path
) -> None:
    """cmd_load_standards fetches from STANDARDS_REPOS (single repo) when no path given.
    Redirect copy destination to tmp_path to avoid writing to data/standards (pytest-* pollution)."""
    fetch_dir = tmp_path / "fetched"
    fetch_dir.mkdir()
    (fetch_dir / "fetched.md").write_text("# Fetched rule\n\nContent.", encoding="utf-8")
    mock_fetch.return_value = (fetch_dir, Path("/tmp/nonexistent_standards_xxx"))
    mock_store = MagicMock()
    mock_store.upsert_curated_snippets.return_value = 1
    mock_get_store.return_value = mock_store
    standards_out = tmp_path / "standards_out"
    standards_out.mkdir()
    args = make_args(standards_path=None)
    original_resolve = Path.resolve

    def resolve_redirect(self: Path) -> Path:
        # Redirect data/standards to tmp to avoid polluting repo (pytest-* dirs)
        if len(self.parts) == 2 and self.parts[0] == "data" and self.parts[1] == "standards":
            return standards_out.resolve()
        return original_resolve(self)

    with (
        patch.dict(
            "os.environ",
            {
                "STANDARDS_DIR": "",
                "STANDARDS_REPOS": "1C-Company/v8-code-style",
            },
        ),
        patch.object(Path, "resolve", resolve_redirect),
    ):
        assert cmd_load_standards(args) == 0
    mock_fetch.assert_called_once()
    mock_store.upsert_curated_snippets.assert_called_once()


@patch("onec_help.search_store.embedding.is_embedding_available", return_value=True)
@patch("onec_help.interfaces.cli._get_memory_store")
@patch("onec_help.knowledge.loaders.standards_loader.fetch_repo_archive")
def test_cmd_load_standards_from_repos(
    mock_fetch, mock_get_store, _mock_embed_avail, tmp_path: Path
) -> None:
    """cmd_load_standards fetches from STANDARDS_REPOS (multiple repos) when set.
    Redirect copy destination to tmp_path to avoid writing to data/standards."""
    fetch1 = tmp_path / "repo1"
    fetch2 = tmp_path / "repo2"
    fetch1.mkdir()
    fetch2.mkdir()
    (fetch1 / "a.md").write_text("# A\n\nFrom first.", encoding="utf-8")
    (fetch2 / "b.md").write_text("# B\n\nFrom second.", encoding="utf-8")
    mock_fetch.side_effect = [
        (fetch1, Path("/tmp/tmp1")),
        (fetch2, Path("/tmp/tmp2")),
    ]
    mock_store = MagicMock()
    mock_store.upsert_curated_snippets.return_value = 2
    mock_get_store.return_value = mock_store
    standards_out = tmp_path / "standards_out"
    standards_out.mkdir()
    args = make_args(standards_path=None)
    original_resolve = Path.resolve

    def resolve_redirect(self: Path) -> Path:
        if len(self.parts) == 2 and self.parts[0] == "data" and self.parts[1] == "standards":
            return standards_out.resolve()
        return original_resolve(self)

    with (
        patch.dict(
            "os.environ",
            {
                "STANDARDS_DIR": "",
                "STANDARDS_REPOS": "1C-Company/v8-code-style:master,zeegin/v8std:main",
            },
        ),
        patch.object(Path, "resolve", resolve_redirect),
    ):
        assert cmd_load_standards(args) == 0
    assert mock_fetch.call_count == 2
    mock_store.upsert_curated_snippets.assert_called_once()


@patch("onec_help.runtime.dashboard_data.get_dashboard_data")
def test_main_dashboard(mock_get_data) -> None:
    """main() parses argv and invokes cmd_dashboard."""
    mock_get_data.return_value = _minimal_dashboard_data(
        collections=[{"name": "onec_help", "points_count": 10}],
    )
    with patch("sys.argv", ["onec_help", "dashboard", "--once"]):
        from onec_help.interfaces.cli import main

        assert main() == 0
    mock_get_data.assert_called()


@patch("onec_help.knowledge.loaders.parse_fastcode.run_parse")
def test_main_parse_fastcode(mock_run, tmp_path: Path) -> None:
    """main() with parse-fastcode invokes run_parse."""
    mock_run.return_value = 0
    out = tmp_path / "fc.json"
    with patch("sys.argv", ["onec_help", "parse-fastcode", "--out", str(out), "--pages", "1"]):
        assert main() == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["out"] == out


@patch("onec_help.knowledge.loaders.parse_helpf.run_parse")
def test_main_parse_helpf(mock_run, tmp_path: Path) -> None:
    """main() with parse-helpf invokes run_parse."""
    mock_run.return_value = 0
    out = tmp_path / "helpf.json"
    with patch(
        "sys.argv",
        ["onec_help", "parse-helpf", "--out", str(out), "--source", "faq", "--pages", "1"],
    ):
        assert main() == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["source"] == "faq"


def _minimal_dashboard_data(**overrides):
    """Minimal get_dashboard_data() shape for tests."""
    data = {
        "ingest": None,
        "ingest_last_run": None,
        "failed_tasks": [],
        "index_status": {},
        "collections": [],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "storage_path_mb": None,
    }
    data.update(overrides)
    return data


@patch("onec_help.knowledge.metadata_graph.build_metadata_graph_from_crawl", return_value=1)
@patch("onec_help.search_store.indexer.add_bm25_to_collection", return_value=1)
@patch("onec_help.search_store.embedding.is_embedding_available", return_value=True)
@patch("onec_help.knowledge.config_crawler.crawl_config")
def test_cmd_build_metadata_graph_success(
    mock_crawl, _mock_embed_avail, mock_add_bm25, mock_build, tmp_path: Path
) -> None:
    """cmd_build_metadata_graph calls crawl_config and metadata_graph.build_metadata_graph_from_crawl."""
    from onec_help.knowledge.config_crawler import ConfigObject, CrawlResult

    crawl = CrawlResult(
        root_dir=tmp_path,
        config_name="Cfg",
        config_version="1.0.0.0",
        platform_version=None,
        objects=[
            ConfigObject(
                id="Document/Test",
                object_type="Document",
                name="Test",
            )
        ],
        relations=[],
    )
    mock_crawl.return_value = crawl
    args = make_args(source_dir=str(tmp_path), recreate=True)
    with patch.dict(
        "os.environ",
        {
            "QDRANT_HOST": "localhost",
            "QDRANT_PORT": "6333",
        },
        clear=False,
    ):
        with patch("onec_help.knowledge.config_crawler.find_config_roots", return_value=[tmp_path]):
            assert cmd_build_metadata_graph(args) == 0
    mock_crawl.assert_called_once()
    mock_build.assert_called_once()
    mock_add_bm25.assert_called_once()


def test_cmd_build_metadata_graph_no_source_dir_returns_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """cmd_build_metadata_graph returns 1 when no source_dir and get_config_source_dir returns empty."""
    args = make_args(source_dir=None, recreate=True)
    with patch("onec_help.interfaces.cli.env_config.get_config_source_dir", return_value=""):
        assert cmd_build_metadata_graph(args) == 1
    err = capsys.readouterr().err
    assert "configuration source dir not set" in err or "Pass path" in err


@patch("onec_help.runtime.dashboard_data.get_dashboard_data")
def test_cmd_dashboard_not_exists(mock_get_data, capsys: pytest.CaptureFixture[str]) -> None:
    """dashboard with no index still renders (No collections, empty tasks) and returns 0."""
    mock_get_data.return_value = _minimal_dashboard_data()
    assert cmd_dashboard(make_args(once=True)) == 0
    out = capsys.readouterr().out
    assert "Tasks" in out or "Ingest" in out  # dashboard rendered


@patch("onec_help.runtime.dashboard_data.get_dashboard_data")
def test_cmd_dashboard_error(mock_get_data, capsys: pytest.CaptureFixture[str]) -> None:
    """dashboard with index_status error returns 1 and prints error."""
    mock_get_data.return_value = _minimal_dashboard_data(
        index_status={"error": "connection refused"},
    )
    assert cmd_dashboard(make_args(once=True)) == 1
    err = capsys.readouterr().err
    assert "connection refused" in err


def test_build_snippets_sources_from_project(tmp_path: Path) -> None:
    """_build_snippets_sources with from_project adds folder."""
    (tmp_path / "a").mkdir()
    args = make_args(from_project=str(tmp_path), snippets_file=None)
    with patch.dict("os.environ", {"SNIPPETS_DIR": "", "SNIPPETS_JSON_PATH": ""}, clear=False):
        sources = _build_snippets_sources(args)
    assert len(sources) == 1
    assert sources[0][1] == "folder"


def test_build_snippets_sources_json_file(tmp_path: Path) -> None:
    """_build_snippets_sources with snippets_file path to file adds json."""
    j = tmp_path / "s.json"
    j.write_text("[]")
    args = make_args(snippets_file=str(j), from_project=None)
    with patch.dict("os.environ", {"SNIPPETS_DIR": "", "SNIPPETS_JSON_PATH": ""}, clear=False):
        sources = _build_snippets_sources(args)
    assert len(sources) >= 1
    assert any(s[1] == "json" for s in sources)


def test_build_snippets_sources_snippets_dir(tmp_path: Path) -> None:
    """_build_snippets_sources with SNIPPETS_DIR adds dir and jsons."""
    (tmp_path / "x.json").write_text("[]")
    args = make_args(snippets_file=None, from_project=None)
    with patch.dict(
        "os.environ", {"SNIPPETS_DIR": str(tmp_path), "SNIPPETS_JSON_PATH": ""}, clear=False
    ):
        sources = _build_snippets_sources(args)
    assert any(s[1] == "folder" for s in sources)
    assert any(s[1] == "json" for s in sources)


@patch("onec_help.runtime.dashboard_data.get_dashboard_data")
def test_cmd_dashboard_once_returns_zero_and_prints(
    mock_get_data, capsys: pytest.CaptureFixture[str]
) -> None:
    """cmd_dashboard --once prints dashboard and returns 0."""
    mock_get_data.return_value = _minimal_dashboard_data(
        collections=[{"name": "onec_help", "points_count": 10}],
    )
    args = make_args(once=True, interval=3)
    assert cmd_dashboard(args) == 0
    out = capsys.readouterr().out
    assert "Tasks" in out
    assert "Errors" in out or "Database" in out


def test_cmd_dashboard_without_rich_returns_one(capsys: pytest.CaptureFixture[str]) -> None:
    """When rich cannot be imported, cmd_dashboard returns 1 and prints install message."""
    real_import = __import__

    def mock_import(name, *args, **kwargs):
        if name == "rich.console" or name == "rich.live":
            raise ImportError("No module named 'rich'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        args = make_args(once=True)
        assert cmd_dashboard(args) == 1
    err = capsys.readouterr().err
    assert "rich" in err.lower()


@patch("onec_help.interfaces.cli.cmd_load_standards", return_value=0)
@patch("onec_help.interfaces.cli.cmd_load_snippets", return_value=0)
@patch("onec_help.interfaces.cli.cmd_ingest", return_value=0)
def test_cmd_init_runs_three_tasks(
    mock_ingest,
    mock_snippets,
    mock_standards,
) -> None:
    """cmd_init runs ingest, load_snippets, load_standards in parallel; returns 0 when all succeed."""
    args = make_args()
    assert cmd_init(args) == 0
    assert mock_ingest.call_count == 1
    assert mock_snippets.call_count == 1
    assert mock_standards.call_count == 1


@patch("onec_help.interfaces.cli.cmd_init", return_value=0)
@patch("onec_help.interfaces.cli._collection_has_data", return_value=True)
def test_cmd_reinit_skips_wipe_when_has_data_no_force(
    mock_has_data,
    mock_init,
) -> None:
    """cmd_reinit without --force when collection has data skips wipe and calls cmd_init."""
    args = make_args(force=False)
    assert cmd_reinit(args) == 0
    mock_init.assert_called_once()
    mock_has_data.assert_called()


@patch("onec_help.interfaces.cli.cmd_load_standards", return_value=0)
@patch("onec_help.interfaces.cli.cmd_load_snippets", return_value=0)
@patch("onec_help.interfaces.cli.cmd_ingest", return_value=1)
def test_cmd_init_returns_one_when_any_task_fails(
    mock_ingest,
    mock_snippets,
    mock_standards,
) -> None:
    """cmd_init returns 1 when any of ingest/snippets/standards returns non-zero."""
    args = make_args()
    assert cmd_init(args) == 1


@patch("onec_help.interfaces.cli.cmd_load_standards", return_value=0)
@patch("onec_help.interfaces.cli.cmd_load_snippets", return_value=0)
@patch("onec_help.interfaces.cli.cmd_ingest", return_value=0)
@patch("onec_help.interfaces.cli._clear_before_reinit")
@patch("onec_help.interfaces.cli._collection_has_data", return_value=False)
def test_cmd_reinit_force_clears_and_runs_tasks(
    mock_has_data,
    mock_clear,
    mock_ingest,
    mock_snippets,
    mock_standards,
) -> None:
    """cmd_reinit with --force calls _clear_before_reinit then runs ingest/snippets/standards."""
    args = make_args(force=True)
    assert cmd_reinit(args) == 0
    mock_clear.assert_called_once()
    assert mock_ingest.call_count == 1
    assert mock_snippets.call_count == 1
    assert mock_standards.call_count == 1
