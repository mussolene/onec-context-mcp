#!/usr/bin/env python3
"""Create and restore physical Qdrant/BM25 backup sets.

The script is intended to run inside the project Docker image so backup and
restore behave the same on macOS, Linux and Windows hosts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tarfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import zstandard as zstd


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d_%H%M%SZ")


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value).strip("-")


def _default_backup_name() -> str:
    git_rev = _safe_name(os.environ.get("GIT_REV", "nogit") or "nogit")
    server_version = _safe_name(os.environ.get("SERVER_VERSION", "local") or "local")
    qdrant_version = _safe_name(os.environ.get("QDRANT_VERSION", "1.12.0") or "1.12.0")
    embedding_model = _safe_name(
        os.environ.get("EMBEDDING_MODEL", "nomic-embed-text-v2-moe") or "nomic-embed-text-v2-moe"
    )
    embedding_dim = _safe_name(os.environ.get("EMBEDDING_DIMENSION", "768") or "768")
    return (
        f"{_now_stamp()}_onec-context-mcp_v{server_version}_git-{git_rev}"
        f"_qdrant-{qdrant_version}_{embedding_model}-{embedding_dim}_physical"
    )


def _tar_zst(source: Path, archive: Path) -> dict[str, Any]:
    start = time.time()
    archive.parent.mkdir(parents=True, exist_ok=True)
    compressor = zstd.ZstdCompressor(level=10)
    with archive.open("wb") as raw:
        with compressor.stream_writer(raw) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as tf:
                tf.add(source, arcname=".")
    return {
        "archive": archive.name,
        "archive_bytes": archive.stat().st_size,
        "source_bytes": _dir_size(source),
        "seconds": round(time.time() - start, 3),
    }


def _safe_extract_stream(tf: tarfile.TarFile, dest: Path) -> None:
    base = dest.resolve()
    for member in tf:
        name = member.name
        target = (base / name).resolve()
        if target != base and base not in target.parents:
            raise SystemExit(f"Unsafe tar member path: {name}")
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not member.isfile():
            raise SystemExit(f"Unsupported tar member type: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        src = tf.extractfile(member)
        if src is None:
            raise SystemExit(f"Unable to extract tar member: {name}")
        with src, target.open("wb") as out:
            shutil.copyfileobj(src, out, length=1024 * 1024)


def _extract_tar_zst(archive: Path, dest: Path) -> dict[str, Any]:
    start = time.time()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    decompressor = zstd.ZstdDecompressor()
    with archive.open("rb") as raw:
        with decompressor.stream_reader(raw) as decompressed:
            with tarfile.open(fileobj=decompressed, mode="r|") as tf:
                _safe_extract_stream(tf, dest)
    return {
        "archive": archive.name,
        "archive_bytes": archive.stat().st_size,
        "restored_bytes": _dir_size(dest),
        "seconds": round(time.time() - start, 3),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _public_weblink(public_url: str) -> str:
    if "/public/" not in public_url:
        raise SystemExit(f"Unsupported Mail.ru public URL: {public_url}")
    return public_url.split("/public/", 1)[1].strip("/")


def _public_folder_items(weblink: str) -> list[dict[str, Any]]:
    url = (
        "https://cloud.mail.ru/api/v2/folder"
        f"?weblink={quote(weblink, safe='')}&offset=0&limit=100000&api=2"
    )
    data = _get_json(url)
    if data.get("status") != 200:
        raise SystemExit(f"Mail.ru folder API returned status={data.get('status')}: {weblink}")
    body = data.get("body") or data.get("result") or {}
    return list(body.get("list") or [])


def _weblink_get_base(public_url: str) -> str:
    request = urllib.request.Request(public_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="ignore")
    match = re.search(r'"weblink_get"\s*:\s*\{[^}]*"url"\s*:\s*"([^"]+)"', html)
    if not match:
        raise SystemExit("Mail.ru weblink_get download host was not found in the public page")
    return match.group(1).rstrip("/")


def _download_file(url: str, dest: Path, expected_size: int | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if expected_size is not None and dest.is_file() and dest.stat().st_size == expected_size:
        print(f"Using cached {dest.name} ({expected_size} bytes)")
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=600) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)
    if expected_size is not None and tmp.stat().st_size != expected_size:
        tmp.unlink(missing_ok=True)
        raise SystemExit(
            f"Downloaded size mismatch for {dest.name}: "
            f"{tmp.stat().st_size if tmp.exists() else 0} != {expected_size}"
        )
    tmp.replace(dest)


def _scroll_payloads(base: str, collection: str, payload_fields: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset: Any = None
    while True:
        body: dict[str, Any] = {
            "limit": 512,
            "with_payload": payload_fields,
            "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset
        result = _post_json(f"{base}/collections/{collection}/points/scroll", body)["result"]
        items.extend(point.get("payload") or {} for point in result.get("points") or [])
        offset = result.get("next_page_offset")
        if offset is None:
            return items


def _configuration_versions(base: str, collections: set[str]) -> list[dict[str, Any]]:
    if "onec_config_metadata" not in collections:
        return []
    objects = _scroll_payloads(
        base,
        "onec_config_metadata",
        ["config_name", "config_version"],
    )
    fields = (
        _scroll_payloads(base, "onec_config_metadata_fields", ["config_version"])
        if "onec_config_metadata_fields" in collections
        else []
    )
    summary: dict[tuple[str, str], dict[str, Any]] = {}
    version_to_key: dict[str, tuple[str, str]] = {}
    for payload in objects:
        name = str(payload.get("config_name") or "")
        version = str(payload.get("config_version") or "")
        if not name and not version:
            continue
        key = (name, version)
        item = summary.setdefault(
            key,
            {"config_name": name, "config_version": version, "objects": 0, "fields": 0},
        )
        item["objects"] += 1
        if version:
            version_to_key.setdefault(version, key)
    for payload in fields:
        version = str(payload.get("config_version") or "")
        key = version_to_key.get(version, ("", version))
        item = summary.setdefault(
            key,
            {"config_name": key[0], "config_version": version, "objects": 0, "fields": 0},
        )
        item["fields"] += 1
    return sorted(
        summary.values(),
        key=lambda row: (row["config_name"], row["config_version"]),
    )


def cmd_probe(args: argparse.Namespace) -> int:
    base = args.qdrant_url.rstrip("/")
    collections = _get_json(f"{base}/collections")["result"]["collections"]
    collection_names = {item["name"] for item in collections}
    result: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "qdrant_url": args.qdrant_url,
        "collections": {},
        "configuration_versions": _configuration_versions(base, collection_names),
    }
    for item in collections:
        name = item["name"]
        if not name.startswith("onec_"):
            continue
        info = _get_json(f"{base}/collections/{name}")["result"]
        result["collections"][name] = {
            "points_count": info.get("points_count"),
            "indexed_vectors_count": info.get("indexed_vectors_count"),
            "status": info.get("status"),
            "payload_indexes": sorted((info.get("payload_schema") or {}).keys()),
        }
    out = Path(args.output).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_json(out, result)
    print(f"Probe written: {out}")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    qdrant_dir = Path(args.qdrant_dir).expanduser().resolve()
    bm25_dir = Path(args.bm25_dir).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    if not qdrant_dir.is_dir():
        raise SystemExit(f"Qdrant storage directory not found: {qdrant_dir}")
    if not bm25_dir.exists():
        bm25_dir.mkdir(parents=True)

    backup_name = args.name or os.environ.get("BACKUP_NAME") or _default_backup_name()
    backup_dir = output_root / backup_name
    if backup_dir.exists():
        raise SystemExit(f"Backup directory already exists: {backup_dir}")
    backup_dir.mkdir(parents=True)

    probe = _read_json(Path(args.probe_file).expanduser().resolve()) if args.probe_file else {}
    qdrant_stats = _tar_zst(qdrant_dir, backup_dir / "qdrant-storage.tar.zst")
    bm25_stats = _tar_zst(bm25_dir, backup_dir / "bm25-vocab.tar.zst")

    manifest = {
        "format": "onec_context_mcp_physical_backup_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "server": {
            "name": "onec-context-mcp",
            "version": os.environ.get("SERVER_VERSION", ""),
            "git_rev": os.environ.get("GIT_REV", ""),
        },
        "qdrant": {
            "version": os.environ.get("QDRANT_VERSION", "1.12.0"),
            "storage_archive": qdrant_stats,
        },
        "bm25": {
            "vocab_archive": bm25_stats,
        },
        "embedding": {
            "backend": os.environ.get("EMBEDDING_BACKEND", "openai_api"),
            "model": os.environ.get("EMBEDDING_MODEL", "nomic-embed-text-v2-moe"),
            "dimension": int(os.environ.get("EMBEDDING_DIMENSION", "768") or 768),
        },
        "probe": probe,
    }
    _write_json(backup_dir / "manifest.json", manifest)
    print(f"Backup written: {backup_dir}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    public_url = args.public_url.rstrip("/")
    root_weblink = _public_weblink(public_url)
    root_items = _public_folder_items(root_weblink)
    folders = [item for item in root_items if item.get("type") == "folder"]
    if args.backup == "latest":
        candidates = [item for item in folders if str(item.get("name") or "").endswith("_physical")]
        if not candidates:
            raise SystemExit(f"No physical backup folders found in {public_url}")
        backup_item = sorted(candidates, key=lambda item: str(item.get("name") or ""))[-1]
    else:
        backup_item = next((item for item in folders if item.get("name") == args.backup), None)
        if backup_item is None:
            raise SystemExit(f"Backup folder not found: {args.backup}")

    backup_name = str(backup_item["name"])
    backup_weblink = str(backup_item["weblink"])
    files = {
        item["name"]: item
        for item in _public_folder_items(backup_weblink)
        if item.get("type") == "file" and item.get("name")
    }
    required = ("manifest.json", "qdrant-storage.tar.zst", "bm25-vocab.tar.zst")
    missing = [name for name in required if name not in files]
    if missing:
        raise SystemExit(
            f"Backup folder {backup_name} is missing required files: {', '.join(missing)}"
        )

    download_base = _weblink_get_base(public_url)
    output_dir = Path(args.output_root).expanduser().resolve() / backup_name
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in required:
        item = files[filename]
        file_weblink = quote(str(item["weblink"]), safe="/")
        expected_size = int(item["size"]) if item.get("size") is not None else None
        url = f"{download_base}/{file_weblink}"
        dest = output_dir / filename
        print(f"Downloading {filename} → {dest}")
        _download_file(url, dest, expected_size=expected_size)

    manifest = _read_json(output_dir / "manifest.json")
    if manifest.get("format") != "onec_context_mcp_physical_backup_v1":
        raise SystemExit(
            f"Downloaded manifest has unsupported format: {output_dir / 'manifest.json'}"
        )
    print(f"Downloaded backup: {output_dir}")
    return 0


def _resolve_backup(root: Path, backup: str) -> Path:
    if backup != "latest":
        path = Path(backup)
        if path.is_absolute():
            return path
        return root / backup
    candidates = [p for p in root.iterdir() if p.is_dir() and (p / "manifest.json").is_file()]
    if not candidates:
        raise SystemExit(f"No backup sets found in {root}")
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def cmd_restore(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root).expanduser().resolve()
    backup_dir = _resolve_backup(backup_root, args.backup).resolve()
    manifest = _read_json(backup_dir / "manifest.json")
    if manifest.get("format") != "onec_context_mcp_physical_backup_v1":
        raise SystemExit(f"Unsupported or missing backup manifest: {backup_dir / 'manifest.json'}")

    qdrant_archive = backup_dir / "qdrant-storage.tar.zst"
    bm25_archive = backup_dir / "bm25-vocab.tar.zst"
    if not qdrant_archive.is_file():
        raise SystemExit(f"Qdrant archive not found: {qdrant_archive}")
    if not bm25_archive.is_file():
        raise SystemExit(f"BM25 archive not found: {bm25_archive}")

    qdrant_stats = _extract_tar_zst(qdrant_archive, Path(args.qdrant_dir).expanduser().resolve())
    bm25_stats = _extract_tar_zst(bm25_archive, Path(args.bm25_dir).expanduser().resolve())
    print(f"Restored backup: {backup_dir}")
    print(json.dumps({"qdrant": qdrant_stats, "bm25": bm25_stats}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe")
    probe.add_argument("--qdrant-url", default="http://qdrant:6333")
    probe.add_argument("--output", required=True)
    probe.set_defaults(func=cmd_probe)

    backup = sub.add_parser("backup")
    backup.add_argument("--qdrant-dir", required=True)
    backup.add_argument("--bm25-dir", required=True)
    backup.add_argument("--output-root", required=True)
    backup.add_argument("--probe-file")
    backup.add_argument("--name")
    backup.set_defaults(func=cmd_backup)

    download = sub.add_parser("download")
    download.add_argument("--public-url", required=True)
    download.add_argument("--backup", default="latest")
    download.add_argument("--output-root", required=True)
    download.set_defaults(func=cmd_download)

    restore = sub.add_parser("restore")
    restore.add_argument("--backup-root", required=True)
    restore.add_argument("--backup", default="latest")
    restore.add_argument("--qdrant-dir", required=True)
    restore.add_argument("--bm25-dir", required=True)
    restore.set_defaults(func=cmd_restore)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
