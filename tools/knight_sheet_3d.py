#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare and audit state sheets generated from the metric Blender knight rig.

One identity image, then one image-generation job per action. Frame slots, world
scale and camera are immutable: no independent crop, fit, recenter or scale repair.
The image provider is external; prompts.json can be sent by a host image tool or
by knight_generate_frames.py. Original generation files remain untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import knight_rig_3d as rig

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "pixelwright" / "scripts" / "pixel_sprite.py"
TOKENS = "123456789ABCDEFGHIJKLMNOPQRSTUV"
BACKGROUND = (32, 42, 56, 255)


def write_json(path, document):
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_layout(contract):
    if (contract["frame_size"] != [128, 128] or contract["sheet_columns"] != 3
            or not contract["animations"]
            or any(len(a["frames"]) != 6 for a in contract["animations"].values())):
        raise ValueError("This knight recipe requires 128x128 frames and six poses in three columns per action")


def load_run(run):
    settings = json.loads((run / "run.json").read_text(encoding="utf-8"))
    contract_path = run / "contract.json"
    if digest(contract_path) != settings["contract_sha256"]:
        raise ValueError("The frozen contract changed after preparation")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    validate_layout(contract)
    rig_dir = Path(settings["rig_dir"])
    if digest(rig_dir / "rig.json") != settings["rig_sha256"]:
        raise ValueError("The 3D rig changed after preparing generation guides")
    for relative, expected in settings.get("guide_sha256", {}).items():
        if digest(run / relative) != expected:
            raise ValueError(f"Frozen generation guide changed: {relative}")
    for relative, expected in settings.get("rig_image_sha256", {}).items():
        if digest(rig_dir / relative) != expected:
            raise ValueError(f"Frozen rendered mesh reference changed: {relative}")
    if rig.validate_contract(contract)["status"] != "pass":
        raise ValueError("The metric 3D rig failed validation")
    return settings, contract, rig_dir


def fresh(path):
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"Use a new or empty output directory: {path}")
    path.mkdir(parents=True, exist_ok=True)


def composite_guide(image):
    result = Image.new("RGBA", image.size, BACKGROUND)
    result.alpha_composite(image.convert("RGBA"))
    return result.convert("RGB")


def skeleton_overlay(image, frame, contract):
    image = image.copy().convert("RGBA")
    draw = ImageDraw.Draw(image)
    k = contract["guide_scale"]
    joints = frame["joints_image"]
    colors = [(255, 90, 100), (255, 195, 75), (110, 230, 160), (100, 180, 255)]
    for i, (a, b) in enumerate(contract["bones"].values()):
        points = [(joints[n][0] * k, joints[n][1] * k) for n in (a, b)]
        draw.line(points, fill=colors[i % len(colors)], width=3)
    for x, y in joints.values():
        draw.ellipse((x * k - 2, y * k - 2, x * k + 2, y * k + 2), fill="white")
    return image


def prepare(rig_dir, out):
    contract = json.loads((rig_dir / "rig.json").read_text())
    report = json.loads((rig_dir / "rig-check.json").read_text())
    if report["status"] != "pass" or rig.validate_contract(contract)["status"] != "pass":
        raise ValueError("The 3D rig must pass before preparing image-generation inputs")
    validate_layout(contract)
    fresh(out); (out / "guides").mkdir(); (out / "references").mkdir(); (out / "raw").mkdir()
    (out / "poses.json").write_text(json.dumps({"canvas": [1024, 1024]}) + "\n")
    frame_size = tuple(v * contract["guide_scale"] for v in contract["frame_size"])
    columns = contract["sheet_columns"]
    for state, animation in contract["animations"].items():
        rows = math.ceil(len(animation["frames"]) / columns)
        size = (frame_size[0] * columns, frame_size[1] * rows)
        sheets = {variant: Image.new("RGB", size, BACKGROUND[:3])
                  for variant in ("volume", "skeleton", "parts", "depth", "normal")}
        previews = []
        for index, frame in enumerate(animation["frames"]):
            origin = (index % columns * frame_size[0], index // columns * frame_size[1])
            beauty = composite_guide(Image.open(rig_dir / frame["guide"]))
            projected = skeleton_overlay(beauty, frame, contract).convert("RGB")
            for variant, image in [("volume", beauty), ("skeleton", projected)] + [
                    (kind, Image.open(rig_dir / frame[kind]).convert("RGB")) for kind in ("parts", "depth", "normal")]:
                sheets[variant].paste(image, origin)
            previews.append(projected.resize(tuple(contract["frame_size"]), Image.Resampling.NEAREST))
        for variant, image in sheets.items():
            image.save(out / "guides" / f"{state}-{variant}.png")
        previews[0].save(out / "guides" / f"{state}-3d.gif", save_all=True,
                         append_images=previews[1:], duration=[f["duration_ms"] for f in animation["frames"]], loop=0)
    anchor_frame = contract["animations"]["block"]["frames"][0]
    anchor = composite_guide(Image.open(rig_dir / anchor_frame["guide"]))
    anchor.save(out / "guides" / "anchor-volume.png")
    # A real indexed-cell sprite at the new detail density, instead of another
    # high-resolution model output masquerading as a low-resolution reference.
    style_source = ROOT / "pixelwright" / "examples" / "layered-scene" / "layers" / "character.png"
    source = Image.open(style_source).convert("RGBA")
    small = source.resize((64, 96), Image.Resampling.NEAREST)
    style = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    style.alpha_composite(small.resize((512, 768), Image.Resampling.NEAREST), (256, 128))
    style.save(out / "references" / "pixel-style.png")
    prompt_anchor = (
        "Edit image 1 into ONE finished hand-drawn 2D pixel-art game sprite on the same whole square canvas. "
        "Preserve the source composition, including the large empty margins. Image 2 is ONLY a pixel-art STYLE example: use its crisp clusters, "
        "single native-pixel outlines, restrained steel/red/brass palette and simple readable shading. "
        "Image 1 is the authoritative orthographic render of a real 3D skeleton with fixed armor and equipment. "
        "Reinterpret image 1 as hand-drawn 2D pixel art, keeping its exact camera, silhouette, body proportions, "
        "equipment sizes and pixel positions. Do not copy the pose or proportions of image 2. "
        "The character occupies only x=31.25%-67.19%, y=27.34%-88.28% of the full square canvas. "
        "Keep the same plain closed steel greathelm with a black visor and narrow brass ridge, broad pauldrons, "
        "breastplate, articulated limbs, brown belt, red steel-rimmed kite shield in the left hand and a flanged "
        "mace in the right hand. This is a TRUE 128x128 logical pixel canvas enlarged 8x: every visible dot "
        "is an 8x8 square; the knight itself is about 76 logical pixels tall. Build coherent 2-6 pixel "
        "shading clusters, not photographic stipple, tiny highlights or high-resolution painted texture. "
        "Strong one-logical-pixel dark outline; 24-31 solid colors, no gradients, no anti-aliasing, no glow. "
        "The entire empty background must be solid exact #FF00FF magenta. No floor, cast shadow, text, "
        "grid, guides or extra figures. Do not crop, zoom, recenter, change perspective or enlarge the model."
    )
    prompts = {"anchor": {"images": ["guides/anchor-volume.png", "references/pixel-style.png"],
                           "prompt": prompt_anchor, "output": "raw/anchor.png", "background": "opaque"}}
    for state, animation in contract["animations"].items():
        descriptions = "; ".join(f"{i + 1}: {f['description']}" for i, f in enumerate(animation["frames"]))
        prompts[state] = {
            "images": [f"guides/{state}-volume.png", "references/anchor-x8.png", f"guides/{state}-skeleton.png"],
            "output": f"raw/{state}.png", "size": "1536x1024", "background": "opaque",
            "prompt": (
                f"Edit image 1 into a finished 2D pixel-art {state.upper()} animation sprite sheet of exactly SIX poses, 3 columns by 2 rows, "
                "read left-to-right then top-to-bottom. Canvas exactly 1536x1024; each fixed cell is 512x512. "
                "Image 2 is the ONLY character identity and pixel style source. Preserve its helmet, face slit, "
                "body proportions, armor design, steel colors, brass trim, red kite shield and flanged mace. "
                "Images 1 and 3 show the SAME actual 3D knight skeleton, armor and equipment through ONE fixed "
                "orthographic camera. Image 1 is the authoritative 3D volume and occlusion reference; image 3 "
                "adds projected joints. For EACH cell, render image 1's exact pose as 2D pixel art in image 2's "
                "style. Keep all joint positions, silhouette extents and head/body/weapon sizes at the exact "
                "locations shown; do not center or fit each figure separately. Depth foreshortening and which "
                "arm or leg is in front come from the 3D guide. Never stretch or swap limbs. "
                f"The six phases are {descriptions}. "
                "Each cell represents the SAME 128x128 logical grid enlarged 4x: one dot is exactly 4x4 "
                "canvas pixels, identical pixel density across all six figures, same as the anchor at native "
                "resolution. Keep coherent pixel clusters and 1-native-pixel dark outlines; no extra texture, "
                "dithering, subpixel details, anti-aliasing, smooth rendering or glow. Shared 24-31 color palette. "
                "Background in ALL empty regions must be solid exact #FF00FF. No visible cell borders, "
                "skeletons, joint dots, guide colors, text, labels, numbers, floor or cast shadow. "
                "Preserve image 1's entire composition and large blank margins exactly. Each knight is about "
                "78 native pixels tall within its 128-pixel cell. Do not change camera, magnify the character, "
                "change canvas layout, omit a pose or merge cells."
            )}
    write_json(out / "contract.json", contract)
    write_json(out / "prompts.json", prompts)
    write_json(out / "run.json", {"schema_version": 1, "rig_dir": str(rig_dir.resolve()),
                                  "rig_sha256": digest(rig_dir / "rig.json"),
                                  "contract_sha256": digest(out / "contract.json"),
                                  "style_source": str(style_source), "style_source_sha256": digest(style_source),
                                  "guide_sha256": {str(p.relative_to(out)): digest(p) for p in sorted((out / "guides").glob("*.png"))},
                                  "rig_image_sha256": {str(p.relative_to(rig_dir)): digest(p) for p in sorted((rig_dir / "frames").rglob("*.png"))},
                                  "pixel_palette_size": 31, "frame_scale": 4,
                                  "reference": "https://github.com/aldegad/sprite-gen/tree/59b2738a2e76ed7043d9691a230396ed6374a336"})
    return {"status": "prepared", "run_dir": str(out.resolve()), "jobs": list(prompts)}


def snap_cells(image, logical_size):
    """One global registered lattice. Never resize or refit individual figures."""
    a = np.asarray(image.convert("RGBA"))
    width, height = logical_size
    if a.shape[0] * width != a.shape[1] * height or a.shape[0] < height * 2:
        raise ValueError(f"Generation aspect {image.size} does not match the fixed canvas {logical_size}")
    rgb = a[:, :, :3].astype(np.int16)
    chroma = (rgb[:, :, 0] > 150) & (rgb[:, :, 2] > 150) & (rgb[:, :, 1] < 115) & (
        np.minimum(rgb[:, :, 0], rgb[:, :, 2]) - rgb[:, :, 1] > 70)
    foreground = (a[:, :, 3] >= 128) & ~chroma
    # Providers need not return an integer enlargement (e.g. 1254x1254). Project
    # their entire fixed-aspect canvas onto the frozen grid, recording this as a
    # lossy derivative, never a PASS of the raw image. No frame is refitted.
    xs = np.floor(np.arange(width + 1) * a.shape[1] / width).astype(int)
    ys = np.floor(np.arange(height + 1) * a.shape[0] / height).astype(int)
    sx, sy = int(np.diff(xs).max()), int(np.diff(ys).max())
    xi = xs[:-1, None] + np.arange(sx); yi = ys[:-1, None] + np.arange(sy)
    valid_x = xi < xs[1:, None]; valid_y = yi < ys[1:, None]
    valid = (valid_y[:, :, None, None] & valid_x[None, None, :, :]).transpose(0, 2, 1, 3).reshape(height, width, -1)
    cells = a[np.minimum(yi, a.shape[0] - 1)[:, :, None, None],
              np.minimum(xi, a.shape[1] - 1)[None, None]].transpose(0, 2, 1, 3, 4).reshape(height, width, -1, 4)
    fg = foreground[np.minimum(yi, a.shape[0] - 1)[:, :, None, None],
                    np.minimum(xi, a.shape[1] - 1)[None, None]].transpose(0, 2, 1, 3).reshape(height, width, -1) & valid
    opaque = fg.sum(axis=2) > valid.sum(axis=2) / 2
    # Robust representative color. Outline bias is bounded to a 40% dark cluster,
    # preserving eyes/contours instead of turning fine highlights into noise.
    luminance = cells[:, :, :, :3] @ np.array((.299, .587, .114))
    dark = fg & (luminance < 65)
    use_dark = dark.sum(axis=2) >= np.maximum(1, fg.sum(axis=2)) * .40
    selected = np.where(use_dark[:, :, None], dark, fg)
    values = np.where(selected[:, :, :, None], cells[:, :, :, :3], np.nan)
    # Empty cells never contribute to the palette. Their arbitrary representative
    # is canonicalized to exact zero RGBA after quantization.
    values[~opaque, :, :] = 0
    colors = np.nanmedian(values, axis=2).astype(np.uint8)
    return colors, opaque


def calibrate_anchor(run):
    """Register the single identity image once, before any motion is generated.

    Image generators often auto-crop their first character. This is a disclosed
    one-time uniform scale of the base, not per-frame motion normalization.
    """
    settings, contract, rig_dir = load_run(run)
    raw = run / "raw" / "anchor.png"
    with Image.open(raw) as source:
        colors, mask = snap_cells(source, tuple(contract["frame_size"]))
        source_size = list(source.size)
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8); rgba[:, :, :3] = colors; rgba[:, :, 3] = mask * 255; rgba[~mask] = 0
    frame = contract["animations"]["block"]["frames"][0]
    ids = read_part_ids(rig_dir / frame["parts"], contract["part_colors"], contract["frame_size"])
    target_box = Image.fromarray((ids > 0).astype(np.uint8) * 255).getbbox()
    image = Image.fromarray(rgba, "RGBA"); source_box = image.getbbox()
    if not source_box or not target_box:
        raise ValueError("Anchor or 3D guide is empty")
    source_pose_check = inspect_pose(mask, ids, contract)
    source_width, source_height = source_box[2] - source_box[0], source_box[3] - source_box[1]
    target_width, target_height = target_box[2] - target_box[0], target_box[3] - target_box[1]
    already_registered = source_pose_check["status"] == "pass"
    # Rasterization and outlined pixel art need not have identical bounding boxes.
    # A candidate that already passes the frozen registration gates must retain
    # its positions; even a one-cell enlargement can distort its head region.
    ratio = 1.0 if already_registered else min(target_width / source_width, target_height / source_height)
    size = (round(source_width * ratio), round(source_height * ratio))
    cropped = image.crop(source_box).resize(size, Image.Resampling.NEAREST)
    strip = Image.fromarray(np.asarray(cropped)[:, :, :3][np.asarray(cropped)[:, :, 3] > 0][None], "RGB")
    palette = strip.quantize(colors=settings["pixel_palette_size"], method=Image.Quantize.MEDIANCUT,
                             dither=Image.Dither.NONE)
    rgb = cropped.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE).convert("RGBA")
    rgb.putalpha(cropped.getchannel("A"))
    origin = source_box[:2] if already_registered else (
        round((target_box[0] + target_box[2] - size[0]) / 2), target_box[3] - size[1])
    canvas = Image.new("RGBA", tuple(contract["frame_size"]), (0, 0, 0, 0)); canvas.alpha_composite(rgb, origin)
    # Canonicalize hidden RGB for the exact RGBA contract.
    pixels = np.asarray(canvas).copy(); pixels[pixels[:, :, 3] == 0] = 0; canvas = Image.fromarray(pixels)
    canvas.save(run / "references" / "anchor-native.png")
    canvas.resize((1024, 1024), Image.Resampling.NEAREST).save(run / "references" / "anchor-x8.png")
    report = {"status": "calibrated_not_art_approval", "source": "raw/anchor.png", "source_sha256": digest(raw),
              "native_sha256": digest(run / "references" / "anchor-native.png"),
              "identity_sha256": digest(run / "references" / "anchor-x8.png"),
              "source_size": source_size, "logical_size": contract["frame_size"], "uniform_base_scale": ratio,
              "source_box": source_box, "target_box": target_box, "placed_origin": origin,
              "registration": "already_registered" if already_registered else "uniform_bbox_fit",
              "source_pose_check": source_pose_check,
              "pose_check": inspect_pose(pixels[:, :, 3] > 0, ids, contract),
              "disclosure": "One-time identity calibration before state generation; raw preserved. No motion frame fitting."}
    write_json(run / "references" / "anchor-calibration.json", report)
    return {"status": report["pose_check"]["status"], "artistic_status": "not_reviewed", "pose_status": report["pose_check"]["status"],
            "uniform_base_scale": ratio, "identity": str(run / "references" / "anchor-x8.png")}


def dilate(mask, radius):
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(
        ImageFilter.MaxFilter(radius * 2 + 1))) > 0 if radius else mask


def silhouette_metrics(actual, expected, slack):
    intersection = int((actual & expected).sum()); union = int((actual | expected).sum())
    return {"iou": intersection / max(1, union),
            "coverage": float((dilate(actual, slack) & expected).sum() / max(1, expected.sum())),
            "precision": float((actual & dilate(expected, slack)).sum() / max(1, actual.sum())),
            "actual_cells": int(actual.sum()), "guide_cells": int(expected.sum())}


def read_part_ids(path, colors, frame_size):
    rgb = np.asarray(Image.open(path).convert("RGB").resize(tuple(frame_size), Image.Resampling.NEAREST))
    palette = np.array([(0, 0, 0)] + list(colors.values()), dtype=np.int32)
    differences = ((rgb[:, :, None, :].astype(np.int32) - palette[None, None]) ** 2).sum(axis=3)
    ids = np.argmin(differences, axis=2)
    if int(np.take_along_axis(differences, ids[:, :, None], axis=2).max()) != 0:
        raise ValueError("The rendered part map is not an exact declared mesh-ID palette")
    return ids


def inspect_pose(actual, ids, contract):
    limits = contract["acceptance"]; expected = ids > 0
    metrics = silhouette_metrics(actual, expected, limits["silhouette_slack_cells"])
    issues = []
    for field, threshold in (("iou", limits["silhouette_iou_min"]),
                             ("coverage", limits["silhouette_coverage_min"]),
                             ("precision", limits["silhouette_precision_min"])):
        if metrics[field] < threshold:
            issues.append({"code": "PROJECTED_SILHOUETTE_" + field.upper(), "severity": "fail",
                           "actual": metrics[field], "minimum": threshold})
    # This is a regional coverage measurement, not an inferred semantic part map.
    # It cannot by itself prove a generated limb's identity or intrinsic length.
    part_coverage = {}
    for index, name in enumerate(contract["part_colors"], 1):
        mask = ids == index
        if mask.sum() >= 6:
            part_coverage[name] = float((dilate(actual, 1) & mask).sum() / mask.sum())
            if part_coverage[name] < .75:
                issues.append({"code": "PROJECTED_PART_REGION_EMPTY", "severity": "fail", "part": name,
                               "coverage": part_coverage[name], "minimum": .75})
    head_id = list(contract["part_colors"]).index("head") + 1
    head = ids == head_id
    if head.any():
        roi = dilate(head, 1)
        observed = actual & roi
        head_ratio = float(observed.sum() / head.sum())
        if observed.any():
            centroid_error = float(np.linalg.norm(np.argwhere(head).mean(axis=0) - np.argwhere(observed).mean(axis=0)))
        else:
            centroid_error = None
        metrics["head_roi_area_ratio"] = head_ratio; metrics["head_roi_center_error_cells"] = centroid_error
        lo, hi = limits["head_area_ratio"]
        if not lo <= head_ratio <= hi:
            issues.append({"code": "HEAD_REGION_SIZE_CHANGED", "severity": "fail", "actual": head_ratio, "range": [lo, hi]})
        if centroid_error is None or centroid_error > limits["head_center_error_max_cells"]:
            issues.append({"code": "HEAD_REGION_DRIFT", "severity": "fail", "error_cells": centroid_error})
    metrics["part_region_coverage"] = part_coverage
    return {"status": "fail" if issues else "pass", "metrics": metrics, "issues": issues,
            "scope": "registered_silhouette_and_projected_regions_not_generated_semantic_segmentation"}


def noise_metrics(rgba):
    """Diagnostic color singleton density; artistic acceptance stays a human review."""
    a = np.asarray(rgba); visible = a[:, :, 3] > 0
    same = np.zeros(visible.shape, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == dy == 0:
                continue
            shifted = np.roll(a, (dy, dx), axis=(0, 1))
            matches = np.all(a == shifted, axis=2)
            if dy > 0: matches[:dy] = False
            if dy < 0: matches[dy:] = False
            if dx > 0: matches[:, :dx] = False
            if dx < 0: matches[:, dx:] = False
            same |= matches
    singletons = int((visible & ~same).sum())
    return {"color_singleton_cells": singletons, "visible_cells": int(visible.sum()),
            "color_singleton_fraction": singletons / max(1, int(visible.sum()))}


def read_shared_palette(path, maximum):
    values = json.loads(path.read_text(encoding="utf-8"))["colors"]
    if not isinstance(values, list) or not 1 <= len(values) <= maximum:
        raise ValueError(f"The shared palette must contain 1-{maximum} opaque RGB colors")
    if any(not isinstance(v, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[fF]{2})?", v) for v in values):
        raise ValueError("Shared palette colors must be opaque #RRGGBB or #RRGGBBFF")
    colors = [tuple(int(v[i:i + 2], 16) for i in (1, 3, 5)) for v in values]
    if len(set(colors)) != len(colors):
        raise ValueError("The shared palette contains duplicate colors")
    return colors


def process(run, out, palette_path=None):
    settings, contract, rig_dir = load_run(run)
    fresh(out)
    frame_size = tuple(contract["frame_size"]); columns = contract["sheet_columns"]
    sources, sampled = {}, {}
    for state, animation in contract["animations"].items():
        path = run / "raw" / f"{state}.png"
        logical = (frame_size[0] * columns, frame_size[1] * math.ceil(len(animation["frames"]) / columns))
        with Image.open(path) as image:
            sampled[state] = snap_cells(image, logical)
            sources[state] = {"path": str(path.resolve()), "sha256": digest(path), "size": list(image.size)}
    # A single palette for the entire character, never per frame or per action.
    samples = np.concatenate([color[mask] for color, mask in sampled.values()])
    if len(samples) == 0:
        raise ValueError("Generated sheets contain no opaque character cells")
    if palette_path:
        colors = read_shared_palette(palette_path, settings["pixel_palette_size"])
    else:
        strip = Image.fromarray(samples[None], "RGB")
        quantized = strip.quantize(colors=settings["pixel_palette_size"], method=Image.Quantize.MEDIANCUT,
                                   dither=Image.Dither.NONE)
        flat = quantized.getpalette()
        colors = sorted({tuple(flat[3 * i:3 * i + 3]) for i in np.unique(np.asarray(quantized))},
                        key=lambda c: (.299 * c[0] + .587 * c[1] + .114 * c[2], c))
    palette = np.asarray(colors, dtype=np.int32)
    tokens = list(TOKENS[:len(colors)])
    palette_spec = {".": "#00000000", **{t: "#%02X%02X%02XFF" % c for t, c in zip(tokens, colors)}}
    frames, animations, pose_reports = [], {}, {}
    scale = settings["frame_scale"]
    contact = Image.new("RGBA", (frame_size[0] * 6, frame_size[1] * len(sampled)), (0, 0, 0, 0))
    overlay = Image.new("RGBA", contact.size, BACKGROUND)
    for state_index, (state, animation) in enumerate(contract["animations"].items()):
        color, mask = sampled[state]
        nearest = np.argmin(((color[:, :, None].astype(np.int32) - palette[None, None]) ** 2).sum(axis=3), axis=2)
        rgba = np.zeros((*mask.shape, 4), dtype=np.uint8); rgba[:, :, :3] = palette[nearest]; rgba[:, :, 3] = mask * 255
        rgba[~mask] = 0
        local_frames, state_reports, indices = [], [], []
        directory = out / "frames" / state; directory.mkdir(parents=True)
        for index, frame in enumerate(animation["frames"]):
            x = (index % columns) * frame_size[0]; y = (index // columns) * frame_size[1]
            pixels = rgba[y:y + frame_size[1], x:x + frame_size[0]].copy()
            ids = read_part_ids(rig_dir / frame["parts"], contract["part_colors"], frame_size)
            report = inspect_pose(pixels[:, :, 3] > 0, ids, contract)
            report.update({"frame": index, "description": frame["description"], "pixel_detail": noise_metrics(pixels)})
            state_reports.append(report)
            image = Image.fromarray(pixels, "RGBA"); image.save(directory / f"frame_{index:02d}.png")
            local_frames.append(image)
            contact.paste(image, (index * frame_size[0], state_index * frame_size[1]))
            under = composite_guide(image).convert("RGBA")
            guide_outline = np.asarray(Image.fromarray((ids > 0).astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0
            edge = guide_outline & ~(ids > 0)
            ov = np.asarray(under).copy(); ov[edge] = (80, 220, 255, 255)
            overlay.paste(skeleton_overlay(Image.fromarray(ov), frame, {**contract, "guide_scale": 1}),
                          (index * frame_size[0], state_index * frame_size[1]))
            token_array = np.asarray(tokens)[nearest[y:y + frame_size[1], x:x + frame_size[0]]]
            token_array = np.where(pixels[:, :, 3] > 0, token_array, ".")
            indices.append(len(frames)); frames.append({"rows": ["".join(row) for row in token_array]})
        durations = [f["duration_ms"] for f in animation["frames"]]
        animations[state] = {"frames": indices, "durations_ms": durations, "loop": animation["loop"]}
        pose_reports[state] = {"status": "fail" if any(r["status"] == "fail" for r in state_reports) else "pass",
                               "frames": state_reports}
        gif_frames = [composite_guide(im).resize((384, 384), Image.Resampling.NEAREST) for im in local_frames]
        gif_frames[0].save(out / f"{state}.gif", save_all=True, append_images=gif_frames[1:], duration=durations,
                           loop=0, disposal=2, optimize=False)
    contact.save(out / "sprite-sheet-native.png")
    contact.resize((contact.width * scale, contact.height * scale), Image.Resampling.NEAREST).save(out / "sprite-sheet.png")
    overlay.resize((overlay.width * 3, overlay.height * 3), Image.Resampling.NEAREST).save(out / "rig-overlay.png")
    spec = {"schema_version": 1, "name": "Knight from metric 3D rig", "frame_size": f"{frame_size[0]}x{frame_size[1]}",
            "layout": {"columns": 6, "rows": len(sampled), "spacing": 0}, "scale": scale,
            "palette": palette_spec, "frames": frames, "animations": animations}
    profile = {"schema_version": 1, "name": "3D knight sheet pixel contract",
               "logical_size": f"{contact.width}x{contact.height}", "scale": scale,
               "max_colors": settings["pixel_palette_size"], "alpha": "binary", "transparent_rgb": "exact",
               "allowed_palette": list(palette_spec.values())}
    write_json(out / "spec.json", spec); write_json(out / "profile.json", profile)
    checked = subprocess.run([sys.executable, str(SCRIPT), "check", "--spec", str(out / "spec.json"),
                              "--sheet", str(out / "sprite-sheet.png"), "--profile", str(out / "profile.json"),
                              "--out-dir", str(out / "pixel-check")], capture_output=True, text=True)
    (out / "pixel-check.log").write_text(checked.stdout + checked.stderr, encoding="utf-8")
    if checked.returncode not in (0, 2):
        raise RuntimeError(f"Pixel checker failed to execute: {checked.stderr}")
    pixel_report = json.loads((out / "pixel-check" / "sprite_report.json").read_text())
    technical = "pass" if pixel_report["status"] == "pass" else "fail"
    pose_status = "fail" if any(r["status"] == "fail" for r in pose_reports.values()) else "pass"
    runtime = {"game_input": "sprite-sheet.png", "frame_layout": {"sheetWidth": contact.width * scale,
                "sheetHeight": contact.height * scale, "cellWidth": frame_size[0] * scale,
                "cellHeight": frame_size[1] * scale, "rows": {}}, "animations": animations}
    for row, (state, animation) in enumerate(contract["animations"].items()):
        runtime["frame_layout"]["rows"][state] = [{"x": i * frame_size[0] * scale, "y": row * frame_size[1] * scale,
                                                   "w": frame_size[0] * scale, "h": frame_size[1] * scale}
                                                  for i in range(len(animation["frames"]))]
    write_json(out / "manifest.json", runtime)
    report = {"schema_version": 1, "status": "pass" if technical == pose_status == "pass" else "fail",
              "pixel_status": technical, "pose_status": pose_status, "artistic_status": "not_reviewed",
              "scope": "pixel_contract_and_registered_3d_projection_not_artistic_acceptance",
              "rig_check": rig.validate_contract(contract), "source_images": sources,
              "originals_unchanged": all(digest(Path(v["path"])) == v["sha256"] for v in sources.values()),
              "frame_size": list(frame_size), "scale": scale, "shared_palette_colors": len(colors),
              "palette_source": {"path": str(palette_path.resolve()), "sha256": digest(palette_path)} if palette_path else "joint_median_cut",
              "resampling": "one_registered_lattice_no_individual_frame_fit", "animations": pose_reports,
              "limitations": ["Generated semantic part labels are not inferred from nearest bones.",
                              "Part-region coverage does not prove intrinsic generated limb dimensions.",
                              "Silhouette and head ROI gates require visual review of occlusion, foot order and pixel clusters."]}
    write_json(out / "report.json", report)
    return {"status": report["status"], "pixel_status": technical, "pose_status": pose_status,
            "artistic_status": report["artistic_status"], "run": str(out.resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare"); prep.add_argument("--rig-dir", required=True, type=Path)
    prep.add_argument("--out-dir", required=True, type=Path)
    anchor = commands.add_parser("anchor"); anchor.add_argument("--run-dir", required=True, type=Path)
    check = commands.add_parser("check"); check.add_argument("--run-dir", required=True, type=Path)
    check.add_argument("--out-dir", required=True, type=Path)
    check.add_argument("--palette", type=Path, help="Optional shared opaque RGB palette, applied to every action")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.rig_dir, args.out_dir)
        elif args.command == "anchor":
            result = calibrate_anchor(args.run_dir)
        else:
            result = process(args.run_dir, args.out_dir, args.palette)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(str(error), file=sys.stderr); return 1
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
