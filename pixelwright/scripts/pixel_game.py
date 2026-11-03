#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Game-wide pixel contracts: one base resolution, one pixel size, one style.

A game contract fixes what every asset in one game shares: the base
resolution, the rule that one image pixel is one game pixel, the palette and
alpha policy, size limits per asset category, and the style decisions an
artist or AI needs before drawing (perspective, light, shading, outline,
dithering, font, animation rate, rotation and effect blending).

Commands:
  brief     print the style brief to follow before drawing any asset
  viewport  whole-number scale and letterbox for window sizes
  asset     check 1x game assets against the contract
  intake    place a new asset beside reference assets at 1x and compare them
  screen    check a lossless game screenshot against the base-resolution grid

Checks are measurements of decoded pixels. Effective pixel size, dithering and
outline width are heuristics reported as REVIEW unless the evidence is
unambiguous; none of them judges appeal. Exit codes: 0 pass, 2 fail/review,
1 invalid input or execution error.
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

import pixel_palette as palettes
import pixel_qa as qa
import pixelwright as pw

VERSION = "0.6.2"
MAX_CONTRACT_BYTES = 1024 * 1024
CONTRACT_KEYS = {"schema_version", "name", "base_resolution", "tile_size", "palette_file", "allowed_palette",
                 "max_colors", "alpha", "letterbox", "categories", "style", "font", "animation", "rotation",
                 "effects", "engine"}
STYLE_KEYS = {"genre", "perspective", "light_direction", "shading", "outline", "dithering", "anti_aliasing",
              "mood", "notes", "references"}
OUTLINE_KEYS = {"mode", "width", "colors"}
CATEGORY_KEYS = {"size", "min_size", "max_size", "notes"}
FONT_KEYS = {"name", "file", "size_px", "line_height_px"}
ENUMS = {
    "alpha": ("binary", "opaque", "any"),
    "perspective": ("side", "top-down", "three-quarter", "isometric", "front", "other"),
    "light_direction": ("upper-left", "upper-right", "top", "left", "right", "front", "none"),
    "shading": ("flat", "cel", "soft", "other"),
    "outline": ("none", "dark", "colored", "selective"),
    "dithering": ("none", "limited", "allowed"),
    "anti_aliasing": ("none", "manual"),
    "rotation": ("none", "quarter_turns", "prerendered"),
    "blending": ("opaque", "palette_alpha"),
    "engine": ("unity", "godot", "phaser", "pixi", "web", "love", "gamemaker", "other"),
}
# Fewer distinct color edges than MIN_EDGES per axis are too little evidence to
# measure dot size at all. Plain 1x art (4x4 checks, a flat square with a 2-pixel
# outline) can still sit on a coarse lattice with a few edges, so only FAIL_EDGES
# or more per axis turn a coarse measurement into a failure.
MIN_EDGES = 3
FAIL_EDGES = 8
MAX_DOT = 8
DITHER_MIN_PIXELS = 16
OUTLINE_MIN_COVERAGE = 0.9
OUTLINE_MAX_DOUBLED = 0.5
NEUTRAL = (58, 63, 74, 255)


def _unique(pairs):
    values = {}
    for key, value in pairs:
        if key in values:
            raise ValueError(f"Duplicate contract field: {key}")
        values[key] = value
    return values


def _text(value, name, limit=2000):
    if not isinstance(value, str) or not 1 <= len(value) <= limit:
        raise ValueError(f"{name} must be a string of 1..{limit} characters")
    return value


def _int(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def _enum(value, name, kind):
    if value not in ENUMS[kind]:
        raise ValueError(f"{name} must be one of: {', '.join(ENUMS[kind])}")
    return value


def _keys(document, allowed, name):
    if not isinstance(document, dict):
        raise ValueError(f"{name} must be a JSON object")
    unknown = set(document) - allowed
    if unknown:
        raise ValueError(f"Unknown {name} fields: {', '.join(sorted(unknown))}")


def _size(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be WIDTHxHEIGHT")
    try:
        return qa.parse_size(value)
    except argparse.ArgumentTypeError as exc:
        raise ValueError(f"{name}: {exc}") from exc


def _inside(base: Path, relative: str, name: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or relative.startswith("/"):
        raise ValueError(f"{name} must be a relative POSIX path inside the contract directory")
    path = (base / relative).resolve()
    if base.resolve() not in path.parents:
        raise ValueError(f"{name} must stay inside the contract directory")
    return path


def load_contract(path: str | Path) -> dict[str, Any]:
    """Validate a contract and resolve its palette, outline colors and references."""
    path = Path(path)
    data = path.read_bytes()
    if len(data) > MAX_CONTRACT_BYTES:
        raise ValueError("Contract exceeds 1 MiB")
    doc = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique)
    _keys(doc, CONTRACT_KEYS, "contract")
    if type(doc.get("schema_version")) is not int or doc["schema_version"] != 1:
        raise ValueError("Contract schema_version must be 1")
    if "name" in doc:
        _text(doc["name"], "name", 256)
    base = _size(doc.get("base_resolution"), "base_resolution")
    if "tile_size" in doc:
        _int(doc["tile_size"], "tile_size", 1, 256)
    _enum(doc.get("alpha", "binary"), "alpha", "alpha")
    if "max_colors" in doc:
        _int(doc["max_colors"], "max_colors", 1, 256)
    letterbox = pw.parse_rgba(doc.get("letterbox", "#000000"))
    if letterbox[3] != 255:
        raise ValueError("letterbox must be an opaque color")
    root = path.resolve().parent
    tokens: dict[str, tuple[int, ...]] = {}
    ramps: dict[str, list[str]] = {}
    if "palette_file" in doc and "allowed_palette" in doc:
        raise ValueError("Use either palette_file or allowed_palette, not both")
    if "palette_file" in doc:
        library = palettes.load_palette(_inside(root, doc["palette_file"], "palette_file"))
        tokens = {token: pw.parse_rgba(value) for token, value in library["colors"].items()}
        ramps = library["ramps"]
    elif "allowed_palette" in doc:
        values = doc["allowed_palette"]
        if not isinstance(values, list) or not 1 <= len(values) <= 256:
            raise ValueError("allowed_palette must list 1..256 colors")
        tokens = {"#%02X%02X%02X%02X" % rgba: rgba for rgba in map(pw.parse_rgba, values)}
    categories = doc.get("categories", {})
    if not isinstance(categories, dict) or len(categories) > 64:
        raise ValueError("categories must be an object with at most 64 entries")
    for name, rule in categories.items():
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name) is None:
            raise ValueError("Category names use 1..64 letters, digits, _ or -")
        _keys(rule, CATEGORY_KEYS, f"category {name!r}")
        for key in ("size", "min_size", "max_size"):
            if key in rule:
                _size(rule[key], f"{name}.{key}")
        if "size" in rule and ("min_size" in rule or "max_size" in rule):
            raise ValueError(f"Category {name!r} uses size or min/max sizes, not both")
        if "notes" in rule:
            _text(rule["notes"], f"{name}.notes")
    style = doc.get("style", {})
    _keys(style, STYLE_KEYS, "style")
    for key in ("genre", "mood", "notes"):
        if key in style:
            _text(style[key], f"style.{key}")
    for key in ("perspective", "light_direction", "shading", "dithering", "anti_aliasing"):
        if key in style:
            _enum(style[key], f"style.{key}", key)
    outline_colors: list[tuple[int, ...]] = []
    if "outline" in style:
        outline = style["outline"]
        _keys(outline, OUTLINE_KEYS, "style.outline")
        _enum(outline.get("mode"), "style.outline.mode", "outline")
        if "width" in outline:
            _int(outline["width"], "style.outline.width", 1, 4)
        if not isinstance(outline.get("colors", []), list):
            raise ValueError("style.outline.colors must be a list of palette tokens or colors")
        for value in outline.get("colors", []):
            if isinstance(value, str) and value in tokens:
                outline_colors.append(tokens[value])
            else:
                outline_colors.append(pw.parse_rgba(value))
    if not isinstance(style.get("references", []), list):
        raise ValueError("style.references must be a list of paths")
    references = []
    for value in style.get("references", []):
        references.append(_inside(root, value, "style.references"))
    if "font" in doc:
        _keys(doc["font"], FONT_KEYS, "font")
        if "name" in doc["font"]:
            _text(doc["font"]["name"], "font.name", 256)
        if "file" in doc["font"]:
            _inside(root, doc["font"]["file"], "font.file")
        for key in ("size_px", "line_height_px"):
            if key in doc["font"]:
                _int(doc["font"][key], f"font.{key}", 1, 256)
    if "animation" in doc:
        _keys(doc["animation"], {"fps"}, "animation")
        _int(doc["animation"].get("fps"), "animation.fps", 1, 240)
    if "rotation" in doc:
        _keys(doc["rotation"], {"mode", "directions"}, "rotation")
        _enum(doc["rotation"].get("mode"), "rotation.mode", "rotation")
        if "directions" in doc["rotation"]:
            _int(doc["rotation"]["directions"], "rotation.directions", 1, 64)
    if "effects" in doc:
        _keys(doc["effects"], {"blending"}, "effects")
        _enum(doc["effects"].get("blending"), "effects.blending", "blending")
    if "engine" in doc:
        _enum(doc["engine"], "engine", "engine")
    return {"document": doc, "path": path.resolve(), "sha256": hashlib.sha256(data).hexdigest(), "base": base,
            "tokens": tokens, "ramps": ramps, "letterbox": letterbox, "outline_colors": outline_colors,
            "references": references}


def _packed(arr: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(arr, dtype=np.uint8).view(np.uint32)[:, :, 0]


def _pack_colors(colors) -> np.ndarray:
    return np.ascontiguousarray(np.array(list(colors), dtype=np.uint8).reshape(-1, 4)).view(np.uint32).ravel()


def _hex(value: int) -> str:
    return "#" + "".join(f"{b:02X}" for b in np.array([value], dtype=np.uint32).view(np.uint8))


def _period(edges: np.ndarray) -> int | None:
    return int(np.gcd.reduce(np.diff(edges))) if len(edges) >= 2 else None


def effective_pixel_size(packed: np.ndarray) -> dict[str, Any]:
    """Dot width and height: the largest spacing that every column and row color edge keeps.

    An image drawn with k-wide pixels has edges only every k columns (with some
    offset), so a width or height above 1 means dots larger than one game pixel.
    The axes are measured separately so stretched, non-square dots also show.
    """
    cols = np.flatnonzero((packed[:, 1:] != packed[:, :-1]).any(axis=0)) + 1
    rows = np.flatnonzero((packed[1:, :] != packed[:-1, :]).any(axis=1)) + 1
    width, height = _period(cols) or 1, _period(rows) or 1
    few = min(len(cols), len(rows))
    return {"x": width, "y": height, "size": max(width, height), "column_edges": int(len(cols)),
            "row_edges": int(len(rows)), "measurable": few >= MIN_EDGES, "conclusive": few >= FAIL_EDGES}


def _window_sums(values: np.ndarray, length: int, axis: int) -> np.ndarray:
    """Sums of every run of `length` consecutive entries along one axis."""
    padded = np.cumsum(np.insert(values.astype(np.int32), 0, 0, axis=axis), axis=axis)
    upper = [slice(None)] * values.ndim
    lower = [slice(None)] * values.ndim
    upper[axis], lower[axis] = slice(length, None), slice(None, -length)
    return padded[tuple(upper)] - padded[tuple(lower)]


def _axis_dots(edges: np.ndarray, span: int, length: int) -> tuple[np.ndarray, np.ndarray]:
    """For every window: edge count along one axis, and the largest dot size those edges keep.

    `edges[i, j]` marks a change between positions j and j+1 in line i; a window
    covers `span` lines and `length` positions. Every window position is tested,
    so an enlarged element is found wherever it sits.
    """
    seen = _window_sums(edges, span, 0) > 0
    if length < 2:
        shape = (seen.shape[0], seen.shape[1] + 1)
        return np.zeros(shape, dtype=np.int32), np.ones(shape, dtype=np.int32)
    position = np.arange(1, seen.shape[1] + 1)
    total = _window_sums(seen, length - 1, 1)
    dots = np.ones_like(total)
    for k in range(2, MAX_DOT + 1):
        used = sum((_window_sums(seen & (position % k == r), length - 1, 1) > 0).astype(np.int32)
                   for r in range(k))
        dots = np.where(used == 1, k, dots)
    return total, dots


def coarse_windows(packed: np.ndarray, window: int) -> list[dict[str, int]]:
    """Regions where every window position shows dots larger than one pixel."""
    h, w = packed.shape
    nh, nw = min(window, h), min(window, w)
    col_total, col_dots = _axis_dots(packed[:, 1:] != packed[:, :-1], nh, nw)
    row_total, row_dots = _axis_dots((packed[1:, :] != packed[:-1, :]).T, nw, nh)
    row_total, row_dots = row_total.T, row_dots.T
    hit = (col_total >= MIN_EDGES) & (row_total >= MIN_EDGES) & ((col_dots > 1) | (row_dots > 1))
    covered = np.zeros((h, w), dtype=bool)
    dots = np.zeros((h, w), dtype=np.int32)
    for y, x in np.argwhere(hit):
        covered[y:y + nh, x:x + nw] = True
        size = max(col_dots[y, x], row_dots[y, x])
        dots[y:y + nh, x:x + nw] = np.maximum(dots[y:y + nh, x:x + nw], size)
    boxes = []
    for y, x in np.argwhere(covered):
        if not covered[y, x]:
            continue
        stack, ys, xs = [(y, x)], [], []
        covered[y, x] = False
        while stack:
            cy, cx = stack.pop()
            ys.append(cy)
            xs.append(cx)
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < h and 0 <= nx < w and covered[ny, nx]:
                    covered[ny, nx] = False
                    stack.append((ny, nx))
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        boxes.append({"x": int(x0), "y": int(y0), "width": int(x1 - x0 + 1), "height": int(y1 - y0 + 1),
                      "pixel_size": int(dots[y0:y1 + 1, x0:x1 + 1].max())})
    return boxes


def dither_windows(packed: np.ndarray, opaque: np.ndarray) -> np.ndarray:
    """Top-left corners of 3x3 two-color checkerboards drawn on opaque pixels."""
    h, w = packed.shape
    if h < 3 or w < 3:
        return np.zeros((0, 2), dtype=int)
    a, b = packed[:-2, :-2], packed[:-2, 1:-1]
    hit = a != b
    for dy in range(3):
        for dx in range(3):
            cell = packed[dy:h - 2 + dy, dx:w - 2 + dx]
            hit &= cell == (a if (dx + dy) % 2 == 0 else b)
            hit &= opaque[dy:h - 2 + dy, dx:w - 2 + dx]
    return np.argwhere(hit)


def outline_metrics(packed: np.ndarray, opaque: np.ndarray, outline: np.ndarray) -> dict[str, Any]:
    """Share of silhouette pixels in outline colors, and how often the outline is two pixels deep."""
    # Beyond the image counts as covered, so tiles and art cut at the border have no silhouette there.
    padded = np.pad(opaque, 1, constant_values=True)
    outside = {(dy, dx): ~padded[1 + dy:padded.shape[0] - 1 + dy, 1 + dx:padded.shape[1] - 1 + dx]
               for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1))}
    edge = opaque & (outside[(-1, 0)] | outside[(1, 0)] | outside[(0, -1)] | outside[(0, 1)])
    inked = opaque & np.isin(packed, outline)
    ink_edge = edge & inked
    deep = np.zeros_like(edge)
    padded_ink = np.pad(inked & ~edge, 1, constant_values=False)
    for (dy, dx), out in outside.items():
        inward = padded_ink[1 - dy:padded_ink.shape[0] - 1 - dy, 1 - dx:padded_ink.shape[1] - 1 - dx]
        deep |= ink_edge & out & inward
    edges = int(edge.sum())
    inks = int(ink_edge.sum())
    return {"silhouette_pixels": edges, "outline_coverage": round(inks / edges, 4) if edges else None,
            "doubled_fraction": round(int(deep.sum()) / inks, 4) if inks else None}


def _issue(code, severity, detail, **extra):
    return {"code": code, "severity": severity, "detail": detail, **extra}


def _status(issues) -> str:
    severities = {i["severity"] for i in issues}
    return "fail" if "fail" in severities else "review" if "review" in severities else "pass"


def measure_asset(image: Image.Image, contract: dict, category: str | None) -> tuple[dict, dict]:
    """Return the report and diagnostic masks for one 1x asset."""
    doc = contract["document"]
    arr = np.asarray(image, dtype=np.uint8)
    h, w = arr.shape[:2]
    packed = _packed(arr)
    alpha = arr[:, :, 3]
    opaque = alpha > 0
    issues, metrics = [], {"size": [w, h]}
    bw, bh = contract["base"]
    if (w > bw or h > bh) and category is None:
        issues.append(_issue("ASSET_LARGER_THAN_SCREEN", "review",
                             f"Asset is {w}x{h}; the base resolution is {bw}x{bh}. At 1x it cannot fit on screen. "
                             "Check it under a category whose size allows it (a background or tileset), "
                             "or check that it was not exported enlarged."))
    if category is not None:
        rules = doc.get("categories", {})
        if category not in rules:
            raise ValueError(f"Unknown category {category!r}; the contract declares: {', '.join(rules) or 'none'}")
        rule = rules[category]
        low = _size(rule.get("size", rule.get("min_size", "1x1")), "size")
        high = _size(rule.get("size", rule.get("max_size", "4096x4096")), "size")
        if not (low[0] <= w <= high[0] and low[1] <= h <= high[1]):
            wanted = rule["size"] if "size" in rule else f"{low[0]}x{low[1]} to {high[0]}x{high[1]}"
            issues.append(_issue("CATEGORY_SIZE", "fail", f"{category} assets must be {wanted}; this one is {w}x{h}."))
    if not opaque.any():
        issues.append(_issue("EMPTY_ASSET", "fail", "The asset has no visible pixels."))
    policy = doc.get("alpha", "binary")
    partial = int(np.count_nonzero((alpha > 0) & (alpha < 255)))
    if policy in ("binary", "opaque") and partial:
        issues.append(_issue("PARTIAL_ALPHA", "fail", f"{partial} pixels are semi-transparent; the contract uses {policy} alpha."))
    if policy == "opaque" and not opaque.all():
        issues.append(_issue("NON_OPAQUE_ALPHA", "fail", "The contract requires every pixel to be opaque."))
    visible = np.unique(packed[opaque])
    metrics["visible_colors"] = int(len(visible))
    if "max_colors" in doc and len(visible) > doc["max_colors"]:
        issues.append(_issue("TOO_MANY_COLORS", "fail", f"{len(visible)} visible colors; the budget is {doc['max_colors']}."))
    off = np.zeros_like(opaque)
    if contract["tokens"]:
        allowed = _pack_colors(contract["tokens"].values())
        off = opaque & ~np.isin(packed, allowed)
        if off.any():
            colors = [_hex(v) for v in np.unique(packed[off])[:12]]
            issues.append(_issue("COLOR_OUTSIDE_PALETTE", "fail",
                                 f"{int(off.sum())} pixels use colors outside the game palette: {', '.join(colors)}."))
    # Transparent pixels all read as one background so hidden RGB cannot fake edges.
    canonical = np.where(opaque, packed, np.uint32(0))
    whole = effective_pixel_size(canonical)
    metrics["effective_pixel_size"] = whole
    coarse = []
    if whole["measurable"] and whole["size"] > 1:
        dots = f"{whole['x']}x{whole['y']}"
        if whole["conclusive"]:
            issues.append(_issue("COARSE_PIXELS", "fail",
                                 f"Every color edge keeps a {dots} spacing: the asset is drawn with {dots} dots, "
                                 "not 1x game pixels. Redraw at 1x; do not shrink it with interpolation."))
        else:
            issues.append(_issue("COARSE_PIXELS", "review",
                                 f"The few color edges all keep a {dots} spacing. The asset may be enlarged, or its "
                                 "details may simply be that wide; check it beside 1x assets."))
    else:
        coarse = coarse_windows(canonical, max(8, doc.get("tile_size", 16)))
        if coarse:
            issues.append(_issue("COARSE_REGION", "review",
                                 f"{len(coarse)} windows contain only dots larger than one pixel; check whether part "
                                 "of the asset was enlarged.", windows=coarse[:50]))
    style = doc.get("style", {})
    dithers = dither_windows(canonical, opaque)
    dithered = np.zeros_like(opaque)
    for y, x in dithers:
        dithered[y:y + 3, x:x + 3] = True
    metrics["dither_pixels"] = int(dithered.sum())
    if style.get("dithering") == "none" and dithered.sum() >= DITHER_MIN_PIXELS:
        issues.append(_issue("DITHERING_FOUND", "review",
                             f"{int(dithered.sum())} pixels form two-color checkerboards; the style declares no dithering.",
                             sample=[{"x": int(x), "y": int(y)} for y, x in dithers[:20]]))
    outline = style.get("outline", {})
    if outline.get("mode") in ("dark", "colored") and contract["outline_colors"] and opaque.any():
        measured = outline_metrics(canonical, opaque, _pack_colors(contract["outline_colors"]))
        metrics["outline"] = measured
        if measured["outline_coverage"] is not None and measured["outline_coverage"] < OUTLINE_MIN_COVERAGE:
            issues.append(_issue("OUTLINE_INCOMPLETE", "review",
                                 f"{measured['outline_coverage']:.0%} of silhouette pixels use outline colors; "
                                 f"the style declares a {outline['mode']} outline."))
        if outline.get("width", 1) == 1 and (measured["doubled_fraction"] or 0) > OUTLINE_MAX_DOUBLED:
            issues.append(_issue("OUTLINE_TOO_THICK", "review",
                                 f"{measured['doubled_fraction']:.0%} of the outline is two pixels deep; the style "
                                 "declares a 1-pixel outline."))
    report = {"tool": "Pixelwright", "version": VERSION, "schema_version": 1, "mode": "game_asset",
              "status": _status(issues), "artistic_status": "not_reviewed", "category": category,
              "issues": issues, "metrics": metrics}
    return report, {"off_palette": off, "coarse": coarse, "dither": dithers}


def _scale_for(size, target=512):
    return max(1, min(16, target // max(size)))


def save_asset_overlay(image: Image.Image, masks: dict, path: Path) -> None:
    k = _scale_for(image.size)
    big = qa.over_background(image.resize((image.width * k, image.height * k), Image.Resampling.NEAREST))
    draw = ImageDraw.Draw(big, "RGBA")
    for y, x in np.argwhere(masks["off_palette"]):
        draw.rectangle((x * k, y * k, (x + 1) * k - 1, (y + 1) * k - 1), outline=(255, 40, 40, 255))
    for box in masks["coarse"]:
        draw.rectangle((box["x"] * k, box["y"] * k, (box["x"] + box["width"]) * k - 1,
                        (box["y"] + box["height"]) * k - 1), outline=(255, 160, 0, 255), width=2)
    for y, x in masks["dither"]:
        draw.rectangle((x * k, y * k, (x + 3) * k - 1, (y + 3) * k - 1), outline=(80, 200, 255, 255))
    big.convert("RGB").save(path)


def _fresh(out_dir: Path, inputs: list[Path]) -> None:
    pw.require_empty_output(out_dir, inputs)
    out_dir.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_asset(source: Path, contract: dict, category: str | None, out_dir: Path) -> dict:
    image = qa.open_rgba(source)
    report, masks = measure_asset(image, contract, category)
    report["provenance"] = {"source_path": str(source.resolve()), "source_sha256": qa.sha256_file(source),
                            "contract_path": str(contract["path"]), "contract_sha256": contract["sha256"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    save_asset_overlay(image, masks, out_dir / "asset_overlay.png")
    _write_json(out_dir / "report.json", report)
    return {"input": str(source), "status": report["status"], "issues": [i["code"] for i in report["issues"]],
            "outputs": {"report": str(out_dir / "report.json"), "overlay": str(out_dir / "asset_overlay.png")}}


def viewport(window: tuple[int, int], base: tuple[int, int]) -> dict[str, Any]:
    """Largest whole-number scale that fits, centered with letterbox bars."""
    scale = min(window[0] // base[0], window[1] // base[1])
    if scale < 1:
        return {"window": list(window), "scale": 0, "fits": False}
    used = (base[0] * scale, base[1] * scale)
    offset = ((window[0] - used[0]) // 2, (window[1] - used[1]) // 2)
    return {"window": list(window), "scale": scale, "fits": True, "viewport": [offset[0], offset[1], *used],
            "bars": {"left": offset[0], "right": window[0] - used[0] - offset[0],
                     "top": offset[1], "bottom": window[1] - used[1] - offset[1]}}


def measure_screen(image: Image.Image, contract: dict, scale: int | None = None,
                   offset: tuple[int, int] | None = None) -> tuple[dict, dict]:
    doc = contract["document"]
    arr = np.asarray(image, dtype=np.uint8)
    h, w = arr.shape[:2]
    base = contract["base"]
    fit = viewport((w, h), base)
    if scale is not None or offset is not None:
        scale = fit["scale"] if scale is None else scale
        if scale < 1:
            raise ValueError("Scale must be at least 1")
        offset = offset if offset is not None else ((w - base[0] * scale) // 2, (h - base[1] * scale) // 2)
        if (offset[0] < 0 or offset[1] < 0 or offset[0] + base[0] * scale > w or offset[1] + base[1] * scale > h):
            raise ValueError("Declared scale and offset place the viewport outside the screenshot")
        fit = {"window": [w, h], "scale": scale, "fits": True,
               "viewport": [offset[0], offset[1], base[0] * scale, base[1] * scale]}
    issues = []
    report = {"tool": "Pixelwright", "version": VERSION, "schema_version": 1, "mode": "game_screen",
              "artistic_status": "not_reviewed", "issues": issues, "viewport": fit}
    if not fit["fits"]:
        issues.append(_issue("WINDOW_SMALLER_THAN_BASE", "fail",
                             f"A {w}x{h} screenshot cannot show the {base[0]}x{base[1]} base resolution at 1x or more."))
        report["status"] = "fail"
        return report, {}
    x0, y0, vw, vh = fit["viewport"]
    s = fit["scale"]
    packed = _packed(arr)
    bars = np.ones((h, w), dtype=bool)
    bars[y0:y0 + vh, x0:x0 + vw] = False
    letterbox = _pack_colors([contract["letterbox"]])[0]
    wrong_bars = bars & (packed != letterbox)
    if wrong_bars.any():
        issues.append(_issue("LETTERBOX_NOT_UNIFORM", "fail",
                             f"{int(wrong_bars.sum())} pixels outside the {vw}x{vh} viewport are not the letterbox color "
                             f"{_hex(letterbox)}; the game is not scaled by a whole number, or draws outside its viewport."))
    cells = packed[y0:y0 + vh, x0:x0 + vw].reshape(base[1], s, base[0], s)
    logical = cells[:, 0, :, 0]
    broken = (cells != logical[:, None, :, None]).any(axis=(1, 3))
    report["metrics"] = {"scale": s, "nonuniform_cells": int(broken.sum()), "cells": base[0] * base[1]}
    if broken.any():
        issues.append(_issue("CELL_NOT_UNIFORM", "fail",
                             f"{int(broken.sum())} of {base[0] * base[1]} game pixels are not one color across their "
                             f"{s}x{s} screen block. Usual causes: positions or camera off whole pixels, runtime rotation "
                             "or non-integer scaling, linear filtering or mipmaps, or lossy capture.",
                             sample=[{"x": int(x), "y": int(y)} for y, x in np.argwhere(broken)[:20]]))
    off = np.zeros_like(broken)
    if contract["tokens"]:
        off = ~broken & ~np.isin(logical, _pack_colors(contract["tokens"].values()))
        if off.any():
            blending = doc.get("effects", {}).get("blending", "opaque")
            colors = [_hex(v) for v in np.unique(logical[off])[:12]]
            issues.append(_issue("COLOR_OUTSIDE_PALETTE", "fail" if blending == "opaque" else "review",
                                 f"{int(off.sum())} game pixels show colors outside the palette ({', '.join(colors)}); "
                                 "translucent or additive effects, tinting or color grading mix new colors.",
                                 sample=[{"x": int(x), "y": int(y)} for y, x in np.argwhere(off)[:20]]))
    coarse = coarse_windows(np.where(broken, np.uint32(0), logical), max(8, doc.get("tile_size", 16)))
    if coarse:
        issues.append(_issue("COARSE_REGION", "review",
                             f"{len(coarse)} screen windows contain only dots larger than one game pixel; a sprite, "
                             "font or UI element may be drawn at 2x or more.", windows=coarse[:50]))
    report["status"] = _status(issues)
    return report, {"logical": logical, "broken": broken, "off": off, "coarse": coarse}


def save_screen_overlay(report: dict, masks: dict, path: Path) -> None:
    logical = masks["logical"]
    rgba = np.ascontiguousarray(logical).view(np.uint8).reshape(*logical.shape, 4).copy()
    rgba[masks["broken"]] = (255, 40, 40, 255)
    image = Image.fromarray(rgba, "RGBA")
    k = _scale_for(image.size, 1536)
    big = qa.over_background(image.resize((image.width * k, image.height * k), Image.Resampling.NEAREST))
    draw = ImageDraw.Draw(big, "RGBA")
    for y, x in np.argwhere(masks["off"]):
        draw.rectangle((x * k, y * k, (x + 1) * k - 1, (y + 1) * k - 1), outline=(255, 0, 255, 255))
    for box in masks["coarse"]:
        draw.rectangle((box["x"] * k, box["y"] * k, (box["x"] + box["width"]) * k - 1,
                        (box["y"] + box["height"]) * k - 1), outline=(255, 160, 0, 255), width=2)
    big.convert("RGB").save(path)


def intake(source: Path, references: list[Path], contract: dict, category: str | None, out_dir: Path) -> dict:
    """Put a new asset beside references at 1x, enlarge all equally, and compare what can be measured."""
    if not references:
        raise ValueError("Intake needs at least one reference: pass --reference or list style.references")
    new = qa.open_rgba(source)
    refs = [qa.open_rgba(path) for path in references]
    new_report, masks = measure_asset(new, contract, category)
    ref_reports = [measure_asset(ref, contract, None)[0] for ref in refs]
    issues = list(new_report["issues"])
    def dots(metrics):
        measured = metrics["effective_pixel_size"]
        return (measured["x"], measured["y"]), measured["conclusive"]

    new_dots, new_sure = dots(new_report["metrics"])
    ref_dots = [dots(r["metrics"]) for r in ref_reports]
    differing = [(size, sure) for size, sure in ref_dots if size != new_dots]
    if differing:
        # Only two clear measurements prove a mismatch; a plain asset with few edges only suggests one.
        severity = "fail" if new_sure and any(sure for _, sure in differing) else "review"
        issues.append(_issue("PIXEL_SIZE_DIFFERS", severity,
                             f"The new asset's dots measure {new_dots[0]}x{new_dots[1]}; the references measure "
                             f"{', '.join(f'{x}x{y}' for (x, y), _ in ref_dots)}."))
    ref_colors = set()
    for ref in refs:
        arr = np.asarray(ref, dtype=np.uint8)
        ref_colors |= set(np.unique(_packed(arr)[arr[:, :, 3] > 0]).tolist())
    arr = np.asarray(new, dtype=np.uint8)
    new_colors = set(np.unique(_packed(arr)[arr[:, :, 3] > 0]).tolist())
    unseen = sorted(new_colors - ref_colors)
    if unseen:
        issues.append(_issue("COLORS_NOT_IN_REFERENCES", "review",
                             f"{len(unseen)} colors do not appear in any reference: "
                             f"{', '.join(_hex(v) for v in unseen[:12])}. Allowed by the palette, but check they belong."))
    outlines = [r["metrics"].get("outline", {}).get("doubled_fraction") for r in ref_reports]
    mine = new_report["metrics"].get("outline", {}).get("doubled_fraction")
    known = [v for v in outlines if v is not None]
    if mine is not None and known and abs(mine - sum(known) / len(known)) > 0.4:
        issues.append(_issue("OUTLINE_WIDTH_DIFFERS", "review",
                             f"{mine:.0%} of the new outline is two pixels deep; the references average "
                             f"{sum(known) / len(known):.0%}."))
    gap = 4
    images = refs + [new]
    width = sum(i.width for i in images) + gap * (len(images) + 1)
    height = max(i.height for i in images) + 2 * gap
    sheet = Image.new("RGBA", (width, height), NEUTRAL)
    x = gap
    for item in images:
        sheet.alpha_composite(item, (x, height - gap - item.height))
        x += item.width + gap
    k = _scale_for(sheet.size, 768)
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet.resize((width * k, height * k), Image.Resampling.NEAREST).convert("RGB").save(out_dir / "side_by_side.png")
    save_asset_overlay(new, masks, out_dir / "asset_overlay.png")
    report = {"tool": "Pixelwright", "version": VERSION, "schema_version": 1, "mode": "game_intake",
              "status": _status(issues), "artistic_status": "not_reviewed", "category": category,
              "issues": issues, "asset": new_report["metrics"],
              "references": [{"path": str(path.resolve()), "sha256": qa.sha256_file(path), "metrics": r["metrics"]}
                             for path, r in zip(references, ref_reports)],
              "side_by_side": {"order": [str(p) for p in references] + [str(source)], "scale": k, "gap": gap},
              "provenance": {"source_path": str(source.resolve()), "source_sha256": qa.sha256_file(source),
                             "contract_sha256": contract["sha256"]}}
    _write_json(out_dir / "report.json", report)
    return report


def brief(contract: dict) -> str:
    """The style brief an artist or AI follows before drawing for this game."""
    doc = contract["document"]
    bw, bh = contract["base"]
    style = doc.get("style", {})
    lines = [f"# Pixel art style brief: {doc.get('name', 'game')}", "",
             "## Screen and pixel size", "",
             f"- Base resolution {bw}x{bh}. The game renders at this size and is shown only at whole-number scales, "
             f"centered, with {_hex(_pack_colors([contract['letterbox']])[0])[:7]} bars filling the rest of the window.",
             "- Draw and deliver every asset at 1x: one image pixel is one game pixel. Sprites, tiles, effects, UI "
             "and fonts all share that pixel size; never enlarge or shrink a single element.",
             "- Positions of the camera and of every sprite are whole game pixels.",
             "- Textures use nearest-neighbor filtering, no mipmaps and lossless storage."]
    if "tile_size" in doc:
        lines.append(f"- Tiles are {doc['tile_size']}x{doc['tile_size']} pixels; size other assets against them.")
    rotation = doc.get("rotation", {"mode": "none"})
    turns = {"none": "Never rotate art at runtime; draw each orientation.",
             "quarter_turns": "Runtime rotation only in 90-degree turns, plus flips.",
             "prerendered": f"Rotations are drawn in advance ({rotation.get('directions', 'a set of')} directions); "
                            "at runtime use only those frames, 90-degree turns and flips."}
    lines.append(f"- {turns[rotation['mode']]}")
    lines += ["", "## Colors", ""]
    if contract["tokens"]:
        lines.append(f"- Use only these {len(contract['tokens'])} colors:")
        lines += [f"  - `{token}` {_hex(_pack_colors([rgba])[0])}" for token, rgba in contract["tokens"].items()]
        for name, ramp in contract["ramps"].items():
            lines.append(f"- Ramp `{name}`, dark to light: {', '.join(ramp)}")
    if "max_colors" in doc:
        lines.append(f"- At most {doc['max_colors']} visible colors per asset.")
    alpha = doc.get("alpha", "binary")
    lines.append({"binary": "- Pixels are fully opaque or fully transparent; no semi-transparent edges.",
                  "opaque": "- Every pixel is opaque.",
                  "any": "- Semi-transparency is allowed only where it is part of the design."}[alpha])
    lines += ["", "## Style", ""]
    labels = {"genre": "Genre", "perspective": "Perspective", "light_direction": "Light comes from",
              "shading": "Shading", "dithering": "Dithering", "anti_aliasing": "Anti-aliasing", "mood": "Mood"}
    for key, label in labels.items():
        if key in style:
            lines.append(f"- {label}: {style[key]}")
    if "outline" in style:
        outline = style["outline"]
        colors = ", ".join(str(c) for c in outline.get("colors", [])) or "not fixed"
        lines.append(f"- Outline: {outline['mode']}, {outline.get('width', 1)} pixel(s) wide, colors {colors}")
    if "notes" in style:
        lines.append(f"- Notes: {style['notes']}")
    if doc.get("categories"):
        lines += ["", "## Sizes", ""]
        for name, rule in doc["categories"].items():
            if "size" in rule:
                size = rule["size"]
            elif "min_size" in rule and "max_size" in rule:
                size = f"{rule['min_size']} to {rule['max_size']}"
            else:
                size = f"at least {rule['min_size']}" if "min_size" in rule else f"up to {rule.get('max_size', 'any size')}"
            note = f" ({rule['notes']})" if "notes" in rule else ""
            lines.append(f"- {name}: {size}{note}")
    lines += ["", "## Text, motion and effects", ""]
    if "font" in doc:
        font = doc["font"]
        lines.append(f"- Font: {font.get('name', 'bitmap font')} at its native {font.get('size_px', '?')} px"
                     + (f", line height {font['line_height_px']} px" if "line_height_px" in font else "")
                     + "; never scaled, no anti-aliasing.")
    else:
        lines.append("- Text uses a bitmap pixel font at its native size, never scaled, no anti-aliasing.")
    if "animation" in doc:
        lines.append(f"- Animation runs at {doc['animation']['fps']} frames per second; hold frames rather than tween.")
    blending = doc.get("effects", {}).get("blending", "opaque")
    lines.append("- Particles and effects are drawn on the same pixel grid with palette colors"
                 + ("; no translucent or additive blending." if blending == "opaque"
                    else "; translucency only where its result is reviewed on screen."))
    if contract["references"]:
        lines += ["", "## Reference assets", ""]
        for path in contract["references"]:
            digest = qa.sha256_file(path)[:12] if path.is_file() else "missing"
            lines.append(f"- {path.relative_to(contract['path'].parent).as_posix()} (sha256 {digest})")
        lines.append("- Before adding an asset, place it beside these at 1x (`pixel_game.py intake`).")
    if "engine" in doc:
        lines += ["", "## Engine", "", f"- {doc['engine']}: apply the settings in references/engines.md."]
    return "\n".join(lines) + "\n"


def _offset(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+),(\d+)", text)
    if match is None:
        raise argparse.ArgumentTypeError("offset must be X,Y")
    return int(match[1]), int(match[2])


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p_brief = sub.add_parser("brief", help="Print the style brief for this game")
    p_view = sub.add_parser("viewport", help="Whole-number scale and letterbox for window sizes")
    p_view.add_argument("windows", nargs="+", type=qa.parse_size)
    p_asset = sub.add_parser("asset", help="Check 1x assets against the contract")
    p_asset.add_argument("images", nargs="+", type=Path)
    p_asset.add_argument("--category")
    p_intake = sub.add_parser("intake", help="Compare a new asset with reference assets at 1x")
    p_intake.add_argument("image", type=Path)
    p_intake.add_argument("--reference", action="append", type=Path, default=[])
    p_intake.add_argument("--category")
    p_screen = sub.add_parser("screen", help="Check a lossless game screenshot")
    p_screen.add_argument("image", type=Path)
    p_screen.add_argument("--scale", type=int)
    p_screen.add_argument("--offset", type=_offset, help="Viewport top-left in screenshot pixels, X,Y")
    for p in (p_brief, p_view, p_asset, p_intake, p_screen):
        p.add_argument("--contract", required=True, type=Path)
    for p in (p_asset, p_intake, p_screen):
        p.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        contract = load_contract(args.contract)
        if args.action == "brief":
            sys.stdout.write(brief(contract))
            return 0
        if args.action == "viewport":
            print(json.dumps([viewport(size, contract["base"]) for size in args.windows], indent=2))
            return 0
        if args.action == "asset":
            _fresh(args.out_dir, args.images + [args.contract])
            if len(args.images) == 1:
                result = check_asset(args.images[0], contract, args.category, args.out_dir)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["status"] == "pass" else 2
            results = []
            for index, source in enumerate(args.images):
                try:
                    results.append(check_asset(source, contract, args.category, args.out_dir / f"{index:04d}"))
                except (ValueError, OSError) as exc:
                    results.append({"input": str(source), "status": "error", "error": str(exc)})
            statuses = {r["status"] for r in results}
            status = ("error" if "error" in statuses else "fail" if "fail" in statuses
                      else "review" if "review" in statuses else "pass")
            summary = {"tool": "Pixelwright", "version": VERSION, "schema_version": 1, "mode": "game_asset_batch",
                       "status": status, "contract_sha256": contract["sha256"], "results": results}
            _write_json(args.out_dir / "batch.json", summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 1 if status == "error" else 0 if status == "pass" else 2
        if args.action == "intake":
            references = args.reference or contract["references"]
            _fresh(args.out_dir, [args.image, args.contract, *references])
            report = intake(args.image, references, contract, args.category, args.out_dir)
            print(json.dumps({"status": report["status"], "issues": [i["code"] for i in report["issues"]],
                              "outputs": {"report": str(args.out_dir / "report.json"),
                                          "side_by_side": str(args.out_dir / "side_by_side.png")}}, indent=2))
            return 0 if report["status"] == "pass" else 2
        _fresh(args.out_dir, [args.image, args.contract])
        image = qa.open_rgba(args.image)
        report, masks = measure_screen(image, contract, args.scale, args.offset)
        report["provenance"] = {"source_path": str(args.image.resolve()), "source_sha256": qa.sha256_file(args.image),
                                "contract_sha256": contract["sha256"]}
        if masks:
            save_screen_overlay(report, masks, args.out_dir / "screen_overlay.png")
        _write_json(args.out_dir / "report.json", report)
        print(json.dumps({"status": report["status"], "viewport": report["viewport"],
                          "issues": [i["code"] for i in report["issues"]]}, indent=2))
        return 0 if report["status"] == "pass" else 2
    except (ValueError, OSError, MemoryError) as exc:
        print(f"Pixelwright error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
