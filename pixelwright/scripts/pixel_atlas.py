#!/usr/bin/env python3
"""Inspect an unchanged sprite-gen atlas using its runtime frame_layout."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

import pixel_qa as qa
import pixel_sprite as sprite
import pixelwright as project


def upstream_metadata() -> dict:
    """Describe the format dependency, without inferring the input's producer."""
    path = Path(__file__).resolve().parents[1] / "upstream-integrations.json"
    metadata, _ = sprite._read_json(path)
    if not isinstance(metadata, dict) or metadata.get("schema_version") != 1:
        raise ValueError("Unsupported upstream integration metadata")
    try:
        upstream = dict(metadata["integrations"]["sprite-gen"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Missing sprite-gen upstream integration metadata") from exc
    return upstream | {"producer_version": None, "producer_version_verified": False}


def _object(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _fraction(value: Any, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be a finite fraction in 0..1")
    return float(value)


def _layout(manifest: dict, image_size: tuple[int, int]) -> tuple[list[dict], np.ndarray]:
    layout = _object(manifest.get("frame_layout"), "manifest.frame_layout")
    width = sprite._int(layout.get("sheetWidth"), "sheetWidth", 1, qa.MAX_PIXELS)
    height = sprite._int(layout.get("sheetHeight"), "sheetHeight", 1, qa.MAX_PIXELS)
    if (width, height) != image_size:
        raise ValueError("Manifest sheet dimensions differ from the actual PNG")
    fw = sprite._int(layout.get("cellWidth"), "cellWidth", 1, width)
    fh = sprite._int(layout.get("cellHeight"), "cellHeight", 1, height)
    rows = _object(layout.get("rows"), "frame_layout.rows")
    if not 1 <= len(rows) <= sprite.MAX_ANIMATIONS:
        raise ValueError(f"frame_layout.rows must contain 1..{sprite.MAX_ANIMATIONS} states")
    animation = _object(manifest.get("animation", {}), "manifest.animation")
    animation_rows = animation.get("rows")
    if animation_rows is not None:
        animation_rows = _object(animation_rows, "animation.rows")
        if animation_rows.keys() != rows.keys():
            raise ValueError("animation.rows and frame_layout.rows must name the same states")
    # Known dimension duplicates must agree; unrelated export metadata is allowed.
    cell = _object(manifest.get("cell", {}), "manifest.cell")
    for entry, key, expected in ((cell, "width", fw), (cell, "height", fh),
                                 (animation, "cellWidth", fw), (animation, "cellHeight", fh)):
        if key in entry and (type(entry[key]) is not int or entry[key] != expected):
            raise ValueError(f"Conflicting manifest cell dimension: {key}")
    claimed = np.zeros((height, width), dtype=bool)
    frames = []
    for state, rects in rows.items():
        if not isinstance(state, str) or not 1 <= len(state) <= 128:
            raise ValueError("State names must contain 1..128 characters")
        if not isinstance(rects, list) or not rects or len(frames) + len(rects) > sprite.MAX_FRAMES:
            raise ValueError(f"Each state needs frames; total frame limit is {sprite.MAX_FRAMES}")
        if animation_rows is not None:
            row = _object(animation_rows[state], f"animation.rows.{state}")
            if sprite._int(row.get("frames"), "animation frame count", 1, sprite.MAX_FRAMES) != len(rects):
                raise ValueError(f"Animation frame count differs from rectangles for {state}")
        for index, value in enumerate(rects):
            rect = _object(value, f"{state} frame {index}")
            x = sprite._int(rect.get("x"), "frame x", 0, width - 1)
            y = sprite._int(rect.get("y"), "frame y", 0, height - 1)
            w = sprite._int(rect.get("w"), "frame w", 1, width)
            h = sprite._int(rect.get("h"), "frame h", 1, height)
            if (w, h) != (fw, fh) or x + w > width or y + h > height:
                raise ValueError("Every frame must match the cell size and fit within the sheet")
            region = claimed[y:y + h, x:x + w]
            if region.any():
                raise ValueError("Manifest frame rectangles overlap")
            region[:] = True
            frames.append({"state": state, "frame": index, "rect": {"x": x, "y": y, "w": w, "h": h}})
    return frames, claimed


def _constraints(manifest: dict, request: dict | None, *, max_colors: int | None,
                 margin_x: int | None, margin_y: int | None,
                 size_tolerance: float, area_tolerance: float) -> dict:
    cell = _object(manifest.get("cell", {}), "manifest.cell")
    request_cell = _object(request.get("cell", {}), "request.cell") if request is not None else {}
    fit = _object(request.get("fit", {}), "request.fit") if request is not None else {}
    declarations = {}
    for key, explicit, fallback, high in (
        ("max_colors", max_colors, [("request.fit.palette_size", fit.get("palette_size"))], 256),
        ("margin_x", margin_x, [("manifest.cell.safe_margin_x", cell.get("safe_margin_x")),
                                 ("request.cell.safe_margin_x", request_cell.get("safe_margin_x")),
                                 ("request.cell.safe_margin", request_cell.get("safe_margin"))],
         manifest["frame_layout"]["cellWidth"] // 2),
        ("margin_y", margin_y, [("manifest.cell.safe_margin_y", cell.get("safe_margin_y")),
                                 ("request.cell.safe_margin_y", request_cell.get("safe_margin_y")),
                                 ("request.cell.safe_margin", request_cell.get("safe_margin"))],
         manifest["frame_layout"]["cellHeight"] // 2),
    ):
        candidates = ([] if explicit is None else [("argument", explicit)]) + fallback
        values = [(source, sprite._int(value, key, 1 if key == "max_colors" else 0, high))
                  for source, value in candidates if value is not None]
        declarations[key] = {"value": values[0][1] if values else None,
                             "source": values[0][0] if values else "undeclared",
                             "other_declarations": [{"source": source, "value": value}
                                                    for source, value in values[1:]]}
    return {"palette": declarations["max_colors"],
            "margin_x": declarations["margin_x"], "margin_y": declarations["margin_y"],
            "size": {"reference": "per_state_median_of_nonempty_frames", "minimum_frames": 3,
                     "dimension_tolerance": _fraction(size_tolerance, "size_tolerance"),
                     "visible_area_tolerance": _fraction(area_tolerance, "area_tolerance"),
                     "outlier_severity": "review", "scope": "visible_silhouette_not_body_part_scale"},
            "visibility": "alpha > 0; all coordinates and areas use source PNG pixels"}


def _rgb_colors(pixels: np.ndarray) -> np.ndarray:
    visible = pixels[:, :, 3] > 0
    return np.unique(pixels[:, :, :3][visible], axis=0)


def _status(issues: list[dict]) -> str:
    return sprite._worst(issues)


def _measure(frames: list[dict], pixels: np.ndarray, contract: dict, issues: list[dict]) -> None:
    for frame in frames:
        r = frame["rect"]
        crop = pixels[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]]
        mask = crop[:, :, 3] > 0
        box = sprite._bbox(mask)
        context = {"state": frame["state"], "frame": frame["frame"]}
        frame.update({"visible_pixels": int(np.count_nonzero(mask)), "bbox": box,
                      "visible_rgb_colors": len(_rgb_colors(crop))})
        if box is None:
            frame.update({"bbox_size": None, "margins": None})
            issues.append(sprite._issue("EMPTY_FRAME", "fail", "A character frame is fully transparent.", **context))
            continue
        x0, y0, x1, y1 = box  # Inclusive visible pixel bounds; margins count empty pixels.
        frame["bbox_size"] = [x1 - x0 + 1, y1 - y0 + 1]
        frame["margins"] = {"left": x0, "top": y0, "right": r["w"] - 1 - x1, "bottom": r["h"] - 1 - y1}
        violated = [side for side in ("left", "right", "top", "bottom")
                    if (minimum := contract["margin_x" if side in ("left", "right") else "margin_y"]["value"]) is not None
                    and frame["margins"][side] < minimum]
        if violated:
            issues.append(sprite._issue("EDGE_MARGIN_VIOLATION", "fail",
                                        "Visible artwork enters the declared safe margin.",
                                        sides=violated, observed_margins=frame["margins"], **context))


def _sizes(frames: list[dict], contract: dict, issues: list[dict]) -> list[dict]:
    results = []
    for state in dict.fromkeys(f["state"] for f in frames):
        members = [f for f in frames if f["state"] == state]
        measured = [f for f in members if f["bbox"] is not None]
        baseline = {key: float(np.median(values)) for key, values in (
            ("width", [f["bbox_size"][0] for f in measured]),
            ("height", [f["bbox_size"][1] for f in measured]),
            ("visible_pixels", [f["visible_pixels"] for f in measured]),
        )} if measured else None
        enough = len(measured) >= contract["size"]["minimum_frames"]
        if not enough:
            issues.append(sprite._issue("SIZE_REFERENCE_INSUFFICIENT", "review",
                                        "At least three nonempty frames are needed for a median size screen.", state=state))
        for frame in members:
            frame["size_ratios"] = None
            frame["size_status"] = "review"
            if frame["bbox"] is None or baseline is None:
                continue
            ratios = {"width": frame["bbox_size"][0] / baseline["width"],
                      "height": frame["bbox_size"][1] / baseline["height"],
                      "visible_pixels": frame["visible_pixels"] / baseline["visible_pixels"]}
            frame["size_ratios"] = ratios
            outside = [key for key, ratio in ratios.items()
                       if abs(ratio - 1) > contract["size"]["visible_area_tolerance" if key == "visible_pixels"
                                                          else "dimension_tolerance"] + 1e-9]
            if enough:
                frame["size_status"] = "review" if outside else "pass"
                if outside:
                    issues.append(sprite._issue("FRAME_SIZE_OUTLIER", "review",
                        "Visible extent or area differs from the state's median. Pose, occlusion or clipping may explain it; inspect the artwork.",
                        state=state, frame=frame["frame"], metrics=outside, ratios=ratios))
        state_issues = [i for i in issues if i.get("state") == state and i["code"] in
                        ("FRAME_SIZE_OUTLIER", "SIZE_REFERENCE_INSUFFICIENT", "EMPTY_FRAME")]
        results.append({"state": state, "frames": len(members), "nonempty_frames": len(measured),
                        "median": baseline, "status": _status(state_issues)})
    return results


def _draw_frame(draw: ImageDraw.ImageDraw, frame: dict, origin: tuple[int, int], contract: dict) -> None:
    x, y = origin
    r = frame["rect"]
    color = {"pass": "#32A875", "review": "#FFB347", "fail": "#FF5263"}[frame["status"]]
    draw.rectangle((x, y, x + r["w"] - 1, y + r["h"] - 1), outline=color, width=1)
    mx, my = contract["margin_x"]["value"], contract["margin_y"]["value"]
    if mx is not None and my is not None and 2 * mx < r["w"] and 2 * my < r["h"]:
        draw.rectangle((x + mx, y + my, x + r["w"] - 1 - mx, y + r["h"] - 1 - my), outline="#00C6E8")
    if frame["bbox"] is not None:
        a, b, c, d = frame["bbox"]
        draw.rectangle((x + a, y + b, x + c, y + d), outline="#FFFFFF")


def _previews(image: Image.Image, frames: list[dict], contract: dict, out: Path) -> dict:
    overlay = Image.new("RGBA", image.size, "#242830")
    overlay.alpha_composite(image)
    draw = ImageDraw.Draw(overlay)
    for frame in frames:
        r = frame["rect"]
        _draw_frame(draw, frame, (r["x"], r["y"]), contract)
    overlay.save(out / "layout_overlay.png")
    outputs = {"layout_overlay": "layout_overlay.png"}
    # Use equal source-sized cells, never crop to each pose's bbox or size-fit it.
    w, h = frames[0]["rect"]["w"], frames[0]["rect"]["h"]
    columns = min(4, len(frames))
    gap, label = 8, 34
    size = (columns * (w + gap) + gap, math.ceil(len(frames) / columns) * (h + label + gap) + gap)
    if size[0] * size[1] > qa.MAX_PIXELS:
        outputs["frames_preview_omitted"] = "Contact preview exceeds the image pixel limit; use the full-sheet overlay."
        return outputs
    board = Image.new("RGBA", size, "#242830")
    draw = ImageDraw.Draw(board)
    for index, frame in enumerate(frames):
        x, y = gap + (index % columns) * (w + gap), gap + (index // columns) * (h + label + gap)
        r = frame["rect"]
        crop = image.crop((r["x"], r["y"], r["x"] + w, r["y"] + h))
        board.alpha_composite(crop, (x, y + label))
        title = f"{frame['state']} #{frame['frame']} {frame['status']}".encode("ascii", "backslashreplace").decode("ascii")
        detail = f"bbox {frame['bbox_size']} area {frame['visible_pixels']}"
        draw.text((x, y), title[:64], fill="white")
        draw.text((x, y + 14), detail, fill="#C6CDD5")
        _draw_frame(draw, frame, (x, y + label), contract)
    board.save(out / "frames.png")
    outputs["frames"] = "frames.png"
    return outputs


def check_sprite_gen(sheet_path: str | Path, manifest_path: str | Path, out_dir: str | Path, *,
                     request_path: str | Path | None = None, max_colors: int | None = None,
                     margin_x: int | None = None, margin_y: int | None = None,
                     size_tolerance: float = .10, area_tolerance: float = .25) -> dict:
    """Report palette/margin failures and silhouette-size review candidates.

    Read frame rectangles, never infer them from alpha or dereference paths in
    the manifest. Missing budgets remain REVIEW. No image is repaired or fitted.
    """
    sheet = Path(sheet_path).expanduser().resolve(strict=True)
    manifest_file = Path(manifest_path).expanduser().resolve(strict=True)
    out = Path(out_dir).expanduser().resolve()
    inputs = [sheet, manifest_file]
    if request_path is not None:
        inputs.append(Path(request_path).expanduser().resolve(strict=True))
    # Check the supplied path too: resolve() would hide a symlink output.
    project.require_empty_output(Path(out_dir).expanduser(), inputs)
    manifest_raw, manifest_bytes = sprite._read_json(manifest_file)
    manifest = _object(manifest_raw, "manifest")
    hashes = {manifest_file: hashlib.sha256(manifest_bytes).hexdigest()}
    request = None
    if request_path is not None:
        request_raw, request_bytes = sprite._read_json(inputs[2])
        request = _object(request_raw, "request")
        hashes[inputs[2]] = hashlib.sha256(request_bytes).hexdigest()
    hashes[sheet] = project.sha256(sheet)
    image = qa.open_rgba(sheet)
    frames, claimed = _layout(manifest, image.size)
    contract = _constraints(manifest, request, max_colors=max_colors, margin_x=margin_x, margin_y=margin_y,
                            size_tolerance=size_tolerance, area_tolerance=area_tolerance)
    pixels = np.asarray(image, dtype=np.uint8)
    issues = []
    for name in ("palette", "margin_x", "margin_y"):
        declaration = contract[name]
        if any(other["value"] != declaration["value"] for other in declaration["other_declarations"]):
            issues.append(sprite._issue("CONSTRAINT_OVERRIDE", "review",
                "Conflicting declarations were resolved by explicit argument, then manifest, then request precedence.",
                constraint=name, selected=declaration))
    colors = _rgb_colors(pixels)
    budget = contract["palette"]["value"]
    if budget is None:
        issues.append(sprite._issue("PALETTE_BUDGET_UNDECLARED", "review",
                                    "Supply --max-colors or a request containing fit.palette_size."))
    elif len(colors) > budget:
        issues.append(sprite._issue("PALETTE_OVER_BUDGET", "fail",
                                    f"The PNG has {len(colors)} visible RGB colors; the shared budget is {budget}."))
    for axis in ("x", "y"):
        if contract[f"margin_{axis}"]["value"] is None:
            issues.append(sprite._issue("SAFE_MARGIN_UNDECLARED", "review",
                                        f"No safe margin is declared for the {axis} axis.", axis=axis))
    outside = (pixels[:, :, 3] > 0) & ~claimed
    if outside.any():
        issues.append(sprite._issue("VISIBLE_PIXELS_OUTSIDE_FRAMES", "fail",
                                    "Visible pixels fall outside all manifest rectangles.", pixels=int(outside.sum()),
                                    samples=sprite._samples(outside)))
    _measure(frames, pixels, contract, issues)
    states = _sizes(frames, contract, issues)
    for frame in frames:
        frame["status"] = _status([i for i in issues if i.get("state") == frame["state"] and
                                    i.get("frame") == frame["frame"]])
    for path, digest in hashes.items():
        if project.sha256(path) != digest:
            raise ValueError(f"Input changed during inspection: {path.name}")
    categories = {
        "palette": {"PALETTE_OVER_BUDGET", "PALETTE_BUDGET_UNDECLARED"},
        "margins": {"EDGE_MARGIN_VIOLATION", "SAFE_MARGIN_UNDECLARED", "EMPTY_FRAME"},
        "size_consistency": {"FRAME_SIZE_OUTLIER", "SIZE_REFERENCE_INSUFFICIENT", "EMPTY_FRAME"},
        "layout": {"VISIBLE_PIXELS_OUTSIDE_FRAMES"},
    }
    report = {
        "tool": "Pixelwright", "version": project.VERSION, "schema_version": 1,
        "acceptance_mode": "sprite_gen_atlas", "status": _status(issues),
        "upstream": upstream_metadata(),
        "scope": "decoded PNG palette, declared frame rectangles, safety margins and visible silhouette size",
        "contract": contract,
        "provenance": {"sheet": {"path": str(sheet), "sha256": hashes[sheet]},
                       "manifest": {"path": str(manifest_file), "sha256": hashes[manifest_file]},
                       "request": {"path": str(inputs[2]), "sha256": hashes[inputs[2]]} if request_path else None,
                       "inputs_unchanged": True,
                       "decoded_rgba_sha256": hashlib.sha256(image.tobytes()).hexdigest()},
        "checks": {key: _status([i for i in issues if i["code"] in codes or
                                  (i["code"] == "CONSTRAINT_OVERRIDE" and
                                   i.get("constraint") in ({"palette"} if key == "palette" else
                                                            {"margin_x", "margin_y"} if key == "margins" else set()))])
                   for key, codes in categories.items()},
        "palette": {"visible_rgb_colors": len(colors), "max_colors": budget,
                    "colors": ["#" + bytes(map(int, color)).hex().upper() for color in colors[:256]],
                    "colors_truncated": len(colors) > 256},
        "sheet_size": list(image.size), "frames": frames, "states": states, "issues": issues,
        "issue_counts": {severity: sum(i["severity"] == severity for i in issues)
                         for severity in ("fail", "review", "info")},
        "pixel_grid_status": "not_checked", "artistic_status": "not_reviewed", "motion_status": "not_checked",
        "limitations": ["Visible bounds and area vary with pose, occlusion and equipment; outliers require review.",
                        "A stable silhouette does not prove constant body-part dimensions or natural motion.",
                        "Frames are compared within each state; a uniformly mis-scaled state needs an external design reference.",
                        "No logical pixel grid is inferred; use the separate strict profile audit for dot fidelity."],
    }
    out.mkdir(parents=True, exist_ok=True)
    report["outputs"] = {"report": "report.json", **_previews(image, frames, contract, out)}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sheet", type=Path, required=True, help="Unchanged sprite-gen atlas PNG")
    parser.add_argument("--manifest", type=Path, required=True, help="Runtime manifest with frame_layout rectangles")
    parser.add_argument("--request", type=Path, help="Optional sprite-request.json, including fit.palette_size")
    parser.add_argument("--max-colors", type=int, help="Shared visible RGB budget; overrides request with disclosure")
    parser.add_argument("--margin-x", type=int, help="Required horizontal margin in source PNG pixels")
    parser.add_argument("--margin-y", type=int, help="Required vertical margin in source PNG pixels")
    parser.add_argument("--size-tolerance", type=float, default=.10, help="Relative width/height deviation from state median (default .10)")
    parser.add_argument("--area-tolerance", type=float, default=.25, help="Relative visible-area deviation from state median (default .25)")
    parser.add_argument("--out-dir", type=Path, required=True)


def check_arguments(args: argparse.Namespace) -> dict:
    return check_sprite_gen(args.sheet, args.manifest, args.out_dir, request_path=args.request,
                            max_colors=args.max_colors, margin_x=args.margin_x, margin_y=args.margin_y,
                            size_tolerance=args.size_tolerance, area_tolerance=args.area_tolerance)
