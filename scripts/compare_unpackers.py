#!/usr/bin/env python3
"""Compare 'our' unpacker (unpack_hbk) vs container+TOC (read-hbk-container).

Unpacks the same .hbk set into data/compare_unpack/our/<key>/ and
data/compare_unpack/toc/<key>/, then prints stats: file count, size, .toc.json, __categories__.

Usage (from repo root):
  PYTHONPATH=src python scripts/compare_unpackers.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# 10 .hbk from different platforms/versions (opt/1cv8)
HBK_SAMPLES = [
    "/opt/1cv8/8.3.27.1719/extui_ru.hbk",
    "/opt/1cv8/8.3.27.1719/schemui_uk.hbk",
    "/opt/1cv8/8.3.27.1719/basicui_lv.hbk",
    "/opt/1cv8/8.3.27.1719/mapui_uk.hbk",
    "/opt/1cv8/8.3.27.1719/shlang_ru.hbk",
    "/opt/1cv8/8.3.27.1719/edbui_el.hbk",
    "/opt/1cv8/8.3.13.1513/schemui_uk.hbk",
    "/opt/1cv8/8.3.13.1513/basicui_lv.hbk",
    "/opt/1cv8/8.5.1.1150/edbui_el.hbk",
    "/opt/1cv8/8.5.1.1150/schemui_uk.hbk",
]

BASE_OUR = Path("data/compare_unpack/our")
BASE_TOC = Path("data/compare_unpack/toc")


def key_from_path(p: str) -> str:
    # e.g. /opt/1cv8/8.3.27.1719/extui_ru.hbk -> 8.3.27.1719_extui_ru
    path = Path(p)
    stem = path.stem
    parent = path.parent.name
    return f"{parent}_{stem}"


def count_files_and_size(root: Path) -> tuple[int, int]:
    if not root.exists():
        return 0, 0
    n, total = 0, 0
    for f in root.rglob("*"):
        if f.is_file():
            n += 1
            total += f.stat().st_size
    return n, total


def has_toc_json(root: Path) -> bool:
    return (root / ".toc.json").is_file()


def has_categories(root: Path) -> bool:
    for d in root.rglob("__categories__"):
        if d.is_file():
            return True
    return False


def run_unpack_our(hbk: str, out_dir: Path) -> bool:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "onec_help", "unpack", hbk, "-o", str(out_dir)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=Path(__file__).resolve().parent.parent,
            env={**os.environ, "PYTHONPATH": "src"},
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def run_read_hbk_container(hbk: str, out_dir: Path, toc_path: Path) -> bool:
    out_dir.mkdir(parents=True, exist_ok=True)
    toc_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "onec_help",
                "read-hbk-container",
                hbk,
                "--out-dir",
                str(out_dir),
                "--toc-json",
                str(toc_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=Path(__file__).resolve().parent.parent,
            env={**os.environ, "PYTHONPATH": "src"},
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    os.chdir(repo)
    BASE_OUR.mkdir(parents=True, exist_ok=True)
    BASE_TOC.mkdir(parents=True, exist_ok=True)

    missing = [p for p in HBK_SAMPLES if not Path(p).is_file()]
    if missing:
        print("Missing .hbk (run on machine with /opt/1cv8):", missing, file=sys.stderr)
        samples = [p for p in HBK_SAMPLES if Path(p).is_file()]
        if not samples:
            return 1
    else:
        samples = HBK_SAMPLES

    print("Unpacking", len(samples), "files: our unpacker vs read-hbk-container (TOC)")
    print()

    results_our: list[dict] = []
    results_toc: list[dict] = []

    for hbk in samples:
        key = key_from_path(hbk)
        our_dir = BASE_OUR / key
        toc_dir = BASE_TOC / key
        toc_json_path = toc_dir / ".toc.json"

        # Our unpacker (7z → zipfile → offset → unzip → scan → container)
        ok_our = run_unpack_our(hbk, our_dir)
        n_our, sz_our = count_files_and_size(our_dir)
        results_our.append({
            "key": key,
            "ok": ok_our,
            "files": n_our,
            "size": sz_our,
            "toc_json": has_toc_json(our_dir),
            "categories": has_categories(our_dir),
        })

        # Container + TOC
        ok_toc = run_read_hbk_container(hbk, toc_dir, toc_json_path)
        # read-hbk-container writes raw TOC bytes to --toc-json; for .toc.json name we have the file
        n_toc, sz_toc = count_files_and_size(toc_dir)
        results_toc.append({
            "key": key,
            "ok": ok_toc,
            "files": n_toc,
            "size": sz_toc,
            "toc_file": toc_json_path.is_file(),
            "categories": has_categories(toc_dir),
        })

    # Report
    print("=" * 80)
    print("OUR UNPACKER (unpack_hbk: 7z → zipfile → offset → unzip → scan → container)")
    print("=" * 80)
    for r in results_our:
        status = "ok" if r["ok"] else "FAIL"
        toc = "TOC" if r["toc_json"] else "-"
        cat = "cat" if r["categories"] else "-"
        print(f"  {r['key']:<35} {status:>4}  files={r['files']:>5}  size={r['size']:>10}  {toc} {cat}")

    print()
    print("=" * 80)
    print("CONTAINER + TOC (read-hbk-container --out-dir --toc-json)")
    print("=" * 80)
    for r in results_toc:
        status = "ok" if r["ok"] else "FAIL"
        toc = "TOC" if r["toc_file"] else "-"
        cat = "cat" if r["categories"] else "-"
        print(f"  {r['key']:<35} {status:>4}  files={r['files']:>5}  size={r['size']:>10}  {toc} {cat}")

    print()
    print("Summary:")
    our_ok = sum(1 for r in results_our if r["ok"])
    toc_ok = sum(1 for r in results_toc if r["ok"])
    our_files = sum(r["files"] for r in results_our)
    toc_files = sum(r["files"] for r in results_toc)
    our_with_toc = sum(1 for r in results_our if r["toc_json"])
    toc_with_toc = sum(1 for r in results_toc if r["toc_file"])
    print(f"  Our unpacker:  {our_ok}/{len(samples)} succeeded, {our_files} total files, {our_with_toc} with .toc.json")
    print(f"  Container:     {toc_ok}/{len(samples)} succeeded, {toc_files} total files, {toc_with_toc} with TOC file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
