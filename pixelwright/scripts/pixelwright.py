#!/usr/bin/env python3
"""Profile gate for static PNG pixel art.

Declare the conditions (kind: sprite, sheet or image; dots; pixels per dot or
full PNG size; origin; sheet layout; alpha; palette). The gate builds the grid
from the declared origin and checks every sample of the decoded PNG against it:
image size, one RGBA value per cell, uniform margins, art drawn at the declared
dot size, transparency for sprites, frame slots for sheets, alpha policy, color
budget and allowed palette. Each condition is
reported as its own check; nothing is resized, rounded or inferred to pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

import pixel_qa as qa

VERSION = "0.7.0"
PROFILE_KEYS = {"schema_version", "name", "kind", "sheet", "logical_size", "scale", "image_size", "origin",
                "max_colors", "alpha", "transparent_rgb", "allowed_palette"}
KINDS = ("sprite", "sheet", "image")
KIND_HELP = ("kind is required: sprite (one subject on a transparent background), sheet (a sprite sheet of equal "
             "frames; also declare sheet), or image (a general picture, opaque by default)")
SHEET_KEYS = {"frame_size", "columns", "rows", "margin", "spacing", "frame_count", "edge_margin"}
MAX_SHEET_SLOTS = 1024
SHEET_CODES = ("GUTTER_NOT_EMPTY", "UNUSED_SLOT_NOT_EMPTY", "EMPTY_FRAME", "FRAME_WITHOUT_TRANSPARENCY",
               "EDGE_MARGIN_VIOLATION")
MAX_IMAGE_SIDE = 65535
# grid_overlay.png is enlarged by a whole number until each cell spans at least this many pixels.
OVERLAY_MIN_CELL = 4
# Rules that concern every decoded sample of the whole PNG. enforce_profile recomputes them on the
# complete image, so a crop or a caller's partial audit can never decide them.
WHOLE_IMAGE_CODES = {"PALETTE_OVER_BUDGET", "PARTIAL_ALPHA", "OPAQUE_BACKGROUND", "NON_OPAQUE_ALPHA",
                     "COLOR_OUTSIDE_ALLOWED_PALETTE", "EMPTY_IMAGE", "SPRITE_WITHOUT_TRANSPARENCY",
                     "COARSER_THAN_DECLARED"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_rgba(value: str) -> tuple[int, int, int, int]:
    if not isinstance(value, str) or re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value) is None:
        raise ValueError("Palette colors must be #RRGGBB or #RRGGBBAA")
    try:
        channels = tuple(int(value[i:i+2], 16) for i in range(1, len(value), 2))
    except ValueError as exc:
        raise ValueError(f"Invalid palette color: {value}") from exc
    return channels + (255,) if len(channels) == 3 else channels


def rgba_hex(rgba) -> str:
    return "#" + "".join(f"{int(v):02X}" for v in rgba)


def parse_image_size(value: Any) -> tuple[int, int]:
    if not isinstance(value, str) or re.fullmatch(r"\s*\d+\s*[xX]\s*\d+\s*", value) is None:
        raise ValueError("image_size must be WIDTHxHEIGHT in pixels, e.g. 512x512")
    width, height = (int(v) for v in value.lower().replace(" ", "").split("x"))
    if not (1 <= width <= MAX_IMAGE_SIDE and 1 <= height <= MAX_IMAGE_SIDE):
        raise ValueError(f"image_size dimensions must each be 1..{MAX_IMAGE_SIDE}")
    if width * height > qa.MAX_PIXELS:
        raise ValueError(f"image_size exceeds {qa.MAX_PIXELS:,} pixels")
    return width, height


def default_alpha(kind: str | None) -> str:
    """A general image is opaque unless declared otherwise; sprites and sheets have transparent backgrounds."""
    return "opaque" if kind == "image" else "binary"


def _bounded_int(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"sheet.{name} must be an integer in {low}..{high}")
    return value


def parse_sheet(value: Any) -> dict[str, Any]:
    """Validate a sprite-sheet layout; sizes are in logical dots, frames numbered row-major.

    width  = 2*margin + columns*frame_width  + (columns-1)*spacing
    height = 2*margin + rows*frame_height    + (rows-1)*spacing
    """
    if not isinstance(value, dict):
        raise ValueError("sheet must be an object with frame_size, columns and rows")
    unknown = set(value) - SHEET_KEYS
    if unknown:
        raise ValueError(f"Unknown sheet fields: {', '.join(sorted(unknown))}")
    if not isinstance(value.get("frame_size"), str):
        raise ValueError("sheet.frame_size must be WIDTHxHEIGHT in dots")
    try:
        fw, fh = qa.parse_size(value["frame_size"])
    except argparse.ArgumentTypeError as exc:
        raise ValueError(f"sheet.frame_size: {exc}") from exc
    for key in ("columns", "rows"):
        if key not in value:
            raise ValueError(f"sheet.{key} is required")
    columns = _bounded_int(value["columns"], "columns", 1, 4096)
    rows = _bounded_int(value["rows"], "rows", 1, 4096)
    capacity = columns * rows
    if capacity > MAX_SHEET_SLOTS:
        raise ValueError(f"A sheet holds at most {MAX_SHEET_SLOTS} frame slots")
    margin = _bounded_int(value.get("margin", 0), "margin", 0, 4096)
    spacing = _bounded_int(value.get("spacing", 0), "spacing", 0, 4096)
    frame_count = _bounded_int(value.get("frame_count", capacity), "frame_count", 1, capacity)
    edge_margin = _bounded_int(value.get("edge_margin", 0), "edge_margin", 0, max(0, (min(fw, fh) - 1) // 2))
    width = 2 * margin + columns * fw + (columns - 1) * spacing
    height = 2 * margin + rows * fh + (rows - 1) * spacing
    if width > 4096 or height > 4096:
        raise ValueError(f"The sheet is {width}x{height} dots; each side must be at most 4096")
    return {"frame_size": (fw, fh), "columns": columns, "rows": rows, "margin": margin, "spacing": spacing,
            "frame_count": frame_count, "edge_margin": edge_margin, "capacity": capacity,
            "sheet_size": (width, height)}


def sheet_slots(sheet: dict) -> list[tuple[int, int]]:
    """Top-left logical cell of every frame slot, row-major."""
    fw, fh = sheet["frame_size"]
    return [(sheet["margin"] + c * (fw + sheet["spacing"]), sheet["margin"] + r * (fh + sheet["spacing"]))
            for r in range(sheet["rows"]) for c in range(sheet["columns"])]


def alpha_policy(profile: dict) -> str:
    return profile.get("alpha", default_alpha(profile.get("kind")))


def resolve_layout(profile: dict) -> dict[str, Any]:
    """Turn the declared conditions into one exact grid, or explain why they contradict.

    The grid starts at `origin` (default 0,0) and has logical_size dots of
    scale x scale pixels. The PNG is image_size pixels; when it is larger than
    the grid, the rest is a declared margin. Missing scale is derived from
    image_size; missing image_size is the grid itself.
    """
    try:
        logical = qa.parse_size(profile["logical_size"])
    except argparse.ArgumentTypeError as exc:
        raise ValueError(str(exc)) from exc
    lw, lh = logical
    origin = tuple(profile.get("origin", (0, 0)))
    ox, oy = origin
    declared = parse_image_size(profile["image_size"]) if "image_size" in profile else None
    scale = profile.get("scale")
    if scale is None:
        span = (declared[0] - ox, declared[1] - oy)
        if min(span) < 1 or span[0] % lw or span[1] % lh or span[0] // lw != span[1] // lh:
            raise ValueError(
                f"image_size {declared[0]}x{declared[1]} from origin ({ox},{oy}) cannot hold {lw}x{lh} square dots "
                f"of one whole-pixel size ({span[0] / lw:.3f} x {span[1] / lh:.3f} px per dot). "
                "Fix the declared sizes, or declare scale explicitly when the image has a right or bottom margin.")
        scale = span[0] // lw
    grid = (lw * scale, lh * scale)
    if declared is None:
        if origin != (0, 0):
            raise ValueError("origin requires image_size, so the margins around the grid are declared")
        declared = grid
    if ox + grid[0] > declared[0] or oy + grid[1] > declared[1]:
        raise ValueError(
            f"The grid ({lw}x{lh} dots x {scale} px = {grid[0]}x{grid[1]} px from ({ox},{oy})) "
            f"does not fit in image_size {declared[0]}x{declared[1]}")
    if declared[0] * declared[1] > qa.MAX_PIXELS:
        raise ValueError(f"The contracted image exceeds {qa.MAX_PIXELS:,} pixels")
    return {"logical": logical, "scale": scale, "origin": (ox, oy), "grid_px": grid,
            "image_size": declared, "has_margin": declared != grid}


def load_profile(path: Path) -> dict:
    """Validate a profile and return it with the derived scale (and kind's alpha default) filled in."""
    def unique_object(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError(f"Duplicate profile field: {key}")
            values[key] = value
        return values
    profile = json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
    if not isinstance(profile, dict):
        raise ValueError("Profile must be a JSON object")
    unknown = set(profile) - PROFILE_KEYS
    if unknown:
        raise ValueError(f"Unknown profile fields: {', '.join(sorted(unknown))}")
    if type(profile.get("schema_version")) is not int or profile["schema_version"] != 1:
        raise ValueError("Profile schema_version must be 1")
    if "name" in profile and not isinstance(profile["name"], str):
        raise ValueError("Profile name must be a string")
    kind = profile.get("kind")
    if kind not in KINDS:
        raise ValueError(KIND_HELP + (f"; got {kind!r}" if kind is not None else ""))
    profile = dict(profile)
    if kind == "sheet":
        if "sheet" not in profile:
            raise ValueError("kind sheet requires a sheet object: frame_size, columns, rows "
                             "(optional margin, spacing, frame_count, edge_margin)")
        sheet = parse_sheet(profile["sheet"])
        derived = f"{sheet['sheet_size'][0]}x{sheet['sheet_size'][1]}"
        if "logical_size" in profile:
            try:
                declared = qa.parse_size(profile["logical_size"]) if isinstance(profile["logical_size"], str) else None
            except argparse.ArgumentTypeError as exc:
                raise ValueError(str(exc)) from exc
            if declared != sheet["sheet_size"]:
                raise ValueError(f"logical_size {profile['logical_size']} differs from the sheet layout's size "
                                 f"{derived}; omit logical_size or make them agree")
        profile["logical_size"] = derived
    elif "sheet" in profile:
        raise ValueError("sheet is only valid with kind sheet")
    if not isinstance(profile.get("logical_size"), str):
        raise ValueError("Profile logical_size must be WIDTHxHEIGHT in dots")
    if "scale" not in profile and "image_size" not in profile:
        raise ValueError("Declare scale (pixels per dot), image_size (full PNG size), or both")
    if "scale" in profile:
        scale = profile["scale"]
        if type(scale) is not int or not 1 <= scale <= 4096:
            raise ValueError("Profile scale must be an integer in 1..4096")
    if "origin" in profile:
        origin = profile["origin"]
        if (not isinstance(origin, list) or len(origin) != 2
                or any(type(v) is not int or not 0 <= v <= MAX_IMAGE_SIDE for v in origin)):
            raise ValueError("origin must be [x, y] with non-negative integer pixel coordinates")
    max_colors = profile.get("max_colors")
    if max_colors is not None and (type(max_colors) is not int or not 1 <= max_colors <= 256):
        raise ValueError("max_colors must be an integer in 1..256")
    alpha = profile.get("alpha", default_alpha(kind))
    if alpha not in ("binary", "opaque", "any"):
        raise ValueError("alpha must be binary, opaque, or any")
    if kind == "sprite" and alpha == "opaque":
        raise ValueError("A sprite needs a transparent background; use alpha binary or any, or kind image")
    if kind == "sheet" and alpha == "opaque" and (sheet["margin"] or sheet["spacing"]
                                                  or sheet["frame_count"] < sheet["capacity"]):
        raise ValueError("An opaque sheet cannot hold transparent margins, spacing or unused slots")
    if profile.get("transparent_rgb", "exact") not in ("exact", "visible"):
        raise ValueError("transparent_rgb must be exact or visible")
    palette = profile.get("allowed_palette")
    if palette is not None:
        if not isinstance(palette, list) or not 1 <= len(palette) <= 256:
            raise ValueError("allowed_palette must contain 1..256 colors")
        for value in palette:
            parse_rgba(value)
    layout = resolve_layout(profile)
    if layout["scale"] == 1 and max_colors is None and palette is None:
        raise ValueError(
            "A 1x profile (one image pixel per dot) must declare max_colors or allowed_palette: cell uniformity "
            "cannot be measured at 1x, so the palette rule is what catches blur and anti-aliasing")
    normalized = dict(profile)
    normalized.setdefault("scale", layout["scale"])
    normalized.setdefault("alpha", alpha)
    return normalized


def contract_options(profile: dict) -> tuple[tuple[int, int], tuple[int, int]]:
    """Logical and rendered size for tools whose grid fills the PNG from (0,0)."""
    layout = resolve_layout(profile)
    if layout["origin"] != (0, 0) or layout["has_margin"]:
        raise ValueError("This tool needs a profile whose grid fills the whole PNG from (0,0); "
                         "origin and margins are supported by pixelwright.py inspect/batch")
    return layout["logical"], layout["grid_px"]


def _status(issues: list[dict]) -> str:
    severities = {i["severity"] for i in issues}
    return "fail" if "fail" in severities else "review" if "review" in severities else "pass"


def sample_logical(arr: np.ndarray, report: dict) -> np.ndarray | None:
    """One sample per cell when the audited array is exactly the grid; None otherwise."""
    try:
        lw, lh = report["logical_size"]["width"], report["logical_size"]["height"]
        sx, sy = report["cell_size"]["width"], report["cell_size"]["height"]
    except (KeyError, TypeError):
        return None
    if arr.shape[:2] != (lh * sy, lw * sx):
        return None
    return arr[::sy, ::sx]


def enforce_profile(report: dict, image: Image.Image, profile: dict, *,
                    logical_pixels: np.ndarray | None = None, review_few_edges: bool = False) -> None:
    """Apply the whole-image rules to every decoded sample of `image`.

    Alpha, color budget and allowed palette concern all samples, including
    margins and colors a preview would discard. Content, sprite transparency
    and dot size concern the logical cells (`logical_pixels`, or one sample per
    cell when the image is exactly the grid).
    """
    raw = np.asarray(image, dtype=np.uint8)
    policy = profile.get("transparent_rgb", "exact")
    arr = qa.normalize_rgba(raw) if policy == "visible" else raw
    alpha = alpha_policy(profile)
    kind = profile.get("kind")
    issues = [i for i in report.get("issues", []) if i["code"] not in WHOLE_IMAGE_CODES]
    metrics = report.setdefault("metrics", {})
    settings = report.setdefault("settings", {})
    settings.update({"maximum_source_rgb_colors": profile.get("max_colors"), "alpha": alpha,
                     "strict_alpha": alpha == "binary", "transparent_rgb": policy, "kind": kind})

    a = arr[:, :, 3]
    partial = int(np.count_nonzero((a > 0) & (a < 255)))
    metrics["partial_alpha_source_pixels"] = partial
    metrics["transparent_source_pixels"] = int(np.count_nonzero(a == 0))
    if partial:
        issues.append({"code": "PARTIAL_ALPHA", "severity": "info" if alpha == "any" else "fail",
                       "detail": f"{partial} samples have partial alpha (1..254); the profile allows {alpha} alpha."})
    if alpha == "opaque":
        count = int(np.count_nonzero(a != 255))
        if count:
            issues.append({"code": "NON_OPAQUE_ALPHA", "severity": "fail",
                           "detail": f"{count} samples are not opaque; the profile requires alpha=255"
                                     + (" (kind image is opaque unless alpha says otherwise)." if kind == "image" else ".")})

    colors = qa.count_visible_colors(arr)
    metrics["visible_rgb_colors_source"] = colors
    if profile.get("max_colors") is not None and colors > profile["max_colors"]:
        issues.append({"code": "PALETTE_OVER_BUDGET", "severity": "fail",
                       "detail": f"The PNG has {colors} visible RGB colors; the budget is {profile['max_colors']}."})

    keys = np.ascontiguousarray(arr).view(np.dtype("V4")).reshape(arr.shape[:2])
    packed, counts = np.unique(np.ascontiguousarray(arr).view(np.uint32).ravel(), return_counts=True)
    values = packed.view(np.uint8).reshape(-1, 4)
    order = np.argsort(-counts, kind="stable")
    report["colors_used"] = [{"rgba": rgba_hex(values[i]), "samples": int(counts[i])} for i in order[:256]]
    report["colors_used_truncated"] = len(values) > 256
    allowed = profile.get("allowed_palette")
    if allowed is not None:
        colors_allowed = np.array([parse_rgba(v) for v in allowed], dtype=np.uint8)
        if policy == "visible":
            colors_allowed[colors_allowed[:, 3] == 0, :3] = 0
        # Packed RGBA keys avoid allocating a pixels x palette comparison tensor.
        allowed_keys = np.ascontiguousarray(colors_allowed).view(np.dtype("V4")).ravel()
        bad = ~np.isin(keys, allowed_keys)
        count = int(np.count_nonzero(bad))
        metrics["outside_palette_source_pixels"] = count
        report["outside_palette_sample"] = [{"x": int(x), "y": int(y)} for y, x in np.argwhere(bad)[:20]]
        allowed_set = {tuple(c) for c in colors_allowed.tolist()}
        report["outside_palette_colors"] = [c["rgba"] for c in report["colors_used"]
                                            if parse_rgba(c["rgba"]) not in allowed_set][:32]
        if count:
            issues.append({"code": "COLOR_OUTSIDE_ALLOWED_PALETTE", "severity": "fail",
                           "detail": f"{count} decoded RGBA samples are outside the declared palette: "
                                     f"{', '.join(report['outside_palette_colors'][:8])}."})

    cells = logical_pixels if logical_pixels is not None else sample_logical(arr, report)
    if cells is not None:
        if policy == "visible":
            cells = qa.normalize_rgba(np.asarray(cells, dtype=np.uint8))
        visible = cells[:, :, 3] > 0
        metrics["visible_cells"] = int(np.count_nonzero(visible))
        metrics["transparent_cells"] = int(np.count_nonzero(cells[:, :, 3] == 0))
        if visible.any():
            ys, xs = np.nonzero(visible)
            report["content_box"] = {"x": int(xs.min()), "y": int(ys.min()),
                                     "width": int(xs.max() - xs.min() + 1), "height": int(ys.max() - ys.min() + 1),
                                     "coordinate_space": "logical_grid"}
        else:
            issues.append({"code": "EMPTY_IMAGE", "severity": "fail",
                           "detail": "No cell has a visible color; the image is completely transparent."})
        if kind == "sprite" and metrics["transparent_cells"] == 0:
            issues.append({"code": "SPRITE_WITHOUT_TRANSPARENCY", "severity": "fail",
                           "detail": "The profile declares a sprite, but no cell is transparent: the background is "
                                     "painted, not transparent (a drawn checkerboard or flat backdrop is not "
                                     "transparency). Export with alpha 0 around the subject, or declare kind image."})
        lattice = qa.dot_lattice(cells)
        lh, lw = cells.shape[:2]
        kx, ky = lattice["dot_width"], lattice["dot_height"]
        report["dot_size"] = {**lattice, "coordinate_space": "logical_grid",
                              "effective_logical_size": {"width": -(-lw // kx), "height": -(-lh // ky)}}
        if lattice["measurable"] and max(kx, ky) > 1:
            suggestion = ""
            if lattice["phase_x"] == 0 and lattice["phase_y"] == 0 and lw % kx == 0 and lh % ky == 0 and kx == ky:
                scale = report.get("cell_size", {}).get("width") or profile.get("scale")
                if scale:
                    suggestion = (f" If that is the intent, declare logical_size {lw // kx}x{lh // ky} with scale "
                                  f"{scale * kx}.")
            severity = "fail" if lattice["conclusive"] else "review" if review_few_edges else "info"
            evidence = ("" if lattice["conclusive"] else
                        f" Only {lattice['column_edges']} column and {lattice['row_edges']} row color edges exist, "
                        "so simple art may line up by chance; compare it with art drawn at the declared size.")
            issues.append({"code": "COARSER_THAN_DECLARED", "severity": severity,
                           "detail": f"Every color edge on the declared {lw}x{lh} grid is {kx}x{ky} cells apart: "
                                     f"the art is drawn with {kx}x{ky}-cell dots, about {-(-lw // kx)}x{-(-lh // ky)} "
                                     f"real dots, not {lw}x{lh}. Redraw at the declared resolution."
                                     + suggestion + evidence})
    if kind is None and not np.any(arr[:, :, 3] < 255):
        issues.append({"code": "OPAQUE_BACKGROUND", "severity": "info",
                       "detail": "No transparency is present. Declare kind sprite or image to make that a rule."})
    report["issues"] = issues
    report["status"] = _status(issues)
    report["artistic_status"] = "not_reviewed"
    report["contract"] = profile


def require_empty_output(out_dir: Path, inputs: list[Path]) -> None:
    qa.validate_output_dir(out_dir)
    target = out_dir.resolve()
    for source in inputs:
        if source.resolve() == target or target in source.resolve().parents:
            raise ValueError("Output directory must not contain an input")


def check_geometry(size: tuple[int, int], layout: dict) -> dict[str, Any]:
    """Compare the PNG's size with the contract. The grid is never inferred from the image."""
    w, h = size
    lw, lh = layout["logical"]
    ew, eh = layout["image_size"]
    ox, oy = layout["origin"]
    gw, gh = layout["grid_px"]
    scale = layout["scale"]
    issues = []
    if (w, h) != (ew, eh):
        where = f" from origin ({ox},{oy})" if (ox, oy) != (0, 0) else ""
        margin = " plus the declared margin" if layout["has_margin"] else ""
        detail = (f"The contract needs a {ew}x{eh} px PNG ({lw}x{lh} dots x {scale} px{where}{margin}); "
                  f"this one is {w}x{h} px.")
        if not layout["has_margin"]:
            if w % lw == 0 and h % lh == 0 and w // lw == h // lh:
                detail += f" It would hold {lw}x{lh} dots at {w // lw} px each; check the declared scale."
            else:
                detail += (f" It cannot hold {lw}x{lh} square dots of one whole-pixel size "
                           f"({w / lw:.3f} x {h / lh:.3f} px per dot).")
        issues.append({"code": "RENDER_SIZE_MISMATCH", "severity": "fail", "detail": detail})
    return {
        "status": "fail" if issues else "pass",
        "rendered_size": {"width": w, "height": h},
        "expected_image_size": {"width": ew, "height": eh},
        "logical_size": {"width": lw, "height": lh},
        "integer_scale": scale,
        "origin": {"x": ox, "y": oy},
        "grid_box": [ox, oy, ox + gw - 1, oy + gh - 1],
        "has_margin": layout["has_margin"],
        "square_logical_pixel": True,
        "issues": issues,
    }


def detect_grid(image: Image.Image) -> dict[str, Any] | None:
    """Estimate the dot size and origin the pixels were actually drawn on, as a repair hint only."""
    lattice = qa.dot_lattice(np.asarray(image, dtype=np.uint8))
    kx, ky = lattice["dot_width"], lattice["dot_height"]
    if not lattice["measurable"] or max(kx, ky) < 2:
        return {"found": False, "detail": "No consistent dot lattice: color edges fall on every pixel spacing, as "
                                          "with blur, anti-aliasing, noise or resampling."}
    px, py = lattice["phase_x"], lattice["phase_y"]
    return {"found": True, "dot_width": kx, "dot_height": ky, "origin": [px, py],
            "logical_size_estimate": {"width": (image.width - px) // kx, "height": (image.height - py) // ky},
            "conclusive": lattice["conclusive"],
            "detail": "Estimated from color edges; declare it only if it matches the intended design. "
                      "A larger dot can hide a finer intended grid."}


def _margin_check(arr: np.ndarray, layout: dict) -> tuple[list[dict], dict, np.ndarray]:
    ox, oy = layout["origin"]
    gw, gh = layout["grid_px"]
    outside = np.ones(arr.shape[:2], dtype=bool)
    outside[oy:oy + gh, ox:ox + gw] = False
    samples = arr[outside]
    values, counts = np.unique(samples, axis=0, return_counts=True)
    info = {"margin_pixels": int(len(samples)), "margin_colors": [rgba_hex(v) for v in values[:8]],
            "margin_color_count": int(len(values))}
    stray = np.zeros(arr.shape[:2], dtype=bool)
    if len(values) > 1:
        stray = outside & np.any(arr != values[int(np.argmax(counts))], axis=2)
        info["margin_stray_pixels"] = int(np.count_nonzero(stray))
        info["margin_stray_sample"] = [{"x": int(x), "y": int(y)} for y, x in np.argwhere(stray)[:20]]
        return [{"code": "MARGIN_NOT_UNIFORM", "severity": "fail",
                 "detail": f"The margin outside the grid uses {len(values)} RGBA values ({info['margin_stray_pixels']} "
                           "pixels differ from the main margin color); it must be one solid color or transparency, "
                           "so no art spills off the declared grid."}], info, stray
    return [], info, stray


def check_sheet(cells: np.ndarray, profile: dict, report: dict) -> np.ndarray:
    """Apply the declared sheet layout to the logical cells; return a mask of offending cells.

    Margins, spacing and unused slots must be transparent; every used frame needs
    visible dots and (unless the sheet is opaque) a transparent background; no
    dot may enter a frame's declared edge margin.
    """
    sheet = parse_sheet(profile["sheet"])
    fw, fh = sheet["frame_size"]
    edge = sheet["edge_margin"]
    opaque = alpha_policy(profile) == "opaque"
    visible = cells[:, :, 3] > 0
    bad = np.zeros(visible.shape, dtype=bool)
    inside = np.zeros(visible.shape, dtype=bool)
    frames, issues = [], []
    empty, solid, edged, unused = [], [], [], []
    for index, (x, y) in enumerate(sheet_slots(sheet)):
        inside[y:y + fh, x:x + fw] = True
        frame = visible[y:y + fh, x:x + fw]
        if index >= sheet["frame_count"]:
            if frame.any():
                unused.append(index)
                bad[y:y + fh, x:x + fw] |= frame
            continue
        entry = {"index": index, "column": index % sheet["columns"], "row": index // sheet["columns"],
                 "box": {"x": x, "y": y, "width": fw, "height": fh}, "visible_cells": int(frame.sum())}
        if frame.any():
            ys, xs = np.nonzero(frame)
            entry["content_box"] = {"x": int(xs.min()), "y": int(ys.min()), "width": int(xs.max() - xs.min() + 1),
                                    "height": int(ys.max() - ys.min() + 1)}
            entry["touches_frame_edge"] = bool(xs.min() == 0 or ys.min() == 0 or xs.max() == fw - 1
                                               or ys.max() == fh - 1)
        else:
            empty.append(index)
        if not opaque and frame.all():
            solid.append(index)
        if edge:
            ring = np.ones((fh, fw), dtype=bool)
            ring[edge:fh - edge, edge:fw - edge] = False
            if (frame & ring).any():
                edged.append(index)
                bad[y:y + fh, x:x + fw] |= frame & ring
        frames.append(entry)
    gutter = visible & ~inside
    bad |= gutter
    if gutter.any():
        issues.append({"code": "GUTTER_NOT_EMPTY", "severity": "fail",
                       "detail": f"{int(gutter.sum())} visible cells lie in the sheet margin or spacing between "
                                 "frames; they must be transparent."})
    if unused:
        issues.append({"code": "UNUSED_SLOT_NOT_EMPTY", "severity": "fail",
                       "detail": f"Slots {unused[:20]} are beyond frame_count {sheet['frame_count']} but hold dots."})
    if empty:
        issues.append({"code": "EMPTY_FRAME", "severity": "review",
                       "detail": f"Frames {empty[:20]} have no visible dots; draw them or lower frame_count."})
    if solid:
        issues.append({"code": "FRAME_WITHOUT_TRANSPARENCY", "severity": "fail",
                       "detail": f"Frames {solid[:20]} have no transparent cell: the background is painted. "
                                 "Sheet frames are sprites on alpha 0."})
    if edged:
        issues.append({"code": "EDGE_MARGIN_VIOLATION", "severity": "fail",
                       "detail": f"Frames {edged[:20]} have dots inside the {edge}-cell edge margin; the art is "
                                 "clipped or bleeds into the next frame."})
    touching = [f["index"] for f in frames if f.get("touches_frame_edge")]
    if touching and not edge:
        issues.append({"code": "FRAME_CONTENT_AT_EDGE", "severity": "info",
                       "detail": f"Frames {touching[:20]} have dots on the frame edge; check that nothing is cut off, "
                                 "or declare edge_margin."})
    report["sheet"] = {"frame_size": {"width": fw, "height": fh}, "columns": sheet["columns"], "rows": sheet["rows"],
                       "margin": sheet["margin"], "spacing": sheet["spacing"], "frame_count": sheet["frame_count"],
                       "edge_margin": edge, "frames": frames, "coordinate_space": "logical_grid"}
    report["metrics"]["sheet_violation_cells"] = int(bad.sum())
    report["issues"].extend(issues)
    report["status"] = _status(report["issues"])
    return bad


def build_checks(report: dict, layout: dict, profile: dict, geometry_ok: bool) -> list[dict[str, Any]]:
    """One row per declared condition: what was required, what the PNG has, and the verdict."""
    codes: dict[str, str] = {}
    for issue in report["issues"]:
        if issue["severity"] in ("fail", "review") and codes.get(issue["code"]) != "fail":
            codes[issue["code"]] = issue["severity"]

    def verdict(*names: str) -> str:
        found = [codes[n] for n in names if n in codes]
        return "fail" if "fail" in found else "review" if found else "pass"

    m = report.get("metrics", {})
    lw, lh = layout["logical"]
    scale = layout["scale"]
    ox, oy = layout["origin"]
    w, h = report["geometry"]["rendered_size"]["width"], report["geometry"]["rendered_size"]["height"]
    ew, eh = layout["image_size"]
    checks = [{"id": "image_size", "status": verdict("RENDER_SIZE_MISMATCH"),
               "expected": f"{ew}x{eh} px = {lw}x{lh} dots x {scale} px from origin ({ox},{oy})"
                           + (" with margin" if layout["has_margin"] else ""),
               "actual": f"{w}x{h} px"}]
    not_measured = "not_measured (image size failed)"
    if layout["has_margin"]:
        checks.append({"id": "margin", "status": verdict("MARGIN_NOT_UNIFORM") if geometry_ok else "not_measured",
                       "expected": "one RGBA value outside the grid",
                       "actual": f"{m.get('margin_color_count')} values" if geometry_ok else not_measured})
    total = lw * lh
    if not geometry_ok:
        cell = ("not_measured", not_measured)
    elif scale == 1:
        cell = ("not_applicable", "1 px per dot: no samples inside a cell to compare")
    else:
        cell = (verdict("NON_SOLID_GRID_CELLS"), f"{m.get('nonuniform_rgba_cells')} of {total} cells mix colors")
    checks.append({"id": "cell_uniformity", "status": cell[0],
                   "expected": f"each of {total} cells ({scale}x{scale} px) is exactly one RGBA value",
                   "actual": cell[1]})
    dot = report.get("dot_size")
    if dot is None:
        dot_row = ("not_measured", not_measured)
    elif not dot["measurable"]:
        dot_row = ("not_measured", f"too few color edges to measure ({dot['column_edges']} column, "
                                   f"{dot['row_edges']} row)")
    else:
        dot_row = (verdict("COARSER_THAN_DECLARED"), f"color edges every {dot['dot_width']}x{dot['dot_height']} cells")
    checks.append({"id": "dot_size", "status": dot_row[0],
                   "expected": f"art drawn with {lw}x{lh} dots of 1 cell (edges every 1x1 cells)",
                   "actual": dot_row[1]})
    if "visible_cells" in m:
        checks.append({"id": "content", "status": verdict("EMPTY_IMAGE"), "expected": "at least one visible cell",
                       "actual": f"{m['visible_cells']} visible cells"})
    else:
        checks.append({"id": "content", "status": "not_measured", "expected": "at least one visible cell",
                       "actual": not_measured})
    kind = profile.get("kind")
    if kind == "sprite":
        kind_row = (verdict("SPRITE_WITHOUT_TRANSPARENCY") if "transparent_cells" in m else "not_measured",
                    "sprite: transparent background around the subject",
                    f"{m['transparent_cells']} transparent cells" if "transparent_cells" in m else not_measured)
    elif kind == "image":
        kind_row = (verdict("NON_OPAQUE_ALPHA") if alpha_policy(profile) == "opaque" else "pass",
                    "image: general picture" + (", fully opaque" if alpha_policy(profile) == "opaque" else ""),
                    f"{m.get('transparent_source_pixels', 0)} transparent samples")
    else:
        sheet = parse_sheet(profile["sheet"])
        fw, fh = sheet["frame_size"]
        expected = (f"sheet: {sheet['columns']}x{sheet['rows']} slots of {fw}x{fh} dots, {sheet['frame_count']} used"
                    f" (margin {sheet['margin']}, spacing {sheet['spacing']}, edge margin {sheet['edge_margin']}); "
                    "gutters and unused slots transparent; every used frame drawn on a transparent background")
        if "sheet" in report:
            frames = report["sheet"]["frames"]
            kind_row = (verdict(*SHEET_CODES), expected,
                        f"{sum(1 for f in frames if f['visible_cells'])} of {len(frames)} frames drawn, "
                        f"{m.get('sheet_violation_cells', 0)} cells break the layout")
        else:
            kind_row = ("not_measured", expected, not_measured)
    checks.append({"id": "kind", "status": kind_row[0], "expected": kind_row[1], "actual": kind_row[2]})
    alpha = alpha_policy(profile)
    alpha_text = {"binary": "alpha 0 or 255 only", "opaque": "alpha 255 only",
                  "any": "any alpha, one value per cell"}[alpha]
    checks.append({"id": "alpha", "status": verdict("PARTIAL_ALPHA", "NON_OPAQUE_ALPHA"), "expected": alpha_text,
                   "actual": f"{m.get('partial_alpha_source_pixels', 0)} partial, "
                             f"{m.get('transparent_source_pixels', 0)} transparent samples"})
    if profile.get("max_colors") is not None:
        checks.append({"id": "color_budget", "status": verdict("PALETTE_OVER_BUDGET"),
                       "expected": f"at most {profile['max_colors']} visible RGB colors",
                       "actual": f"{m.get('visible_rgb_colors_source')} colors"})
    else:
        checks.append({"id": "color_budget", "status": "not_declared", "expected": "declare max_colors",
                       "actual": f"{m.get('visible_rgb_colors_source')} colors"})
    if profile.get("allowed_palette") is not None:
        checks.append({"id": "allowed_palette", "status": verdict("COLOR_OUTSIDE_ALLOWED_PALETTE"),
                       "expected": f"every sample is one of {len(profile['allowed_palette'])} declared RGBA colors"
                                   f" (transparent_rgb {profile.get('transparent_rgb', 'exact')})",
                       "actual": f"{m.get('outside_palette_source_pixels')} samples outside"})
    else:
        checks.append({"id": "allowed_palette", "status": "not_declared", "expected": "declare allowed_palette",
                       "actual": f"{len(report.get('colors_used', []))} RGBA values used"})
    return checks


def _overlay_magnification(size: tuple[int, int], scale: int) -> int:
    magnify = max(1, math.ceil(OVERLAY_MIN_CELL / scale))
    while magnify > 1 and size[0] * size[1] * magnify * magnify > qa.MAX_PIXELS:
        magnify -= 1
    return magnify


def _draw_grid(draw: ImageDraw.ImageDraw, size: tuple[int, int], layout: dict, magnify: int, color) -> bool:
    """Draw every declared cell boundary from the origin; False when cells are too small to show lines."""
    step = layout["scale"] * magnify
    if step < 3:
        return False
    lw, lh = layout["logical"]
    ox, oy = (v * magnify for v in layout["origin"])
    gw, gh = (v * magnify for v in layout["grid_px"])
    w, h = size
    for i in range(lw + 1):
        x = ox + i * step
        if x < w:  # the far boundary of a grid that ends at the image edge lies outside the canvas
            draw.line((x, oy, x, min(oy + gh, h) - 1), fill=color, width=1)
    for j in range(lh + 1):
        y = oy + j * step
        if y < h:
            draw.line((ox, y, min(ox + gw, w) - 1, y), fill=color, width=1)
    return True


def write_artifacts(out_dir: Path, image: Image.Image, layout: dict, report: dict, *,
                    nonuniform: np.ndarray | None = None, logical_pixels: np.ndarray | None = None,
                    off_palette: np.ndarray | None = None,
                    stray_margin: np.ndarray | None = None,
                    sheet_bad: np.ndarray | None = None) -> dict[str, str]:
    geometry_ok = nonuniform is not None
    names = ["report.json", "grid_overlay.png", "grid_lines.png", "correction_prompt.txt"]
    if geometry_ok:
        names += ["logical_preview.png", "violation_mask.png"]
    qa.ensure_new_files([out_dir / n for n in names])
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"report": out_dir / "report.json", "overlay": out_dir / "grid_overlay.png",
             "grid_lines": out_dir / "grid_lines.png", "correction_prompt": out_dir / "correction_prompt.txt"}
    scale = layout["scale"]
    magnify = _overlay_magnification(image.size, scale)
    size = (image.width * magnify, image.height * magnify)
    base = qa.over_background(image).resize(size, Image.Resampling.NEAREST)
    marks = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(marks, "RGBA")
    ox, oy = layout["origin"]
    step = scale * magnify
    if geometry_ok:
        for y, x in np.argwhere(nonuniform):
            box = ((ox + x * scale) * magnify, (oy + y * scale) * magnify,
                   (ox + (x + 1) * scale) * magnify - 1, (oy + (y + 1) * scale) * magnify - 1)
            draw.rectangle(box, fill=(255, 35, 45, 150), outline=(255, 75, 60, 245) if step >= 4 else None)
        if off_palette is not None:
            for y, x in np.argwhere(off_palette):
                x0, y0 = (ox + x * scale) * magnify, (oy + y * scale) * magnify
                x1, y1 = x0 + step - 1, y0 + step - 1
                draw.rectangle((x0, y0, x1, y1), outline=(255, 255, 255, 255), width=1)
                draw.line((x0, y0, x1, y1), fill=(0, 0, 0, 255), width=1)
                draw.line((x0, y1, x1, y0), fill=(0, 0, 0, 255), width=1)
        if sheet_bad is not None:
            for y, x in np.argwhere(sheet_bad):
                box = ((ox + x * scale) * magnify, (oy + y * scale) * magnify,
                       (ox + (x + 1) * scale) * magnify - 1, (oy + (y + 1) * scale) * magnify - 1)
                draw.rectangle(box, fill=(255, 35, 45, 150), outline=(255, 75, 60, 245) if step >= 4 else None)
        if stray_margin is not None:
            for y, x in np.argwhere(stray_margin)[:5000]:
                draw.rectangle((x * magnify - 2, y * magnify - 2, (x + 1) * magnify + 1, (y + 1) * magnify + 1),
                               fill=(255, 35, 45, 200))
    grid_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    lines_drawn = _draw_grid(ImageDraw.Draw(grid_layer), size, layout,
                             magnify, (0, 215, 245, 140) if geometry_ok else (245, 155, 40, 170))
    if "sheet" in report:
        frame_draw = ImageDraw.Draw(grid_layer)
        fw, fh = report["sheet"]["frame_size"]["width"], report["sheet"]["frame_size"]["height"]
        for frame in report["sheet"]["frames"]:
            x0 = (ox + frame["box"]["x"] * scale) * magnify
            y0 = (oy + frame["box"]["y"] * scale) * magnify
            frame_draw.rectangle((x0, y0, x0 + fw * step - 1, y0 + fh * step - 1),
                                 outline=(255, 200, 0, 255), width=2 if step >= 6 else 1)
    if layout["has_margin"]:
        gw, gh = layout["grid_px"]
        ImageDraw.Draw(grid_layer).rectangle(
            (ox * magnify, oy * magnify, (ox + gw) * magnify - 1, (oy + gh) * magnify - 1),
            outline=(230, 60, 230, 255), width=1)
    combined = Image.alpha_composite(Image.alpha_composite(base, marks), grid_layer)
    if not geometry_ok:
        banner = ImageDraw.Draw(combined, "RGBA")
        banner.rectangle((0, 0, min(size[0], 470), 34), fill=(100, 10, 10, 235))
        banner.text((10, 10), "SIZE MISMATCH: orange lines = declared grid", fill=(255, 255, 255, 255))
    combined.convert("RGB").save(paths["overlay"])
    lines = Image.new("RGBA", image.size, (0, 0, 0, 0))
    _draw_grid(ImageDraw.Draw(lines), image.size, layout, 1, (0, 215, 245, 130))
    lines.save(paths["grid_lines"])
    report["grid_preview"] = {
        "sampled": False, "magnification": magnify, "spacing_px": {"x": step, "y": step},
        "origin_px": {"x": ox * magnify, "y": oy * magnify}, "grid_lines_drawn": lines_drawn,
        "legend": "cyan: declared cell boundaries; red fill: cell with more than one RGBA value; "
                  "black X in a white box: cell with a color outside allowed_palette; magenta: grid box inside the margin; "
                  "red square in the margin: pixel that differs from the margin color; "
                  "amber: frame slot of a sprite sheet (red fill also marks dots in gutters, unused slots or edge margins); "
                  "orange: declared grid on an image of the wrong size",
    }
    if geometry_ok:
        paths["logical_preview"] = out_dir / "logical_preview.png"
        paths["violation_mask"] = out_dir / "violation_mask.png"
        qa.save_preview(logical_pixels, paths["logical_preview"])
        Image.fromarray(nonuniform.astype(np.uint8) * 255, "L").save(paths["violation_mask"])
    paths["correction_prompt"].write_text(correction_text(report, layout), encoding="utf-8")
    paths["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                               encoding="utf-8")
    return {key: str(value) for key, value in paths.items()}


def correction_text(report: dict, layout: dict) -> str:
    lw, lh = layout["logical"]
    ew, eh = layout["image_size"]
    codes = {i["code"] for i in report["issues"] if i["severity"] in ("fail", "review")}
    if "RENDER_SIZE_MISMATCH" in codes:
        text = (f"Deliver a {ew}x{eh} px PNG: {lw}x{lh} logical dots, each a solid {layout['scale']}x"
                f"{layout['scale']} px block, starting at pixel {layout['origin']}. Do not resize or round an "
                "existing image to fit; redraw it on the declared grid.\n")
        hint = report.get("detected_grid")
        if hint and hint.get("found"):
            text += (f"The submitted pixels appear to use {hint['dot_width']}x{hint['dot_height']} px dots from "
                     f"origin {hint['origin']}, about {hint['logical_size_estimate']['width']}x"
                     f"{hint['logical_size_estimate']['height']} dots.\n")
        return text
    lines = [qa.correction_prompt(report).rstrip("\n")] if "worst_cells" in report else []
    if "COARSER_THAN_DECLARED" in codes:
        lines.append(f"Draw with single-cell dots on the {lw}x{lh} grid; the art currently uses larger blocks.")
    if "SPRITE_WITHOUT_TRANSPARENCY" in codes:
        lines.append("Leave the background fully transparent (alpha 0); do not paint a checkerboard or backdrop.")
    if "MARGIN_NOT_UNIFORM" in codes:
        lines.append("Keep everything outside the grid box one solid color; no art may cross the grid edge.")
    if "COLOR_OUTSIDE_ALLOWED_PALETTE" in codes:
        lines.append("Use only the declared palette colors: " + ", ".join(report["contract"]["allowed_palette"]) + ".")
    if codes & {"GUTTER_NOT_EMPTY", "UNUSED_SLOT_NOT_EMPTY", "EDGE_MARGIN_VIOLATION"}:
        lines.append("Keep every dot inside its frame slot: margins, spacing, unused slots and frame edge margins "
                     "stay transparent.")
    if "FRAME_WITHOUT_TRANSPARENCY" in codes:
        lines.append("Draw each frame's subject on a transparent background (alpha 0).")
    if "EMPTY_FRAME" in codes:
        lines.append("Draw every used frame, or lower frame_count to the frames that exist.")
    if "EMPTY_IMAGE" in codes:
        lines.append("The image is empty; draw the subject.")
    hint = report.get("detected_grid")
    if hint and hint.get("found") and "NON_SOLID_GRID_CELLS" in codes:
        lines.append(f"The pixels appear to sit on {hint['dot_width']}x{hint['dot_height']} px dots from origin "
                     f"{hint['origin']}, not on the declared grid; align the art to the declared origin and cell size.")
    return "\n".join(lines) + "\n"


def audit_one(image_path: Path, profile: dict, profile_path: Path, out_dir: Path) -> dict:
    image = qa.open_rgba(image_path)
    layout = resolve_layout(profile)
    geometry = check_geometry(image.size, layout)
    policy = profile.get("transparent_rgb", "exact")
    alpha = alpha_policy(profile)
    raw = np.asarray(image, dtype=np.uint8)
    arr = qa.normalize_rgba(raw) if policy == "visible" else raw
    nonuniform = logical_pixels = off_palette = stray_margin = sheet_bad = None
    if geometry["status"] == "pass":
        ox, oy = layout["origin"]
        gw, gh = layout["grid_px"]
        grid_image = image if image.size == (gw, gh) else image.crop((ox, oy, ox + gw, oy + gh))
        grid_image.info.update(image.info)
        audit = qa.inspect_image(grid_image, layout["logical"], max_colors=None, strict_alpha=alpha == "binary",
                                 strict_cells=True, transparent_rgb=policy)
        report = audit.result
        if layout["scale"] == 1:
            report["issues"] = [i for i in report["issues"] if i["code"] != "NATIVE_RESOLUTION_NO_GRID_EVIDENCE"]
        if (ox, oy) != (0, 0):
            for entry in report.get("worst_cells", []) + report.get("nonuniform_rgba_cell_samples", []):
                x0, y0, x1, y1 = entry["source_box"]
                entry["source_box"] = [x0 + ox, y0 + oy, x1 + ox, y1 + oy]
        if layout["has_margin"]:
            margin_issues, margin_info, stray_margin = _margin_check(arr, layout)
            report["issues"].extend(margin_issues)
            report["metrics"].update(margin_info)
        report["geometry"] = geometry
        report["input_size"] = {"width": image.width, "height": image.height}
        report["grid_box"] = geometry["grid_box"]
        nonuniform = audit.exact_nonuniform
        logical_pixels = audit.logical_pixels
        enforce_profile(report, image, profile, logical_pixels=logical_pixels, review_few_edges=True)
        if profile["kind"] == "sheet":
            cells = qa.normalize_rgba(logical_pixels) if policy == "visible" else logical_pixels
            sheet_bad = check_sheet(cells, profile, report)
        if profile.get("allowed_palette") is not None:
            allowed = np.array([parse_rgba(v) for v in profile["allowed_palette"]], dtype=np.uint8)
            if policy == "visible":
                allowed[allowed[:, 3] == 0, :3] = 0
            grid = arr[oy:oy + gh, ox:ox + gw]
            keys = np.ascontiguousarray(grid).view(np.dtype("V4")).reshape(grid.shape[:2])
            bad = ~np.isin(keys, np.ascontiguousarray(allowed).view(np.dtype("V4")).ravel())
            lw, lh = layout["logical"]
            s = layout["scale"]
            off_palette = bad.reshape(lh, s, lw, s).any(axis=(1, 3))
    else:
        report = {"tool": "Pixelwright", "version": VERSION, "schema_version": 1,
                  "scope": "technical_checks_only_not_artistic_quality", "acceptance": "exact",
                  "input_size": geometry["rendered_size"], "logical_size": geometry["logical_size"],
                  "geometry": geometry, "issues": list(geometry["issues"]),
                  "metrics": {"grid_measurable": False, "uniform_rgba_cells": None, "nonuniform_rgba_cells": None},
                  "provenance": {"source_sha256": image.info.get("pixelwright_source_sha256"),
                                 "decoded_rgba_sha256": hashlib.sha256(raw.tobytes()).hexdigest(),
                                 "sample_scope": "decoded_rgba8_without_exif_or_color_management"},
                  "note": "No resampling performed; cell checks need the contracted image size."}
        enforce_profile(report, image, profile)
    cell_failed = any(i["code"] in ("NON_SOLID_GRID_CELLS", "RENDER_SIZE_MISMATCH") for i in report["issues"])
    if cell_failed:
        report["detected_grid"] = detect_grid(image)
    report["layout"] = {"logical_size": {"width": layout["logical"][0], "height": layout["logical"][1]},
                        "scale": layout["scale"], "origin": {"x": layout["origin"][0], "y": layout["origin"][1]},
                        "image_size": {"width": layout["image_size"][0], "height": layout["image_size"][1]},
                        "grid_box": geometry["grid_box"], "has_margin": layout["has_margin"],
                        "cell_rule": "cell (x,y) covers pixels [ox+x*S, ox+(x+1)*S) x [oy+y*S, oy+(y+1)*S)"}
    report["checks"] = build_checks(report, layout, profile, geometry["status"] == "pass")
    report.setdefault("provenance", {}).update({
        "profile_sha256": sha256(profile_path), "source_path": str(image_path.resolve()),
        "profile_path": str(profile_path.resolve())})
    report["provenance"]["source_sha256"] = report["provenance"].get("source_sha256") or sha256(image_path)
    report["schema_version"] = 1
    report["acceptance_mode"] = "strict_profile"
    paths = write_artifacts(out_dir, image, layout, report, nonuniform=nonuniform,
                            logical_pixels=logical_pixels, off_palette=off_palette, stray_margin=stray_margin,
                            sheet_bad=sheet_bad)
    return {"input": str(image_path), "status": report["status"],
            "checks": report["checks"],
            "outputs": paths}


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    inspect = sub.add_parser("inspect", help="Audit one PNG against a profile")
    inspect.add_argument("images", type=Path, nargs=1)
    batch = sub.add_parser("batch", help="Audit explicit static PNG inputs using one contract")
    batch.add_argument("images", type=Path, nargs="+")
    for p in (inspect, batch):
        p.add_argument("--profile", required=True, type=Path)
        p.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        profile = load_profile(args.profile)
        require_empty_output(args.out_dir, args.images + [args.profile])
        # Expand no globs implicitly: the shell/user controls the submitted files.
        if args.action == "inspect":
            result = audit_one(args.images[0], profile, args.profile, args.out_dir)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "pass" else 2
        args.out_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for index, source in enumerate(args.images):
            try:
                results.append(audit_one(source, profile, args.profile, args.out_dir / f"{index:04d}"))
            except (ValueError, OSError, MemoryError) as exc:
                results.append({"input": str(source), "status": "error", "error": str(exc)})
        statuses = {r["status"] for r in results}
        status = "error" if "error" in statuses else "fail" if "fail" in statuses else "review" if "review" in statuses else "pass"
        summary = {"tool": "Pixelwright", "version": VERSION, "schema_version": 1, "status": status,
                   "profile_sha256": sha256(args.profile), "contract": profile, "results": results}
        (args.out_dir / "batch.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1 if status == "error" else 0 if status == "pass" else 2
    except (ValueError, OSError, MemoryError) as exc:
        print(f"Pixelwright error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
