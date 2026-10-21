#!/usr/bin/env python3
"""Extract, reuse and remap named RGBA palettes for static PNG pixel art."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import pixel_qa as qa
import pixelwright as pw

VERSION = "0.6.1"
MAX_PALETTE_BYTES = 1024 * 1024
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _hex(rgba) -> str:
    return "#" + "".join(f"{int(v):02X}" for v in rgba)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def validate_palette(document: dict) -> dict:
    """Validate a named library, retaining exact RGBA and insertion order."""
    if not isinstance(document, dict):
        raise ValueError("Palette must be a JSON object")
    unknown = set(document) - {"schema_version", "name", "colors", "ramps"}
    if unknown:
        raise ValueError(f"Unknown palette fields: {', '.join(sorted(unknown))}")
    if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        raise ValueError("Palette schema_version must be integer 1")
    if "name" in document and (not isinstance(document["name"], str)
                               or not 1 <= len(document["name"]) <= 256):
        raise ValueError("Palette name must contain 1..256 characters")
    raw_colors = document.get("colors")
    if not isinstance(raw_colors, dict) or not 1 <= len(raw_colors) <= 256:
        raise ValueError("Palette colors must map 1..256 tokens to RGBA colors")
    colors, seen = {}, set()
    for token, value in raw_colors.items():
        if not isinstance(token, str) or _TOKEN.fullmatch(token) is None:
            raise ValueError("Color tokens must be 1..64 ASCII letters/digits/_/-, starting alphanumeric")
        rgba = pw.parse_rgba(value)
        if rgba in seen:
            raise ValueError(f"Duplicate RGBA color: {_hex(rgba)}")
        seen.add(rgba)
        colors[token] = _hex(rgba)
    ramps = document.get("ramps", {})
    if not isinstance(ramps, dict) or len(ramps) > 64:
        raise ValueError("ramps must be an object with at most 64 named ramps")
    normalized_ramps = {}
    for name, tokens in ramps.items():
        if not isinstance(name, str) or _TOKEN.fullmatch(name) is None:
            raise ValueError("Ramp names follow the same rules as color tokens")
        if (not isinstance(tokens, list) or not 2 <= len(tokens) <= 256
                or any(not isinstance(token, str) or token not in colors for token in tokens)
                or len(set(tokens)) != len(tokens)):
            raise ValueError(f"Ramp {name!r} must reference 2..256 distinct existing color tokens")
        normalized_ramps[name] = list(tokens)
    result = {"schema_version": 1}
    if "name" in document:
        result["name"] = document["name"]
    result.update(colors=colors, ramps=normalized_ramps)
    return result


def _palette_snapshot(path: str | Path) -> tuple[dict, bytes, Path]:
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file() or source.stat().st_size > MAX_PALETTE_BYTES:
        raise ValueError("Palette must be a regular JSON file of at most 1 MiB")
    data = source.read_bytes()
    if len(data) > MAX_PALETTE_BYTES:
        raise ValueError("Palette exceeds 1 MiB")
    document = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    return validate_palette(document), data, source


def load_palette(path: str | Path) -> dict:
    return _palette_snapshot(path)[0]


def _json_bytes(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _write(path: Path, data: bytes) -> None:
    created = False
    try:
        with path.open("xb") as stream:
            created = True
            stream.write(data)
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise


def _png_bytes(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()


def _identities(paths: list[Path]) -> list[dict]:
    return [{"path": str(path.resolve()), "sha256": qa.sha256_file(path)} for path in paths]


def _check_inputs(inputs: list[dict]) -> None:
    for item in inputs:
        path = Path(item["path"])
        if not path.is_file() or qa.sha256_file(path) != item["sha256"]:
            raise ValueError(f"Input changed during palette operation: {path}")


@contextmanager
def _fresh_output(out_dir: str | Path, inputs: list[Path]):
    requested = Path(out_dir).expanduser()
    pw.require_empty_output(requested, inputs)
    output = requested.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Output directory is no longer empty")
    lock = output / ".pixelwright-palette.lock"
    with lock.open("xb"):
        pass
    try:
        if any(path != lock for path in output.iterdir()):
            raise ValueError("Output directory is no longer empty")
        yield output
    finally:
        lock.unlink(missing_ok=True)


def _swatch(palette: dict) -> Image.Image:
    colors = list(palette["colors"].items())
    cols = min(4, len(colors))
    image = Image.new("RGB", (cols * 200, ((len(colors) + cols - 1) // cols) * 56), "#202030")
    draw = ImageDraw.Draw(image)
    for index, (token, value) in enumerate(colors):
        x, y = (index % cols) * 200, (index // cols) * 56
        chip = qa.checkerboard((32, 32), square=8).convert("RGBA")
        chip.alpha_composite(Image.new("RGBA", chip.size, pw.parse_rgba(value)))
        image.paste(chip.convert("RGB"), (x + 4, y + 4))
        draw.text((x + 40, y + 4), token[:22], fill="white")
        draw.text((x + 40, y + 20), value, fill="white")
    return image


def _export_library(output: Path, palette: dict, report: dict, inputs: list[dict]) -> dict:
    _check_inputs(inputs)
    palette_bytes = _json_bytes(palette)
    _write(output / "palette.json", palette_bytes)
    _write(output / "swatch.png", _png_bytes(_swatch(palette)))
    report.update(tool="Pixelwright", version=VERSION, schema_version=1,
                  artistic_status="not_reviewed", palette=palette, provenance={"inputs": inputs},
                  outputs={name: str(output / filename) for name, filename in
                           (("palette", "palette.json"), ("swatch", "swatch.png"),
                            ("palette_report", "palette_report.json"))})
    report["palette_sha256"] = hashlib.sha256(palette_bytes).hexdigest()
    _check_inputs(inputs)
    _write(output / "palette_report.json", _json_bytes(report))
    return report


def _unique_rgba(pixels: np.ndarray):
    # Sort packed bytes, not palette indices; ties are RGBA lexicographic.
    packed = np.ascontiguousarray(pixels).reshape(-1, 4).view("V4").ravel()
    values, inverse, counts = np.unique(packed, return_inverse=True, return_counts=True)
    return values.view(np.uint8).reshape(-1, 4), inverse, counts


def extract_palette(image_path: str | Path, out_dir: str | Path, *, max_colors: int = 256,
                    name: str = "Extracted palette", transparent_rgb: str = "exact") -> dict:
    if type(max_colors) is not int or not 1 <= max_colors <= 256:
        raise ValueError("max_colors must be an integer in 1..256")
    if transparent_rgb not in ("exact", "visible"):
        raise ValueError("transparent_rgb must be exact or visible")
    source = Path(image_path).expanduser().resolve(strict=True)
    inputs = _identities([source])
    image = qa.open_rgba(source)
    pixels = np.asarray(image, dtype=np.uint8)
    if transparent_rgb == "visible":
        pixels = qa.normalize_rgba(pixels)
    colors, _, counts = _unique_rgba(pixels)
    selected = np.argsort(-counts, kind="stable")[:max_colors]
    palette = validate_palette({"schema_version": 1, "name": name,
                                "colors": {f"color_{i:03d}": _hex(colors[index])
                                           for i, index in enumerate(selected)}})
    report = {
        "operation": "extract", "status": "extracted",
        "scope": "palette_extraction_not_grid_or_artistic_acceptance",
        "transparent_rgb": transparent_rgb,
        "input_size": {"width": image.width, "height": image.height},
        "metrics": {"distinct_rgba_colors": len(colors), "selected_colors": len(selected),
                    "truncated": len(colors) > len(selected),
                    "omitted_source_pixels": int(pixels.shape[0] * pixels.shape[1] - counts[selected].sum())},
        "counts": {token: int(counts[index]) for token, index in zip(palette["colors"], selected)},
        "selection": "observed RGBA; descending sample count, then lexicographic RGBA",
    }
    with _fresh_output(out_dir, [source]) as output:
        return _export_library(output, palette, report, inputs)


def generate_ramp(start: str, end: str, steps: int, name: str, out_dir: str | Path,
                  *, palette_path: str | Path | None = None) -> dict:
    if not isinstance(name, str) or _TOKEN.fullmatch(name) is None:
        raise ValueError("Ramp name must be a valid 1..64 character token")
    if type(steps) is not int or not 2 <= steps <= 256:
        raise ValueError("Ramp steps must be an integer in 2..256")
    first, last = pw.parse_rgba(start), pw.parse_rgba(end)
    if first[3] != last[3]:
        raise ValueError("Ramp endpoints must have the same alpha")
    paths, inputs = [], []
    if palette_path is not None:
        palette, data, source = _palette_snapshot(palette_path)
        paths = [source]
        inputs = [{"path": str(source), "sha256": hashlib.sha256(data).hexdigest()}]
    else:
        palette = {"schema_version": 1, "name": f"{name} ramp", "colors": {}, "ramps": {}}
    if name in palette["ramps"]:
        raise ValueError(f"Ramp {name!r} already exists; choose a new name")
    denominator = steps - 1
    shades = [tuple((first[c] * (denominator - i) + last[c] * i + denominator // 2)
                    // denominator for c in range(3)) + (first[3],) for i in range(steps)]
    if len(set(shades)) != steps:
        raise ValueError("Ramp rounds to duplicate RGBA shades; choose fewer steps or wider endpoints")
    existing = {value: token for token, value in palette["colors"].items()}
    tokens = []
    for index, rgba in enumerate(shades):
        value = _hex(rgba)
        if value in existing:
            tokens.append(existing[value])
            continue
        token = f"{name}_{index}"
        if len(token) > 64 or token in palette["colors"]:
            raise ValueError("Generated ramp token collides or exceeds 64 characters; use a shorter/new name")
        palette["colors"][token] = value
        existing[value] = token
        tokens.append(token)
    palette["ramps"][name] = tokens
    palette = validate_palette(palette)
    report = {"operation": "ramp", "status": "created", "ramp": name, "steps": steps,
              "interpolation": "encoded sRGB bytes, integer half-up rounding, alpha unchanged",
              "start": _hex(first), "end": _hex(last), "ramp_tokens": tokens}
    with _fresh_output(out_dir, paths) as output:
        return _export_library(output, palette, report, inputs)


def _target_colors(palette: dict, ramp: str | None) -> tuple[list[str], np.ndarray]:
    if ramp is None:
        tokens = list(palette["colors"])
    else:
        if ramp not in palette["ramps"]:
            raise ValueError(f"Unknown ramp: {ramp}")
        tokens = list(palette["ramps"][ramp])
        # Transparency is structural, so selecting an opaque material ramp does
        # not remove the library's transparent entries.
        tokens.extend(token for token, value in palette["colors"].items()
                      if pw.parse_rgba(value)[3] == 0 and token not in tokens)
    return tokens, np.array([pw.parse_rgba(palette["colors"][t]) for t in tokens], dtype=np.uint8)


def remap_image(image_path: str | Path, palette_path: str | Path, profile_path: str | Path,
                out_dir: str | Path, *, ramp: str | None = None) -> dict:
    source = Path(image_path).expanduser().resolve(strict=True)
    profile_source = Path(profile_path).expanduser().resolve(strict=True)
    if profile_source.stat().st_size > MAX_PALETTE_BYTES:
        raise ValueError("Profile exceeds 1 MiB")
    palette, palette_data, palette_source = _palette_snapshot(palette_path)
    input_paths = [source, profile_source, palette_source]
    inputs = _identities(input_paths)
    if inputs[2]["sha256"] != hashlib.sha256(palette_data).hexdigest():
        raise ValueError("Palette changed while loading")
    profile = pw.load_profile(profile_source)
    tokens, target = _target_colors(palette, ramp)
    policy = profile.get("transparent_rgb", "exact")
    image = qa.open_rgba(source)
    raw = np.asarray(image, dtype=np.uint8)
    logical_size, render_size = pw.contract_options(profile)
    _check_inputs(inputs)
    with _fresh_output(out_dir, input_paths) as output:
        report = {"tool": "Pixelwright", "version": VERSION, "schema_version": 1,
                  "operation": "remap", "status": "fail", "artistic_status": "not_reviewed",
                  "contract": profile, "target_palette": palette, "selected_ramp": ramp,
                  "palette_profile_scope": "final used colors; unused library colors do not invalidate an asset",
                  "target_tokens": tokens, "issues": [], "final": {"status": "not_remapped"},
                  "method": "nearest encoded RGB squared distance among equal-alpha colors; first target wins ties",
                  "provenance": {"inputs": inputs},
                  "outputs": {"palette_report": str(output / "palette_report.json")}}
        report["source"] = pw.audit_one(source, profile, profile_source, output / "source")
        source_report = json.loads(Path(report["source"]["outputs"]["report"]).read_text(encoding="utf-8"))
        geometry = qa.grid_geometry(image.size, logical_size, render_size)
        alpha = raw[:, :, 3]
        alpha_policy = profile.get("alpha", "binary")
        invalid_alpha = ((alpha != 0) & (alpha != 255)).any() if alpha_policy == "binary" else (
            (alpha != 255).any() if alpha_policy == "opaque" else False)
        if (geometry["status"] != "pass"
                or source_report.get("metrics", {}).get("nonuniform_rgba_cells", 1) != 0
                or invalid_alpha):
            report["issues"].append({"code": "SOURCE_STRUCTURE_OR_ALPHA_FAILED",
                                     "detail": "Remap changes colors only; source grid and declared alpha must already hold."})
            _check_inputs(inputs)
            _write(output / "palette_report.json", _json_bytes(report))
            return report
        scale = profile["scale"]
        original_native = raw[::scale, ::scale].copy()
        native = qa.normalize_rgba(original_native) if policy == "visible" else original_native
        values, inverse, counts = _unique_rgba(native)
        mapped = np.empty_like(values)
        missing = []
        for opacity in np.unique(values[:, 3]):
            indices = np.flatnonzero(values[:, 3] == opacity)
            candidates = target[target[:, 3] == opacity]
            if not len(candidates):
                missing.append(int(opacity))
                continue
            for offset in range(0, len(indices), 4096):
                chunk = indices[offset:offset + 4096]
                delta = values[chunk, None, :3].astype(np.int32) - candidates[None, :, :3].astype(np.int32)
                nearest = np.argmin((delta * delta).sum(axis=2), axis=1)
                mapped[chunk] = candidates[nearest]
        if missing:
            report["issues"].append({"code": "NO_ALPHA_MATCH", "alpha_values": missing,
                                     "detail": "Target palette needs at least one color for each source alpha value."})
            _check_inputs(inputs)
            _write(output / "palette_report.json", _json_bytes(report))
            return report
        result = mapped[inverse].reshape(native.shape)
        candidate_native = Image.fromarray(result)
        rendered = candidate_native.resize(image.size, Image.Resampling.NEAREST)
        changed = np.any(raw != np.asarray(rendered), axis=2)
        logical_mask = changed.reshape(logical_size[1], scale, logical_size[0], scale).any(axis=(1, 3))
        report["metrics"] = {"changed_source_pixels": int(changed.sum()),
                             "changed_source_pixel_fraction": float(changed.mean()),
                             "changed_logical_cells": int(logical_mask.sum()),
                             "alpha_changed_source_pixels": int(np.count_nonzero(raw[:, :, 3] != np.asarray(rendered)[:, :, 3])),
                             "hidden_rgb_changed_source_pixels": int(np.count_nonzero(changed & (alpha == 0))),
                             "source_rgba_colors": len(values), "used_target_rgba_colors": len(np.unique(mapped, axis=0))}
        report["mappings"] = [{"from": _hex(color), "to": _hex(mapped[i]), "logical_cells": int(counts[i])}
                               for i, color in enumerate(values[:256])]
        report["mappings_truncated"] = len(values) > 256
        report["source_decoded_rgba_sha256"] = hashlib.sha256(raw.tobytes()).hexdigest()
        report["output_decoded_rgba_sha256"] = hashlib.sha256(np.asarray(rendered).tobytes()).hexdigest()
        candidate = output / "candidate"
        candidate.mkdir()
        native_bytes, rendered_bytes = _png_bytes(candidate_native), _png_bytes(rendered)
        report["output_sha256"] = {"native": hashlib.sha256(native_bytes).hexdigest(),
                                   "rendered": hashlib.sha256(rendered_bytes).hexdigest()}
        _write(candidate / "native.png", native_bytes)
        _write(candidate / "rendered.png", rendered_bytes)
        _write(output / "changed_cells.png", _png_bytes(Image.fromarray(logical_mask.astype(np.uint8) * 255)))
        qa.save_side_by_side(image, rendered, output / "comparison.png", right_title="Palette remap")
        report["outputs"].update(changed_cells=str(output / "changed_cells.png"), comparison=str(output / "comparison.png"))
        # The same original contract is reapplied; a second palette membership
        # check is explicit even when that contract has no allowed_palette.
        report["final"] = pw.audit_one(candidate / "rendered.png", profile, profile_source, output / "final")
        saved = qa.open_rgba(candidate / "rendered.png")
        target_profile = profile | {"allowed_palette": [_hex(color) for color in target]}
        target_report = {"issues": [], "metrics": {}}
        pw.enforce_profile(target_report, saved, target_profile)
        report["target_status"] = target_report["status"]
        report["target_issues"] = target_report["issues"]
        report["status"] = "pass" if report["final"]["status"] == "pass" and report["target_status"] == "pass" else "fail"
        _check_inputs(inputs)
        promoted = []
        try:
            if report["status"] == "pass":
                if hashlib.sha256(rendered_bytes).hexdigest() != qa.sha256_file(candidate / "rendered.png"):
                    raise ValueError("Saved candidate differs from audited output")
                for filename, data in (("native.png", native_bytes), ("rendered.png", rendered_bytes)):
                    path = output / filename
                    _write(path, data)
                    promoted.append(path)
                    report["outputs"][filename.removesuffix(".png")] = str(path)
            else:
                report["outputs"].update(candidate_native=str(candidate / "native.png"), candidate_rendered=str(candidate / "rendered.png"))
            _check_inputs(inputs)
            _write(output / "palette_report.json", _json_bytes(report))
        except BaseException:
            for path in promoted:
                path.unlink(missing_ok=True)
            raise
        return report


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    extract = sub.add_parser("extract", help="Extract frequent observed RGBA colors; never certify the grid")
    extract.add_argument("image", type=Path)
    extract.add_argument("--max-colors", type=int, default=256)
    extract.add_argument("--name", default="Extracted palette")
    extract.add_argument("--transparent-rgb", choices=("exact", "visible"), default="exact")
    ramp = sub.add_parser("ramp", help="Create and save a reusable constant-alpha RGB ramp")
    ramp.add_argument("--start", required=True)
    ramp.add_argument("--end", required=True)
    ramp.add_argument("--steps", required=True, type=int)
    ramp.add_argument("--name", required=True)
    ramp.add_argument("--palette", type=Path)
    remap = sub.add_parser("remap", help="Remap a valid source grid and re-audit the original profile")
    remap.add_argument("image", type=Path)
    remap.add_argument("--palette", required=True, type=Path)
    remap.add_argument("--profile", required=True, type=Path)
    remap.add_argument("--ramp")
    for command in (extract, ramp, remap):
        command.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation == "extract":
            report = extract_palette(args.image, args.out_dir, max_colors=args.max_colors,
                                     name=args.name, transparent_rgb=args.transparent_rgb)
        elif args.operation == "ramp":
            report = generate_ramp(args.start, args.end, args.steps, args.name, args.out_dir, palette_path=args.palette)
        else:
            report = remap_image(args.image, args.palette, args.profile, args.out_dir, ramp=args.ramp)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2 if report["status"] == "fail" else 0
    except (ValueError, OSError, MemoryError, UnicodeError) as exc:
        print(f"Pixelwright palette error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
