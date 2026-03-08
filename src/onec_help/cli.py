"""CLI: unpack, build-docs, build-index, mcp."""

import argparse
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import env_config


def _make_args(**kwargs: Any) -> argparse.Namespace:
    """Build argparse-like namespace for cmd_* calls."""
    return argparse.Namespace(**kwargs)


def _env_path(name: str, default=None):
    v = os.environ.get(name)
    if v:
        return v
    return default


def _load_operation_running_path(name: str) -> Path:
    """Path to marker file so dashboard can show 'Standards/Snippets: loading…'."""
    from .ingest import _ingest_cache_path

    return Path(_ingest_cache_path()).parent / f"load_{name}.running"


def _load_operation_status_path(name: str) -> Path:
    """Path to status JSON (loaded/total pts) for dashboard progress."""
    return _load_operation_running_path(name).with_suffix(".status.json")


def cmd_unpack(args: argparse.Namespace) -> int:
    """Unpack .hbk with 7z."""
    from .unpack import unpack_hbk

    try:
        unpack_hbk(args.archive, args.output_dir)
        print(f"Unpacked to {args.output_dir}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Run: python -m onec_help unpack-diag <file> -o /tmp/out", file=sys.stderr)
        return 1


def cmd_unpack_diag(args: argparse.Namespace) -> int:
    """Diagnose unpack failure: try each method and print results."""
    from .unpack import unpack_diag

    try:
        unpack_diag(args.archive, args.output_dir or "/tmp/unpack_diag")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_build_docs(args: argparse.Namespace) -> int:
    """Generate Markdown from HTML in project dir."""
    from .html2md import build_docs

    out = args.output or Path(args.project_dir) / "docs_md"
    out = Path(out)
    try:
        created = build_docs(args.project_dir, out)
        print(f"Created {len(created)} .md files in {out}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_build_index(args: argparse.Namespace) -> int:
    """Build Qdrant index from Markdown (or HTML) in directory."""
    from .indexer import build_index

    docs_dir = args.docs_dir or args.directory
    try:
        count = build_index(
            docs_dir=Path(docs_dir),
            qdrant_host=env_config.get_qdrant_host(),
            qdrant_port=env_config.get_qdrant_port(),
            collection=env_config.get_qdrant_collection(),
            incremental=getattr(args, "incremental", False),
            embedding_batch_size=getattr(args, "embedding_batch_size", None),
            embedding_workers=getattr(args, "embedding_workers", None),
            bm25=not getattr(args, "no_bm25", False),
        )
        print(f"Indexed {count} chunks")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_add_bm25(args: argparse.Namespace) -> int:
    """Add BM25 sparse vectors to all collections that lack it (no re-ingest, no re-embedding)."""
    from .indexer import add_bm25_to_all_collections

    try:
        result = add_bm25_to_all_collections(
            qdrant_host=env_config.get_qdrant_host(),
            qdrant_port=env_config.get_qdrant_port(),
            batch_size=200,
            verbose=True,
        )
        for coll, count in result.items():
            print(f"{coll}: migrated {count} points with BM25")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _categorize_error(err: str) -> str:
    """Categorize error: unpack|embed|index|build|other."""
    e = (err or "").lower()
    if any(x in e for x in ["unpack", "7z", "unzip", "all unpack methods failed", "no such file"]):
        return "unpack"
    if any(x in e for x in ["embed", "api", "429", "timeout", "connection", "placeholder"]):
        return "embed"
    if any(x in e for x in ["qdrant", "upsert", "collection", "vector"]):
        return "index"
    if any(x in e for x in ["build", "html", "markdown", "parse"]):
        return "build"
    return "other"


def _short_error(err: str, max_len: int = 40) -> str:
    """Compact error message for display."""
    e = (err or "").strip().split("\n")[0]
    if "All unpack methods failed" in e:
        return "unpack failed"
    if "No such file" in e and "unzip" in e:
        return "unzip not found"
    if "7z" in e or "invalid archive" in e:
        return "7z/invalid archive"
    if "timeout" in e.lower():
        return "timeout"
    if "429" in e or "rate limit" in e.lower():
        return "rate limit"
    if len(e) > max_len:
        return e[: max_len - 2] + "…"
    return e


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Print dashboard (Tasks, Errors, Database). --once: one frame; else Live refresh.
    Database (Qdrant) and tasks are re-fetched each refresh from env QDRANT_HOST/QDRANT_PORT."""
    import time

    from .dashboard_data import get_dashboard_data
    from .dashboard_render import render_dashboard

    once = getattr(args, "once", False)
    interval = max(0.5, float(getattr(args, "interval", 1.5)))
    qdrant_host = env_config.get_qdrant_host()
    qdrant_port = env_config.get_qdrant_port()

    try:
        from rich.console import Console
        from rich.live import Live
    except ImportError:
        print("Install rich: pip install rich", file=sys.stderr)
        return 1

    data = get_dashboard_data(qdrant_host=qdrant_host, qdrant_port=qdrant_port)
    idx_err = (data.get("index_status") or {}).get("error")
    if idx_err:
        print(f"Error: {idx_err}", file=sys.stderr)
        return 1

    if once:
        console = Console()
        console.print(render_dashboard(data))
        return 0

    def _gen():
        return render_dashboard(
            get_dashboard_data(qdrant_host=qdrant_host, qdrant_port=qdrant_port)
        )

    console = Console()
    try:
        with Live(
            _gen(), console=console, refresh_per_second=1 / interval, transient=False
        ) as live:
            while True:
                time.sleep(interval)
                live.update(_gen())
    except KeyboardInterrupt:
        pass
    return 0


def cmd_unpack_dir(args: argparse.Namespace) -> int:
    """Unpack all .hbk from source dir(s) into output_dir (no indexing)."""
    from pathlib import Path

    from .ingest import (
        discover_version_dirs,
        parse_languages_env,
        parse_source_dirs_env,
        run_unpack_only,
    )

    sources: list[tuple[str, str]] = []
    if getattr(args, "sources", None):
        for s in args.sources:
            s = s.strip()
            if ":" in s:
                p, v = s.split(":", 1)
                sources.append((p.strip(), v.strip()))
            else:
                sources.append((s, Path(s).name or "default"))
    if not sources:
        base = env_config.get_help_source_base()
        if base:
            discovered = discover_version_dirs(base)
            sources = [(str(p), v) for p, v in discovered]
        if not sources:
            sources = parse_source_dirs_env(env_config.get_help_source_dirs())
    if not sources:
        # Single directory as version
        src = getattr(args, "source_dir", None) or ""
        if src and Path(src).is_dir():
            sources = [(src, Path(src).name or "default")]
    if not sources:
        print(
            "Error: no source directories. Set HELP_SOURCE_BASE or use --sources or pass source_dir",
            file=sys.stderr,
        )
        return 1
    raw_lang = getattr(args, "languages", None)
    languages = parse_languages_env(
        raw_lang if raw_lang is not None and raw_lang.strip() else env_config.get_help_languages()
    )
    out = Path(args.output_dir or "./unpacked").resolve()
    try:
        n = run_unpack_only(
            source_dirs_with_versions=sources,
            output_dir=out,
            languages=languages,
            max_workers=getattr(args, "workers", 4),
            verbose=not getattr(args, "quiet", False),
        )
        print(f"Unpacked {n} archive(s) to {out}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_unpack_sync(args: argparse.Namespace) -> int:
    """Unpack .hbk to data/unpacked with .hbk_info.json, skip unchanged by hash."""
    from pathlib import Path

    from .ingest import (
        discover_version_dirs,
        parse_languages_env,
        parse_source_dirs_env,
        run_unpack_sync,
    )

    sources: list[tuple[str, str]] = []
    if getattr(args, "sources", None):
        for s in args.sources:
            s = s.strip()
            if ":" in s:
                p, v = s.split(":", 1)
                sources.append((p.strip(), v.strip()))
            else:
                sources.append((s, Path(s).name or "default"))
    if not sources:
        base = env_config.get_help_source_base()
        if base:
            discovered = discover_version_dirs(base)
            sources = [(str(p), v) for p, v in discovered]
        if not sources:
            sources = parse_source_dirs_env(env_config.get_help_source_dirs())
    if not sources:
        src = getattr(args, "source_dir", None) or ""
        if src and Path(src).is_dir():
            discovered = discover_version_dirs(src)
            sources = (
                [(str(p), v) for p, v in discovered]
                if discovered
                else [(src, Path(src).name or "default")]
            )
    if not sources:
        print(
            "Error: no source directories. Set HELP_SOURCE_BASE or use --sources",
            file=sys.stderr,
        )
        return 1
    raw_lang = getattr(args, "languages", None)
    languages = parse_languages_env(
        raw_lang if raw_lang is not None and raw_lang.strip() else env_config.get_help_languages()
    )
    out = getattr(args, "output_dir", None) or env_config.get_data_unpacked_dir()
    out = Path(out).resolve()
    try:
        n = run_unpack_sync(
            source_dirs_with_versions=sources,
            output_dir=out,
            languages=languages,
            max_workers=getattr(args, "workers", 4),
            verbose=not getattr(args, "quiet", False),
        )
        print(f"Unpacked {n} archive(s) to {out}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_read_hbk_container(args: argparse.Namespace) -> int:
    """Read HBK binary container (source: alkoleft/hbk-viewer); list entities or extract to dir."""
    from pathlib import Path

    from .hbk_container import (
        extract_filestorage_bytes,
        extract_packblock_toc_bytes,
        read_container_from_path,
    )

    hbk_path = Path(getattr(args, "file", None) or "").resolve()
    if not hbk_path.is_file():
        print(f"Error: not a file: {hbk_path}", file=sys.stderr)
        return 1
    try:
        entities = read_container_from_path(hbk_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: invalid HBK container: {e}", file=sys.stderr)
        return 1

    out_dir = getattr(args, "out_dir", None)
    toc_json = getattr(args, "toc_json", None)
    if not out_dir and not toc_json:
        print("Entities:", ", ".join(sorted(entities.keys())))
        for name, body in sorted(entities.items()):
            print(f"  {name}: {len(body)} bytes")
        return 0

    if toc_json:
        toc_bytes = extract_packblock_toc_bytes(entities)
        if toc_bytes:
            Path(toc_json).parent.mkdir(parents=True, exist_ok=True)
            Path(toc_json).write_bytes(toc_bytes)
            print(f"TOC written to {toc_json} ({len(toc_bytes)} bytes)")
        else:
            print("No PackBlock TOC in container", file=sys.stderr)

    if out_dir:
        out_path = Path(out_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)
        fs = extract_filestorage_bytes(entities)
        if fs:
            import io
            import zipfile

            z = zipfile.ZipFile(io.BytesIO(fs), "r")
            z.extractall(out_path)
            print(f"FileStorage extracted to {out_path}")
        else:
            print("No FileStorage in container", file=sys.stderr)
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest .hbk from multiple read-only source dirs: unpack to temp, build docs, index, cleanup."""
    from pathlib import Path

    from .ingest import (
        discover_version_dirs,
        parse_languages_env,
        parse_source_dirs_env,
        run_ingest,
    )

    sources: list[tuple[str, str]] = []
    if getattr(args, "sources", None):
        for s in args.sources:
            s = s.strip()
            if ":" in s:
                p, v = s.split(":", 1)
                sources.append((p.strip(), v.strip()))
            else:
                sources.append((s, Path(s).name or "default"))
    if not sources and getattr(args, "sources_file", None):
        # sources_file path is from CLI args; CLI is intended for trusted operator use only
        for line in Path(args.sources_file).read_text(encoding="utf-8").strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                p, v = line.split(":", 1)
                sources.append((p.strip(), v.strip()))
            else:
                sources.append((line, Path(line).name or "default"))
    if not sources:
        base = env_config.get_help_source_base()
        if base:
            discovered = discover_version_dirs(base)
            sources = [(str(p), v) for p, v in discovered]
        if not sources:
            sources = parse_source_dirs_env(env_config.get_help_source_dirs())
    if not sources:
        print(
            "Error: no source directories. Set HELP_SOURCE_BASE (path to folder with version subdirs) or use --sources / --sources-file",
            file=sys.stderr,
        )
        return 1
    raw_lang = getattr(args, "languages", None)
    if raw_lang is not None:
        languages = parse_languages_env(raw_lang if raw_lang.strip() else "all")
    else:
        languages = parse_languages_env(env_config.get_help_languages())
    if getattr(args, "no_cache", False):
        os.environ["INGEST_SKIP_CACHE"] = "1"
    try:
        # По умолчанию: распаковка в data/unpacked, индексация из неё (одна папка, без удаления).
        # INGEST_USE_TEMP=1 — старый режим: временная папка с удалением после индексации.
        use_temp = env_config.get_ingest_use_temp()
        if not use_temp and not getattr(args, "dry_run", False):
            from .ingest import run_ingest_from_unpacked, run_unpack_sync

            unpacked_dir = env_config.get_data_unpacked_dir()
            unpacked_base = Path(unpacked_dir).resolve()
            unpacked_base.mkdir(parents=True, exist_ok=True)
            run_unpack_sync(
                source_dirs_with_versions=sources,
                output_dir=unpacked_base,
                languages=languages,
                max_workers=getattr(args, "workers", None) or 4,
                verbose=not getattr(args, "quiet", False),
            )
            n = run_ingest_from_unpacked(
                unpacked_base=unpacked_base,
                qdrant_host=env_config.get_qdrant_host(),
                qdrant_port=env_config.get_qdrant_port(),
                collection=env_config.get_qdrant_collection(),
                incremental=not getattr(args, "recreate", False),
                verbose=not getattr(args, "quiet", False),
                embedding_batch_size=getattr(args, "embedding_batch_size", None),
                embedding_workers=getattr(args, "embedding_workers", None),
                max_workers=getattr(args, "workers", None),
            )
        else:
            _default_temp = os.path.join(tempfile.gettempdir(), "help_ingest")
            n = run_ingest(
                source_dirs_with_versions=sources,
                languages=languages,
                temp_base=args.temp_base or env_config.get_ingest_temp_dir() or _default_temp,
                qdrant_host=env_config.get_qdrant_host(),
                qdrant_port=env_config.get_qdrant_port(),
                collection=env_config.get_qdrant_collection(),
                incremental=not getattr(args, "recreate", False),
                max_workers=getattr(args, "workers", None),
                max_tasks=getattr(args, "max_tasks", None),
                verbose=not getattr(args, "quiet", False),
                dry_run=getattr(args, "dry_run", False),
                index_batch_size=getattr(args, "index_batch_size", 500),
                embedding_batch_size=getattr(args, "embedding_batch_size", None),
                embedding_workers=getattr(args, "embedding_workers", None),
            )
        print(f"Ingested and indexed {n} chunks")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_ingest_from_unpacked(args: argparse.Namespace) -> int:
    """Index help from unpacked dir (data/unpacked structure: version/stem)."""
    from pathlib import Path

    from .ingest import run_ingest_from_unpacked

    unpacked_dir = getattr(args, "dir", None) or env_config.get_data_unpacked_dir()
    base = Path(unpacked_dir).resolve()
    if not base.is_dir():
        print(f"Error: unpacked dir not found: {base}", file=sys.stderr)
        return 1
    bm25_val = None
    if getattr(args, "bm25", False):
        bm25_val = True
    elif getattr(args, "no_bm25", False):
        bm25_val = False
    try:
        n = run_ingest_from_unpacked(
            unpacked_base=base,
            qdrant_host=env_config.get_qdrant_host(),
            qdrant_port=env_config.get_qdrant_port(),
            collection=env_config.get_qdrant_collection(),
            incremental=not getattr(args, "recreate", False),
            verbose=not getattr(args, "quiet", False),
            embedding_batch_size=getattr(args, "embedding_batch_size", None),
            embedding_workers=getattr(args, "embedding_workers", None),
            bm25=bm25_val,
        )
        print(f"Ingested from unpacked: {n} points")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _build_snippets_sources(args: argparse.Namespace) -> list[tuple[Path, str]]:
    """Build list of (path, type) for snippets sources. type: 'json' | 'folder'."""
    path_arg = getattr(args, "snippets_file", None) or env_config.get_snippets_json_path()
    snippets_dir = env_config.get_snippets_dir()
    from_project = getattr(args, "from_project", None)
    sources: list[tuple[Path, str]] = []

    if from_project:
        d = Path(from_project.strip()).resolve()
        if d.exists() and d.is_dir():
            sources.append((d, "folder"))
    elif path_arg and path_arg.strip():
        p = Path(path_arg.strip()).resolve()
        if not p.exists():
            return []
        if p.is_dir():
            for j in sorted(p.glob("*.json")):
                sources.append((j, "json"))
            sources.append((p, "folder"))
        else:
            sources.append((p, "json"))
    elif snippets_dir:
        d = Path(snippets_dir).resolve()
        if d.exists():
            for j in sorted(d.glob("*.json")):
                sources.append((j, "json"))
            sources.append((d, "folder"))
    return sources


def _load_json_items(p: Path) -> list[dict]:
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("JSON must be an array of {title, description, code_snippet}")
    return data


def _load_folder_items(d: Path, per_func: bool = False) -> list[dict]:
    from .snippets_loader import collect_from_folder

    return collect_from_folder(d, per_function=per_func)


def cmd_load_snippets(args: argparse.Namespace) -> int:
    """Load curated snippets from JSON and/or folder into onec_help_memory (domain=snippets).
    By default (explicit run) always loads; use --use-cache or SNIPPETS_SKIP_CACHE=0 to only load changed sources."""
    import time

    from ._utils import progress_done, progress_line
    from .memory import get_memory_store
    from .snippets_cache import (
        _file_signature,
        _folder_signature,
        get_snippets_sources_to_load,
        record_snippets_run,
        update_snippets_cache,
    )

    # Explicit run: default force load. Use cache only when --use-cache or init passes use_cache=True.
    use_cache = getattr(args, "use_cache", False)
    skip_cache = (not use_cache) or env_config.get_snippets_skip_cache()

    try:
        sources = _build_snippets_sources(args)
        if not sources:
            path_arg = getattr(args, "snippets_file", None) or env_config.get_snippets_json_path()
            if path_arg:
                p = Path(path_arg.strip())
                if not p.exists():
                    print(f"Error: path not found: {p}", file=sys.stderr)
                    return 1
            elif not env_config.get_snippets_dir() and not getattr(args, "from_project", None):
                print(
                    "No source: set SNIPPETS_DIR, pass path, or use --from-project.",
                    file=sys.stderr,
                )
                return 0
            print("SNIPPETS_DIR not found or empty.", file=sys.stderr)
            return 0

        to_load = sources if skip_cache else get_snippets_sources_to_load(sources)[0]
        files_skipped = len(sources) - len(to_load)

        started_at = time.time()

        if not to_load:
            print(
                f"load-snippets │ All {len(sources)} source(s) unchanged (cache); nothing to do.",
                file=sys.stderr,
            )
            record_snippets_run(0, len(sources), 0, started_at)
            return 0

        _snippets_marker = _load_operation_running_path("snippets")
        try:
            _snippets_marker.write_text(str(started_at), encoding="utf-8")
        except OSError:
            pass
        try:
            _load_operation_status_path("snippets").write_text(
                json.dumps({"phase": "parsing"}, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass
        try:
            if files_skipped > 0:
                print(
                    f"load-snippets │ Cache hit: skip {files_skipped} unchanged; loading {len(to_load)}",
                    file=sys.stderr,
                )

            items: list[dict] = []
            folder_ext = frozenset({".bsl", ".1c", ".md"})
            per_func = getattr(args, "per_function", False)

            for path, stype in to_load:
                path = Path(path).resolve()
                src_items = (
                    _load_json_items(path)
                    if stype == "json"
                    else _load_folder_items(path, per_func=per_func)
                )
                items.extend(src_items)
                # Update cache per source
                key = str(path)
                sig = (
                    _file_signature(path)
                    if stype == "json"
                    else _folder_signature(path, folder_ext)
                )
                if sig:
                    update_snippets_cache(key, sig, len(src_items))

            if not items:
                print("No snippets to load.", file=sys.stderr)
                return 0

            from . import embedding

            if not embedding.is_embedding_available():
                print(
                    "load-snippets │ Embedding not available (check EMBEDDING_BACKEND and EMBEDDING_API_URL); onec_help_memory will not be updated.",
                    file=sys.stderr,
                )
                return 1

            by_domain: dict[str, list[dict]] = {"snippets": [], "community_help": []}
            for it in items:
                t = (it.get("type") or "snippet").lower()
                domain = "community_help" if t == "reference" else "snippets"
                by_domain[domain].append(it)

            status_path = _load_operation_status_path("snippets")
            total_items = len(items)
            try:
                status_path.write_text(
                    json.dumps(
                        {"loaded": 0, "total": total_items, "phase": "embedding"},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass

            def _progress(loaded: int, tot: int, skipped: int) -> None:
                # loaded/tot from memory.upsert_curated_snippets are cumulative and total
                progress_line(
                    f"load-snippets │ {loaded + skipped}/{tot} │ {loaded} loaded │ {skipped} skip"
                )
                try:
                    status_path.write_text(
                        json.dumps(
                            {
                                "loaded": loaded,
                                "total": total_items,
                                "phase": "embedding",
                            },
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                except OSError:
                    pass

            store = get_memory_store()
            total_loaded = 0
            domain_counts: list[str] = []
            for domain, domain_items in by_domain.items():
                if not domain_items:
                    continue
                n = store.upsert_curated_snippets(
                    domain_items, progress_callback=_progress, domain=domain
                )
                total_loaded += n
                domain_counts.append(f"{domain}={n}")

            record_snippets_run(len(to_load), files_skipped, total_loaded, started_at)
            progress_done(
                f"load-snippets │ ✓ {total_loaded} loaded ({', '.join(domain_counts)}) → onec_help_memory"
            )
            return 0
        finally:
            _snippets_marker.unlink(missing_ok=True)
            _load_operation_status_path("snippets").unlink(missing_ok=True)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _slug_for_standards_file(title: str, max_len: int = 80) -> str:
    """Safe filename stem from title (ASCII/digits/underscore). Fallback: short hash if empty."""
    s = (title or "page").strip()
    out: list[str] = []
    for c in s:
        if c.isascii() and (c.isalnum() or c in "-_"):
            out.append(c)
        elif c.isspace() or c in "/\\":
            if out and out[-1] != "_":
                out.append("_")
    name = "".join(out).strip("_")
    if not name or len(name) < 2:
        import hashlib

        name = hashlib.md5(title.encode("utf-8")).hexdigest()[:12]
    return name[:max_len]


def _parse_standards_repo_spec(spec: str, default_branch: str = "master") -> tuple[str, str]:
    """Parse 'owner/repo' or 'owner/repo:branch'. Returns (repo_url, branch)."""
    spec = spec.strip()
    if ":" in spec:
        repo, branch = spec.rsplit(":", 1)
        return repo.strip(), (branch.strip() or default_branch)
    return spec, default_branch


_DEFAULT_STANDARDS_REPOS = "1C-Company/v8-code-style:master,zeegin/v8std:main"


def cmd_load_standards(args: argparse.Namespace) -> int:
    """Load standards (markdown) into onec_help_memory (domain=standards).
    Sources: path arg, STANDARDS_DIR (only when no repos set), STANDARDS_REPOS (comma-separated).
    By default loads both v8-code-style and v8std. When STANDARDS_REPOS is set, STANDARDS_DIR is used only as copy destination."""
    path_arg = (getattr(args, "standards_path", None) or "").strip()
    standards_repos = env_config.get_standards_repos()
    standards_subpath = env_config.get_standards_subpath()
    default_branch = env_config.get_standards_branch()
    # Use STANDARDS_DIR as source only when no repo is configured (else it's the copy destination)
    if not path_arg and not standards_repos:
        path_arg = env_config.get_standards_dir()
    if not path_arg and not standards_repos:
        standards_repos = _DEFAULT_STANDARDS_REPOS
    temp_dirs: list[Path] = []
    dirs_to_load: list[Path] = []

    if path_arg:
        d = Path(path_arg)
        if not d.exists() or not d.is_dir():
            print(f"Error: path not found or not a directory: {d}", file=sys.stderr)
            return 1
        dirs_to_load.append(d)
    elif standards_repos:
        for spec in standards_repos.split(","):
            if not spec.strip():
                continue
            repo_url, branch = _parse_standards_repo_spec(spec, default_branch)
            if "github.com" not in repo_url:
                repo_url = f"https://github.com/{repo_url}"
            try:
                from .standards_loader import fetch_repo_archive

                d, tmp = fetch_repo_archive(repo_url, subpath=standards_subpath, branch=branch)
                dirs_to_load.append(d)
                temp_dirs.append(tmp)
            except Exception as e:
                print(f"Error fetching {repo_url}: {e}", file=sys.stderr)
                for t in temp_dirs:
                    import shutil

                    shutil.rmtree(t, ignore_errors=True)
                return 1
    else:
        its_only = getattr(args, "its_v8std", False) or env_config.get_standards_its_v8std()
        if not its_only:
            print(
                "No source: set STANDARDS_REPOS (e.g. 1C-Company/v8-code-style:master,zeegin/v8std:main) "
                "or STANDARDS_DIR / pass path, or use --its-v8std.",
                file=sys.stderr,
            )
            return 0
        # ITS v8std only: dirs_to_load stays empty

    try:
        import shutil as _shutil
        import time as _time

        from . import redis_cache
        from ._utils import progress_done, progress_line
        from .memory import get_memory_store
        from .standards_loader import collect_from_folder

        started_at = _time.time()
        _marker = _load_operation_running_path("standards")
        try:
            _marker.write_text(str(started_at), encoding="utf-8")
        except OSError:
            pass
        try:
            _load_operation_status_path("standards").write_text(
                json.dumps({"phase": "parsing"}, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

        # Копировать загруженные репо в папку standards (если загрузка из репо, а не из path)
        if temp_dirs:
            standards_out = Path(env_config.get_standards_dir()).resolve()
            standards_out.mkdir(parents=True, exist_ok=True)
            for d in dirs_to_load:
                subdir = d.parent.name
                dest = standards_out / subdir
                _shutil.copytree(d, dest, dirs_exist_ok=True)
            progress_done(f"load-standards │ copied to {standards_out}")

        items: list[dict[str, Any]] = []
        for d in dirs_to_load:
            items.extend(collect_from_folder(d))

        # Optional: load from ITS v8std (https://its.1c.ru/db/v8std) if enabled
        its_v8std = env_config.get_standards_its_v8std() or getattr(args, "its_v8std", False)
        if its_v8std:
            try:
                from .parse_its_v8std import fetch_its_v8std_items

                progress_line("load-standards │ fetching ITS v8std (its.1c.ru)...")
                max_content_env = env_config.get_its_v8std_max_content_raw()
                max_content = int(max_content_env) if max_content_env else None
                its_items = fetch_its_v8std_items(max_content=max_content)
                items.extend(its_items)
                if its_items:
                    # Сохранить статьи ITS в папки по разделам: its-v8std/Раздел1/Подраздел/791_Название.md
                    from .parse_its_v8std import _safe_folder_name

                    standards_out = Path(env_config.get_standards_dir()).resolve()
                    its_dir = standards_out / "its-v8std"
                    its_dir.mkdir(parents=True, exist_ok=True)
                    for item in its_items:
                        url = item.get("detail_url", "")
                        content_id = item.get("content_id", "")
                        if not content_id and "/content/" in url:
                            content_id = url.split("/content/")[1].split("/")[0]
                        section_path = item.get("section_path") or []
                        if not section_path:
                            section_path = ["v8std"]
                        subdir = its_dir
                        for part in section_path:
                            subdir = subdir / _safe_folder_name(part)
                            subdir.mkdir(parents=True, exist_ok=True)
                        slug = _slug_for_standards_file(item.get("title", "page"))
                        fname = f"{content_id}_{slug}.md" if content_id else f"{slug}.md"
                        body = item.get("code_snippet", "")
                        frontmatter = (
                            f"---\nurl: {url}\nid: {content_id}\nsource: its.1c.ru\n---\n\n"
                        )
                        (subdir / fname).write_text(frontmatter + body, encoding="utf-8")
                    progress_done(f"load-standards │ ITS v8std: {len(its_items)} items → {its_dir}")
            except Exception as e:
                print(f"Warning: ITS v8std fetch failed: {e}", file=sys.stderr)
        else:
            # Подгрузить ITS с диска, если папка уже есть (без повторного fetch)
            standards_out = Path(env_config.get_standards_dir()).resolve()
            its_dir = standards_out / "its-v8std"
            if its_dir.exists():
                its_from_disk = collect_from_folder(its_dir)
                if its_from_disk:
                    items.extend(its_from_disk)
                    progress_done(
                        f"load-standards │ ITS from disk: {len(its_from_disk)} items ← {its_dir}"
                    )

        if not items:
            print("No .md files found.", file=sys.stderr)
            return 0

        from . import embedding

        if not embedding.is_embedding_available():
            print(
                "load-standards │ Embedding not available (check EMBEDDING_BACKEND and EMBEDDING_API_URL); onec_help_memory will not be updated.",
                file=sys.stderr,
            )
            return 1

        _status_path = _load_operation_status_path("standards")
        try:
            _status_path.write_text(
                json.dumps(
                    {"loaded": 0, "total": len(items), "phase": "embedding"},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

        def _progress(loaded: int, tot: int, skipped: int) -> None:
            progress_line(
                f"load-standards │ {loaded + skipped}/{tot} │ {loaded} loaded │ {skipped} skip"
            )
            try:
                _status_path.write_text(
                    json.dumps(
                        {"loaded": loaded, "total": tot, "phase": "embedding"},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass

        store = get_memory_store()
        n = store.upsert_curated_snippets(items, progress_callback=_progress, domain="standards")
        redis_cache.standards_run_record(n, started_at)
        progress_done(f"load-standards │ ✓ {n} loaded → onec_help_memory (domain=standards)")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        import shutil

        _load_operation_running_path("standards").unlink(missing_ok=True)
        _load_operation_status_path("standards").unlink(missing_ok=True)
        for tmp in temp_dirs:
            shutil.rmtree(tmp, ignore_errors=True)


def cmd_parse_fastcode(args: argparse.Namespace) -> int:
    """Parse FastCode templates into snippets JSON."""
    from .parse_fastcode import run_parse

    pages = None
    if args.pages and args.pages.lower() != "auto":
        if "-" in args.pages:
            lo, hi = args.pages.split("-", 1)
            pages = list(range(int(lo), int(hi) + 1))
        else:
            pages = [int(p) for p in args.pages.split(",")]

    out_path = args.out
    if not out_path:
        snippets_dir = env_config.get_snippets_dir()
        if snippets_dir:
            out_path = str(Path(snippets_dir) / "fastcode_snippets.json")
        else:
            out_path = "data/snippets/fastcode_snippets.json"
    out = Path(out_path)
    fetch_detail = not getattr(args, "no_fetch_detail", False)
    return run_parse(out=out, pages=pages, delay=args.delay, fetch_detail=fetch_detail)


def cmd_parse_helpf(args: argparse.Namespace) -> int:
    """Parse HelpF.pro FAQ and Files into snippets JSON."""
    from .parse_helpf import run_parse

    pages = None
    if args.pages and args.pages.lower() != "auto":
        if "-" in args.pages:
            lo, hi = args.pages.split("-", 1)
            pages = list(range(int(lo), int(hi) + 1))
        else:
            pages = [int(p) for p in args.pages.split(",")]

    out_path = args.out
    if not out_path:
        snippets_dir = env_config.get_snippets_dir()
        if snippets_dir:
            out_path = str(Path(snippets_dir) / "helpf_snippets.json")
        else:
            out_path = "data/snippets/helpf_snippets.json"
    out = Path(out_path)
    fetch_detail = not getattr(args, "no_fetch_detail", False)
    return run_parse(
        out=out,
        source=args.source,
        pages=pages,
        max_items=getattr(args, "max_items", 0),
        delay=args.delay,
        fetch_detail=fetch_detail,
        skip_minimal=getattr(args, "skip_minimal", False),
    )


def cmd_watchdog(args: argparse.Namespace) -> int:
    """Run watchdog: monitor .hbk, ingest on change; process pending memory."""
    from .watchdog import run_watchdog

    try:
        run_watchdog(
            poll_interval_sec=args.poll_interval,
            pending_interval_sec=args.pending_interval,
        )
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_mcp(args: argparse.Namespace) -> int:
    """Run MCP server (stdio, sse, http, streamable-http). Requires fastmcp (pip install fastmcp)."""
    try:
        from .mcp_server import run_mcp
    except ImportError:
        print("MCP requires fastmcp (Python 3.10+): pip install fastmcp", file=sys.stderr)
        return 1
    transport = getattr(args, "transport", None) or env_config.get_mcp_transport()
    host = getattr(args, "host", None) or env_config.get_mcp_host()
    port = int(getattr(args, "port", None) or env_config.get_mcp_port())
    path = getattr(args, "path", None) or env_config.get_mcp_path()
    try:
        run_mcp(
            help_path=Path(args.directory or "data").resolve(),
            transport=transport,
            host=host,
            port=port,
            path=path,
        )
    except RuntimeError as e:
        if "fastmcp" in str(e).lower():
            print("MCP requires fastmcp (Python 3.10+): pip install fastmcp", file=sys.stderr)
            return 1
        raise
    return 0


def _collection_has_data(qdrant_host: str, qdrant_port: int, collection: str) -> bool:
    """Return True if collection exists and has points > 0."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(host=qdrant_host, port=qdrant_port, check_compatibility=False)
        if not client.collection_exists(collection):
            return False
        info = client.get_collection(collection)
        pts = getattr(info, "points_count", None) or getattr(info, "pointsCount", 0)
        return (pts or 0) > 0
    except Exception:
        return False


def _clear_before_reinit(
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
    collection: str = "onec_help",
) -> bool:
    """Delete Qdrant collections (onec_help, onec_help_memory) and ingest cache. Returns True on success."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(host=qdrant_host, port=qdrant_port, check_compatibility=False)
        for coll in (collection, "onec_help_memory"):
            if client.collection_exists(coll):
                client.delete_collection(coll)
                print(f"Dropped Qdrant collection: {coll}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: could not drop Qdrant collections: {e}", file=sys.stderr)
    from .ingest import clear_ingest_cache

    if clear_ingest_cache():
        print("Cleared ingest cache.", file=sys.stderr)
    return True


def cmd_init(args: argparse.Namespace) -> int:
    """Initial load: ingest (help), load-snippets, load-standards in parallel. Does not erase existing data."""
    ingest_args = _make_args(
        sources=getattr(args, "sources", None),
        sources_file=getattr(args, "sources_file", None),
        languages=getattr(args, "languages", None) or env_config.get_help_languages(),
        temp_base=env_config.get_ingest_temp_dir() or None,
        workers=None,
        max_tasks=None,
        quiet=getattr(args, "quiet", False),
        dry_run=False,
        recreate=False,
        no_cache=False,
        index_batch_size=500,
        embedding_batch_size=None,
        embedding_workers=None,
    )
    snippets_args = _make_args(
        snippets_file=env_config.get_snippets_json_path(),
        per_function=getattr(args, "per_function", False),
        from_project=getattr(args, "from_project", None),
        use_cache=True,  # init: only load changed to avoid redundant work
    )
    standards_args = _make_args(standards_path=env_config.get_standards_dir())

    with ThreadPoolExecutor(max_workers=3) as executor:
        f_ingest = executor.submit(cmd_ingest, ingest_args)
        f_snippets = executor.submit(cmd_load_snippets, snippets_args)
        f_standards = executor.submit(cmd_load_standards, standards_args)
        results = [f_ingest.result(), f_snippets.result(), f_standards.result()]
    return 1 if any(r != 0 for r in results) else 0


def cmd_reinit(args: argparse.Namespace) -> int:
    """Reinit: erase Qdrant + cache, then init. If DB exists with data, runs init (no wipe) unless --force."""
    qdrant_host = env_config.get_qdrant_host()
    qdrant_port = env_config.get_qdrant_port()
    collection = env_config.get_qdrant_collection()
    force = getattr(args, "force", False)
    if not force and _collection_has_data(qdrant_host, qdrant_port, collection):
        if not getattr(args, "quiet", False):
            print(
                "Index exists with data; skipping wipe. Use --force to erase and reindex.",
                file=sys.stderr,
            )
        return cmd_init(args)
    _clear_before_reinit(qdrant_host=qdrant_host, qdrant_port=qdrant_port, collection=collection)
    reinit_args = _make_args(
        sources=getattr(args, "sources", None),
        sources_file=getattr(args, "sources_file", None),
        languages=getattr(args, "languages", None) or env_config.get_help_languages(),
        temp_base=env_config.get_ingest_temp_dir() or None,
        workers=None,
        max_tasks=None,
        quiet=getattr(args, "quiet", False),
        dry_run=False,
        recreate=True,
        no_cache=True,
        index_batch_size=500,
        embedding_batch_size=None,
        embedding_workers=None,
    )
    snippets_args = _make_args(
        snippets_file=env_config.get_snippets_json_path(),
        per_function=getattr(args, "per_function", False),
        from_project=getattr(args, "from_project", None),
        use_cache=False,  # reinit: force full reload
    )
    standards_args = _make_args(standards_path=env_config.get_standards_dir())

    with ThreadPoolExecutor(max_workers=3) as executor:
        f_ingest = executor.submit(cmd_ingest, reinit_args)
        f_snippets = executor.submit(cmd_load_snippets, snippets_args)
        f_standards = executor.submit(cmd_load_standards, standards_args)
        results = [f_ingest.result(), f_snippets.result(), f_standards.result()]
    return 1 if any(r != 0 for r in results) else 0


def _bm25_vocab_dir() -> Path:
    """Path to data/bm25_vocab (for backup/restore)."""
    d = Path(env_config.get_data_dir())
    if not d.is_absolute():
        d = Path.cwd() / d
    return d.resolve() / "bm25_vocab"


def cmd_qdrant_backup(args: argparse.Namespace) -> int:
    """Создать снапшот коллекции и сохранить в data/backup/; копировать BM25 vocab."""
    import shutil
    import urllib.request
    from datetime import datetime

    host = env_config.get_qdrant_host()
    port = env_config.get_qdrant_port()
    collection = env_config.get_qdrant_collection()
    base = f"http://{host}:{port}"
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Create snapshot
        req = urllib.request.Request(
            f"{base}/collections/{collection}/snapshots",
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode())
        name = data.get("result", {}).get("name")
        if not name:
            print("Error: no snapshot name in response", file=sys.stderr)
            return 1

        # 2. Download snapshot
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = out_dir / f"onec_help-{ts}.snapshot"
        req = urllib.request.Request(f"{base}/collections/{collection}/snapshots/{name}")
        with urllib.request.urlopen(req, timeout=600) as resp:
            out_path.write_bytes(resp.read())

        # 3. Copy BM25 vocab (for keyword search after restore)
        vocab_src = _bm25_vocab_dir()
        vocab_dst = out_dir / "bm25_vocab"
        if vocab_src.is_dir():
            if vocab_dst.exists():
                shutil.rmtree(vocab_dst)
            shutil.copytree(vocab_src, vocab_dst)
            print(f"BM25 vocab copied: {vocab_dst}")
        print(f"Backup saved: {out_path}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_qdrant_restore(args: argparse.Namespace) -> int:
    """Восстановить коллекцию из снапшота и BM25 vocab при наличии."""
    import shutil
    import urllib.request

    host = env_config.get_qdrant_host()
    port = env_config.get_qdrant_port()
    collection = env_config.get_qdrant_collection()
    base = f"http://{host}:{port}"
    backup_dir = Path(args.backup_dir)

    if args.file:
        snap_path = Path(args.file)
        if not snap_path.is_file():
            print(f"Error: file not found: {snap_path}", file=sys.stderr)
            return 1
    else:
        snaps = sorted(backup_dir.glob("onec_help-*.snapshot"), reverse=True)
        if not snaps:
            print(f"Error: no snapshots in {backup_dir}", file=sys.stderr)
            return 1
        snap_path = snaps[0]
        print(f"Using latest: {snap_path}")

    try:
        boundary = "----WebKitFormBoundary7MA4YWxk"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="snapshot"; filename="snapshot.snapshot"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        body += snap_path.read_bytes()
        body += f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{base}/collections/{collection}/snapshots/upload?priority=snapshot",
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            json.loads(resp.read().decode())

        # Restore BM25 vocab if present in backup
        vocab_src = backup_dir / "bm25_vocab"
        vocab_dst = _bm25_vocab_dir()
        if vocab_src.is_dir():
            vocab_dst.parent.mkdir(parents=True, exist_ok=True)
            if vocab_dst.exists():
                shutil.rmtree(vocab_dst)
            shutil.copytree(vocab_src, vocab_dst)
            print(f"BM25 vocab restored: {vocab_dst}")
        print(f"Restored from {snap_path}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="onec_help", description="1C Help: unpack, docs, index, MCP"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # unpack
    p_unpack = sub.add_parser("unpack", help="Unpack .hbk with 7z")
    p_unpack.add_argument("archive", type=str, help="Path to .hbk file")
    p_unpack.add_argument(
        "--output-dir", "-o", type=str, default="./unpacked", help="Output directory"
    )
    p_unpack.set_defaults(func=cmd_unpack)

    p_unpack_diag = sub.add_parser(
        "unpack-diag",
        help="Diagnose unpack failure (try each method, print 7z output)",
    )
    p_unpack_diag.add_argument("archive", type=str, help="Path to .hbk file")
    p_unpack_diag.add_argument(
        "--output-dir", "-o", type=str, default="/tmp/unpack_diag", help="Output dir"
    )
    p_unpack_diag.set_defaults(func=cmd_unpack_diag)

    # unpack-dir — only unpack all .hbk into a directory (no build-docs, no index)
    p_unpack_dir = sub.add_parser(
        "unpack-dir", help="Unpack all .hbk from source tree into output dir (no indexing)"
    )
    p_unpack_dir.add_argument(
        "source_dir",
        type=str,
        nargs="?",
        default="",
        help="Root dir with version subdirs (or set HELP_SOURCE_BASE)",
    )
    p_unpack_dir.add_argument(
        "--output-dir", "-o", type=str, default="./unpacked", help="Output directory"
    )
    p_unpack_dir.add_argument(
        "--sources",
        "-s",
        type=str,
        nargs="*",
        help="path:version pairs (overrides source_dir / HELP_SOURCE_BASE)",
    )
    p_unpack_dir.add_argument(
        "--languages",
        "-l",
        type=str,
        default=None,
        help="Comma-separated, e.g. ru (default: HELP_LANGUAGES or all)",
    )
    p_unpack_dir.add_argument("--workers", "-w", type=int, default=4, help="Parallel workers")
    p_unpack_dir.add_argument("--quiet", "-q", action="store_true", help="Less output")
    p_unpack_dir.set_defaults(func=cmd_unpack_dir)

    # unpack-sync — unpack to data/unpacked with .hbk_info.json, skip unchanged
    p_unpack_sync = sub.add_parser(
        "unpack-sync",
        help="Unpack .hbk to data/unpacked (version/stem), write .hbk_info.json, skip unchanged",
    )
    p_unpack_sync.add_argument(
        "source_dir",
        type=str,
        nargs="?",
        default="",
        help="Root dir with version subdirs (or set HELP_SOURCE_BASE)",
    )
    p_unpack_sync.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Output (default: DATA_UNPACKED_DIR or data/unpacked)",
    )
    p_unpack_sync.add_argument(
        "--sources",
        "-s",
        type=str,
        nargs="*",
        help="path:version pairs",
    )
    p_unpack_sync.add_argument(
        "--languages",
        "-l",
        type=str,
        default=None,
        help="Comma-separated, e.g. ru",
    )
    p_unpack_sync.add_argument("--workers", "-w", type=int, default=4, help="Parallel workers")
    p_unpack_sync.add_argument("--quiet", "-q", action="store_true", help="Less output")
    p_unpack_sync.set_defaults(func=cmd_unpack_sync)

    # read-hbk-container — read HBK binary container (source: alkoleft/hbk-viewer)
    p_read_hbk = sub.add_parser(
        "read-hbk-container",
        help="Read HBK binary container; list entities or extract FileStorage/TOC",
    )
    p_read_hbk.add_argument("file", type=str, help="Path to .hbk file")
    p_read_hbk.add_argument(
        "--out-dir", "-o", type=str, default=None, help="Extract FileStorage ZIP to this directory"
    )
    p_read_hbk.add_argument(
        "--toc-json", type=str, default=None, help="Write PackBlock TOC (UTF-8) to this file"
    )
    p_read_hbk.set_defaults(func=cmd_read_hbk_container)

    # build-docs
    p_docs = sub.add_parser("build-docs", help="Generate Markdown from HTML")
    p_docs.add_argument("project_dir", type=str, help="Directory with HTML files")
    p_docs.add_argument(
        "--output", "-o", type=str, help="Output directory (default: project_dir/docs_md)"
    )
    p_docs.set_defaults(func=cmd_build_docs)

    # build-index
    p_idx = sub.add_parser("build-index", help="Build Qdrant index from Markdown/docs (recursive)")
    p_idx.add_argument("directory", type=str, help="Directory with .md or HTML")
    p_idx.add_argument("--docs-dir", type=str, help="Alias for directory (optional)")
    p_idx.add_argument(
        "--incremental",
        action="store_true",
        help="Add/update only, do not recreate collection (new files in folder will be indexed)",
    )
    p_idx.add_argument(
        "--embedding-batch-size",
        type=int,
        default=None,
        metavar="N",
        help="Texts per embedding batch (default: env EMBEDDING_BATCH_SIZE or 64)",
    )
    p_idx.add_argument(
        "--embedding-workers",
        type=int,
        default=None,
        metavar="N",
        help="Parallel API requests for openai_api (default: env EMBEDDING_WORKERS or 6)",
    )
    p_idx.add_argument(
        "--no-bm25",
        action="store_true",
        help="Disable BM25 sparse vectors (default: BM25_ENABLED=1)",
    )
    p_idx.set_defaults(func=cmd_build_index)

    # add-bm25
    p_add_bm25 = sub.add_parser(
        "add-bm25",
        help="Add BM25 sparse vectors to all collections (clears bm25_vocab and existing BM25, then adds)",
    )
    p_add_bm25.set_defaults(func=cmd_add_bm25)

    # ingest
    p_ingest = sub.add_parser(
        "ingest", help="Ingest .hbk from multiple read-only dirs (temp unpack, index, cleanup)"
    )
    p_ingest.add_argument(
        "--sources",
        "-s",
        type=str,
        nargs="*",
        help="Alternating path:version (or set HELP_SOURCE_BASE to scan a folder of version subdirs)",
    )
    p_ingest.add_argument("--sources-file", type=str, help="File with lines: path or path:version")
    p_ingest.add_argument(
        "--languages",
        "-l",
        type=str,
        default=None,
        help="Comma-separated, e.g. ru or ru,en; default from HELP_LANGUAGES; empty=all",
    )
    p_ingest.add_argument(
        "--temp-base",
        type=str,
        default=None,
        help="Temp dir in container (default INGEST_TEMP_DIR or /tmp/help_ingest)",
    )
    p_ingest.add_argument(
        "--workers",
        "-w",
        type=int,
        default=None,
        metavar="N",
        help="Parallel workers (default: half of CPUs for temp ingest; INGEST_MAX_WORKERS or 4 for from-unpacked)",
    )
    p_ingest.add_argument(
        "--max-tasks",
        "-n",
        type=int,
        default=None,
        help="Process only first N .hbk files (avoids timeout; run multiple times for full index)",
    )
    p_ingest.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="No progress output (default: print progress to stderr)",
    )
    p_ingest.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report how many .hbk tasks would be processed (no unpack/index)",
    )
    p_ingest.add_argument(
        "--index-batch-size",
        type=int,
        default=500,
        metavar="N",
        help="Index N files per upsert (default 500); smaller = more progress output, less memory",
    )
    p_ingest.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate Qdrant collection (e.g. after changing EMBEDDING_DIMENSION or model)",
    )
    p_ingest.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore ingest cache; re-parse and re-embed all .hbk (env INGEST_SKIP_CACHE=1)",
    )
    p_ingest.add_argument(
        "--embedding-batch-size",
        type=int,
        default=None,
        metavar="N",
        help="Texts per embedding batch (default: env EMBEDDING_BATCH_SIZE or 64)",
    )
    p_ingest.add_argument(
        "--embedding-workers",
        type=int,
        default=None,
        metavar="N",
        help="Parallel API requests for openai_api (default: env EMBEDDING_WORKERS or 6)",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    # ingest-from-unpacked — index from data/unpacked (version/stem structure)
    p_ingest_unpacked = sub.add_parser(
        "ingest-from-unpacked",
        help="Index from unpacked dir (version/stem, path_prefix in payload)",
    )
    p_ingest_unpacked.add_argument(
        "--dir",
        "-d",
        type=str,
        default=None,
        help="Unpacked base dir (default: DATA_UNPACKED_DIR or data/unpacked)",
    )
    p_ingest_unpacked.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate Qdrant collection before indexing",
    )
    p_ingest_unpacked.add_argument("--quiet", "-q", action="store_true", help="Less output")
    p_ingest_unpacked.add_argument(
        "--embedding-batch-size",
        type=int,
        default=None,
        metavar="N",
        help="Texts per embedding batch",
    )
    p_ingest_unpacked.add_argument(
        "--embedding-workers",
        type=int,
        default=None,
        metavar="N",
        help="Parallel embedding requests",
    )
    p_ingest_unpacked.add_argument(
        "--bm25",
        action="store_true",
        help="Enable BM25 sparse vectors",
    )
    p_ingest_unpacked.add_argument(
        "--no-bm25",
        action="store_true",
        dest="no_bm25",
        help="Disable BM25",
    )
    p_ingest_unpacked.set_defaults(func=cmd_ingest_from_unpacked)

    # init — ingest + load-snippets + load-standards (no erase)
    p_init = sub.add_parser(
        "init",
        help="Initial load: ingest help, load snippets, load standards (uses env; does not erase)",
    )
    p_init.add_argument(
        "--sources", "-s", type=str, nargs="*", help="path:version (or HELP_SOURCE_BASE)"
    )
    p_init.add_argument("--sources-file", type=str, help="File with path or path:version lines")
    p_init.add_argument("--languages", "-l", type=str, default=None, help="e.g. ru or ru,en")
    p_init.add_argument("--quiet", "-q", action="store_true", help="Less output")
    p_init.add_argument(
        "--per-function", action="store_true", help="Split .bsl by procedures for snippets"
    )
    p_init.add_argument("--from-project", type=str, help="Load snippets from 1C project path")
    p_init.set_defaults(func=cmd_init)

    # reinit — erase collections + cache, then init (skip wipe if DB exists, unless --force)
    p_reinit = sub.add_parser(
        "reinit",
        help="Init load. If index exists with data, runs init (no wipe). Use --force to erase and reindex.",
    )
    p_reinit.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Always erase collections and cache before init",
    )
    p_reinit.add_argument(
        "--sources", "-s", type=str, nargs="*", help="path:version (or HELP_SOURCE_BASE)"
    )
    p_reinit.add_argument("--sources-file", type=str, help="File with path or path:version lines")
    p_reinit.add_argument("--languages", "-l", type=str, default=None, help="e.g. ru or ru,en")
    p_reinit.add_argument("--quiet", "-q", action="store_true", help="Less output")
    p_reinit.add_argument(
        "--per-function", action="store_true", help="Split .bsl by procedures for snippets"
    )
    p_reinit.add_argument("--from-project", type=str, help="Load snippets from 1C project path")
    p_reinit.set_defaults(func=cmd_reinit)

    # load-snippets
    p_load_snippets = sub.add_parser(
        "load-snippets",
        help="Load curated snippets from JSON and/or folder into onec_help_memory (domain=snippets)",
    )
    p_load_snippets.add_argument(
        "snippets_file",
        type=str,
        nargs="?",
        default=None,
        help="Path to snippets.json or folder (default: SNIPPETS_DIR or SNIPPETS_JSON_PATH)",
    )
    p_load_snippets.add_argument(
        "--per-function",
        action="store_true",
        dest="per_function",
        help="Split large .bsl by procedures/functions (each as snippet, min 50 lines)",
    )
    p_load_snippets.add_argument(
        "--from-project",
        type=str,
        default=None,
        metavar="PATH",
        help="Load snippets from 1C project path (e.g. src). Uses collect_from_folder on **/*.bsl.",
    )
    p_load_snippets.add_argument(
        "--use-cache",
        action="store_true",
        dest="use_cache",
        help="Only load sources that changed (by default explicit run loads all)",
    )
    p_load_snippets.set_defaults(func=cmd_load_snippets)

    # load-standards
    p_load_standards = sub.add_parser(
        "load-standards",
        help="Load v8-code-style docs (markdown) into onec_help_memory (domain=standards)",
    )
    p_load_standards.add_argument(
        "standards_path",
        type=str,
        nargs="?",
        default=None,
        help="Path to folder with .md (default: STANDARDS_DIR env)",
    )
    p_load_standards.add_argument(
        "--its-v8std",
        action="store_true",
        help="Also fetch standards from ITS v8std (https://its.1c.ru/db/v8std); auth via ITS_AUTH_COOKIE",
    )
    p_load_standards.set_defaults(func=cmd_load_standards)

    # parse-fastcode
    p_parse_fastcode = sub.add_parser(
        "parse-fastcode",
        help="Parse FastCode.im templates into snippets JSON",
    )
    p_parse_fastcode.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output path (default: SNIPPETS_DIR/fastcode_snippets.json or data/snippets/)",
    )
    p_parse_fastcode.add_argument(
        "--pages",
        type=str,
        default="auto",
        help="Page range: auto (detect from site), 1-51, or 1,2,3",
    )
    p_parse_fastcode.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests in seconds",
    )
    p_parse_fastcode.add_argument(
        "--no-fetch-detail",
        action="store_true",
        dest="no_fetch_detail",
        help="Do not fetch detail pages (faster, but code may be truncated)",
    )
    p_parse_fastcode.set_defaults(func=cmd_parse_fastcode)

    # parse-helpf
    p_parse_helpf = sub.add_parser(
        "parse-helpf",
        help="Parse HelpF.pro FAQ/Files into snippets JSON",
    )
    p_parse_helpf.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output path (default: SNIPPETS_DIR/helpf_snippets.json or data/snippets/)",
    )
    p_parse_helpf.add_argument(
        "--source",
        type=str,
        default="faq",
        choices=("faq", "file", "help", "freelance", "all"),
        help="Source: faq, file, help (forum), freelance, or all",
    )
    p_parse_helpf.add_argument(
        "--pages",
        type=str,
        default="auto",
        help="Page range: auto (detect from site), 1-10, or 1,2,3",
    )
    p_parse_helpf.add_argument(
        "--max-items",
        type=int,
        default=0,
        help="Max detail pages to fetch (0 = all)",
    )
    p_parse_helpf.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests in seconds",
    )
    p_parse_helpf.add_argument(
        "--no-fetch-detail",
        action="store_true",
        dest="no_fetch_detail",
        help="Do not fetch detail pages (listing only, no full content)",
    )
    p_parse_helpf.add_argument(
        "--skip-minimal",
        action="store_true",
        dest="skip_minimal",
        help="Exclude items with no real content (title-only, no code)",
    )
    p_parse_helpf.set_defaults(func=cmd_parse_helpf)

    # dashboard (Tasks, Errors, Qdrant, versions 1C)
    p_dashboard = sub.add_parser(
        "dashboard",
        help="Show dashboard (Tasks, Errors, Qdrant, versions 1C). --once: one frame; else Live refresh.",
    )
    p_dashboard.add_argument(
        "--once",
        action="store_true",
        help="Print one frame and exit (no live refresh)",
    )
    p_dashboard.add_argument(
        "--interval",
        "-n",
        type=float,
        default=1.5,
        metavar="SEC",
        help="Refresh interval in seconds when not --once (default: 1.5)",
    )
    p_dashboard.set_defaults(func=cmd_dashboard)

    # mcp
    p_mcp = sub.add_parser("mcp", help="Run MCP server (stdio, sse, http, streamable-http)")
    p_mcp.add_argument(
        "directory",
        type=str,
        nargs="?",
        default=env_config.get_help_path(),
        help="Directory with help (.md or HTML); default: HELP_PATH or DATA_DIR",
    )
    p_mcp.add_argument(
        "--transport",
        "-t",
        type=str,
        default=None,
        help="Transport: stdio (default), sse, http, streamable-http",
    )
    p_mcp.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host for sse/http (default: 127.0.0.1). Use 0.0.0.0 in Docker.",
    )
    p_mcp.add_argument(
        "--port", "-p", type=int, default=None, help="Port for sse/http (default: 8050)"
    )
    p_mcp.add_argument("--path", type=str, default=None, help="URL path (default: /mcp)")
    p_mcp.set_defaults(func=cmd_mcp)

    # watchdog
    p_watchdog = sub.add_parser(
        "watchdog",
        help="Monitor new .hbk files, run ingest on change; process pending memory embeddings",
    )
    p_watchdog.add_argument(
        "--poll-interval",
        type=int,
        default=env_config.get_watchdog_poll_interval(),
        help="Seconds between .hbk checks (default: 600)",
    )
    p_watchdog.add_argument(
        "--pending-interval",
        type=int,
        default=env_config.get_watchdog_pending_interval(),
        help="Seconds between pending memory processing (default: 600)",
    )
    p_watchdog.set_defaults(func=cmd_watchdog)

    # qdrant-backup / qdrant-restore — снапшоты в data/backup/
    p_qdrant_backup = sub.add_parser(
        "qdrant-backup",
        help="Создать снапшот коллекции onec_help и сохранить в data/backup/",
    )
    p_qdrant_backup.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="data/backup",
        help="Каталог для снапшота (default: data/backup)",
    )
    p_qdrant_backup.set_defaults(func=cmd_qdrant_backup)

    p_qdrant_restore = sub.add_parser(
        "qdrant-restore",
        help="Восстановить коллекцию onec_help из снапшота в data/backup/",
    )
    p_qdrant_restore.add_argument(
        "--file",
        "-f",
        type=str,
        default=None,
        help="Путь к снапшоту (default: последний в data/backup/)",
    )
    p_qdrant_restore.add_argument(
        "--backup-dir",
        type=str,
        default="data/backup",
        help="Каталог со снапшотами (default: data/backup)",
    )
    p_qdrant_restore.set_defaults(func=cmd_qdrant_restore)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
