#!/usr/bin/env python3
"""Execute a trusted Pixelwright ZIP's builder, palettes, sprites, and strict gate.

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


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rgba_pixels(image):
    data = image.convert("RGBA").tobytes()
    return (tuple(data[offset:offset + 4]) for offset in range(0, len(data), 4))


def verify_grid_intervals(path, logical_size, scale):
    """Check every guide boundary on both axes in original image coordinates."""
    expected_size = (logical_size[0] * scale, logical_size[1] * scale)
    with Image.open(path) as grid:
        if grid.size != expected_size:
            raise ValueError("Installed grid guide must retain the original rendered dimensions")
        alpha = grid.convert("RGBA").getchannel("A")
    width, height = expected_size
    # Row/column 1 lie inside a cell, so perpendicular guide lines cannot hide
    # missing boundaries. Right/bottom boundaries lie outside the half-open canvas.
    x_alpha = alpha.crop((0, 1, width, 2)).tobytes()
    y_alpha = alpha.crop((1, 0, 2, height)).tobytes()
    actual_x = {index for index, opacity in enumerate(x_alpha) if opacity}
    actual_y = {index for index, opacity in enumerate(y_alpha) if opacity}
    expected_x = set(range(0, width, scale))
    expected_y = set(range(0, height, scale))
    if actual_x != expected_x or actual_y != expected_y:
        raise ValueError(f"Installed grid guide must show every {scale}px cell boundary on both axes")
    return {"layered_grid_x_interval": scale, "layered_grid_y_interval": scale,
            "layered_grid_all_boundaries": True}


def verify_palette_workflow(skill, out, source, damaged):
    """Exercise installed palette tools and independently inspect their PNGs."""
    palette_tool = skill / "scripts" / "pixel_palette.py"
    checker = skill / "scripts" / "pixelwright.py"
    builder = skill / "scripts" / "pixel_build.py"
    demo = skill / "examples" / "palette-demo"
    demo_spec, demo_palette, demo_profile = (demo / name for name in
                                             ("artwork.json", "palette.json", "profile.json"))
    demo_hashes = {path: file_hash(path) for path in (demo_spec, demo_palette, demo_profile)}
    demo_build, demo_audit = out / "palette-demo-build", out / "palette-demo-audit"
    run(builder, ["--spec", demo_spec, "--out-dir", demo_build], 0)
    demo_manifest = read_json(demo_build / "build.json")
    if (demo_manifest["grid"]["logical_width"], demo_manifest["grid"]["logical_height"],
            demo_manifest["grid"]["scale"]) != (16, 16, 8):
        raise ValueError("Bundled palette demonstration must retain its declared 16x16 scale-8 grid")
    if (demo_manifest["palette_source"]["sha256"] != demo_hashes[demo_palette]
            or Path(demo_manifest["palette_source"]["path"]).resolve() != demo_palette.resolve()):
        raise ValueError("Bundled palette demonstration must record the packaged palette's identity")
    run(checker, ["inspect", demo_build / "rendered.png", "--profile", demo_profile,
                  "--out-dir", demo_audit], 0)
    demo_report = read_json(demo_audit / "report.json")
    if demo_report["status"] != "pass" or demo_report["metrics"]["uniform_rgba_cells"] != 256:
        raise ValueError("Bundled palette demonstration must pass all 256 cells under its packaged profile")
    base_palette = out / "palette-base.json"
    base_palette.write_text(json.dumps({"schema_version": 1,
                                        "colors": {"transparent": "#00000000"},
                                        "ramps": {}}, indent=2) + "\n", encoding="utf-8")
    base_hash = file_hash(base_palette)
    palette_out = out / "palette-ramp"
    run(palette_tool, ["ramp", "--start", "#202030", "--end", "#F4BD52", "--steps", 5,
                       "--name", "metal", "--palette", base_palette, "--out-dir", palette_out], 0)
    palette_path = palette_out / "palette.json"
    palette_document = read_json(palette_path)
    ramp_tokens = palette_document["ramps"]["metal"]
    if len(ramp_tokens) != 5 or len(set(ramp_tokens)) != 5:
        raise ValueError("Installed ramp generator must emit five ordered reusable tokens")
    if (bytes.fromhex(palette_document["colors"][ramp_tokens[0]].lstrip("#")) != bytes.fromhex("202030FF")
            or bytes.fromhex(palette_document["colors"][ramp_tokens[-1]].lstrip("#")) != bytes.fromhex("F4BD52FF")):
        raise ValueError("Installed ramp generator must retain exact RGBA endpoints")
    ramp_colors = {tuple(bytes.fromhex(palette_document["colors"][token].lstrip("#")))
                   for token in ramp_tokens}
    # The same profile audits both source and result. Target palette membership
    # is checked separately so a palette transformation cannot relax source QA.
    profile = out / "palette-profile.json"
    profile.write_text(json.dumps({"schema_version": 1, "name": "release palette smoke",
                                   "logical_size": "16x16", "scale": 8, "max_colors": 16,
                                   "alpha": "binary", "transparent_rgb": "exact"}, indent=2) + "\n",
                       encoding="utf-8")
    input_hashes = {path: file_hash(path) for path in (source, damaged, profile, palette_path)}
    remap_out = out / "palette-remap"
    run(palette_tool, ["remap", source, "--palette", palette_path, "--profile", profile,
                       "--ramp", "metal", "--out-dir", remap_out], 0)
    remap_report = read_json(remap_out / "palette_report.json")
    if (remap_report["status"] != "pass" or remap_report["source"]["status"] != "pass"
            or remap_report["final"]["status"] != "pass"):
        raise ValueError("Installed remap must preserve source QA and pass final QA")
    remapped = remap_out / "rendered.png"
    independent_audit = out / "palette-remap-audit"
    run(checker, ["inspect", remapped, "--profile", profile, "--out-dir", independent_audit], 0)
    audited = read_json(independent_audit / "report.json")
    if audited["status"] != "pass":
        raise ValueError("Installed remap result must pass the original profile")
    with Image.open(source) as original, Image.open(remapped) as result:
        original_rgba = original.convert("RGBA")
        result_rgba = result.convert("RGBA")
        if original_rgba.size != result_rgba.size:
            raise ValueError("Remapping changed the source dimensions")
        if original_rgba.getchannel("A").tobytes() != result_rgba.getchannel("A").tobytes():
            raise ValueError("Remapping changed the source alpha plane")
        visible = {rgba for rgba in rgba_pixels(result_rgba) if rgba[3] != 0}
    if not visible or not visible <= ramp_colors:
        raise ValueError("Installed remap result contains colors outside the selected ramp")
    extraction_out = out / "palette-extract"
    run(palette_tool, ["extract", remapped, "--max-colors", 16, "--out-dir", extraction_out], 0)
    extracted = read_json(extraction_out / "palette.json")
    extracted_visible = {tuple(bytes.fromhex(color.lstrip("#")))
                         for color in extracted["colors"].values()
                         if bytes.fromhex(color.lstrip("#"))[-1] != 0}
    if extracted_visible != visible:
        raise ValueError("Exact extraction must preserve all remapped visible colors")
    reuse_spec = out / "palette-reuse.json"
    reuse_spec.write_text(json.dumps({"schema_version": 1, "scale": 8,
                                     "palette_file": "palette-ramp/palette.json",
                                     "rows": [[ramp_tokens[0], ramp_tokens[2], ramp_tokens[4]]]},
                                    indent=2) + "\n", encoding="utf-8")
    reuse_hash = file_hash(reuse_spec)
    reuse_out = out / "palette-reuse"
    run(builder, ["--spec", reuse_spec, "--out-dir", reuse_out], 0)
    with Image.open(reuse_out / "native.png") as reuse:
        actual = list(rgba_pixels(reuse))
    expected = [tuple(bytes.fromhex(palette_document["colors"][token].lstrip("#")))
                for token in (ramp_tokens[0], ramp_tokens[2], ramp_tokens[4])]
    if actual != expected:
        raise ValueError("Builder palette_file reuse did not preserve exact token colors")
    rejected_out = out / "palette-rejected"
    run(palette_tool, ["remap", damaged, "--palette", palette_path, "--profile", profile,
                       "--out-dir", rejected_out], 2)
    if any((rejected_out / name).exists() for name in ("native.png", "rendered.png")):
        raise ValueError("An invalid source grid must not produce an accepted remapped PNG")
    if read_json(rejected_out / "palette_report.json")["status"] != "fail":
        raise ValueError("An invalid source grid must retain a failed palette report")
    if any(file_hash(path) != expected_hash for path, expected_hash in input_hashes.items()):
        raise ValueError("A palette operation changed an original input")
    if any(file_hash(path) != expected_hash for path, expected_hash in demo_hashes.items()):
        raise ValueError("Building the bundled palette demonstration changed a packaged input")
    if file_hash(reuse_spec) != reuse_hash or file_hash(base_palette) != base_hash:
        raise ValueError("Builder palette reuse changed the source specification")
    return {"palette_demo_status": demo_report["status"],
            "palette_demo_cells": demo_report["metrics"]["uniform_rgba_cells"],
            "palette_demo_source_verified": True,
            "palette_ramp_steps": len(ramp_tokens), "palette_remap_status": audited["status"],
            "palette_remap_visible_colors": len(visible), "palette_target_verified": True,
            "palette_extraction_exact": True, "palette_builder_reuse": True,
            "palette_invalid_source_rejected": True, "palette_inputs_unchanged": True}


def verify_sprite_workflow(skill, out):
    """Build and check the installed rigged examples, then break one joint."""
    tool = skill / "scripts" / "pixel_sprite.py"
    results = {}
    for name, parts in (("sprite-walk", 8), ("sprite-lever", 3)):
        example = skill / "examples" / name
        spec, profile = example / "spec.json", example / "profile.json"
        hashes = {path: file_hash(path) for path in (spec, profile)}
        build, check = out / f"{name}-build", out / f"{name}-check"
        run(tool, ["build", "--spec", spec, "--out-dir", build], 0)
        manifest = read_json(build / "build.json")
        if manifest["outputs"]["rendered.png"]["sha256"] != file_hash(build / "rendered.png"):
            raise ValueError(f"Installed {name} build record must identify its rendered sheet")
        run(tool, ["check", "--spec", spec, "--sheet", build / "rendered.png", "--profile", profile,
                   "--out-dir", check], 0)
        report = read_json(check / "sprite_report.json")
        if (report["status"] != "pass" or report["sheet_audit"]["status"] != "pass"
                or report["checks"]["rig"] != "checked" or len(report["rig"]["parts"]) != parts):
            raise ValueError(f"Installed {name} must pass its sheet, frame and rig checks")
        previews = [*report["outputs"]["animation_previews"].values(), *report["outputs"]["rig_previews"].values()]
        for output in ["rig_overlay.png", "layout_overlay.png", *previews]:
            if not (check / output).is_file():
                raise ValueError(f"Installed {name} check must write {output}")
        for animation in report["animations"]:
            for kind in ("animation_previews", "rig_previews"):
                path = check / report["outputs"][kind][animation["id"]]
                with Image.open(path) as preview:
                    if preview.format != "GIF" or preview.n_frames != len(animation["frames"]):
                        raise ValueError(f"Installed {name} {kind} must retain every animation frame")
                    if (preview.info.get("loop") == 0) != animation["loop"]:
                        raise ValueError(f"Installed {name} {kind} must retain its loop policy")
                    duration = 0
                    for index in range(preview.n_frames):
                        preview.seek(index)
                        duration += preview.info.get("duration", 0)
                    if duration != animation["total_ms"]:
                        raise ValueError(f"Installed {name} {kind} must retain its playback duration")
        if any(file_hash(path) != digest for path, digest in hashes.items()):
            raise ValueError(f"Checking {name} changed a packaged input")
        results[name] = report["layout"]["frame_count"]
    # Exercise the installed encoder's timing boundary, keeping the game spec's
    # requested milliseconds distinct from GIF's representable 10 ms ticks.
    timing_spec = out / "short-gif-timing.json"
    timing_document = read_json(skill / "examples" / "sprite-walk" / "spec.json")
    for animation in timing_document["animations"].values():
        animation.pop("durations_ms", None)
        animation["frame_ms"] = 9
    timing_spec.write_bytes((json.dumps(timing_document, indent=2) + "\n").encode("utf-8"))
    timing_check = out / "short-gif-timing-check"
    run(tool, ["check", "--spec", timing_spec, "--sheet", out / "sprite-walk-build" / "rendered.png",
               "--profile", skill / "examples" / "sprite-walk" / "profile.json", "--out-dir", timing_check], 2)
    timing_report = read_json(timing_check / "sprite_report.json")
    if (timing_report["status"] != "review"
            or "GIF_TIMING_QUANTIZED" not in {issue["code"] for issue in timing_report["issues"]}):
        raise ValueError("Unrepresentable GIF timing must be disclosed as REVIEW")
    for animation in timing_report["animations"]:
        if animation["durations_ms"] != [9] * len(animation["frames"]):
            raise ValueError("GIF preview quantization must preserve requested game timings")
        for kind, timing_name in (("animation_previews", "art"), ("rig_previews", "rig")):
            metadata = animation["preview_timing"][timing_name]
            path = timing_check / timing_report["outputs"][kind][animation["id"]]
            with Image.open(path) as preview:
                durations = []
                for index in range(preview.n_frames):
                    preview.seek(index)
                    durations.append(preview.info.get("duration", 0))
            if (not metadata["metadata_verified"] or not metadata["quantized"]
                    or metadata["actual_durations_ms"] != durations
                    or any(value < 10 for value in durations)
                    or metadata["actual_total_ms"] != sum(durations)):
                raise ValueError("Installed GIF preview must retain its actual nonzero timing metadata")
    broken = out / "broken-lever-spec.json"
    document = read_json(skill / "examples" / "sprite-lever" / "spec.json")
    document["frames"][1]["joints"]["grip"][0] += 1
    broken.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    rejected = out / "broken-lever-check"
    run(tool, ["check", "--spec", broken, "--sheet", out / "sprite-lever-build" / "rendered.png",
               "--profile", skill / "examples" / "sprite-lever" / "profile.json", "--out-dir", rejected], 2)
    report = read_json(rejected / "sprite_report.json")
    found = {(issue["code"], issue.get("frame"), issue.get("part")) for issue in report["issues"]}
    if report["status"] != "fail" or ("PART_JOINT_MISMATCH", 1, "knob") not in found:
        raise ValueError("A rigid knob that no longer follows its pivot must fail the rig check")
    return {"sprite_walk_frames": results["sprite-walk"], "sprite_lever_frames": results["sprite-lever"],
            "sprite_examples_status": "pass", "sprite_gif_playback_verified": True,
            "sprite_gif_quantization_status": timing_report["status"], "sprite_gif_minimum_delay_verified": True,
            "sprite_broken_joint_status": report["status"]}


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
        palette_summary = verify_palette_workflow(skill, out, build / "rendered.png", damaged)
        layers_tool = skill / "scripts" / "pixel_layers.py"
        scene = skill / "examples" / "layered-scene" / "scene.json"
        layer_output = out / "layered-scene"
        run(layers_tool, ["compose", "--manifest", scene, "--out-dir", layer_output], 0)
        layer_summary = json.loads((layer_output / "layers.json").read_text(encoding="utf-8"))
        if layer_summary["status"] != "pass" or layer_summary["final"]["status"] != "pass":
            raise ValueError("Installed layered scene must pass every layer and the final audit")
        if any(item["status"] != "pass" for item in layer_summary["results"]):
            raise ValueError("Installed scene contains a rejected layer")
        grid_summary = verify_grid_intervals(layer_output / "final" / "grid_lines.png", (320, 224), 4)
        sprite_summary = verify_sprite_workflow(skill, out)
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
                   "original_layer_unchanged": True, **palette_summary, **grid_summary, **sprite_summary}
        (out / "release-check.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        print(f"Release check error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
