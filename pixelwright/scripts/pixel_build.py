#!/usr/bin/env python3
"""Build exact square-cell pixel art from an indexed JSON logical canvas.

Only construction properties are guaranteed: every logical cell has one RGBA
value and expands to a complete scale-by-scale square using nearest neighbor.
This tool does not assess composition, silhouette, animation, or artistic merit.
Requires Python 3.12+ and Pillow. Run with --spec artwork.json --out-dir build.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image

VERSION = "0.6.2"
MAX_RENDERED_PIXELS = 12_000_000
MAX_SPEC_BYTES = 32 * 1024 * 1024
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")
_ARTIFACT_NAMES = ("native.png", "rendered.png", "build.json")
_LOCK_NAME = ".pixelwright-build.lock"


class SpecError(ValueError):
    """The logical-canvas specification cannot be built safely or exactly."""


@dataclass(frozen=True)
class PixelSpec:
    palette: dict[str, tuple[int, int, int, int]]
    rows: tuple[tuple[str, ...], ...]
    scale: int
    palette_source: dict[str, str] | None = None

    @property
    def width(self) -> int:
        return len(self.rows[0])

    @property
    def height(self) -> int:
        return len(self.rows)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SpecError(f"Duplicate JSON object key: {key!r}.")
        result[key] = value
    return result


def _color(value: Any, token: str) -> tuple[int, int, int, int]:
    if value == "transparent":
        return (0, 0, 0, 0)
    if not isinstance(value, str) or _HEX_COLOR.fullmatch(value) is None:
        raise SpecError(
            f"Palette token {token!r} requires #RRGGBB, #RRGGBBAA, or 'transparent'."
        )
    channels = tuple(int(value[i:i + 2], 16) for i in range(1, len(value), 2))
    rgba = channels + (255,) if len(channels) == 3 else channels
    # Hidden RGB has no visible meaning. Canonicalization also avoids creating
    # multiple apparently identical transparent colors in downstream tools.
    if rgba[3] == 0:
        return (0, 0, 0, 0)
    return rgba


def parse_spec(document: Any, *, base_dir: Path | None = None) -> PixelSpec:
    """Validate a schema-version-1 document without resampling or guessing.

    Rows are arrays of palette tokens. Strings are also accepted when every
    palette token is a single Unicode character; each character is one cell.
    All dimensions come from the rectangular rows, and scale must be >= 2.
    """
    if not isinstance(document, dict):
        raise SpecError("The specification must be a JSON object.")
    required = {"schema_version", "rows", "scale"}
    missing = required - document.keys()
    if missing:
        raise SpecError(f"Missing required fields: {', '.join(sorted(missing))}.")
    unexpected = document.keys() - (required | {"palette", "palette_file"})
    if unexpected:
        raise SpecError(f"Unknown specification fields: {', '.join(sorted(unexpected))}.")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise SpecError("schema_version must be the integer 1.")
    scale = document["scale"]
    if type(scale) is not int or scale < 2:
        raise SpecError("scale must be an integer >= 2 (booleans and floats are invalid).")
    if ("palette" in document) == ("palette_file" in document):
        raise SpecError("Specify exactly one of palette or palette_file.")
    palette_source = None
    if "palette_file" in document:
        reference = document["palette_file"]
        if (not isinstance(reference, str) or not reference or "\\" in reference or ":" in reference
                or PurePosixPath(reference).is_absolute() or ".." in PurePosixPath(reference).parts):
            raise SpecError("palette_file must be a confined relative POSIX path.")
        if base_dir is None:
            raise SpecError("palette_file needs the specification directory; use build_from_spec.")
        base = Path(base_dir).resolve()
        try:
            library_path = (base / reference).resolve(strict=True)
            if not library_path.is_relative_to(base):
                raise SpecError("palette_file resolves outside the specification directory.")
            import pixel_palette
            library, library_bytes, library_path = pixel_palette._palette_snapshot(library_path)
        except (OSError, ValueError, UnicodeError) as exc:
            raise SpecError(f"Invalid palette_file: {exc}") from exc
        raw_palette = library["colors"]
        palette_source = {"path": str(library_path), "sha256": _sha256(library_bytes)}
    else:
        raw_palette = document["palette"]
    if not isinstance(raw_palette, dict) or not raw_palette:
        raise SpecError("palette must be a nonempty object mapping tokens to colors.")
    palette: dict[str, tuple[int, int, int, int]] = {}
    for token, value in raw_palette.items():
        if not isinstance(token, str) or not token:
            raise SpecError("Every palette token must be a nonempty string.")
        palette[token] = _color(value, token)

    raw_rows = document["rows"]
    if not isinstance(raw_rows, list) or not raw_rows:
        raise SpecError("rows must be a nonempty array of rows.")
    character_palette = all(len(token) == 1 for token in palette)
    rows: list[tuple[str, ...]] = []
    width: int | None = None
    for y, row in enumerate(raw_rows):
        if isinstance(row, str):
            if not character_palette:
                raise SpecError(
                    f"Row {y} is a string, but palette has multi-character tokens; "
                    "use explicit token arrays to avoid ambiguous cells."
                )
            row = list(row)
        if not isinstance(row, list) or not row:
            raise SpecError(f"Row {y} must be a nonempty token array or character string.")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise SpecError(f"Row {y} has {len(row)} cells; expected {width} (ragged grid).")
        for x, token in enumerate(row):
            if not isinstance(token, str) or token not in palette:
                raise SpecError(f"Unknown palette token at row {y}, column {x}: {token!r}.")
        rows.append(tuple(row))

    assert width is not None
    if width > 4096 or len(rows) > 4096:
        raise SpecError("Logical dimensions must each be 1..4096 to match the audit contract.")
    rendered_pixels = width * len(rows) * scale * scale
    if rendered_pixels > MAX_RENDERED_PIXELS:
        raise SpecError(
            f"Rendered image would contain {rendered_pixels:,} pixels; "
            f"the limit is {MAX_RENDERED_PIXELS:,}. Reduce rows or scale."
        )
    return PixelSpec(palette=palette, rows=tuple(rows), scale=scale, palette_source=palette_source)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _png_bytes(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()


def _load_spec(spec_path: Path) -> tuple[PixelSpec, bytes]:
    if spec_path.stat().st_size > MAX_SPEC_BYTES:
        raise SpecError(f"Specification exceeds the {MAX_SPEC_BYTES:,}-byte input limit.")
    data = spec_path.read_bytes()
    if len(data) > MAX_SPEC_BYTES:
        raise SpecError(f"Specification exceeds the {MAX_SPEC_BYTES:,}-byte input limit.")
    try:
        # UTF-8 BOM is harmless, including when editors on Windows add it.
        document = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SpecError(f"Invalid UTF-8 JSON specification: {exc}.") from exc
    return parse_spec(document, base_dir=spec_path.parent), data


def build_from_spec(spec_path: str | Path, out_dir: str | Path) -> dict[str, Any]:
    """Build native.png, rendered.png and build.json without overwriting files.

    The input is read once and hashed byte-for-byte. A new or empty output
    directory is allowed. An existing nonempty directory, directory symlink,
    or directory containing the input is rejected. Writes use exclusive create.
    The returned manifest is also saved as build.json.
    """
    source = Path(spec_path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise SpecError("--spec must identify an existing regular JSON file.")
    requested_output = Path(out_dir).expanduser()
    if requested_output.is_symlink():
        raise SpecError("Output directory must not be a symbolic link.")
    output = requested_output.resolve()
    if source == output or output in source.parents:
        raise SpecError("Output directory cannot contain or replace the input specification.")
    if output.exists():
        if not output.is_dir():
            raise SpecError("Output path exists and is not a directory.")
        if any(output.iterdir()):
            raise SpecError("Output directory is not empty; choose a new directory.")
    # Complete validation before creating any output paths.
    spec, original_bytes = _load_spec(source)
    logical_rgba = bytes(
        channel
        for row in spec.rows
        for token in row
        for channel in spec.palette[token]
    )
    native = Image.frombytes("RGBA", (spec.width, spec.height), logical_rgba)
    rendered = native.resize(
        (spec.width * spec.scale, spec.height * spec.scale), Image.Resampling.NEAREST
    )
    native_bytes = _png_bytes(native)
    rendered_bytes = _png_bytes(rendered)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "pixelwright_version": VERSION,
        "input": {
            "path": str(source),
            "sha256": _sha256(original_bytes),
            "format": "pixelwright-indexed-json-v1",
        },
        "grid": {
            "logical_width": spec.width,
            "logical_height": spec.height,
            "scale": spec.scale,
            "rendered_width": rendered.width,
            "rendered_height": rendered.height,
            "origin": [0, 0],
        },
        "palette": {
            token: "#" + "".join(f"{channel:02X}" for channel in rgba)
            for token, rgba in spec.palette.items()
        },
        "construction": {
            "method": "indexed-logical-canvas",
            "resize_filter": "nearest-neighbor",
            "transparent_rgb": "normalized-to-zero",
            "uniform_square_rgba_cells": True,
            "artistic_quality_assessed": False,
        },
        "outputs": {
            "native.png": {
                "width": native.width,
                "height": native.height,
                "mode": "RGBA",
                "sha256": _sha256(native_bytes),
                "pixel_rgba_sha256": _sha256(logical_rgba),
            },
            "rendered.png": {
                "width": rendered.width,
                "height": rendered.height,
                "mode": "RGBA",
                "sha256": _sha256(rendered_bytes),
                "pixel_rgba_sha256": _sha256(rendered.tobytes()),
            },
        },
    }
    if spec.palette_source is not None:
        manifest["palette_source"] = spec.palette_source
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    created_directory = False
    try:
        output.mkdir(parents=True, exist_ok=False)
        created_directory = True
    except FileExistsError:
        # Recheck after expensive image work in case another process wrote here.
        if not output.is_dir() or any(output.iterdir()):
            raise SpecError("Output directory is no longer empty; choose a new directory.")
    lock = output / _LOCK_NAME
    try:
        with lock.open("xb"):
            pass
    except FileExistsError as exc:
        raise SpecError("Another build is using the output directory.") from exc
    created_files: list[Path] = []
    try:
        if spec.palette_source is not None:
            library_path = Path(spec.palette_source["path"])
            if _sha256(library_path.read_bytes()) != spec.palette_source["sha256"]:
                raise SpecError("Palette library changed during build.")
        # Exclusive create prevents clobbering if a competing process writes an
        # artifact after the emptiness check. Never delete a file we did not create.
        if any(path.name != _LOCK_NAME for path in output.iterdir()):
            raise SpecError("Output directory is no longer empty; choose a new directory.")
        for name, data in zip(_ARTIFACT_NAMES, (native_bytes, rendered_bytes, manifest_bytes)):
            path = output / name
            with path.open("xb") as stream:
                created_files.append(path)
                stream.write(data)
        if spec.palette_source is not None:
            if _sha256(Path(spec.palette_source["path"]).read_bytes()) != spec.palette_source["sha256"]:
                raise SpecError("Palette library changed during build.")
    except BaseException:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise
    finally:
        lock.unlink(missing_ok=True)
        if created_directory and not any(output.iterdir()):
            output.rmdir()
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path, help="Indexed JSON logical canvas.")
    parser.add_argument("--out-dir", required=True, type=Path, help="New or empty output directory.")
    args = parser.parse_args(argv)
    try:
        manifest = build_from_spec(args.spec, args.out_dir)
    except (SpecError, OSError) as exc:
        print(f"pixel_build: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "built", "out_dir": str(args.out_dir.resolve()), "grid": manifest["grid"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
