#!/usr/bin/env python3
"""Build portable Pixelwright ZIPs and verify their structure and SHA-256 lists."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

VERSION = "0.6.1"
ROOT = Path(__file__).resolve().parents[1]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect(base: Path, prefix: str, include_tests: bool = True) -> dict[str, bytes]:
    entries = {}
    for path in sorted(base.rglob("*")):
        relative = path.relative_to(base)
        if not path.is_file() or any(p in ("__pycache__", ".venv") for p in relative.parts):
            continue
        if path.suffix == ".pyc" or (not include_tests and relative.parts[0] == "tests"):
            continue
        entries[f"{prefix}/{relative.as_posix()}"] = path.read_bytes()
    return entries


def write_zip(path: Path, entries: dict[str, bytes], top: str) -> None:
    manifest = "".join(f"{digest(data)}  {name[len(top)+1:]}\n" for name, data in sorted(entries.items()))
    entries = entries | {f"{top}/MANIFEST.sha256": manifest.encode("utf-8")}
    # Fixed metadata makes repeated builds identical within the same dependency environment.
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 14, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def verify(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        # ZipInfo normalizes Windows separators in filename; inspect the raw name too.
        if any("\\" in info.orig_filename for info in archive.infolist()):
            raise ValueError("Unsafe ZIP member")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("ZIP has duplicate members")
        for name in names:
            part = PurePosixPath(name)
            if part.is_absolute() or ".." in part.parts or "\\" in name or ":" in name:
                raise ValueError("Unsafe ZIP member")
        tops = {PurePosixPath(n).parts[0] for n in names}
        if len(tops) != 1:
            raise ValueError("Expected one top-level directory")
        top = next(iter(tops))
        if top not in ("pixelwright", "pixelwright-development-kit"):
            raise ValueError("Unexpected package root")
        required = f"{top}/SKILL.md" if top == "pixelwright" else f"{top}/pixelwright/SKILL.md"
        if required not in names:
            raise ValueError("Missing skill entrypoint")
        for legal_name in ("LICENSE", "NOTICE", "SECURITY.md"):
            if f"{top}/{legal_name}" not in names:
                raise ValueError(f"Missing legal or policy file: {legal_name}")
        manifest_name = f"{top}/MANIFEST.sha256"
        manifest = archive.read(manifest_name).decode("utf-8")
        covered = set()
        for line in manifest.splitlines():
            expected, relative = line.split("  ", 1)
            name = f"{top}/{relative}"
            if name in covered or name not in names or digest(archive.read(name)) != expected:
                raise ValueError(f"Manifest mismatch: {relative}")
            covered.add(name)
        if covered != set(names) - {manifest_name}:
            raise ValueError("Manifest does not cover every packaged file")
    return {"path": str(path.resolve()), "sha256": digest(path.read_bytes()), "files": len(names), "verified": True}


def run_cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--out-dir", type=Path)
    group.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.verify:
            print(json.dumps(verify(args.verify), indent=2))
            return 0
        args.out_dir.mkdir(parents=True, exist_ok=True)
        skill = collect(ROOT / "pixelwright", "pixelwright", include_tests=False)
        for name in ("LICENSE", "NOTICE", "SECURITY.md"):
            skill[f"pixelwright/{name}"] = (ROOT / name).read_bytes()
        installed = args.out_dir / f"pixelwright-v{VERSION}.zip"
        write_zip(installed, skill, "pixelwright")
        top = "pixelwright-development-kit"
        dev = collect(ROOT / "pixelwright", f"{top}/pixelwright")
        dev.update(collect(ROOT / "docs", f"{top}/docs"))
        dev.update(collect(ROOT / "tools", f"{top}/tools"))
        dev.update(collect(ROOT / ".github", f"{top}/.github"))
        for name in ("README.md", "README.ko.md", "LICENSE", "NOTICE", "SECURITY.md", ".gitignore", ".gitattributes"):
            dev[f"{top}/{name}"] = (ROOT / name).read_bytes()
        development = args.out_dir / f"pixelwright-development-kit-v{VERSION}.zip"
        write_zip(development, dev, top)
        results = [verify(installed), verify(development)]
        (args.out_dir / "SHA256SUMS").write_text("".join(f"{r['sha256']}  {Path(r['path']).name}\n" for r in results), encoding="utf-8")
        print(json.dumps(results, indent=2))
        return 0
    except (ValueError, OSError, zipfile.BadZipFile, KeyError) as exc:
        print(f"Package error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
