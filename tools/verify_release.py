#!/usr/bin/env python3
"""Execute a trusted Pixelwright ZIP's builder and strict gate.

Only use archives built from reviewed source. Manifest hashes check consistency,
not authenticity; this tool executes the extracted Python scripts.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from PIL import Image

from package_skill import verify


def run(script, args, expected):
    result = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True)
    if result.returncode != expected:
        raise ValueError(f"{script.name}: expected {expected}, got {result.returncode}: {result.stderr}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        integrity = verify(args.archive)
        with zipfile.ZipFile(args.archive) as archive:
            if "pixelwright/SKILL.md" not in archive.namelist():
                raise ValueError("Provide the installation ZIP, not the development kit")
            out = args.out_dir.resolve()
            if out == args.archive.resolve() or out in args.archive.resolve().parents:
                raise ValueError("Output directory cannot contain the archive")
            if args.out_dir.is_symlink() or (out.exists() and (not out.is_dir() or any(out.iterdir()))):
                raise ValueError("Output directory must be empty or nonexistent")
            out.mkdir(parents=True, exist_ok=True)
            archive.extractall(out)
        skill = out / "pixelwright"
        build = out / "build"
        audit = out / "audit"
        builder = skill / "scripts" / "pixel_build.py"
        checker = skill / "scripts" / "pixelwright.py"
        profile = skill / "examples" / "item-profile.json"
        run(builder, ["--spec", skill / "examples" / "lantern.json", "--out-dir", build], 0)
        run(checker, ["inspect", build / "rendered.png", "--profile", profile, "--out-dir", audit], 0)
        report = json.loads((audit / "report.json").read_text(encoding="utf-8"))
        source_hash = hashlib.sha256((build / "rendered.png").read_bytes()).hexdigest()
        damaged = out / "damaged.png"
        with Image.open(build / "rendered.png") as original:
            image = original.convert("RGBA")
        image.putpixel((0, 0), (1, 0, 0, 0))
        image.save(damaged)
        failed_audit = out / "failed-audit"
        run(checker, ["inspect", damaged, "--profile", profile, "--out-dir", failed_audit], 2)
        failed = json.loads((failed_audit / "report.json").read_text(encoding="utf-8"))
        if failed["metrics"]["nonuniform_rgba_cells"] != 1:
            raise ValueError("One damaged source sample must produce exactly one invalid cell")
        if source_hash != hashlib.sha256((build / "rendered.png").read_bytes()).hexdigest():
            raise ValueError("Original generated PNG changed")
        summary = {"archive": integrity, "valid_status": report["status"], "valid_cells": report["metrics"]["uniform_rgba_cells"],
                   "damaged_status": failed["status"], "damaged_cells": failed["metrics"]["nonuniform_rgba_cells"],
                   "source_unchanged": True}
        (out / "release-check.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        print(f"Release check error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
