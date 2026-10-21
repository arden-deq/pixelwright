#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build and audit sprite sheets, animations and declared part rigs.

A sprite spec places equally sized frames on one static PNG sheet, names
optional animations, and can declare a rig: joint coordinates per frame plus a
part map assigning visible logical cells to body or object parts. The checker
audits the whole sheet with the strict profile first. It then verifies empty
gutters and frame bounds, draws the declared skeleton over every frame, and
checks whether each part keeps its dots while its joints move. It never infers
a skeleton, resizes or redraws art. PASS does not assess timing or appeal.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

import pixel_build as builder
import pixel_qa as qa
import pixelwright as project

VERSION = "0.6.0"
MAX_SPEC_BYTES = 8 * 1024 * 1024
MAX_FRAMES = 1024
MAX_PARTS = 64
MAX_JOINTS = 128
MAX_ANIMATIONS = 256
MAX_DURATION_MS = 60_000
NO_PART = "."
MOTIONS = ("fixed", "rigid", "bone", "free")
DEFAULTS = {"area_tolerance": 0.25, "length_tolerance": 1.0, "min_shape_match": 0.8, "max_drift": 1.0}
# Fewer comparable dots than this make a centroid too noisy to judge drift.
DRIFT_MIN_CELLS = 6
SPEC_KEYS = {"schema_version", "name", "frame_size", "layout", "frame_count", "edge_margin",
             "scale", "palette", "palette_file", "frames", "animations", "rig"}
LAYOUT_KEYS = {"columns", "rows", "margin", "spacing"}
FRAME_KEYS = {"rows", "parts", "joints", "hidden", "z"}
ANIMATION_KEYS = {"frames", "loop", "frame_ms", "durations_ms"}
RIG_KEYS = {"reference_frame", "coverage", "max_joint_step", "defaults", "joints", "parts"}
JOINT_KEYS = {"fixed"}
PART_KEYS = {"token", "motion", "bone", "pivot", "parent", "axis", "z", "reference_frame",
             "area_tolerance", "length_tolerance", "min_shape_match", "max_drift"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_LOCK = ".pixelwright-sprite.lock"
_EPSILON = 1e-9
# Distinct overlay hues; they mark part membership only and never enter artwork.
PART_COLORS = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48),
               (145, 30, 180), (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212),
               (0, 128, 128), (220, 190, 255), (170, 110, 40), (255, 250, 200), (128, 0, 0),
               (170, 255, 195), (128, 128, 0), (255, 215, 180), (0, 0, 128), (128, 128, 128)]


@dataclass(frozen=True)
class Layout:
    frame_size: tuple[int, int]
    columns: int
    rows: int
    margin: int
    spacing: int
    frame_count: int
    edge_margin: int

    @property
    def capacity(self) -> int:
        return self.columns * self.rows

    @property
    def sheet_size(self) -> tuple[int, int]:
        fw, fh = self.frame_size
        return (2 * self.margin + self.columns * fw + (self.columns - 1) * self.spacing,
                2 * self.margin + self.rows * fh + (self.rows - 1) * self.spacing)

    def origin(self, index: int) -> tuple[int, int]:
        """Top-left logical cell of a row-major frame slot."""
        fw, fh = self.frame_size
        column, row = index % self.columns, index // self.columns
        return self.margin + column * (fw + self.spacing), self.margin + row * (fh + self.spacing)


@dataclass(frozen=True)
class Part:
    id: str
    token: str
    motion: str
    bone: tuple[str, str] | None
    pivot: str | None
    parent: str | None
    axis: tuple[float, float] | None
    z: int
    reference_frame: int
    area_tolerance: float
    length_tolerance: float
    min_shape_match: float
    max_drift: float

    @property
    def joints(self) -> tuple[str, ...]:
        return self.bone if self.bone else (self.pivot,) if self.pivot else ()


@dataclass(frozen=True)
class Rig:
    reference_frame: int
    coverage: str
    max_joint_step: float | None
    joints: tuple[str, ...]
    fixed_joints: tuple[str, ...]
    parts: tuple[Part, ...]
    maps: tuple[tuple[str, ...], ...]
    poses: tuple[dict[str, tuple[float, float]], ...]
    hidden: tuple[frozenset[str], ...]
    depths: tuple[dict[str, int], ...]


@dataclass(frozen=True)
class SpritePlan:
    name: str | None
    layout: Layout
    scale: int | None
    palette_document: dict[str, Any] | None
    frame_rows: tuple[Any, ...] | None
    animations: tuple[dict[str, Any], ...]
    rig: Rig | None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number is unsupported: {value}")


def _read_json(path: Path) -> tuple[Any, bytes]:
    if path.stat().st_size > MAX_SPEC_BYTES:
        raise ValueError(f"JSON input exceeds {MAX_SPEC_BYTES:,} bytes")
    data = path.read_bytes()
    if len(data) > MAX_SPEC_BYTES:
        raise ValueError(f"JSON input exceeds {MAX_SPEC_BYTES:,} bytes")
    try:
        document = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid UTF-8 JSON: {exc}") from exc
    return document, data


def _fields(value: Any, name: str, allowed: set[str], required: tuple[str, ...] = ()) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    unknown = set(value) - allowed
    missing = set(required) - value.keys()
    if unknown or missing:
        raise ValueError(f"{name} fields invalid; missing={sorted(missing)}, unknown={sorted(unknown)}")
    return value


def _int(value: Any, name: str, low: int, high: int) -> int:
    # Booleans are integers in Python; reject them so `true` cannot mean 1.
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def _number(value: Any, name: str, low: float, high: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be a number in {low:g}..{high:g}")
    return float(value)


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be 1..64 safe ASCII letters, digits, '_' or '-'")
    return value


def _size(value: Any, name: str) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be WIDTHxHEIGHT")
    try:
        return qa.parse_size(value)
    except argparse.ArgumentTypeError as exc:
        raise ValueError(f"{name}: {exc}") from exc


def _parse_layout(document: dict[str, Any]) -> Layout:
    frame_size = _size(document["frame_size"], "frame_size")
    raw = _fields(document["layout"], "layout", LAYOUT_KEYS, ("columns", "rows"))
    columns = _int(raw["columns"], "layout.columns", 1, 4096)
    rows = _int(raw["rows"], "layout.rows", 1, 4096)
    margin = _int(raw.get("margin", 0), "layout.margin", 0, 4096)
    spacing = _int(raw.get("spacing", 0), "layout.spacing", 0, 4096)
    if columns * rows > MAX_FRAMES:
        raise ValueError(f"A sheet holds at most {MAX_FRAMES} frame slots")
    frame_count = _int(document.get("frame_count", columns * rows), "frame_count", 1, columns * rows)
    edge_margin = _int(document.get("edge_margin", 0), "edge_margin", 0, 2048)
    if edge_margin and 2 * edge_margin >= min(frame_size):
        raise ValueError("edge_margin leaves no drawable cells inside the frame")
    layout = Layout(frame_size, columns, rows, margin, spacing, frame_count, edge_margin)
    if any(value > 4096 for value in layout.sheet_size):
        raise ValueError("Sheet logical dimensions must each be 1..4096")
    return layout


def _parse_animations(raw: Any, frame_count: int) -> tuple[dict[str, Any], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict) or not 1 <= len(raw) <= MAX_ANIMATIONS:
        raise ValueError(f"animations must be an object with 1..{MAX_ANIMATIONS} entries")
    animations = []
    for animation_id, entry in raw.items():
        _identifier(animation_id, "Animation id")
        name = f"Animation {animation_id}"
        _fields(entry, name, ANIMATION_KEYS, ("frames",))
        frames = entry["frames"]
        if not isinstance(frames, list) or not 1 <= len(frames) <= 4096:
            raise ValueError(f"{name} frames must list 1..4096 frame indices")
        frames = [_int(index, f"{name} frame index", 0, frame_count - 1) for index in frames]
        loop = entry.get("loop", True)
        if type(loop) is not bool:
            raise ValueError(f"{name} loop must be a boolean")
        if "frame_ms" in entry and "durations_ms" in entry:
            raise ValueError(f"{name} uses frame_ms or durations_ms, not both")
        if "durations_ms" in entry:
            durations = entry["durations_ms"]
            if not isinstance(durations, list) or len(durations) != len(frames):
                raise ValueError(f"{name} durations_ms must match its frame list")
            durations = [_int(value, f"{name} duration", 1, MAX_DURATION_MS) for value in durations]
        else:
            durations = [_int(entry.get("frame_ms", 100), f"{name} frame_ms", 1, MAX_DURATION_MS)] * len(frames)
        animations.append({"id": animation_id, "frames": tuple(frames), "loop": loop,
                           "durations_ms": tuple(durations)})
    return tuple(animations)


def _parse_point(value: Any, name: str, size: tuple[int, int]) -> tuple[float, float]:
    # Integer coordinates name logical cell centers; .5 lies between two cells.
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must be [x, y] in logical cells")
    x = _number(value[0], f"{name} x", -0.5, size[0] - 0.5)
    y = _number(value[1], f"{name} y", -0.5, size[1] - 0.5)
    return x, y


def _parse_part(part_id: str, raw: Any, joints: set[str], rig_reference: int,
                frame_count: int, defaults: dict[str, float], order: int) -> Part:
    name = f"Part {part_id}"
    _fields(raw, name, PART_KEYS, ("token", "motion"))
    token = raw["token"]
    if not isinstance(token, str) or len(token) != 1 or token == NO_PART or not token.isprintable() or token.isspace():
        raise ValueError(f"{name} token must be one printable non-space character other than '{NO_PART}'")
    motion = raw["motion"]
    if motion not in MOTIONS:
        raise ValueError(f"{name} motion must be one of {', '.join(MOTIONS)}")
    bone = raw.get("bone")
    if (motion == "bone") != (bone is not None):
        raise ValueError(f"{name} declares bone exactly when motion is 'bone'")
    if bone is not None:
        if (not isinstance(bone, list) or len(bone) != 2 or bone[0] == bone[1]
                or any(not isinstance(value, str) or value not in joints for value in bone)):
            raise ValueError(f"{name} bone must name two different declared joints")
        bone = (bone[0], bone[1])
    pivot = raw.get("pivot")
    # A rigid copy is placed by its pivot, so partly covered frames can still be checked.
    if (motion == "rigid") != (pivot is not None) or (pivot is not None and (not isinstance(pivot, str) or pivot not in joints)):
        raise ValueError(f"{name} declares a pivot joint exactly when motion is 'rigid'")
    axis = raw.get("axis")
    if axis is not None:
        if motion != "rigid" or not isinstance(axis, list) or len(axis) != 2:
            raise ValueError(f"{name} axis must be [dx, dy] on a rigid part")
        axis = (_number(axis[0], f"{name} axis", -4096, 4096), _number(axis[1], f"{name} axis", -4096, 4096))
        if axis == (0.0, 0.0):
            raise ValueError(f"{name} axis must not be zero")
    parent = raw.get("parent")
    if parent is not None:
        _identifier(parent, f"{name} parent")
        if parent == part_id:
            raise ValueError(f"{name} cannot be its own parent")
    z = _int(raw.get("z", order), f"{name} z", -4096, 4096)
    reference = _int(raw.get("reference_frame", rig_reference), f"{name} reference_frame", 0, frame_count - 1)
    tolerances = {
        "area_tolerance": _number(raw.get("area_tolerance", defaults["area_tolerance"]), f"{name} area_tolerance", 0, 4),
        "length_tolerance": _number(raw.get("length_tolerance", defaults["length_tolerance"]), f"{name} length_tolerance", 0, 4096),
        "min_shape_match": _number(raw.get("min_shape_match", defaults["min_shape_match"]), f"{name} min_shape_match", 0, 1),
        "max_drift": _number(raw.get("max_drift", defaults["max_drift"]), f"{name} max_drift", 0, 4096),
    }
    return Part(part_id, token, motion, bone, pivot, parent, axis, z, reference, **tolerances)


def _parse_rig(raw: Any, frames: list[dict[str, Any]] | None, layout: Layout) -> Rig:
    _fields(raw, "rig", RIG_KEYS, ("joints", "parts"))
    count = layout.frame_count
    reference = _int(raw.get("reference_frame", 0), "rig.reference_frame", 0, count - 1)
    coverage = raw.get("coverage", "complete")
    if coverage not in ("complete", "partial"):
        raise ValueError("rig.coverage must be complete or partial")
    max_step = raw.get("max_joint_step")
    if max_step is not None:
        max_step = _number(max_step, "rig.max_joint_step", 0, 4096)
        if max_step <= 0:
            raise ValueError("rig.max_joint_step must be positive")
    defaults = dict(DEFAULTS)
    raw_defaults = _fields(raw.get("defaults", {}), "rig.defaults", set(DEFAULTS))
    for key, value in raw_defaults.items():
        limit = {"area_tolerance": 4, "min_shape_match": 1}.get(key, 4096)
        defaults[key] = _number(value, f"rig.defaults.{key}", 0, limit)
    raw_joints = raw["joints"]
    if not isinstance(raw_joints, dict) or len(raw_joints) > MAX_JOINTS:
        raise ValueError(f"rig.joints must be an object with at most {MAX_JOINTS} joints")
    fixed_joints = []
    for joint, options in raw_joints.items():
        _identifier(joint, "Joint name")
        _fields(options, f"Joint {joint}", JOINT_KEYS)
        fixed = options.get("fixed", False)
        if type(fixed) is not bool:
            raise ValueError(f"Joint {joint} fixed must be a boolean")
        if fixed:
            fixed_joints.append(joint)
    joints = tuple(raw_joints)
    raw_parts = raw["parts"]
    if not isinstance(raw_parts, dict) or not 1 <= len(raw_parts) <= MAX_PARTS:
        raise ValueError(f"rig.parts must be an object with 1..{MAX_PARTS} parts")
    # Parts are listed back to front; that order is the default drawing depth z.
    parts = tuple(_parse_part(_identifier(part_id, "Part id"), value, set(joints), reference, count, defaults, order)
                  for order, (part_id, value) in enumerate(raw_parts.items()))
    ids = {part.id for part in parts}
    tokens = [part.token for part in parts]
    if len(set(tokens)) != len(tokens):
        raise ValueError("Every part needs a unique token")
    for part in parts:
        if part.parent is not None and part.parent not in ids:
            raise ValueError(f"Part {part.id} parent is not a declared part")
    parents = {part.id: part.parent for part in parts}
    for part in parts:
        seen, current = set(), part.id
        while current is not None:
            if current in seen:
                raise ValueError(f"Part parents form a cycle at {part.id}")
            seen.add(current)
            current = parents[current]
    if frames is None:
        raise ValueError("A rig needs frames with a part map and joints for every frame")
    token_set = set(tokens) | {NO_PART}
    fw, fh = layout.frame_size
    maps, poses, hidden_parts, depths = [], [], [], []
    for index, frame in enumerate(frames):
        name = f"Frame {index}"
        if "parts" not in frame or "joints" not in frame:
            raise ValueError(f"{name} needs parts and joints when a rig is declared")
        rows = frame["parts"]
        if not isinstance(rows, list) or len(rows) != fh:
            raise ValueError(f"{name} parts must contain {fh} rows")
        for y, row in enumerate(rows):
            if not isinstance(row, str) or len(row) != fw:
                raise ValueError(f"{name} parts row {y} must be a string of {fw} part tokens")
            unknown = set(row) - token_set
            if unknown:
                raise ValueError(f"{name} parts row {y} uses undeclared tokens: {''.join(sorted(unknown))!r}")
        maps.append(tuple(rows))
        pose = _fields(frame["joints"], f"{name} joints", set(joints), joints)
        poses.append({joint: _parse_point(pose[joint], f"{name} joint {joint}", layout.frame_size)
                      for joint in joints})
        hidden = frame.get("hidden", [])
        if (not isinstance(hidden, list) or any(not isinstance(value, str) or value not in ids for value in hidden)
                or len(set(hidden)) != len(hidden)):
            raise ValueError(f"{name} hidden must list unique declared part ids")
        for part in parts:
            if part.id in hidden and any(part.token in row for row in rows):
                raise ValueError(f"{name} lists {part.id} as hidden but its part map shows it")
        hidden_parts.append(frozenset(hidden))
        overrides = _fields(frame.get("z", {}), f"{name} z", ids)
        depths.append({part.id: _int(overrides.get(part.id, part.z), f"{name} z of {part.id}", -4096, 4096)
                       for part in parts})
    for part in parts:
        ref = part.reference_frame
        if not any(part.token in row for row in maps[ref]):
            raise ValueError(f"Part {part.id} must be visible in its reference frame {ref}")
        if part.bone is not None and _distance(poses[ref][part.bone[0]], poses[ref][part.bone[1]]) < 1:
            raise ValueError(f"Part {part.id} bone must be at least one cell long in its reference frame")
    return Rig(reference, coverage, max_step, joints, tuple(fixed_joints), parts,
               tuple(maps), tuple(poses), tuple(hidden_parts), tuple(depths))


def parse_spec(document: Any) -> SpritePlan:
    """Validate a schema-version-1 sprite spec without reading any PNG."""
    _fields(document, "Sprite spec", SPEC_KEYS, ("schema_version", "frame_size", "layout"))
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("Sprite spec schema_version must be the integer 1")
    name = document.get("name")
    if name is not None and (not isinstance(name, str) or len(name) > 256):
        raise ValueError("Sprite spec name must be a string of at most 256 characters")
    layout = _parse_layout(document)
    scale = document.get("scale")
    if scale is not None:
        scale = _int(scale, "scale", 2, 4096)
        width, height = layout.sheet_size
        if width * height * scale * scale > qa.MAX_PIXELS:
            raise ValueError(f"Rendered sheet would exceed {qa.MAX_PIXELS:,} pixels")
    if "palette" in document and "palette_file" in document:
        raise ValueError("Specify at most one of palette or palette_file")
    palette_document = ({key: document[key] for key in ("palette", "palette_file") if key in document}
                        or None)
    frames = document.get("frames")
    if frames is not None:
        if not isinstance(frames, list) or len(frames) != layout.frame_count:
            raise ValueError(f"frames must list exactly {layout.frame_count} frame entries")
        for index, frame in enumerate(frames):
            _fields(frame, f"Frame {index}", FRAME_KEYS)
    frame_rows = None
    if frames is not None and any("rows" in frame for frame in frames):
        if not all("rows" in frame for frame in frames):
            raise ValueError("Provide color rows for every frame or for none")
        if palette_document is None:
            raise ValueError("Frame color rows need palette or palette_file")
        frame_rows = tuple(frame["rows"] for frame in frames)
    animations = _parse_animations(document.get("animations"), layout.frame_count)
    rig = None
    if "rig" in document:
        rig = _parse_rig(document["rig"], frames, layout)
    elif frames is not None and any(key in frame for frame in frames for key in ("parts", "joints", "hidden", "z")):
        raise ValueError("Frame parts, joints, hidden and z require a rig declaration")
    return SpritePlan(name, layout, scale, palette_document, frame_rows, animations, rig)


def load_spec(path: str | Path) -> tuple[SpritePlan, Path, bytes]:
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("Sprite spec must be an existing file")
    document, data = _read_json(source)
    return parse_spec(document), source, data


def _hex(rgba: tuple[int, ...]) -> str:
    return "#" + "".join(f"{channel:02X}" for channel in rgba)


def frames_from_rows(plan: SpritePlan, base_dir: Path, scale: int) -> tuple[list[np.ndarray], dict[str, str], dict[str, str] | None]:
    """Expand frame token rows using the indexed builder's validation rules."""
    if plan.frame_rows is None or plan.palette_document is None:
        raise ValueError("Every frame needs color rows and the spec needs a palette")
    arrays: list[np.ndarray] = []
    palette: dict[str, str] = {}
    source = None
    for index, rows in enumerate(plan.frame_rows):
        # Resolve a palette_file once; later frames reuse those exact colors.
        colors = plan.palette_document if index == 0 else {"palette": palette}
        try:
            spec = builder.parse_spec({"schema_version": 1, "scale": scale, **colors, "rows": rows},
                                      base_dir=base_dir)
        except builder.SpecError as exc:
            raise ValueError(f"Frame {index}: {exc}") from exc
        if index == 0:
            palette = {token: _hex(rgba) for token, rgba in spec.palette.items()}
            source = spec.palette_source
        if (spec.width, spec.height) != plan.layout.frame_size:
            raise ValueError(f"Frame {index} rows are {spec.width}x{spec.height}; frame_size is "
                             f"{plan.layout.frame_size[0]}x{plan.layout.frame_size[1]}")
        arrays.append(np.array([[spec.palette[token] for token in row] for row in spec.rows], dtype=np.uint8))
    return arrays, palette, source


def _png_bytes(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def _prepare_output(out_dir: str | Path, inputs: list[Path]) -> Path:
    requested = Path(out_dir).expanduser()
    project.require_empty_output(requested, inputs)
    root = requested.resolve()
    root.mkdir(parents=True, exist_ok=True)
    _write_new(root / _LOCK, b"")
    if any(path.name != _LOCK for path in root.iterdir()):
        (root / _LOCK).unlink(missing_ok=True)
        raise ValueError("Output directory is no longer empty")
    return root


def _layout_record(layout: Layout) -> dict[str, Any]:
    return {"frame_size": list(layout.frame_size), "columns": layout.columns, "rows": layout.rows,
            "margin": layout.margin, "spacing": layout.spacing, "frame_count": layout.frame_count,
            "edge_margin": layout.edge_margin, "sheet_logical_size": list(layout.sheet_size),
            "order": "row_major", "gutter": "alpha_zero",
            "frame_origins": [list(layout.origin(index)) for index in range(layout.frame_count)]}


def build_sheet(spec_path: str | Path, out_dir: str | Path) -> dict[str, Any]:
    """Assemble frame token rows into native.png and rendered.png sheets.

    Gutters, margins and unused slots are fully transparent. The rendered sheet
    is one nearest-neighbor enlargement of the native sheet. Construction is
    recorded in build.json; acceptance still requires `check` on the saved PNG.
    """
    plan, source, data = load_spec(spec_path)
    if plan.scale is None:
        raise ValueError("Building a sheet requires scale in the sprite spec")
    frames, palette, palette_source = frames_from_rows(plan, source.parent, plan.scale)
    inputs = [source] + ([Path(palette_source["path"])] if palette_source else [])
    width, height = plan.layout.sheet_size
    fw, fh = plan.layout.frame_size
    canvas = np.zeros((height, width, 4), dtype=np.uint8)
    for index, frame in enumerate(frames):
        x, y = plan.layout.origin(index)
        canvas[y:y + fh, x:x + fw] = frame
    native = Image.fromarray(canvas, "RGBA")
    rendered = native.resize((width * plan.scale, height * plan.scale), Image.Resampling.NEAREST)
    native_bytes, rendered_bytes = _png_bytes(native), _png_bytes(rendered)
    manifest: dict[str, Any] = {
        "schema_version": 1, "pixelwright_version": VERSION,
        "input": {"path": str(source), "sha256": _sha256(data), "format": "pixelwright-sprite-spec-v1"},
        "grid": {"logical_width": width, "logical_height": height, "scale": plan.scale,
                 "rendered_width": rendered.width, "rendered_height": rendered.height, "origin": [0, 0]},
        "layout": _layout_record(plan.layout),
        "palette": palette,
        "construction": {"method": "indexed-frame-sheet", "resize_filter": "nearest-neighbor",
                         "transparent_rgb": "normalized-to-zero", "uniform_square_rgba_cells": True,
                         "rig_checked": False, "artistic_quality_assessed": False},
        "outputs": {
            "native.png": {"width": native.width, "height": native.height, "mode": "RGBA",
                           "sha256": _sha256(native_bytes), "pixel_rgba_sha256": _sha256(native.tobytes())},
            "rendered.png": {"width": rendered.width, "height": rendered.height, "mode": "RGBA",
                             "sha256": _sha256(rendered_bytes), "pixel_rgba_sha256": _sha256(rendered.tobytes())},
        },
    }
    if palette_source is not None:
        manifest["palette_source"] = palette_source
    root = _prepare_output(out_dir, inputs)
    created: list[Path] = []
    try:
        if palette_source is not None and qa.sha256_file(Path(palette_source["path"])) != palette_source["sha256"]:
            raise ValueError("Palette library changed during build")
        for name, payload in (("native.png", native_bytes), ("rendered.png", rendered_bytes),
                              ("build.json", _json_bytes(manifest))):
            created.append(root / name)
            _write_new(root / name, payload)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    finally:
        (root / _LOCK).unlink(missing_ok=True)
    return manifest


def _issue(code: str, severity: str, detail: str, **context: Any) -> dict[str, Any]:
    entry = {"code": code, "severity": severity, "detail": detail}
    entry.update({key: value for key, value in context.items() if value is not None})
    return entry


def _worst(issues: list[dict[str, Any]], base: str = "pass") -> str:
    severities = {issue["severity"] for issue in issues}
    if base == "fail" or "fail" in severities:
        return "fail"
    return "review" if base == "review" or "review" in severities else "pass"


def _num(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(float(value), 4)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _dilate(mask: np.ndarray) -> np.ndarray:
    """Grow a mask by one cell in all eight directions (Chebyshev distance 1)."""
    grown = mask.copy()
    h, w = mask.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                grown[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)] |= \
                    mask[max(0, -dy):h + min(0, -dy), max(0, -dx):w + min(0, -dx)]
    return grown


def _components(mask: np.ndarray) -> int:
    """Count 8-connected groups of cells."""
    seen = np.zeros_like(mask, dtype=bool)
    h, w = mask.shape
    groups = 0
    for y, x in np.argwhere(mask):
        if seen[y, x]:
            continue
        groups += 1
        seen[y, x] = True
        queue = deque([(int(y), int(x))])
        while queue:
            cy, cx = queue.popleft()
            for ny in range(max(0, cy - 1), min(h, cy + 2)):
                for nx in range(max(0, cx - 1), min(w, cx + 2)):
                    if mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        queue.append((ny, nx))
    return groups


def _keys(frame: np.ndarray) -> np.ndarray:
    # One packed integer per RGBA cell lets masks compare exact colors cheaply.
    return np.ascontiguousarray(frame).view(np.uint32).reshape(frame.shape[:2])


def _bbox(mask: np.ndarray) -> list[int] | None:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def _samples(mask: np.ndarray, origin: tuple[int, int] = (0, 0), limit: int = 20) -> list[dict[str, int]]:
    return [{"x": int(x) + origin[0], "y": int(y) + origin[1]} for y, x in np.argwhere(mask)[:limit]]


def _audit_sheet(sheet_path: Path, profile: dict[str, Any], profile_path: Path,
                 audit_dir: Path, root: Path) -> tuple[dict[str, Any], dict[str, str], Image.Image, np.ndarray | None]:
    """Run the strict profile audit and keep the exact decoded samples it saw."""
    before = qa.sha256_file(sheet_path)
    image = qa.open_rgba(sheet_path)
    after = qa.sha256_file(sheet_path)
    logical, rendered = project.contract_options(profile)
    geometry = qa.grid_geometry(image.size, logical, rendered)
    native = None
    policy = profile.get("transparent_rgb", "exact")
    if geometry["status"] == "pass":
        audit = qa.inspect_image(image, logical, max_colors=profile.get("max_colors"),
                                 strict_alpha=profile.get("alpha", "binary") == "binary",
                                 strict_cells=True, transparent_rgb=policy)
        report = audit.result
        report["geometry"] = geometry
        project.enforce_profile(report, image, profile)
        paths = qa.write_audit(audit, audit_dir)
        # Frame and rig checks need exactly one color per cell. Palette or alpha
        # failures still allow these diagnostics; nonuniform cells do not.
        if report["metrics"]["nonuniform_rgba_cells"] == 0:
            arr = np.asarray(image, dtype=np.uint8)
            if policy == "visible":
                arr = qa.normalize_rgba(arr)
            native = arr[::profile["scale"], ::profile["scale"]].copy()
    else:
        paths = qa.write_geometry_failure(image, logical, audit_dir, geometry)
        report = json.loads(Path(paths["report"]).read_text(encoding="utf-8"))
        report["contract"] = profile
        report["artistic_status"] = "not_reviewed"
    if before != after:
        report["issues"].append({"code": "INPUT_CHANGED", "severity": "fail",
                                 "detail": "Sheet bytes changed while being decoded and audited."})
        report["status"] = "fail"
        native = None
    report["version"] = VERSION
    report["acceptance_mode"] = "strict_sprite_sheet"
    report.setdefault("provenance", {}).update({
        "source_path": sheet_path.name, "source_sha256": before, "source_sha256_after_audit": after,
        "profile_path": profile_path.name, "profile_sha256": qa.sha256_file(profile_path)})
    Path(paths["report"]).write_bytes(_json_bytes(report))
    relative = {key: Path(value).resolve().relative_to(root).as_posix() for key, value in paths.items()}
    return report, relative, image, native


def _check_frames(native: np.ndarray, layout: Layout) -> tuple[list[np.ndarray], list[dict[str, Any]], list[dict[str, Any]], np.ndarray]:
    fw, fh = layout.frame_size
    visible = native[:, :, 3] > 0
    claimed = np.zeros(visible.shape, dtype=bool)
    frames: list[np.ndarray] = []
    records: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index in range(layout.capacity):
        x, y = layout.origin(index)
        claimed[y:y + fh, x:x + fw] = True
        seen = visible[y:y + fh, x:x + fw]
        if index >= layout.frame_count:
            count = int(np.count_nonzero(seen))
            if count:
                issues.append(_issue("UNUSED_SLOT_NOT_EMPTY", "fail",
                                     f"Unused slot {index} contains {count} visible cells.",
                                     slot=index, sample=_samples(seen, (x, y))))
            continue
        frames.append(native[y:y + fh, x:x + fw].copy())
        box = _bbox(seen)
        record = {"index": index, "slot": [index % layout.columns, index // layout.columns],
                  "origin": [x, y], "visible_cells": int(np.count_nonzero(seen)), "bbox": box}
        if box is None:
            issues.append(_issue("EMPTY_FRAME", "review", f"Frame {index} has no visible cells.", frame=index))
        elif layout.edge_margin:
            m = layout.edge_margin
            if box[0] < m or box[1] < m or box[2] > fw - 1 - m or box[3] > fh - 1 - m:
                issues.append(_issue("EDGE_MARGIN_VIOLATION", "fail",
                                     f"Frame {index} content bbox {box} enters the declared {m}-cell edge margin.",
                                     frame=index))
        records.append(record)
    gutter = visible & ~claimed
    count = int(np.count_nonzero(gutter))
    if count:
        issues.append(_issue("GUTTER_NOT_EMPTY", "fail",
                             f"{count} visible cells lie in margins or spacing between frames.",
                             sample=_samples(gutter)))
    return frames, records, issues, gutter


def _check_animations(animations: tuple[dict[str, Any], ...], frames: list[np.ndarray],
                      records: list[dict[str, Any]], frame_count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results, issues = [], []
    used: set[int] = set()
    for animation in animations:
        sequence = animation["frames"]
        used.update(sequence)
        boxes = [records[index]["bbox"] for index in sequence]
        baselines = sorted({box[3] for box in boxes if box})
        if len(baselines) > 1:
            issues.append(_issue("BASELINE_SHIFT", "info",
                                 f"Lowest visible row varies across the sequence: {baselines}. "
                                 "Intentional for jumps or bobbing; otherwise the sprite may jitter.",
                                 animation=animation["id"]))
        pairs = list(zip(sequence, sequence[1:]))
        if animation["loop"] and len(sequence) > 1:
            pairs.append((sequence[-1], sequence[0]))
        repeated = [[a, b] for a, b in pairs if a != b and np.array_equal(frames[a], frames[b])]
        if repeated:
            issues.append(_issue("DUPLICATE_ADJACENT_FRAMES", "info",
                                 f"Adjacent frames have identical pixels: {repeated}. Use a duration to hold a pose.",
                                 animation=animation["id"]))
        results.append({"id": animation["id"], "frames": list(sequence), "loop": animation["loop"],
                        "durations_ms": list(animation["durations_ms"]),
                        "total_ms": sum(animation["durations_ms"]), "baseline_rows": baselines})
    unused = sorted(set(range(frame_count)) - used)
    if animations and unused:
        issues.append(_issue("UNUSED_FRAMES", "info", f"Frames not referenced by any animation: {unused}."))
    return results, issues


def _part_masks(rows: tuple[str, ...], parts: tuple[Part, ...]) -> dict[str, np.ndarray]:
    grid = np.array([list(row) for row in rows], dtype="<U1")
    return {part.id: grid == part.token for part in parts}


def _shift(mask: np.ndarray, keys: np.ndarray, dx: int, dy: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Move reference cells by an integer offset; count cells leaving the frame."""
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    tx, ty = xs + dx, ys + dy
    inside = (tx >= 0) & (tx < w) & (ty >= 0) & (ty < h)
    moved = np.zeros_like(mask)
    moved_keys = np.zeros_like(keys)
    moved[ty[inside], tx[inside]] = True
    moved_keys[ty[inside], tx[inside]] = keys[ys[inside], xs[inside]]
    return moved, moved_keys, int(np.count_nonzero(~inside))


def _bone_map(xs: np.ndarray, ys: np.ndarray, start0, end0, start1, end1) -> tuple[np.ndarray, np.ndarray]:
    """Carry cell centers along a bone: keep distance across it, stretch along it."""
    a0, b0, a1, b1 = (np.array(point, dtype=np.float64) for point in (start0, end0, start1, end1))
    l0, l1 = np.linalg.norm(b0 - a0), np.linalg.norm(b1 - a1)
    d0, d1 = (b0 - a0) / l0, (b1 - a1) / l1
    n0, n1 = np.array([-d0[1], d0[0]]), np.array([-d1[1], d1[0]])
    relative = np.stack([xs - a0[0], ys - a0[1]], axis=1)
    along, across = relative @ d0 / l0, relative @ n0
    target = a1 + np.outer(along * l1, d1) + np.outer(across, n1)
    return np.floor(target[:, 0] + 0.5).astype(np.int64), np.floor(target[:, 1] + 0.5).astype(np.int64)


def _inside(xs: np.ndarray, ys: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    return (xs >= 0) & (xs < shape[1]) & (ys >= 0) & (ys < shape[0])


def _bridged(mask: np.ndarray, cover: np.ndarray) -> np.ndarray:
    # Cells drawn in front may split a part visually; let them reconnect it.
    return mask | (cover & _dilate(mask))


class _RigCheck:
    """Compare every part in every frame with the part's reference frame.

    A part's dot may be missing only where a part drawn in front of it (higher
    z) covers that cell. Dots that appear where the reference itself was
    covered are new information about the part, not errors.
    """

    def __init__(self, rig: Rig, frames: list[np.ndarray]):
        self.rig = rig
        self.frames = frames
        self.keys = [_keys(frame) for frame in frames]
        self.visible = [frame[:, :, 3] > 0 for frame in frames]
        self.masks = [_part_masks(rows, rig.parts) for rows in rig.maps]
        shape = frames[0].shape[:2]
        self.marks = [np.zeros(shape, dtype=bool) for _ in frames]
        self.expected: list[dict[str, np.ndarray]] = [{} for _ in frames]
        self.issues: list[dict[str, Any]] = []
        self._covers: dict[tuple[int, str], np.ndarray] = {}

    def cover(self, index: int, part_id: str, above: int | None = None) -> np.ndarray:
        """Cells of parts drawn in front of a part (or of a given depth) in a frame."""
        depth = self.rig.depths[index]
        level = depth[part_id] if above is None else above
        key = (index, part_id if above is None else f"z>{above}")
        if key not in self._covers:
            mask = np.zeros(self.frames[0].shape[:2], dtype=bool)
            for part in self.rig.parts:
                if depth[part.id] > level:
                    mask |= self.masks[index][part.id]
            self._covers[key] = mask
        return self._covers[key]

    def run(self, animations: tuple[dict[str, Any], ...]) -> dict[str, Any]:
        self._annotations()
        joints = self._joints(animations)
        parts = {part.id: self._part(part) for part in self.rig.parts}
        return {"reference_frame": self.rig.reference_frame, "coverage": self.rig.coverage,
                "max_joint_step": self.rig.max_joint_step, "joints": joints, "parts": parts}

    def _annotations(self) -> None:
        for index, masks in enumerate(self.masks):
            assigned = np.zeros_like(self.visible[index])
            for mask in masks.values():
                assigned |= mask
            stray = assigned & ~self.visible[index]
            if stray.any():
                self.marks[index] |= stray
                self.issues.append(_issue(
                    "PART_MAP_ON_TRANSPARENT", "fail",
                    f"{int(np.count_nonzero(stray))} part-map cells lie on transparent art; the map does not match the dots.",
                    frame=index, sample=_samples(stray)))
            loose = self.visible[index] & ~assigned
            if loose.any():
                complete = self.rig.coverage == "complete"
                if complete:
                    self.marks[index] |= loose
                self.issues.append(_issue(
                    "UNASSIGNED_VISIBLE_CELLS", "fail" if complete else "info",
                    f"{int(np.count_nonzero(loose))} visible cells belong to no part.",
                    frame=index, sample=_samples(loose)))

    def _joints(self, animations: tuple[dict[str, Any], ...]) -> dict[str, Any]:
        rig = self.rig
        reference = rig.poses[rig.reference_frame]
        result: dict[str, Any] = {}
        for joint in rig.joints:
            positions = [[_num(v) for v in pose[joint]] for pose in rig.poses]
            entry = {"fixed": joint in rig.fixed_joints, "positions": positions}
            if joint in rig.fixed_joints:
                for index, pose in enumerate(rig.poses):
                    if _distance(pose[joint], reference[joint]) > _EPSILON:
                        self.issues.append(_issue(
                            "FIXED_JOINT_MOVED", "fail",
                            f"Fixed joint {joint} moved from {positions[rig.reference_frame]} to {positions[index]}.",
                            frame=index, joint=joint))
            steps = []
            for animation in animations:
                sequence = animation["frames"]
                pairs = list(zip(sequence, sequence[1:]))
                if animation["loop"] and len(sequence) > 1:
                    pairs.append((sequence[-1], sequence[0]))
                for a, b in pairs:
                    step = _distance(rig.poses[a][joint], rig.poses[b][joint])
                    steps.append(step)
                    if rig.max_joint_step is not None and step > rig.max_joint_step + _EPSILON:
                        self.issues.append(_issue(
                            "JOINT_STEP_EXCEEDED", "fail",
                            f"Joint {joint} jumps {step:.2f} cells from frame {a} to {b}; "
                            f"the declared maximum is {_num(rig.max_joint_step)}.",
                            frame=b, joint=joint, animation=animation["id"]))
            entry["max_step"] = round(max(steps), 4) if steps else None
            result[joint] = entry
        return result

    def _part(self, part: Part) -> dict[str, Any]:
        rig = self.rig
        ref = part.reference_frame
        reference = self.masks[ref][part.id]
        frames = [self._part_frame(part, index, reference) for index in range(len(self.frames))]
        summary: dict[str, Any] = {"token": part.token, "motion": part.motion, "z": part.z,
                                   "reference_frame": ref, "reference_cells": int(np.count_nonzero(reference)),
                                   "frames": frames}
        for key in ("bone", "pivot", "parent", "axis"):
            value = getattr(part, key)
            if value is not None:
                summary[key] = [_num(v) for v in value] if key == "axis" else list(value) if key == "bone" else value
        if part.motion == "bone":
            summary.update({"reference_length": round(_distance(rig.poses[ref][part.bone[0]], rig.poses[ref][part.bone[1]]), 4),
                            "length_tolerance": part.length_tolerance, "min_shape_match": part.min_shape_match,
                            "max_drift": part.max_drift})
        if part.motion in ("bone", "free"):
            summary["area_tolerance"] = part.area_tolerance
        status = [entry["status"] for entry in frames]
        summary["status"] = "fail" if "fail" in status else "review" if "review" in status else "pass"
        return summary

    def _part_frame(self, part: Part, index: int, reference: np.ndarray) -> dict[str, Any]:
        rig = self.rig
        ref = part.reference_frame
        mask = self.masks[index][part.id]
        cells = int(np.count_nonzero(mask))
        hidden = part.id in rig.hidden[index]
        entry: dict[str, Any] = {"frame": index, "cells": cells, "hidden": hidden,
                                 "z": rig.depths[index][part.id]}
        found: list[dict[str, Any]] = []

        def flag(code: str, severity: str, detail: str, cells_mask: np.ndarray | None = None) -> None:
            found.append(_issue(code, severity, detail, frame=index, part=part.id))
            if cells_mask is not None and severity == "fail":
                self.marks[index] |= cells_mask

        revealed = None
        if cells == 0 and not hidden:
            flag("PART_MISSING", "fail",
                 f"Part {part.id} has no cells; list it under the frame's hidden parts if something covers it.")
        elif part.motion in ("fixed", "rigid"):
            self._exact_motion(part, index, mask, reference, entry, flag)
        elif part.motion == "bone":
            revealed = self._bone_motion(part, index, mask, reference, entry, flag)
        elif cells:
            ratio = cells / np.count_nonzero(reference)
            entry["area_ratio"] = round(float(ratio), 4)
            self._area(part, ratio, flag)
        if cells and part.motion in ("bone", "free"):
            reference_colors = np.unique(self.keys[ref][reference])
            added = mask & ~np.isin(self.keys[index], reference_colors)
            if revealed is not None:
                # Colors on dots the reference could not show are not changes.
                added &= ~revealed
            if added.any():
                colors = sorted({_hex(tuple(v)) for v in self.frames[index][added].tolist()})
                flag("PART_COLOR_ADDED", "review",
                     f"{int(np.count_nonzero(added))} cells use colors absent from the reference part: {colors}.")
            before = _components(_bridged(reference, self.cover(ref, part.id)))
            if _components(_bridged(mask, self.cover(index, part.id))) > before:
                flag("PART_FRAGMENTED", "review",
                     f"Part {part.id} splits into more separate pieces than in reference frame {ref}.")
        if cells:
            self._attachment(part, index, mask, flag)
        entry["status"] = _worst(found)
        self.issues.extend(found)
        return entry

    def _area(self, part: Part, ratio: float, flag) -> None:
        low, high = 1 - part.area_tolerance, 1 + part.area_tolerance
        if not low - _EPSILON <= ratio <= high + _EPSILON:
            flag("PART_AREA_CHANGED", "fail",
                 f"Part {part.id} has {ratio:.2f}x its expected cell count; allowed {max(low, 0):.2f}..{high:.2f}.")

    def _exact_errors(self, part: Part, index: int, reference: np.ndarray, offset: tuple[int, int]) -> tuple[np.ndarray, np.ndarray, int]:
        """Compare a moved exact copy of the reference with the frame's dots."""
        ref = part.reference_frame
        mask, keys = self.masks[index][part.id], self.keys[index]
        expected, expected_keys, outside = _shift(reference, self.keys[ref], *offset)
        # Missing dots need something drawn in front of them in this frame.
        vanished = expected & ~mask & ~self.cover(index, part.id)
        extra = mask & ~expected
        ys, xs = np.nonzero(extra)
        rx, ry = xs - offset[0], ys - offset[1]
        inside = _inside(rx, ry, mask.shape)
        known = np.ones(len(xs), dtype=bool)
        # Extra dots are acceptable where the reference copy itself was covered.
        known[inside] = ~self.cover(ref, part.id)[ry[inside], rx[inside]]
        stray = np.zeros_like(mask)
        stray[ys[known], xs[known]] = True
        recolored = expected & mask & (expected_keys != keys)
        return vanished | stray | recolored, expected, outside

    def _exact_motion(self, part: Part, index: int, mask: np.ndarray, reference: np.ndarray, entry, flag) -> None:
        """Fixed parts stay put; rigid parts move as an exact copy with their pivot."""
        rig = self.rig
        ref = part.reference_frame
        offset = (0, 0)
        if part.motion == "rigid":
            moved = np.subtract(rig.poses[index][part.pivot], rig.poses[ref][part.pivot])
            if np.any(np.abs(moved - np.round(moved)) > _EPSILON):
                flag("PART_JOINT_MISMATCH", "fail",
                     f"Pivot {part.pivot} moved by a fractional offset {[_num(v) for v in moved]}; "
                     "a rigid copy of whole cells cannot follow it.", mask)
                return
            offset = (int(round(moved[0])), int(round(moved[1])))
            entry["offset"] = list(offset)
            if part.axis is not None and abs(offset[0] * part.axis[1] - offset[1] * part.axis[0]) > _EPSILON:
                flag("RIGID_AXIS_VIOLATION", "fail",
                     f"Part {part.id} moved by {list(offset)}, not along its declared axis {[_num(v) for v in part.axis]}.",
                     mask)
        errors, expected, outside = self._exact_errors(part, index, reference, offset)
        mismatched = int(np.count_nonzero(errors)) + outside
        entry["mismatched_cells"] = mismatched
        if not mismatched:
            return
        self.expected[index][part.id] = expected
        if not mask.any():
            flag("OCCLUSION_WITHOUT_OCCLUDER", "fail",
                 f"{mismatched} cells of hidden part {part.id} are not covered by any part drawn in front of it.",
                 errors)
            return
        if part.motion == "rigid":
            ys, xs = np.nonzero(mask)
            rys, rxs = np.nonzero(reference)
            dots = (int(xs.min() - rxs.min()), int(ys.min() - rys.min()))
            if dots != offset:
                alternative, _, beyond = self._exact_errors(part, index, reference, dots)
                if not alternative.any() and not beyond:
                    flag("PART_JOINT_MISMATCH", "fail",
                         f"Dots of {part.id} moved by {list(dots)} but pivot {part.pivot} moved by {list(offset)}.",
                         mask)
                    return
        code = "FIXED_PART_CHANGED" if part.motion == "fixed" else "RIGID_PART_CHANGED"
        flag(code, "fail",
             f"{mismatched} cells of {part.id} differ from reference frame {ref} moved by {list(offset)}.", errors)

    def _bone_motion(self, part: Part, index: int, mask: np.ndarray, reference: np.ndarray,
                     entry, flag) -> np.ndarray | None:
        """Carry the reference dots along the bone and measure how well they land.

        Returns the frame's dots that map back onto or beside cells covered in
        the reference: they may show colors the reference could not show.
        """
        rig = self.rig
        ref = part.reference_frame
        start, end = part.bone
        a0, b0 = rig.poses[ref][start], rig.poses[ref][end]
        a1, b1 = rig.poses[index][start], rig.poses[index][end]
        length, reference_length = _distance(a1, b1), _distance(a0, b0)
        entry["bone_length"] = round(length, 4)
        if abs(length - reference_length) > part.length_tolerance + _EPSILON:
            flag("BONE_LENGTH_CHANGED", "fail",
                 f"Bone {start}-{end} of {part.id} is {length:.2f} cells long; reference frame {ref} has "
                 f"{reference_length:.2f} (tolerance {_num(part.length_tolerance)}).")
        if length < _EPSILON:
            flag("BONE_DEGENERATE", "fail", f"Bone {start}-{end} of {part.id} has zero length.")
            return None
        shape = mask.shape
        ys, xs = np.nonzero(reference)
        px, py = _bone_map(xs, ys, a0, b0, a1, b1)
        inside = _inside(px, py, shape)
        predicted = np.zeros_like(mask)
        predicted[py[inside], px[inside]] = True
        outside = len(set(zip(px[~inside].tolist(), py[~inside].tolist())))
        cover = self.cover(index, part.id)
        # Positions carry the same one-cell tolerance as dot matching.
        near_actual, near_cover = _dilate(mask), _dilate(cover)
        matched_predicted = int(np.count_nonzero(predicted & near_actual))
        missed = predicted & ~near_actual & ~near_cover
        missed_predicted = int(np.count_nonzero(missed)) + outside
        ay, ax = np.nonzero(mask)
        bx, by = _bone_map(ax, ay, a1, b1, a0, b0)
        back = _inside(bx, by, shape)
        hidden_before = self.cover(ref, part.id)
        revealed, beside = np.zeros_like(mask), np.zeros_like(mask)
        for target, cover_before in ((revealed, hidden_before), (beside, _dilate(hidden_before))):
            flags = np.zeros(len(ax), dtype=bool)
            flags[back] = cover_before[by[back], bx[back]] & ~reference[by[back], bx[back]]
            target[ay[flags], ax[flags]] = True
        near_predicted = _dilate(predicted)
        stray = mask & ~near_predicted & ~revealed
        cells = len(ax)
        if not cells:
            total = matched_predicted + missed_predicted
            entry["shape_match"] = None
            if total and missed_predicted / total > 1 - part.min_shape_match + _EPSILON:
                self.expected[index][part.id] = predicted
                flag("OCCLUSION_WITHOUT_OCCLUDER", "fail",
                     f"{missed_predicted} of {total} cells expected along the bone of hidden part {part.id} "
                     "are not covered by any part drawn in front of it.", missed)
            return beside
        matched_actual = int(np.count_nonzero(mask & near_predicted))
        considered = matched_predicted + missed_predicted + matched_actual + int(np.count_nonzero(stray))
        score = (matched_predicted + matched_actual) / considered if considered else 1.0
        entry["shape_match"] = round(score, 4)
        if score < part.min_shape_match - _EPSILON:
            self.expected[index][part.id] = predicted
            flag("PART_OFF_SKELETON", "fail",
                 f"Only {score:.0%} of {part.id}'s dots line up with its bone moved from reference frame {ref}; "
                 f"required {part.min_shape_match:.0%}.", stray | missed)
        # Thin diagonal parts can slide about 1.4 cells and still meet the one-cell
        # match, so also compare where the comparable dots sit along and across the bone.
        seen_predicted, seen_actual = predicted & ~cover, mask & ~revealed
        if min(np.count_nonzero(seen_predicted), np.count_nonzero(seen_actual)) >= DRIFT_MIN_CELLS:
            direction = np.subtract(b1, a1) / length
            delta = np.argwhere(seen_actual)[:, ::-1].mean(axis=0) - np.argwhere(seen_predicted)[:, ::-1].mean(axis=0)
            along = float(delta @ direction)
            across = float(delta @ np.array([-direction[1], direction[0]]))
            entry["drift"] = {"along": round(along, 4), "across": round(across, 4)}
            if max(abs(along), abs(across)) > part.max_drift + _EPSILON:
                self.expected[index][part.id] = predicted
                flag("PART_DRIFT", "fail",
                     f"Dots of {part.id} sit {abs(across):.2f} cells across and {abs(along):.2f} along its bone "
                     f"from where the reference places them; allowed {_num(part.max_drift)}.", mask)
        # Compare whole-part sizes: add dots covered now, and dots that were covered in the reference.
        expected_area = np.count_nonzero(reference) * length / reference_length + np.count_nonzero(beside)
        ratio = (cells + np.count_nonzero(predicted & cover & ~mask)) / expected_area
        entry["area_ratio"] = round(float(ratio), 4)
        self._area(part, ratio, flag)
        return beside

    def _attachment(self, part: Part, index: int, mask: np.ndarray, flag) -> None:
        rig = self.rig
        depth = rig.depths[index]
        if part.parent is not None:
            parent = self.masks[index][part.parent]
            if parent.any():
                # The joint between child and parent may sit behind a part drawn in front of both.
                bridge = self.cover(index, part.id, above=max(depth[part.id], depth[part.parent]))
                reach, previous = parent.copy(), None
                while previous is None or np.count_nonzero(reach) != previous:
                    previous = int(np.count_nonzero(reach))
                    reach |= _dilate(reach) & bridge
                if not (mask & _dilate(reach)).any():
                    flag("PART_DETACHED", "fail", f"Part {part.id} does not touch its parent {part.parent}.", mask)
        cover = self.cover(index, part.id)
        ys, xs = np.nonzero(mask | cover)
        own = mask[ys, xs]
        for joint in part.joints:
            x, y = rig.poses[index][joint]
            gaps = np.maximum(np.abs(xs - x), np.abs(ys - y))
            # A joint may hide behind a part drawn in front, but must not float in empty space.
            if not np.any(gaps <= 1 + _EPSILON):
                gap = float(gaps[own].min())
                flag("JOINT_OFF_PART", "fail",
                     f"Joint {joint} lies {gap:.1f} cells from the nearest dot of {part.id}; "
                     "the skeleton is not drawn on this part.")


def _panel_scale(layout: Layout, columns: int, target: int, limit: int) -> int:
    fw, fh = layout.frame_size
    scale = max(1, min(16, target // max(fw, fh)))
    while scale > 1 and columns * (fw * scale + 8) + 8 > limit:
        scale -= 1
    return scale


STATUS_COLORS = {"pass": (120, 220, 140), "review": (250, 200, 80), "fail": (255, 90, 90)}


def _part_colors(rig: Rig) -> dict[str, tuple[int, int, int]]:
    return {part.id: PART_COLORS[i % len(PART_COLORS)] for i, part in enumerate(rig.parts)}


def _rig_panels(index: int, frame: np.ndarray, rig: Rig, check: _RigCheck, k: int,
                art_background: Image.Image | None = None) -> tuple[Image.Image, Image.Image]:
    """Return one frame twice at scale k: art under the skeleton, and the part map.

    White outlines mark where the reference places a failing part's dots; red
    outlines mark failing cells. Both panels are diagnostics, never artwork.
    """
    fh, fw = frame.shape[:2]
    colors = _part_colors(rig)
    art = Image.fromarray(frame, "RGBA").resize((fw * k, fh * k), Image.Resampling.NEAREST)
    art_panel = qa.over_background(art) if art_background is None else Image.alpha_composite(art_background, art)
    flat = np.zeros((fh, fw, 4), dtype=np.uint8)
    flat[:, :] = (48, 52, 62, 255)
    flat[check.visible[index]] = (110, 110, 110, 255)
    for part in rig.parts:
        flat[check.masks[index][part.id]] = colors[part.id] + (255,)
    part_panel = Image.fromarray(flat, "RGBA").resize((fw * k, fh * k), Image.Resampling.NEAREST)
    line, radius = max(1, k // 4), max(2, k // 3)
    pose = rig.poses[index]

    def point(joint: str) -> tuple[float, float]:
        return (pose[joint][0] + 0.5) * k, (pose[joint][1] + 0.5) * k

    parts = {part.id: part for part in rig.parts}
    # Thin links join each bone chain to its parent's nearest joint (clavicle, pelvis).
    links = []
    for part in rig.parts:
        parent = parts.get(part.parent) if part.bone else None
        if parent is not None and parent.joints:
            anchor = part.bone[0]
            nearest = min(parent.joints, key=lambda joint: _distance(pose[joint], pose[anchor]))
            if _distance(pose[nearest], pose[anchor]) > 0.5:
                links.append((point(nearest), point(anchor)))

    for panel in (art_panel, part_panel):
        draw = ImageDraw.Draw(panel, "RGBA")
        for expected in check.expected[index].values():
            for y, x in np.argwhere(expected):
                draw.rectangle((x * k + 1, y * k + 1, (x + 1) * k - 2, (y + 1) * k - 2), outline=(255, 255, 255, 230))
        for y, x in np.argwhere(check.marks[index]):
            draw.rectangle((x * k, y * k, (x + 1) * k - 1, (y + 1) * k - 1), outline=(255, 40, 40, 255),
                           width=max(1, k // 6))
        for ends in links:
            draw.line(ends, fill=(20, 20, 24, 255), width=line + 1)
            draw.line(ends, fill=(205, 205, 215, 255), width=max(1, line - 1))
        for part in rig.parts:
            if part.bone:
                ends = [point(joint) for joint in part.bone]
                draw.line(ends, fill=(20, 20, 24, 255), width=line + 2)
                draw.line(ends, fill=colors[part.id] + (255,), width=line)
        for joint in rig.joints:
            x, y = point(joint)
            shape = draw.rectangle if joint in rig.fixed_joints else draw.ellipse
            shape((x - radius, y - radius, x + radius, y + radius), fill=(255, 255, 255, 255),
                  outline=(20, 20, 24, 255))
    return art_panel, part_panel


def _save_rig_overlay(path: Path, frames: list[np.ndarray], layout: Layout, rig: Rig, check: _RigCheck,
                      frame_status: list[str]) -> None:
    """Show each frame twice: art under its declared skeleton, then the part map."""
    fw, fh = layout.frame_size
    count = len(frames)
    columns = max(1, min(count, layout.columns, 8))
    k = _panel_scale(layout, columns, 192, 2048)
    pad, title, gap = 8, 14, 4
    panel_w, panel_h = fw * k, fh * k
    block_h = title + 2 * panel_h + gap + pad
    grid_rows = math.ceil(count / columns)
    width = max(columns * (panel_w + pad) + pad, 520)
    per_row = max(1, (width - pad) // 170)
    header_h = 18
    legend_h = math.ceil(len(rig.parts) / per_row) * 16 + pad
    height = header_h + grid_rows * block_h + pad + legend_h
    canvas = Image.new("RGB", (width, height), (34, 38, 46))
    draw_canvas = ImageDraw.Draw(canvas)
    draw_canvas.text((pad, 4), "Top: art + declared skeleton   Bottom: part map   "
                     "White: expected dots   Red: failing cells", fill=(200, 205, 215))
    for index, frame in enumerate(frames):
        art_panel, part_panel = _rig_panels(index, frame, rig, check, k)
        column, row = index % columns, index // columns
        left = pad + column * (panel_w + pad)
        top = header_h + row * block_h
        draw_canvas.text((left, top), f"#{index} {frame_status[index].upper()}", fill=STATUS_COLORS[frame_status[index]])
        canvas.paste(art_panel.convert("RGB"), (left, top + title))
        canvas.paste(part_panel.convert("RGB"), (left, top + title + panel_h + gap))
    _draw_legend(draw_canvas, rig, pad, height - legend_h, per_row)
    canvas.save(path)


def _draw_legend(draw: ImageDraw.ImageDraw, rig: Rig, left: int, top: int, per_row: int) -> None:
    colors = _part_colors(rig)
    for i, part in enumerate(rig.parts):
        x = left + (i % per_row) * 170
        y = top + (i // per_row) * 16
        draw.rectangle((x, y + 2, x + 10, y + 12), fill=colors[part.id])
        draw.text((x + 15, y + 1), f"{part.id} ({part.motion}, z{part.z})", fill=(230, 230, 230))


def _save_layout_overlay(path: Path, image: Image.Image, layout: Layout, scale: int,
                         gutter: np.ndarray, frame_issues: dict[int, str]) -> None:
    base = qa.over_background(image)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    for y, x in np.argwhere(gutter):
        draw.rectangle((x * scale, y * scale, (x + 1) * scale - 1, (y + 1) * scale - 1), fill=(255, 35, 45, 190))
    fw, fh = layout.frame_size
    for index in range(layout.capacity):
        x, y = layout.origin(index)
        box = (x * scale, y * scale, (x + fw) * scale - 1, (y + fh) * scale - 1)
        if index >= layout.frame_count:
            draw.rectangle(box, outline=(150, 150, 150, 220))
            continue
        color = {"fail": (255, 60, 60, 255), "review": (250, 190, 40, 255)}.get(frame_issues.get(index), (0, 200, 120, 255))
        draw.rectangle(box, outline=color, width=max(1, scale // 2))
        if fw * scale >= 24:
            draw.text((box[0] + 3, box[1] + 2), str(index), fill=color)
    Image.alpha_composite(base, overlay).convert("RGB").save(path)


def preview_scale(layout: Layout, requested: int | None = None) -> int:
    """Whole-number enlargement for animation previews, about 512 px tall by default."""
    if requested is not None:
        return _int(requested, "preview scale", 1, 16)
    return max(1, min(8, 512 // max(layout.frame_size)))


def _write_gif(path: Path, images: list[Image.Image], animation: dict[str, Any]) -> None:
    options: dict[str, Any] = {"save_all": True, "append_images": images[1:],
                               "duration": list(animation["durations_ms"]), "disposal": 2}
    if animation["loop"]:
        options["loop"] = 0
    stream = io.BytesIO()
    images[0].save(stream, format="GIF", **options)
    _write_new(path, stream.getvalue())


def _save_animation(path: Path, frames: list[np.ndarray], animation: dict[str, Any], layout: Layout, k: int) -> None:
    """Write a playback preview on a flat background; the sheet remains the audited artwork."""
    fw, fh = layout.frame_size
    images = []
    for index in animation["frames"]:
        art = Image.fromarray(frames[index], "RGBA").resize((fw * k, fh * k), Image.Resampling.NEAREST)
        images.append(Image.alpha_composite(Image.new("RGBA", art.size, (48, 52, 62, 255)), art).convert("RGB"))
    _write_gif(path, images, animation)


def _save_rig_animation(path: Path, frames: list[np.ndarray], animation: dict[str, Any], layout: Layout,
                        rig: Rig, check: _RigCheck, frame_status: list[str], k: int) -> None:
    """Play the art under its skeleton beside the part colors, frame by frame."""
    fw, fh = layout.frame_size
    pad, title = 8, 16
    per_row = max(1, (2 * fw * k + pad) // 170)
    legend_h = math.ceil(len(rig.parts) / per_row) * 16 + 4
    width, height = 2 * fw * k + 3 * pad, title + fh * k + pad + legend_h
    background = Image.new("RGBA", (fw * k, fh * k), (48, 52, 62, 255))
    images = []
    for index in animation["frames"]:
        art_panel, part_panel = _rig_panels(index, frames[index], rig, check, k, background)
        canvas = Image.new("RGB", (width, height), (34, 38, 46))
        draw = ImageDraw.Draw(canvas)
        draw.text((pad, 3), f"{animation['id']}  frame {index}  {frame_status[index].upper()}",
                  fill=STATUS_COLORS[frame_status[index]])
        canvas.paste(art_panel.convert("RGB"), (pad, title))
        canvas.paste(part_panel.convert("RGB"), (2 * pad + fw * k, title))
        _draw_legend(draw, rig, pad, title + fh * k + pad // 2, per_row)
        images.append(canvas)
    _write_gif(path, images, animation)


def check_sheet(spec_path: str | Path, sheet_path: str | Path, profile_path: str | Path,
                out_dir: str | Path, *, scale: int | None = None) -> dict[str, Any]:
    """Audit a sheet PNG against its profile, layout, animations and rig.

    Writes sprite_report.json, the strict sheet audit under sheet/, a layout
    overlay, a rig overlay and animation previews, each enlarged by `scale`
    (default about 512 px tall). Inputs are never modified.
    """
    plan, spec_source, spec_data = load_spec(spec_path)
    k = preview_scale(plan.layout, scale)
    profile_file = Path(profile_path).expanduser().resolve(strict=True)
    profile_digest = qa.sha256_file(profile_file)
    profile = project.load_profile(profile_file)
    sheet = Path(sheet_path).expanduser().resolve(strict=True)
    logical, _ = project.contract_options(profile)
    layout = plan.layout
    if logical != layout.sheet_size:
        raise ValueError(f"Profile logical_size {logical[0]}x{logical[1]} differs from the sprite layout's "
                         f"sheet size {layout.sheet_size[0]}x{layout.sheet_size[1]}")
    if plan.scale is not None and plan.scale != profile["scale"]:
        raise ValueError("Sprite spec scale differs from the profile scale")
    if profile.get("alpha", "binary") == "opaque" and (layout.margin or layout.spacing or layout.frame_count < layout.capacity):
        raise ValueError("An opaque profile cannot hold transparent gutters or unused slots")
    expected_frames = None
    inputs = [spec_source, profile_file, sheet]
    if plan.frame_rows is not None:
        expected_frames, _, palette_source = frames_from_rows(plan, spec_source.parent, profile["scale"])
        if palette_source is not None:
            inputs.append(Path(palette_source["path"]))
    root = _prepare_output(out_dir, inputs)
    try:
        report, sheet_outputs, image, native = _audit_sheet(sheet, profile, profile_file, root / "sheet", root)
        issues: list[dict[str, Any]] = []
        summary: dict[str, Any] = {
            "tool": "Pixelwright", "version": VERSION, "schema_version": 1, "status": "fail",
            "scope": "technical_checks_only_not_artistic_quality", "artistic_status": "not_reviewed",
            "preview_scale": k,
            "inputs": {"spec": {"path": spec_source.name, "sha256": _sha256(spec_data)},
                       "sheet": {"path": sheet.name, "sha256": report["provenance"]["source_sha256"]},
                       "profile": {"path": profile_file.name, "sha256": profile_digest}},
            "name": plan.name, "contract": profile, "layout": _layout_record(layout),
            "sheet_audit": {"status": report["status"], "report": sheet_outputs["report"], "outputs": sheet_outputs},
            "checks": {"frames": "not_checked", "animations": "not_checked",
                       "rig": "not_declared" if plan.rig is None else "not_checked"},
            "frames": [], "animations": [], "rig": None, "issues": issues, "outputs": {"sprite_report": "sprite_report.json"}}
        if native is None:
            summary["reason"] = "The sheet grid must decode to one exact color per cell before frames are checked."
        else:
            frames, records, frame_issues, gutter = _check_frames(native, layout)
            issues.extend(frame_issues)
            summary["checks"]["frames"] = "checked"
            if expected_frames is not None:
                differing = [index for index, expected in enumerate(expected_frames)
                             if not np.array_equal(expected, frames[index])]
                if differing:
                    issues.append(_issue("SHEET_DIFFERS_FROM_SPEC_ROWS", "review",
                                         f"Frames {differing} differ from the spec's color rows; part maps may be stale."))
            animation_results, animation_issues = _check_animations(plan.animations, frames, records, layout.frame_count)
            issues.extend(animation_issues)
            summary["animations"] = animation_results
            summary["checks"]["animations"] = "checked" if plan.animations else "not_declared"
            rig_check = None
            if plan.rig is not None:
                rig_check = _RigCheck(plan.rig, frames)
                summary["rig"] = rig_check.run(plan.animations)
                issues.extend(rig_check.issues)
                summary["checks"]["rig"] = "checked"
            frame_status = [_worst([i for i in issues if i.get("frame") == index]) for index in range(layout.frame_count)]
            for record, status in zip(records, frame_status):
                record["status"] = status
            summary["frames"] = records
            _save_layout_overlay(root / "layout_overlay.png", image, layout, profile["scale"], gutter,
                                 {index: status for index, status in enumerate(frame_status) if status != "pass"})
            summary["outputs"]["layout_overlay"] = "layout_overlay.png"
            if rig_check is not None:
                _save_rig_overlay(root / "rig_overlay.png", frames, layout, plan.rig, rig_check, frame_status)
                summary["outputs"]["rig_overlay"] = "rig_overlay.png"
            for animation in plan.animations:
                relative = f"animations/{animation['id']}.gif"
                _save_animation(root / relative, frames, animation, layout, k)
                summary["outputs"].setdefault("animation_previews", {})[animation["id"]] = relative
                if rig_check is not None:
                    relative = f"animations/{animation['id']}-rig.gif"
                    _save_rig_animation(root / relative, frames, animation, layout, plan.rig, rig_check,
                                        frame_status, k)
                    summary["outputs"].setdefault("rig_previews", {})[animation["id"]] = relative
        if qa.sha256_file(spec_source) != _sha256(spec_data) or qa.sha256_file(profile_file) != profile_digest:
            issues.append(_issue("INPUT_CHANGED", "fail", "The sprite spec or profile changed during the check."))
        counts = {level: sum(1 for issue in issues if issue["severity"] == level) for level in ("fail", "review", "info")}
        summary["issue_counts"] = counts
        summary["status"] = "fail" if native is None else _worst(issues, report["status"])
        summary["visual_review_required"] = [
            "Watch each animation preview at native and enlarged size",
            "Check silhouette, timing, weight and contact with the ground",
            "Confirm the declared skeleton matches the intended anatomy or mechanism",
            "Review parts listed as hidden, draw order and any colors a part gains while moving",
        ]
        _write_new(root / "sprite_report.json", _json_bytes(summary))
        return summary
    finally:
        (root / _LOCK).unlink(missing_ok=True)


def _plan_output(plan: SpritePlan) -> dict[str, Any]:
    layout = plan.layout
    output: dict[str, Any] = {
        "tool": "Pixelwright", "version": VERSION, "schema_version": 1, "status": "plan",
        "qa_performed": False, "name": plan.name, "layout": _layout_record(layout), "scale": plan.scale,
        "render_size": [v * plan.scale for v in layout.sheet_size] if plan.scale else None,
        "build_ready": plan.scale is not None and plan.frame_rows is not None,
        "animations": [{"id": a["id"], "frames": list(a["frames"]), "loop": a["loop"],
                        "durations_ms": list(a["durations_ms"])} for a in plan.animations],
        "rig": None}
    if plan.rig is not None:
        output["rig"] = {
            "reference_frame": plan.rig.reference_frame, "coverage": plan.rig.coverage,
            "joints": list(plan.rig.joints), "fixed_joints": list(plan.rig.fixed_joints),
            "parts": [{"id": p.id, "token": p.token, "motion": p.motion,
                       "bone": list(p.bone) if p.bone else None, "pivot": p.pivot, "parent": p.parent,
                       "reference_frame": p.reference_frame} for p in plan.rig.parts]}
    return output


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    listing = sub.add_parser("list", help="Validate and summarize a sprite spec; no PNG QA")
    building = sub.add_parser("build", help="Assemble frame color rows into native and rendered sheets")
    checking = sub.add_parser("check", help="Audit a sheet PNG, its frames, animations and rig")
    for command in (listing, building, checking):
        command.add_argument("--spec", required=True, type=Path)
    building.add_argument("--out-dir", required=True, type=Path)
    checking.add_argument("--sheet", required=True, type=Path)
    checking.add_argument("--profile", required=True, type=Path)
    checking.add_argument("--out-dir", required=True, type=Path)
    checking.add_argument("--preview-scale", type=int,
                          help="Whole-number enlargement of GIF previews, 1..16; default about 512 px tall")
    args = parser.parse_args(argv)
    try:
        if args.action == "list":
            plan, _, _ = load_spec(args.spec)
            print(json.dumps(_plan_output(plan), ensure_ascii=False, indent=2))
            return 0
        if args.action == "build":
            manifest = build_sheet(args.spec, args.out_dir)
            print(json.dumps({"status": "built", "out_dir": str(args.out_dir.resolve()),
                              "grid": manifest["grid"], "frame_count": manifest["layout"]["frame_count"]}))
            return 0
        summary = check_sheet(args.spec, args.sheet, args.profile, args.out_dir, scale=args.preview_scale)
        print(json.dumps({"status": summary["status"], "issue_counts": summary["issue_counts"],
                          "checks": summary["checks"], "outputs": summary["outputs"]},
                         ensure_ascii=False, indent=2))
        return 0 if summary["status"] == "pass" else 2
    except (ValueError, OSError, MemoryError) as exc:
        print(f"Pixelwright sprite error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
