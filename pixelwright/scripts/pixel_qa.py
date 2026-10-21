#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Deterministic grid-compliance auditor for AI-generated pixel art.

This tool checks whether the submitted *rendered image* can be represented as
uniform nearest-neighbor blocks on an explicitly declared logical pixel grid.
It does not judge whether the art is good or whether the sprite is on-model.

Requires: Pillow, NumPy. Python 3.12+.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

VERSION = "0.6.1"
MAX_PIXELS = 12_000_000
MAX_PREVIEW_DIMENSION = 2048


@dataclass
class Audit:
    result: dict[str, Any]
    logical_pixels: np.ndarray
    violation: np.ndarray | None
    source: Image.Image
    cell_size: tuple[int, int]
    exact_nonuniform: np.ndarray | None = None


def validate_size(size: tuple[int, int], *, name: str, logical: bool = False) -> None:
    if (not isinstance(size, (tuple, list)) or len(size) != 2
            or any(not isinstance(v, int) or isinstance(v, bool) or v < 1 for v in size)):
        raise ValueError(f"{name} must contain two positive integer dimensions")
    if logical and any(v > 4096 for v in size):
        raise ValueError("logical dimensions must each be 1..4096")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_new_files(paths: list[Path]) -> None:
    """Reject collisions before writing any output, including symlinks."""
    for path in paths:
        if path.exists() or path.is_symlink():
            raise ValueError(f"Output already exists; choose a fresh output directory: {path}")


def validate_output_dir(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"Output directory must be empty or nonexistent: {path}")
    if path.is_symlink():
        raise ValueError(f"Output directory must not be a symlink: {path}")


def parse_size(text: str) -> tuple[int, int]:
    s = text.lower().replace(" ", "")
    parts = s.split("x")
    if len(parts) != 2 or any(not v.isdecimal() for v in parts):
        raise argparse.ArgumentTypeError("logical size must be WIDTHxHEIGHT, e.g. 32x32")
    w, h = map(int, parts)
    if not (1 <= w <= 4096 and 1 <= h <= 4096):
        raise argparse.ArgumentTypeError("logical dimensions must each be 1..4096")
    return w, h


def grid_geometry(
    rendered: tuple[int, int],
    logical: tuple[int, int],
    expected_rendered: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Validate the *declared* logical grid; never infer or resample it.

    With logical (W,H) and rendered (w,h), a true uniformly enlarged square
    pixel must have one positive integer factor S: w=W*S and h=H*S.
    """
    validate_size(rendered, name="rendered size")
    validate_size(logical, name="logical size", logical=True)
    if expected_rendered is not None:
        validate_size(expected_rendered, name="expected rendered size")
    w, h = rendered
    lw, lh = logical
    scale_x, scale_y = w / lw, h / lh
    exact_division = w >= lw and h >= lh and w % lw == 0 and h % lh == 0
    square = exact_division and (w // lw == h // lh)
    issues: list[dict[str, str]] = []
    if expected_rendered and rendered != expected_rendered:
        issues.append({
            "code": "RENDER_SIZE_MISMATCH", "severity": "fail",
            "detail": f"Expected {expected_rendered[0]}x{expected_rendered[1]} px, got {w}x{h} px.",
        })
    if not exact_division:
        issues.append({
            "code": "NON_INTEGER_PIXEL_SCALE", "severity": "fail",
            "detail": (
                f"Logical {lw}x{lh} requires integer-sized pixel cells, but "
                f"the displayed scale is {scale_x:.5f}x{scale_y:.5f}. "
                "There can be no exact square-pixel grid on these dimensions."
            ),
        })
    elif not square:
        issues.append({
            "code": "NON_SQUARE_CELL", "severity": "fail",
            "detail": f"A logical pixel covers {w//lw}x{h//lh} source pixels, which is rectangular.",
        })
    return {
        "status": "pass" if not issues else "fail",
        "rendered_size": {"width": w, "height": h},
        "logical_size": {"width": lw, "height": lh},
        "expected_render_size": (
            {"width": expected_rendered[0], "height": expected_rendered[1]}
            if expected_rendered else None
        ),
        "scale_x": round(scale_x, 8),
        "scale_y": round(scale_y, 8),
        "exact_integer_division": exact_division,
        "square_logical_pixel": square,
        "integer_scale": int(w // lw) if square else None,
        "issues": issues,
    }


def open_rgba(path: Path) -> Image.Image:
    """Decode a static PNG with lossless expansion to RGBA8.

    The guarantee concerns decoded RGBA8 values, not PNG compression bytes,
    palette indices, display color management, or EXIF-oriented presentation.
    """
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"File not found: {path}")
    with path.open("rb") as stream:
        header = stream.read(33)
        if len(header) != 33 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            raise ValueError("Input must be a static PNG expandable losslessly to RGBA8")
        # Reject resource-heavy dimensions before scanning chunks or invoking
        # Pillow, whose decompression-bomb threshold is larger than our limit.
        width, height = struct.unpack(">II", header[16:24])
        if width == 0 or height == 0:
            raise ValueError("PNG dimensions must be positive")
        if width * height > MAX_PIXELS:
            raise ValueError(f"Image too large: max {MAX_PIXELS:,} pixels")
        if header[24] not in (1, 2, 4, 8):
            raise ValueError("Input PNG must use at most 8-bit samples; 16-bit downconversion is forbidden")
        # Even a one-frame APNG is an animation container. Do not silently
        # certify just its first frame as though it were the complete asset.
        while True:
            chunk_header = stream.read(8)
            if len(chunk_header) != 8:
                raise ValueError("Invalid PNG chunk structure")
            length, chunk_type = struct.unpack(">I4s", chunk_header)
            if chunk_type == b"acTL":
                raise ValueError("Animated PNG is unsupported; audit individual static frames")
            stream.seek(length + 4, 1)
            if chunk_type == b"IEND":
                break
    with Image.open(path) as loaded:
        if loaded.format != "PNG" or getattr(loaded, "n_frames", 1) != 1:
            raise ValueError("Input must be a static PNG expandable losslessly to RGBA8")
        if loaded.width * loaded.height > MAX_PIXELS:
            raise ValueError(f"Image too large: max {MAX_PIXELS:,} pixels")
        image = loaded.convert("RGBA")
    image.info["pixelwright_source_sha256"] = sha256_file(path)
    image.info["pixelwright_source_path"] = str(path.resolve())
    return image


def normalize_rgba(arr: np.ndarray) -> np.ndarray:
    """Canonicalize invisible RGB samples when the visible policy is selected."""
    copied = arr.copy()
    copied[copied[:, :, 3] == 0, :3] = 0
    return copied


def dominant_color(pixels: np.ndarray) -> np.ndarray:
    """Choose an actual observed pixel; avoid introducing a blur/interpolated color."""
    values, counts = np.unique(pixels.reshape(-1, 4), axis=0, return_counts=True)
    max_count = counts.max()
    candidates = values[counts == max_count]
    if len(candidates) == 1:
        return candidates[0]
    med = np.median(pixels, axis=0)
    dif = candidates.astype(np.float64) - med
    return candidates[np.argmin(np.sum(dif * dif, axis=1))]


def count_visible_colors(arr: np.ndarray) -> int:
    visible = arr[arr[:, :, 3] > 0, :3]
    return int(len(np.unique(visible, axis=0))) if len(visible) else 0


def isolated_color_pixels(arr: np.ndarray, sample_limit: int = 30) -> tuple[int, list[dict[str, int]]]:
    """Count pixels lacking exact 8-connected same-color neighbors; no deletion.

    Vectorized for fast audits of native-resolution assets. This is a *candidate*
    metric and may include legitimate eyes, highlights, stars, and dither.
    """
    h, w, _ = arr.shape
    has_match = np.zeros((h, w), dtype=np.bool_)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            y0, y1 = max(0, -dy), min(h, h-dy)
            x0, x1 = max(0, -dx), min(w, w-dx)
            same = (arr[y0:y1, x0:x1] == arr[y0+dy:y1+dy, x0+dx:x1+dx]).all(axis=2)
            has_match[y0:y1, x0:x1] |= same
    is_isolated = (arr[:, :, 3] > 0) & ~has_match
    count = int(np.count_nonzero(is_isolated))
    points = np.argwhere(is_isolated)[:sample_limit]
    return count, [{"x": int(x), "y": int(y)} for y, x in points]


def inspect_image(
    image: Image.Image,
    logical_size: tuple[int, int],
    *,
    tolerance: int = 0,
    min_grid_score: float = 100.0,
    max_colors: int | None = None,
    strict_alpha: bool = False,
    strict_cells: bool = True,
    transparent_rgb: str = "exact",
) -> Audit:
    validate_size(logical_size, name="logical size", logical=True)
    validate_size(image.size, name="image size")
    if image.width * image.height > MAX_PIXELS:
        raise ValueError(f"Image too large: max {MAX_PIXELS:,} pixels")
    if image.mode != "RGBA":
        raise ValueError("inspect_image requires a decoded RGBA8 image; use open_rgba for PNG inputs")
    if transparent_rgb not in ("exact", "visible"):
        raise ValueError("transparent_rgb must be 'exact' or 'visible'")
    lw, lh = logical_size
    width, height = image.size
    if width < lw or height < lh or width % lw or height % lh:
        raise ValueError(
            f"Image {width}x{height} cannot be evenly divided into logical "
            f"{lw}x{lh}. Choose an exact divisor; do not treat resized output "
            f"as evidence of original grid compliance."
        )
    if not isinstance(tolerance, int) or isinstance(tolerance, bool) or tolerance < 0 or tolerance > 64:
        raise ValueError("tolerance must be 0..64")
    if not math.isfinite(min_grid_score) or min_grid_score < 0 or min_grid_score > 100:
        raise ValueError("min grid score must be 0..100")
    if max_colors is not None and (not isinstance(max_colors, int) or isinstance(max_colors, bool) or not 1 <= max_colors <= 256):
        raise ValueError("max colors must be 1..256")

    sx, sy = width // lw, height // lh
    raw_arr = np.asarray(image, dtype=np.uint8)
    arr = normalize_rgba(raw_arr) if transparent_rgb == "visible" else raw_arr
    # (logical_y, logical_x, source-pixels-per-cell, RGBA)
    cells = arr.reshape(lh, sy, lw, sx, 4).transpose(0, 2, 1, 3, 4).reshape(lh, lw, sx * sy, 4)

    # Exact equality is the primary contract. For each (x,y) logical grid
    # cell, ALL rendered RGBA samples must be equal (zero tolerance).
    # Visible mode alone ignores hidden RGB under alpha zero.
    exact_uniform = np.all(cells == cells[:, :, :1, :], axis=(2, 3))
    exact_bad_cells = int(np.count_nonzero(~exact_uniform))

    if sx == 1 and sy == 1:
        logical_pixels = arr.copy()  # direct native-size copy; no measurable intra-cell variation
        violation = np.zeros((lh, lw), dtype=np.float64)
    else:
        logical_pixels = np.empty((lh, lw, 4), dtype=np.uint8)
        violation = np.zeros((lh, lw), dtype=np.float64)
        # Exact mode for compact sprite grids; vectorized medoid for very large
        # ones to avoid hundreds of thousands of Python-level sort operations.
        if lw * lh <= 10_000:
            for y in range(lh):
                for x in range(lw):
                    px = cells[y, x]
                    chosen = dominant_color(px)
                    logical_pixels[y, x] = chosen
                    mismatch = (np.abs(px.astype(np.int16) - chosen.astype(np.int16)) > tolerance).any(axis=1)
                    violation[y, x] = float(mismatch.mean())
        else:
            flat = cells.reshape(lw * lh, sx * sy, 4)
            first = flat[:, 0, :].copy()
            variation = (np.abs(flat.astype(np.int16) - first[:, None, :].astype(np.int16)) > tolerance).any(axis=2)
            varied_indices = np.flatnonzero(variation.any(axis=1))
            if len(varied_indices):
                uncertain = flat[varied_indices]
                median = np.median(uncertain, axis=1)
                d = uncertain.astype(np.float32) - median[:, None, :]
                distances = (d*d).sum(axis=2)
                representative = uncertain[np.arange(len(uncertain)), np.argmin(distances, axis=1)]
                first[varied_indices] = representative
            logical_pixels = first.reshape(lh, lw, 4)
            changed = (np.abs(flat.astype(np.int16) - first[:, None, :].astype(np.int16)) > tolerance).any(axis=2)
            violation = changed.mean(axis=1).reshape(lh, lw)

    # At scale 1 there are no within-cell samples, so no grid fidelity measurement.
    measurable = sx > 1 or sy > 1
    mismatch_count = int(round(violation.sum() * sx * sy)) if measurable else None
    pixel_score = round(float(100 * (1.0 - violation.mean())), 4) if measurable else None
    bad_cells = int(np.count_nonzero(violation > 0)) if measurable else None
    visible = arr[:, :, 3] > 0
    partial_alpha = (arr[:, :, 3] > 0) & (arr[:, :, 3] < 255)
    partial_count = int(np.count_nonzero(partial_alpha))
    color_count = count_visible_colors(arr)
    logical_colors = count_visible_colors(logical_pixels)
    suspect_count, suspects = isolated_color_pixels(logical_pixels)

    issues: list[dict[str, Any]] = []
    if sx != sy:
        issues.append({
            "code": "NON_SQUARE_CELL", "severity": "fail",
            "detail": f"Rendered cell is {sx}x{sy}; square pixel scale requires equal axes.",
        })
    if strict_cells and measurable and exact_bad_cells:
        issues.append({
            "code": "NON_SOLID_GRID_CELLS", "severity": "fail",
            "detail": (
                f"{exact_bad_cells} / {lw*lh} declared pixel cells contain "
                "more than one exact visible RGBA value. A single inconsistent "
                "source pixel is sufficient to fail this strict check."
            ),
        })
    if not measurable:
        issues.append({
            "code": "NATIVE_RESOLUTION_GRID_UNMEASURABLE", "severity": "info",
            "detail": "At 1x scale, within-cell grid alignment is unmeasurable; image is already at logical resolution.",
        })
    elif bad_cells:
        issues.append({
            "code": "OFF_GRID_PIXELS", "severity": "fail" if pixel_score < min_grid_score else "review",
            "detail": f"{bad_cells} logical cells contain pixels inconsistent with their representative cell color.",
        })
    if max_colors is not None and color_count > max_colors:
        issues.append({
            "code": "PALETTE_OVER_BUDGET", "severity": "fail",
            "detail": f"Source image has {color_count} visible RGB colors; budget is {max_colors}.",
        })
    if partial_count:
        issues.append({
            "code": "PARTIAL_ALPHA", "severity": "fail" if strict_alpha else "review",
            "detail": f"{partial_count} source pixels have partial alpha (1..254). Intentional translucency is possible.",
        })
    if suspect_count:
        issues.append({
            "code": "COLOR_ISOLATION_CANDIDATES", "severity": "info",
            "detail": f"{suspect_count} logical pixels have no immediately adjacent pixel of exactly the same RGBA color. They may be intentional.",
        })
    if not np.any(arr[:, :, 3] < 255):
        issues.append({
            "code": "OPAQUE_BACKGROUND", "severity": "info",
            "detail": "No transparency is present. Foreground/background separation and silhouette checks cannot be inferred reliably.",
        })

    if not measurable and strict_cells:
        issues.append({
            "code": "NATIVE_RESOLUTION_NO_GRID_EVIDENCE", "severity": "review",
            "detail": "Every native pixel trivially forms a 1x1 cell; there is no enlarged block to test for uniformity.",
        })
    if any(i["severity"] == "fail" for i in issues):
        status = "fail"
    elif any(i["severity"] == "review" for i in issues):
        status = "review"
    else:
        status = "pass"

    worst: list[dict[str, Any]] = []
    if measurable:
        order = np.argsort(violation.ravel())[::-1]
        for flat_idx in order:
            y, x = divmod(int(flat_idx), lw)
            if violation[y, x] == 0 or len(worst) >= 12:
                break
            worst.append({
                "logical_x": x, "logical_y": y,
                "source_box": [x*sx, y*sy, (x+1)*sx - 1, (y+1)*sy - 1],
                "mismatch_ratio": round(float(violation[y, x]), 5),
                "exactly_uniform": bool(exact_uniform[y, x]),
                "distinct_visible_rgba_values": int(len(np.unique(cells[y, x], axis=0))),
            })

    exact_bad_samples = []
    for y, x in np.argwhere(~exact_uniform)[:20]:
        y, x = int(y), int(x)
        exact_bad_samples.append({
            "logical_x": x, "logical_y": y,
            "source_box": [x*sx, y*sy, (x+1)*sx - 1, (y+1)*sy - 1],
            "distinct_rgba_values": int(len(np.unique(cells[y, x], axis=0))),
        })

    report = {
        "tool": "Pixelwright", "version": VERSION, "schema_version": 1,
        "scope": "technical_checks_only_not_artistic_quality",
        "status": status,
        "input_size": {"width": width, "height": height},
        "logical_size": {"width": lw, "height": lh},
        "cell_size": {"width": sx, "height": sy},
        "strict_grid": strict_cells,
        "acceptance": "exact" if strict_cells else "diagnostic",
        "provenance": {
            "source_sha256": image.info.get("pixelwright_source_sha256"),
            "decoded_rgba_sha256": hashlib.sha256(raw_arr.tobytes()).hexdigest(),
            "sample_scope": "decoded_rgba8_without_exif_or_color_management",
            "transparent_rgb": transparent_rgb,
        },
        "settings": {
            "difference_tolerance_per_channel": tolerance,
            "minimum_grid_score": min_grid_score,
            "maximum_source_rgb_colors": max_colors,
            "strict_alpha": strict_alpha,
            "transparent_rgb": transparent_rgb,
        },
        "metrics": {
            "grid_score": pixel_score,
            "grid_measurable": measurable,
            "square_cell_geometry": sx == sy,
            "uniform_rgba_cells": int(lw * lh - exact_bad_cells),
            "nonuniform_rgba_cells": exact_bad_cells,
            "uniform_rgba_cell_fraction": round(float(exact_uniform.mean()), 8),
            "off_grid_source_pixels": mismatch_count,
            "off_grid_logical_cells": bad_cells,
            "total_logical_cells": lw * lh,
            "visible_rgb_colors_source": color_count,
            "visible_rgb_colors_logical_preview": logical_colors,
            "partial_alpha_source_pixels": partial_count,
            "possible_color_isolated_logical_pixels": suspect_count,
        },
        "worst_cells": worst,
        "nonuniform_rgba_cell_samples": exact_bad_samples,
        "nonuniform_rgba_cell_samples_truncated": exact_bad_cells > len(exact_bad_samples),
        "violation_mask": {
            "file": "violation_mask.png", "coordinate_space": "logical_grid",
            "encoding": "0=uniform,255=nonuniform", "width": lw, "height": lh,
        },
        "possible_isolated_pixels_sample": suspects,
        "issues": issues,
        "visual_review_required": [
            "Recognizable silhouette at logical resolution",
            "Intentional pixel clusters, shading, and outline design",
            "Anatomy, props, anatomy of motion, and style consistency",
            "Check if any grid projection loses important facial or object detail",
        ],
    }
    return Audit(report, logical_pixels, violation if measurable else None, image, (sx, sy), ~exact_uniform)


def checkerboard(size: tuple[int, int], square: int = 16) -> Image.Image:
    w, h = size
    board = Image.new("RGBA", size, (234, 234, 234, 255))
    draw = ImageDraw.Draw(board)
    for y in range(0, h, square):
        for x in range(0, w, square):
            if (x // square + y // square) % 2:
                draw.rectangle((x, y, min(x + square - 1, w-1), min(y + square - 1, h-1)), fill=(207, 207, 207, 255))
    return board


def over_background(image: Image.Image) -> Image.Image:
    return Image.alpha_composite(checkerboard(image.size), image.convert("RGBA"))


def create_grid_lines(
    rendered_size: tuple[int, int],
    logical_size: tuple[int, int],
    *,
    approximate: bool = False,
) -> Image.Image:
    """Create a transparent reference layer in ORIGINAL image coordinates.

    On a valid grid, these lines fall exactly on cell boundaries. With invalid
    input dimensions they only illustrate the proposed (fractional) partition;
    they are NOT proof that the geometry can be repaired by rounding.
    """
    w, h = rendered_size
    lw, lh = logical_size
    out = Image.new("RGBA", rendered_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(out)
    color = (245, 155, 40, 120) if approximate else (0, 215, 245, 130)
    # Show every declared cell boundary. Sampling axes independently can make
    # a valid square-cell image appear to have rectangular cells (e.g.320x224).
    # The right/bottom boundaries lie at w/h, outside the half-open canvas;
    # clamping them to w-1/h-1 would create a misleading shorter final cell.
    for x in range(lw):
        boundary = round(x * w / lw)
        draw.line((boundary, 0, boundary, h - 1), fill=color, width=1)
    for y in range(lh):
        boundary = round(y * h / lh)
        draw.line((0, boundary, w - 1, boundary), fill=color, width=1)
    return out


def save_overlay(audit: Audit, path: Path) -> None:
    base = over_background(audit.source)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    sx, sy = audit.cell_size
    lw = audit.result["logical_size"]["width"]
    lh = audit.result["logical_size"]["height"]
    bad_mask = audit.exact_nonuniform
    if bad_mask is None and audit.violation is not None:
        bad_mask = audit.violation > 0
    if bad_mask is not None:
        for y in range(lh):
            for x in range(lw):
                frac = float(audit.violation[y, x]) if audit.violation is not None else 0
                if bad_mask[y, x]:
                    # Even one off-grid source pixel should be immediately
                    # visible as a full red-marked logical cell.
                    opacity = min(190, max(125, round(frac * 190)))
                    bounds = (x*sx, y*sy, (x+1)*sx-1, (y+1)*sy-1)
                    draw.rectangle(bounds, fill=(255, 35, 45, opacity))
                    if min(sx, sy) >= 4:
                        draw.rectangle(bounds, outline=(255, 75, 60, 245), width=1)
    grid = create_grid_lines(base.size, (lw, lh))
    combined = Image.alpha_composite(Image.alpha_composite(base, overlay), grid)
    combined.convert("RGB").save(path)


def write_geometry_failure(
    image: Image.Image,
    logical_size: tuple[int, int],
    out_dir: Path,
    geometry: dict[str, Any],
) -> dict[str, str]:
    """Always output an actionable report/overlay for impossible grids."""
    ensure_new_files([out_dir / name for name in (
        "grid_lines.png", "grid_overlay.png", "report.json", "correction_prompt.txt")])
    out_dir.mkdir(parents=True, exist_ok=True)
    layer = create_grid_lines(image.size, logical_size, approximate=True)
    grid_path = out_dir / "grid_lines.png"
    layer.save(grid_path)
    overlay = Image.alpha_composite(over_background(image), layer)
    draw = ImageDraw.Draw(overlay, "RGBA")
    draw.rectangle((0, 0, min(image.width, 470), 34), fill=(100, 10, 10, 235))
    draw.text((10, 10), "INVALID GRID: orange lines are approximate", fill=(255, 255, 255, 255))
    overlay_path = out_dir / "grid_overlay.png"
    overlay.convert("RGB").save(overlay_path)
    report = {
        "tool": "Pixelwright", "version": VERSION, "schema_version": 1,
        "status": "fail", "scope": "geometry_check_only",
        "acceptance": "exact",
        "provenance": {
            "source_sha256": image.info.get("pixelwright_source_sha256"),
            "decoded_rgba_sha256": hashlib.sha256(np.asarray(image, dtype=np.uint8).tobytes()).hexdigest(),
            "sample_scope": "decoded_rgba8_without_exif_or_color_management",
        },
        "geometry": geometry,
        "input_size": geometry["rendered_size"],
        "logical_size": geometry["logical_size"],
        "metrics": {"grid_measurable": False, "grid_score": None,
                    "uniform_rgba_cells": None, "nonuniform_rgba_cells": None},
        "issues": geometry["issues"],
        "note": "No resampling performed; grid lines show proposed boundaries only.",
    }
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lw, lh = logical_size
    next_scale = max(1, round(image.width / lw))
    fix_dimensions = f"{lw * next_scale}x{lh * next_scale} (scale {next_scale}x)"
    correction = out_dir / "correction_prompt.txt"
    correction.write_text(
        f"Prepare a {lw}x{lh} logical pixel-art canvas with a single integer "
        f"square scale on both axes. Example valid render: {fix_dimensions}. "
        "Do not claim the original passed merely by resizing or rounding "
        "fractional grid lines. Render each cell as an exact RGBA solid block.\n",
        encoding="utf-8",
    )
    return {"report": str(report_path), "overlay": str(overlay_path),
            "grid_lines": str(grid_path), "correction_prompt": str(correction)}


def save_preview(logical_pixels: np.ndarray, path: Path, *, scale: int = 12) -> None:
    h, w, _ = logical_pixels.shape
    # A 4096-cell canvas must not become a 49152px preview. Never downsample
    # logical art; reduce only the integer enlargement, to 1x if necessary.
    scale = max(1, min(scale, MAX_PREVIEW_DIMENSION // max(w, h)))
    native = Image.fromarray(logical_pixels, "RGBA")
    out = native.resize((w * scale, h * scale), resample=Image.Resampling.NEAREST)
    over_background(out).convert("RGB").save(path)


def correction_prompt(report: dict[str, Any]) -> str:
    logical = report["logical_size"]
    size = f'{logical["width"]}x{logical["height"]}'
    lines = [
        "Rework the attached pixel-art sprite rather than merely applying a pixelation filter.",
        f"Design the art on an intentional {size} logical-pixel canvas.",
        "Use clear discrete pixel clusters, readable silhouette and clean stepped contours.",
        "Avoid anti-aliased edge blending, floating micro-detail, random isolated noise and soft painterly shading.",
        "Preserve the subject's identity, pose and important design elements.",
        "Render the final logical sprite with nearest-neighbor enlargement only.",
        "Avoid gradients and unplanned color variations within an intended logical pixel.",
    ]
    issues = {i["code"] for i in report["issues"]}
    if "OFF_GRID_PIXELS" in issues or "NON_SOLID_GRID_CELLS" in issues:
        lines.append("Important: the previous render violated the cell grid: each logical pixel must remain a solid single-color block.")
    if "NON_SQUARE_CELL" in issues:
        lines.append("Use square logical pixels, not rectangular tiles.")
    if "PALETTE_OVER_BUDGET" in issues:
        budget = report["settings"].get("maximum_source_rgb_colors", report["settings"].get("maximum_logical_rgb_colors"))
        lines.append(f'Keep the final source to at most {budget} visible RGB colors, using deliberate value ramps.')
    if "PARTIAL_ALPHA" in issues:
        lines.append("Prefer hard opaque/transparent silhouette pixels unless translucent effects are intentional.")
    priority_cells = report["worst_cells"] or report.get("nonuniform_rgba_cell_samples", [])
    if priority_cells:
        cells = ", ".join(f'({c["logical_x"]},{c["logical_y"]})' for c in priority_cells[:6])
        lines.append(f"Priority logical-grid regions to redesign: {cells} (coordinates are 0-based from top-left).")
    lines.extend([
        "Do not assume a visually pixelated picture meets this constraint: inspect the output again programmatically.",
        "NOTE: A generative image model cannot be guaranteed to produce mathematically exact grid-aligned pixels on request.",
    ])
    return "\n".join(lines) + "\n"


def quantize_logical_rgba(logical: np.ndarray, colors: int) -> np.ndarray:
    if not 1 <= colors <= 256:
        raise ValueError("palette color count must be between 1 and 256")
    out = logical.copy()
    opaque_mask = out[:, :, 3] > 0
    pixels = out[opaque_mask, :3]
    if len(pixels) < 1 or len(np.unique(pixels, axis=0)) <= colors:
        return out
    # Work on visible RGB only: background transparency is preserved separately.
    source = Image.fromarray(pixels.reshape((1, len(pixels), 3)), "RGB")
    paletted = source.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    out[opaque_mask, :3] = np.asarray(paletted.convert("RGB"), dtype=np.uint8).reshape(-1, 3)
    return out


def save_side_by_side(source: Image.Image, fixed: Image.Image, dest: Path,
                     *, right_title: str = "Grid projection (review before use)") -> None:
    w, h = source.size
    gap, margin, title_h = 20, 12, 30
    canvas = Image.new("RGB", (w*2 + gap + margin*2, h + title_h + margin*2), (32, 36, 44))
    left = over_background(source).convert("RGB")
    right = over_background(fixed).convert("RGB")
    canvas.paste(left, (margin, margin + title_h))
    canvas.paste(right, (margin + w + gap, margin + title_h))
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, margin+6), "Original", fill="white")
    draw.text((margin+w+gap, margin+6), right_title, fill="white")
    canvas.save(dest)


def write_audit(audit: Audit, out_dir: Path) -> dict[str, str]:
    ensure_new_files([out_dir / name for name in (
        "report.json", "grid_overlay.png", "grid_lines.png", "logical_preview.png",
        "violation_mask.png", "correction_prompt.txt")])
    out_dir.mkdir(parents=True, exist_ok=True)
    audit.result["grid_preview"] = {
        "sampled": False, "logical_cell_step": {"x": 1, "y": 1},
        "spacing_px": {"x": audit.cell_size[0], "y": audit.cell_size[1]},
        "outer_boundary": "right/bottom lie outside the half-open source canvas",
    }
    report = out_dir / "report.json"
    overlay = out_dir / "grid_overlay.png"
    grid_lines = out_dir / "grid_lines.png"
    preview = out_dir / "logical_preview.png"
    corrections = out_dir / "correction_prompt.txt"
    mask_path = out_dir / "violation_mask.png"
    save_overlay(audit, overlay)
    create_grid_lines(audit.source.size, (
        audit.result["logical_size"]["width"], audit.result["logical_size"]["height"]
    )).save(grid_lines)
    save_preview(audit.logical_pixels, preview)
    bad_mask = audit.exact_nonuniform
    if bad_mask is None:
        raise ValueError("Audit is missing its complete exact violation mask")
    Image.fromarray(bad_mask.astype(np.uint8) * 255, "L").save(mask_path)
    corrections.write_text(correction_prompt(audit.result), encoding="utf-8")
    report.write_text(json.dumps(audit.result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return {"report": str(report), "overlay": str(overlay), "grid_lines": str(grid_lines), "logical_preview": str(preview), "violation_mask": str(mask_path), "correction_prompt": str(corrections)}


def fix_image(
    audit: Audit,
    out_dir: Path,
    *,
    palette: int | None = None,
    hard_alpha: bool = False,
) -> dict[str, str]:
    if audit.cell_size[0] != audit.cell_size[1]:
        raise ValueError("Cannot project a square grid onto rectangular rendered cells")
    ensure_new_files([out_dir / name for name in (
        "fixed_native.png", "fixed_upscaled.png", "comparison.png")])
    out_dir.mkdir(parents=True, exist_ok=True)
    pixels = audit.logical_pixels.copy()
    if palette is not None:
        pixels = quantize_logical_rgba(pixels, palette)
    if hard_alpha:
        pixels[:, :, 3] = np.where(pixels[:, :, 3] >= 128, 255, 0).astype(np.uint8)
        pixels[pixels[:, :, 3] == 0, :3] = 0
    native = Image.fromarray(pixels, "RGBA")
    native_path = out_dir / "fixed_native.png"
    upscaled_path = out_dir / "fixed_upscaled.png"
    compared_path = out_dir / "comparison.png"
    native.save(native_path)
    upscaled = native.resize(audit.source.size, resample=Image.Resampling.NEAREST)
    upscaled.save(upscaled_path)
    save_side_by_side(audit.source, upscaled, compared_path)
    return {"fixed_native": str(native_path), "fixed_upscaled": str(upscaled_path), "comparison": str(compared_path)}


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit AI pixel-art grid compliance; optional deterministic projection (not artistic polishing).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subs = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "fix"):
        p = subs.add_parser(action, help="Technical audit" if action == "inspect" else "Audit and export projected sprite")
        p.add_argument("image", type=Path, help="Input image (PNG preferred)")
        p.add_argument("--logical-size", required=True, type=parse_size, help="Intended pixel grid, e.g. 32x32")
        p.add_argument("--render-size", type=parse_size, help="Optional required physical PNG dimensions, e.g. 512x768")
        p.add_argument("--out-dir", type=Path, default=Path("pixel-qa-output"))
        p.add_argument("--tolerance", type=int, default=0, help="Diagnostics only: RGBA mismatch tolerance; strict cell uniformity still uses exact equality")
        p.add_argument("--min-grid-score", type=float, default=100.0, help="Threshold for failed grid fidelity; defaults to perfection")
        p.add_argument("--relaxed-grid", action="store_true", help="Opt out of exact RGBA uniform-cell enforcement (not suitable for strict asset QA)")
        p.add_argument("--max-colors", type=int, help="Fail if the source exceeds this visible RGB color count")
        p.add_argument("--transparent-rgb", choices=("exact", "visible"), default="exact",
                       help="exact checks hidden RGB too; visible ignores RGB when alpha is zero")
        p.add_argument("--strict-alpha", action="store_true", help="Fail rather than review when encountering partial transparency")
        p.add_argument("--fail-on-violation", action="store_true", help="Exit with code 2 for review/fail, suitable for CI")
        if action == "fix":
            p.add_argument("--palette", type=int, help="Optionally quantize corrected sprite to at most N visible colors (1..256)")
            p.add_argument("--hard-alpha", action="store_true", help="Round alpha to 0 or 255; may lose translucent detail")
    args = parser.parse_args(argv)
    try:
        validate_output_dir(args.out_dir)
        image = open_rgba(args.image)
        geometry = grid_geometry(image.size, args.logical_size, args.render_size)
        if geometry["status"] != "pass":
            paths = write_geometry_failure(image, args.logical_size, args.out_dir, geometry)
            print(json.dumps({"status": "fail", "geometry": geometry, "outputs": paths}, ensure_ascii=False, indent=2))
            return 2
        audit = inspect_image(
            image, args.logical_size, tolerance=args.tolerance,
            min_grid_score=args.min_grid_score, max_colors=args.max_colors,
            strict_alpha=args.strict_alpha, strict_cells=not args.relaxed_grid,
            transparent_rgb=args.transparent_rgb,
        )
        paths = write_audit(audit, args.out_dir)
        final_audit = audit
        if args.action == "fix":
            paths.update(fix_image(audit, args.out_dir, palette=args.palette, hard_alpha=args.hard_alpha))
            fixed = open_rgba(Path(paths["fixed_upscaled"]))
            post_audit = inspect_image(
                fixed, args.logical_size, tolerance=args.tolerance,
                min_grid_score=args.min_grid_score, max_colors=args.max_colors,
                strict_alpha=args.strict_alpha, strict_cells=not args.relaxed_grid,
                transparent_rgb=args.transparent_rgb,
            )
            final_audit = post_audit
            post_report_path = args.out_dir / "post_report.json"
            post_mask_path = args.out_dir / "post_violation_mask.png"
            post_audit.result["violation_mask"]["file"] = post_mask_path.name
            Image.fromarray(post_audit.exact_nonuniform.astype(np.uint8) * 255, "L").save(post_mask_path)
            post_report_path.write_text(json.dumps(post_audit.result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            paths["post_report"] = str(post_report_path)
            paths["post_violation_mask"] = str(post_mask_path)
            pre_pixels = np.asarray(audit.source, dtype=np.uint8)
            post_pixels = np.asarray(fixed, dtype=np.uint8)
            visible_changed = int(np.count_nonzero(np.any(normalize_rgba(pre_pixels) != normalize_rgba(post_pixels), axis=2)))
            changed = int(np.count_nonzero(np.any(pre_pixels != post_pixels, axis=2)))
            impact = {
                "changed_source_pixels": changed,
                "changed_source_pixel_fraction": round(changed / (fixed.width * fixed.height), 6),
                "changed_visible_source_pixels": visible_changed,
                "original_status": audit.result["status"],
                "original_source_sha256": audit.result["provenance"]["source_sha256"],
                "fixed_source_sha256": post_audit.result["provenance"]["source_sha256"],
                "post_projection_technical_status": post_audit.result["status"],
                "post_projection_grid_score": post_audit.result["metrics"]["grid_score"],
                "post_projection_visible_logical_colors": post_audit.result["metrics"]["visible_rgb_colors_logical_preview"],
                "disclaimer": "Grid compliance after projection is expected by construction, NOT independent proof of sprite or art quality. Review comparison.png before using.",
            }
            impact_path = args.out_dir / "fix_review.json"
            impact_path.write_text(json.dumps(impact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            paths["fix_review"] = str(impact_path)
            paths["note"] = "Grid projection can remove detail; review comparison.png before adopting. Original was not overwritten."
        summary = {"status": final_audit.result["status"], "original_status": audit.result["status"],
                   "metrics": final_audit.result["metrics"], "outputs": paths}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        # Inspections with verified failed constraints return a nonzero process
        # status by default, making it useful as a CI quality gate.
        if final_audit.result["status"] == "fail":
            return 2
        return 2 if args.fail_on_violation and final_audit.result["status"] != "pass" else 0
    except (ValueError, OSError, MemoryError) as exc:
        print(f"Pixelwright error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
