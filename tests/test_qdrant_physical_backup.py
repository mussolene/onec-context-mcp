"""Tests for Docker-oriented Qdrant physical backup helper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "qdrant_physical_backup.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("qdrant_physical_backup", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backup_restore_roundtrip_includes_qdrant_and_bm25(tmp_path: Path) -> None:
    mod = _load_module()
    qdrant = tmp_path / "qdrant"
    bm25 = tmp_path / "bm25"
    qdrant.mkdir()
    bm25.mkdir()
    (qdrant / "collection").mkdir()
    (qdrant / "collection" / "segment.bin").write_bytes(b"qdrant")
    (bm25 / "onec_help_api_members.json").write_text("{}", encoding="utf-8")

    probe = tmp_path / "probe.json"
    probe.write_text(
        json.dumps({"collections": {"onec_help_api_members": {"points_count": 1}}}),
        encoding="utf-8",
    )
    out = tmp_path / "backup"

    rc = mod.cmd_backup(
        mod.argparse.Namespace(
            qdrant_dir=str(qdrant),
            bm25_dir=str(bm25),
            output_root=str(out),
            probe_file=str(probe),
            name="test-backup",
        )
    )
    assert rc == 0

    backup = out / "test-backup"
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "onec_context_mcp_physical_backup_v1"
    assert (backup / "qdrant-storage.tar.zst").is_file()
    assert (backup / "bm25-vocab.tar.zst").is_file()
    assert manifest["probe"]["collections"]["onec_help_api_members"]["points_count"] == 1

    restored_qdrant = tmp_path / "restored_qdrant"
    restored_bm25 = tmp_path / "restored_bm25"
    rc = mod.cmd_restore(
        mod.argparse.Namespace(
            backup_root=str(out),
            backup="test-backup",
            qdrant_dir=str(restored_qdrant),
            bm25_dir=str(restored_bm25),
        )
    )
    assert rc == 0
    assert (restored_qdrant / "collection" / "segment.bin").read_bytes() == b"qdrant"
    assert (restored_bm25 / "onec_help_api_members.json").read_text(encoding="utf-8") == "{}"


def test_restore_rejects_missing_manifest(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "broken").mkdir()
    with pytest.raises(SystemExit, match="No backup sets found|Unsupported or missing"):
        mod.cmd_restore(
            mod.argparse.Namespace(
                backup_root=str(tmp_path),
                backup="broken",
                qdrant_dir=str(tmp_path / "q"),
                bm25_dir=str(tmp_path / "b"),
            )
        )


def test_download_public_backup_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mod = _load_module()
    calls: list[tuple[str, str, int | None]] = []

    def fake_items(weblink: str) -> list[dict[str, object]]:
        if weblink == "NzFn/qLfhyf8zo":
            return [
                {
                    "type": "folder",
                    "name": "2026-05-21_demo_physical",
                    "weblink": "NzFn/qLfhyf8zo/2026-05-21_demo_physical",
                }
            ]
        return [
            {
                "type": "file",
                "name": "manifest.json",
                "weblink": f"{weblink}/manifest.json",
                "size": 53,
            },
            {
                "type": "file",
                "name": "qdrant-storage.tar.zst",
                "weblink": f"{weblink}/qdrant-storage.tar.zst",
                "size": 6,
            },
            {
                "type": "file",
                "name": "bm25-vocab.tar.zst",
                "weblink": f"{weblink}/bm25-vocab.tar.zst",
                "size": 4,
            },
        ]

    def fake_download(url: str, dest: Path, expected_size: int | None = None) -> None:
        calls.append((url, dest.name, expected_size))
        if dest.name == "manifest.json":
            dest.write_text(
                '{"format":"onec_context_mcp_physical_backup_v1"}',
                encoding="utf-8",
            )
        else:
            dest.write_bytes(b"x" * int(expected_size or 0))

    monkeypatch.setattr(mod, "_public_folder_items", fake_items)
    monkeypatch.setattr(mod, "_weblink_get_base", lambda _url: "https://download.example/public/no")
    monkeypatch.setattr(mod, "_download_file", fake_download)

    rc = mod.cmd_download(
        mod.argparse.Namespace(
            public_url="https://cloud.mail.ru/public/NzFn/qLfhyf8zo",
            backup="latest",
            output_root=str(tmp_path),
        )
    )

    assert rc == 0
    backup_dir = tmp_path / "2026-05-21_demo_physical"
    assert (backup_dir / "manifest.json").is_file()
    assert [call[1] for call in calls] == [
        "manifest.json",
        "qdrant-storage.tar.zst",
        "bm25-vocab.tar.zst",
    ]
    assert calls[0][0] == (
        "https://download.example/public/no/NzFn/qLfhyf8zo/2026-05-21_demo_physical/manifest.json"
    )
