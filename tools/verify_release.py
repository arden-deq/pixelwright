#!/usr/bin/env python3
"""Execute a trusted Pixelwright ZIP's builder and strict gate.

Only use archives built from reviewed source. Manifest hashes check consistency,
not authenticity; this tool executes the extracted Python scripts.
"""
import argparse
import hashlib
import json
import shutil
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
        layers_tool = skill / "scripts" / "pixel_layers.py"
        scene = skill / "examples" / "layered-scene" / "scene.json"
        layer_output = out / "layered-scene"
        run(layers_tool, ["compose", "--manifest", scene, "--out-dir", layer_output], 0)
        layer_summary = json.loads((layer_output / "layers.json").read_text(encoding="utf-8"))
        if layer_summary["status"] != "pass" or layer_summary["final"]["status"] != "pass":
            raise ValueError("Installed layered scene must pass every layer and the final audit")
        if any(item["status"] != "pass" for item in layer_summary["results"]):
            raise ValueError("Installed scene contains a rejected layer")
        original_layer = scene.parent / "layers" / "title.png"
        original_layer_hash = hashlib.sha256(original_layer.read_bytes()).hexdigest()
        broken_input = out / "broken-layer-input"
        shutil.copytree(scene.parent, broken_input)
        damaged_layer = broken_input / "layers" / "title.png"
        with Image.open(damaged_layer) as original:
            altered = original.convert("RGBA")
        altered.putpixel((0, 0), (238, 235, 227, 255))
        altered.save(damaged_layer)
        broken_scene = broken_input / "scene.json"
        broken_document = json.loads(broken_scene.read_text(encoding="utf-8"))
        for item in broken_document["layers"]:
            if item["id"] == "title":
                item["visible"] = False
                item["sha256"] = hashlib.sha256(damaged_layer.read_bytes()).hexdigest()
        broken_scene.write_text(json.dumps(broken_document, indent=2) + "\n", encoding="utf-8")
        rejected_output = out / "rejected-layers"
        run(layers_tool, ["compose", "--manifest", broken_scene, "--out-dir", rejected_output], 2)
        rejected = json.loads((rejected_output / "layers.json").read_text(encoding="utf-8"))
        if rejected["status"] != "fail" or rejected["final"]["status"] != "not_composed":
            raise ValueError("A damaged hidden layer must prevent composition")
        if any((rejected_output / name).exists() for name in ("native.png", "rendered.png")):
            raise ValueError("Rejected layers must not produce accepted PNGs")
        if hashlib.sha256(original_layer.read_bytes()).hexdigest() != original_layer_hash:
            raise ValueError("Original installed layer changed during negative validation")
        summary = {"archive": integrity, "valid_status": report["status"], "valid_cells": report["metrics"]["uniform_rgba_cells"],
                   "damaged_status": failed["status"], "damaged_cells": failed["metrics"]["nonuniform_rgba_cells"],
                   "source_unchanged": True,
                   "layered_status": layer_summary["status"], "layer_count": len(layer_summary["results"]),
                   "layered_uniform_cells": json.loads((layer_output / "final/report.json").read_text(encoding="utf-8"))["metrics"]["uniform_rgba_cells"],
                   "hidden_damaged_layer_status": rejected["status"], "rejected_final_status": rejected["final"]["status"],
                   "original_layer_unchanged": True}
        (out / "release-check.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        print(f"Release check error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
