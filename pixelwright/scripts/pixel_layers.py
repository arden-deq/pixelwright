#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Manage, audit and compose static PNG layers on a shared logical pixel grid.

Layer order is bottom to top. A passing composition uses only integer native
coordinates, binary-alpha overwrite and one final nearest-neighbor enlargement.
Every submitted layer, including hidden layers, must pass its own strict audit.
Technical PASS does not assess artistic quality, overlap, anatomy or readability.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import re
import struct
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
from PIL import Image

import pixel_qa as qa
import pixelwright as project

VERSION = "0.6.0"
MAX_LAYERS = 64
MAX_INPUT_PIXELS = 48_000_000
MAX_JSON_BYTES = 1024 * 1024
MANIFEST_KEYS = {"schema_version", "name", "profile", "layers"}
LAYER_KEYS = {"id", "image", "logical_size", "position", "visible", "sha256"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_LOCK = ".pixelwright-layers.lock"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number is unsupported: {value}")


def _read_document(path: Path) -> tuple[dict[str, Any], str]:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"JSON input exceeds {MAX_JSON_BYTES:,} bytes")
    data = path.read_bytes()
    if len(data) > MAX_JSON_BYTES:
        raise ValueError(f"JSON input exceeds {MAX_JSON_BYTES:,} bytes")
    try:
        document = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("Manifest must be a JSON object")
    return document, hashlib.sha256(data).hexdigest()


def _relative_file(base: Path, value: Any, field: str) -> Path:
    if (not isinstance(value, str) or not value or len(value) > 1024
            or "\\" in value or ":" in value or "\x00" in value):
        raise ValueError(f"{field} must be a relative POSIX file path")
    path = PurePosixPath(value)
    # Check the spelling as well as normalized parts: '.' and empty segments
    # should not silently disappear when a manifest is reviewed or rewritten.
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError(f"{field} must remain within the manifest directory")
    resolved = (base / Path(*path.parts)).resolve(strict=True)
    if not resolved.is_relative_to(base) or not resolved.is_file():
        raise ValueError(f"{field} must resolve to a file within the manifest directory")
    return resolved


def _size(value: Any, field: str) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be WIDTHxHEIGHT")
    try:
        return qa.parse_size(value)
    except argparse.ArgumentTypeError as exc:
        raise ValueError(f"{field}: {exc}") from exc


def _validate_document(document: dict[str, Any], source: Path,
                       manifest_sha256: str | None = None) -> dict[str, Any]:
    unknown = set(document) - MANIFEST_KEYS
    missing = {"schema_version", "profile", "layers"} - document.keys()
    if unknown or missing:
        raise ValueError(f"Manifest fields invalid; missing={sorted(missing)}, unknown={sorted(unknown)}")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("Manifest schema_version must be the integer 1")
    if "name" in document and (not isinstance(document["name"], str)
                               or len(document["name"]) > 256):
        raise ValueError("Manifest name must be a string of at most 256 characters")
    base = source.parent
    profile_path = _relative_file(base, document["profile"], "profile")
    if profile_path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"Profile exceeds {MAX_JSON_BYTES:,} bytes")
    profile_digest = qa.sha256_file(profile_path)
    profile = project.load_profile(profile_path)
    if qa.sha256_file(profile_path) != profile_digest:
        raise ValueError("Profile bytes changed while loading the shared contract")
    if profile.get("max_colors") is None:
        raise ValueError("Layer composition requires a shared max_colors budget")
    if profile.get("allowed_palette") is None:
        raise ValueError("Layer composition requires a shared allowed_palette")
    if profile.get("transparent_rgb", "exact") != "exact":
        raise ValueError("Layer composition requires transparent_rgb=exact")
    if profile.get("alpha", "binary") not in ("binary", "opaque"):
        raise ValueError("Final alpha must be binary or opaque")
    logical, rendered = project.contract_options(profile)
    raw_layers = document["layers"]
    if not isinstance(raw_layers, list) or not 1 <= len(raw_layers) <= MAX_LAYERS:
        raise ValueError(f"layers must contain 1..{MAX_LAYERS} entries")
    seen: set[str] = set()
    layers: list[dict[str, Any]] = []
    total_pixels = 0
    for index, raw in enumerate(raw_layers):
        if not isinstance(raw, dict):
            raise ValueError(f"Layer {index} must be an object")
        unknown = set(raw) - LAYER_KEYS
        missing = {"id", "image", "logical_size", "position"} - raw.keys()
        if unknown or missing:
            raise ValueError(f"Layer {index} fields invalid; missing={sorted(missing)}, unknown={sorted(unknown)}")
        layer_id = raw["id"]
        if not isinstance(layer_id, str) or _ID.fullmatch(layer_id) is None:
            raise ValueError(f"Layer {index} id must be 1..64 safe ASCII letters, digits, '_' or '-'")
        if layer_id in seen:
            raise ValueError(f"Duplicate layer id: {layer_id}")
        seen.add(layer_id)
        size = _size(raw["logical_size"], f"Layer {layer_id} logical_size")
        position = raw["position"]
        if (not isinstance(position, list) or len(position) != 2
                or any(type(v) is not int for v in position)):
            raise ValueError(f"Layer {layer_id} position must be two integer native coordinates")
        x, y = position
        if x < 0 or y < 0 or x + size[0] > logical[0] or y + size[1] > logical[1]:
            raise ValueError(f"Layer {layer_id} must fit completely within the logical canvas")
        visible = raw.get("visible", True)
        if type(visible) is not bool:
            raise ValueError(f"Layer {layer_id} visible must be a boolean")
        pinned = raw.get("sha256")
        if "sha256" in raw and (not isinstance(pinned, str) or _SHA256.fullmatch(pinned) is None):
            raise ValueError(f"Layer {layer_id} sha256 must contain 64 hexadecimal characters")
        image_path = _relative_file(base, raw["image"], f"Layer {layer_id} image")
        physical = tuple(v * profile["scale"] for v in size)
        pixels = physical[0] * physical[1]
        if pixels > qa.MAX_PIXELS:
            raise ValueError(f"Layer {layer_id} rendered size exceeds {qa.MAX_PIXELS:,} pixels")
        total_pixels += pixels
        if total_pixels > MAX_INPUT_PIXELS:
            raise ValueError(f"Declared input layers exceed {MAX_INPUT_PIXELS:,} rendered pixels")
        layers.append({"id": layer_id, "index": index, "image": raw["image"],
                       "image_path": image_path, "logical_size": size,
                       "render_size": physical, "position": tuple(position), "visible": visible,
                       "sha256": pinned.lower() if pinned else None})
    return {"document": copy.deepcopy(document), "manifest_path": source,
            "manifest_sha256": manifest_sha256, "profile_path": profile_path,
            "profile_sha256": profile_digest, "profile": profile,
            "logical_size": logical, "render_size": rendered, "scale": profile["scale"],
            "declared_input_pixels": total_pixels, "layers": layers}


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Validate structure, paths, contracts and declared resource bounds.

    This is a plan, not a PNG acceptance verdict. Pixel values and physical PNG
    dimensions are checked by compose; list never certifies layer quality.
    """
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("Manifest must be an existing file")
    document, digest = _read_document(source)
    return _validate_document(document, source, digest)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def _write_json(path: Path, value: Any) -> None:
    _write_bytes(path, _json_bytes(value))


def _rewrite_owned_report(path: Path, report: dict[str, Any]) -> None:
    # Only QA reports created by this invocation are updated with provenance.
    with path.open("wb") as stream:
        stream.write(_json_bytes(report))


def _relative_outputs(paths: dict[str, str], root: Path) -> dict[str, str]:
    return {key: Path(value).resolve().relative_to(root).as_posix() for key, value in paths.items()}


def _audit(image_path: Path, profile: dict[str, Any], profile_path: Path,
           audit_dir: Path, root: Path, *, pinned: str | None = None,
           source_display: str | None = None,
           source_path_base: str = "manifest_directory",
           acceptance_mode: str = "strict_layer_contract") -> tuple[dict[str, Any], np.ndarray | None]:
    before = qa.sha256_file(image_path)
    image = qa.open_rgba(image_path)
    after = qa.sha256_file(image_path)
    logical, rendered = project.contract_options(profile)
    geometry = qa.grid_geometry(image.size, logical, rendered)
    native = None
    if geometry["status"] == "pass":
        audit = qa.inspect_image(image, logical, max_colors=profile.get("max_colors"),
                                 strict_alpha=profile.get("alpha", "binary") == "binary",
                                 strict_cells=True, transparent_rgb="exact")
        report = audit.result
        report["geometry"] = geometry
        project.enforce_profile(report, image, profile)
        paths = qa.write_audit(audit, audit_dir)
        # Use the actual decoded, audited image; never reload a layer after QA.
        native = np.asarray(image, dtype=np.uint8)[::profile["scale"], ::profile["scale"]].copy()
    else:
        paths = qa.write_geometry_failure(image, logical, audit_dir, geometry)
        report = json.loads(Path(paths["report"]).read_text(encoding="utf-8"))
        report["contract"] = profile
    if before != after:
        report["issues"].append({"code": "INPUT_CHANGED", "severity": "fail",
                                 "detail": "Input bytes changed while being decoded and audited."})
        report["status"] = "fail"
    if pinned is not None and before != pinned:
        report["issues"].append({"code": "SHA256_MISMATCH", "severity": "fail",
                                 "detail": "Input bytes do not match the pinned SHA-256."})
        report["status"] = "fail"
    report["version"] = VERSION
    report["schema_version"] = 1
    report["acceptance_mode"] = acceptance_mode
    report["artistic_status"] = "not_reviewed"
    report.setdefault("provenance", {}).update({
        "source_path": source_display or image_path.name,
        "source_path_base": source_path_base,
        "source_sha256": before, "source_sha256_after_audit": after,
        "profile_path": profile_path.relative_to(root).as_posix(),
        "profile_path_base": "output_directory",
        "profile_sha256": qa.sha256_file(profile_path), "pinned_sha256": pinned})
    _rewrite_owned_report(Path(paths["report"]), report)
    relative = _relative_outputs(paths, root)
    return {"status": report["status"], "report": relative["report"],
            "outputs": relative, "source_sha256": before,
            "report_sha256": qa.sha256_file(Path(paths["report"]))}, native


def _png_bytes(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _artifact(path: Path, root: Path, size: tuple[int, int], decoded: bytes) -> dict[str, Any]:
    return {"path": path.relative_to(root).as_posix(), "width": size[0], "height": size[1],
            "sha256": qa.sha256_file(path),
            "decoded_rgba_sha256": hashlib.sha256(decoded).hexdigest()}


def _check_header_budget(image_path: Path, used_pixels: int) -> int:
    with image_path.open("rb") as stream:
        header = stream.read(24)
    if len(header) == 24 and header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR":
        width, height = struct.unpack(">II", header[16:24])
        used_pixels += width * height
        if used_pixels > MAX_INPUT_PIXELS:
            raise ValueError(f"Actual submitted PNGs exceed {MAX_INPUT_PIXELS:,} rendered pixels")
    return used_pixels


def _check_input_integrity(plan: dict[str, Any], summary: dict[str, Any]) -> bool:
    """Recheck metadata snapshots, retaining any earlier mismatch as a failure."""
    checks = summary.setdefault("input_integrity", {})
    issues = summary.setdefault("issues", [])
    for role in ("manifest", "profile"):
        source = plan[f"{role}_path"]
        try:
            current = qa.sha256_file(source)
        except OSError:
            current = None
        previous = checks.get(role, {})
        unchanged = (current == plan[f"{role}_sha256"]
                     and previous.get("unchanged_during_checks", True))
        checks[role] = {"source_path": source.name if role == "manifest" else plan["document"]["profile"],
                        "source_path_base": "manifest_directory",
                        "sha256_before": plan[f"{role}_sha256"], "sha256_after": current,
                        "unchanged_during_checks": unchanged,
                        "check_count": previous.get("check_count", 0) + 1}
        code = f"{role.upper()}_CHANGED"
        if not unchanged and not any(issue["code"] == code for issue in issues):
            issues.append({"code": code, "severity": "fail",
                           "detail": f"The input {role} changed or became unreadable during this run."})
    return all(value["unchanged_during_checks"] for value in checks.values())


def _invalidate_final_for_metadata(summary: dict[str, Any], root: Path) -> None:
    """Retain diagnosed pixels as candidates when an input contract changes."""
    final = summary["final"]
    metadata_issues = [issue for issue in summary.get("issues", [])
                       if issue["code"] in ("MANIFEST_CHANGED", "PROFILE_CHANGED")]
    if not metadata_issues:
        return
    if final.get("accepted"):
        for artifact in final["artifacts"].values():
            source = root / artifact["path"]
            target = root / "candidate" / source.name
            _write_bytes(target, source.read_bytes())
            if qa.sha256_file(target) != artifact["sha256"]:
                raise ValueError("Candidate preservation differs from the audited export")
            source.unlink()
            artifact["path"] = target.relative_to(root).as_posix()
        summary["outputs"] = {key: value["path"] for key, value in final["artifacts"].items()}
    if "report" in final:
        report_path = root / final["report"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        present = {issue["code"] for issue in report["issues"]}
        report["issues"].extend(copy.deepcopy(issue) for issue in metadata_issues if issue["code"] not in present)
        report["status"] = "fail"
        report["provenance"]["source_path"] = "candidate/rendered.png"
        report["provenance"]["accepted_export_sha256_verified"] = False
        _rewrite_owned_report(report_path, report)
        final["status"] = "fail"
        final["accepted"] = False
        final["report_sha256"] = qa.sha256_file(report_path)
    else:
        final["reason"] = "Input manifest or profile changed during the run; composition is not accepted."
    if summary["status"] != "error":
        summary["status"] = "fail"


def compose(manifest_path: str | Path, out_dir: str | Path) -> dict[str, Any]:
    """Audit every layer, compose accepted samples and re-audit a saved PNG.

    Returns and saves layers.json. Layer failure prevents composition. A final
    failure retains only candidate PNGs; accepted root PNGs exist only on PASS.
    Input files are never rewritten, output directories must be new or empty.
    """
    plan = load_manifest(manifest_path)
    requested = Path(out_dir).expanduser()
    inputs = [plan["manifest_path"], plan["profile_path"]] + [v["image_path"] for v in plan["layers"]]
    project.require_empty_output(requested, inputs)
    root = requested.resolve()
    root.mkdir(parents=True, exist_ok=True)
    _write_bytes(root / _LOCK, b"")
    try:
        if any(path.name != _LOCK for path in root.iterdir()):
            raise ValueError("Output directory is no longer empty")
        # Store the exact shared contract used in this run, independent of later
        # edits to the original input profile. Layer overrides get their own file.
        final_profile_path = root / "profile.json"
        _write_json(final_profile_path, plan["profile"])
        summary: dict[str, Any] = {
            "tool": "Pixelwright", "version": VERSION, "schema_version": 1,
            "status": "error", "scope": "technical_checks_only_not_artistic_quality",
            "manifest": {"path": plan["manifest_path"].name, "path_base": "manifest_directory",
                         "sha256": plan["manifest_sha256"]},
            "profile": {"path": plan["document"]["profile"], "path_base": "manifest_directory",
                        "sha256": plan["profile_sha256"]},
            "contract": plan["profile"],
            "composition": {"order": "bottom_to_top", "coordinates": "integer_logical_cells",
                            "alpha": "binary_overwrite", "resize_filter": "nearest_neighbor",
                            "hidden_layers_audited": True, "declared_input_pixels": plan["declared_input_pixels"]},
            "results": [], "final": {"status": "not_composed"}, "outputs": {}}
        natives: list[np.ndarray | None] = []
        used_pixels = 0
        for layer in plan["layers"]:
            entry = {"id": layer["id"], "index": layer["index"], "image": layer["image"],
                     "visible": layer["visible"], "position": list(layer["position"]),
                     "logical_size": list(layer["logical_size"])}
            native = None
            layer_dir = root / "layers" / f"{layer['index']:04d}"
            layer_profile = copy.deepcopy(plan["profile"])
            layer_profile["logical_size"] = f"{layer['logical_size'][0]}x{layer['logical_size'][1]}"
            layer_profile["alpha"] = "binary"
            layer_profile_path = layer_dir / "profile.json"
            _write_json(layer_profile_path, layer_profile)
            try:
                used_pixels = _check_header_budget(layer["image_path"], used_pixels)
                result, native = _audit(layer["image_path"], layer_profile, layer_profile_path,
                                        layer_dir / "qa", root, pinned=layer["sha256"],
                                        source_display=layer["image"])
                entry.update(result)
            except (ValueError, OSError, MemoryError) as exc:
                error_report = {"tool": "Pixelwright", "version": VERSION, "schema_version": 1,
                                "status": "error", "error": str(exc), "artistic_status": "not_reviewed",
                                "contract": layer_profile,
                                "provenance": {"source_path": layer["image"],
                                               "source_path_base": "manifest_directory",
                                               "profile_path": layer_profile_path.relative_to(root).as_posix(),
                                               "profile_path_base": "output_directory"}}
                # An interrupted audit may have emitted partial diagnostics.
                # Do not overwrite those; provide a separate explicit error report.
                error_path = layer_dir / "error.json"
                _write_json(error_path, error_report)
                entry.update({"status": "error", "error": str(exc),
                              "report": error_path.relative_to(root).as_posix(),
                              "report_sha256": qa.sha256_file(error_path), "outputs": {}})
            summary["results"].append(entry)
            natives.append(native if entry["status"] == "pass" else None)
        statuses = {entry["status"] for entry in summary["results"]}
        metadata_unchanged = _check_input_integrity(plan, summary)
        if statuses != {"pass"} or not metadata_unchanged:
            summary["status"] = "error" if "error" in statuses else "fail"
            summary["final"]["reason"] = "All layers, including hidden layers, must pass before composition."
        else:
            width, height = plan["logical_size"]
            canvas = np.zeros((height, width, 4), dtype=np.uint8)
            for layer, native in zip(plan["layers"], natives):
                if not layer["visible"]:
                    continue
                assert native is not None
                x, y = layer["position"]
                lw, lh = layer["logical_size"]
                region = canvas[y:y + lh, x:x + lw]
                opaque = native[:, :, 3] == 255
                region[opaque] = native[opaque]
            native_image = Image.fromarray(canvas, "RGBA")
            rendered = native_image.resize(plan["render_size"], Image.Resampling.NEAREST)
            candidate = root / "candidate"
            native_path, rendered_path = candidate / "native.png", candidate / "rendered.png"
            _write_bytes(native_path, _png_bytes(native_image))
            _write_bytes(rendered_path, _png_bytes(rendered))
            final, _ = _audit(rendered_path, plan["profile"], final_profile_path,
                              root / "final", root, source_display="candidate/rendered.png",
                              source_path_base="output_directory",
                              acceptance_mode="strict_final_contract")
            if not _check_input_integrity(plan, summary):
                final["status"] = "fail"
            final["acceptance_mode"] = "strict_final_contract"
            final["accepted"] = final["status"] == "pass"
            summary["status"] = final["status"]
            if final["status"] == "pass":
                promoted: list[Path] = []
                try:
                    for source in (native_path, rendered_path):
                        target = root / source.name
                        with target.open("xb") as stream:
                            promoted.append(target)
                            stream.write(source.read_bytes())
                        if qa.sha256_file(source) != qa.sha256_file(target):
                            raise ValueError("Accepted export differs from the saved, audited candidate")
                except BaseException:
                    for path in promoted:
                        path.unlink(missing_ok=True)
                    raise
                native_path.unlink()
                rendered_path.unlink()
                candidate.rmdir()
                native_path, rendered_path = root / "native.png", root / "rendered.png"
                report_path = root / final["report"]
                report = json.loads(report_path.read_text(encoding="utf-8"))
                report["acceptance_mode"] = "strict_final_contract"
                report["provenance"]["source_path"] = "rendered.png"
                report["provenance"]["accepted_export_sha256_verified"] = True
                _rewrite_owned_report(report_path, report)
                final["report_sha256"] = qa.sha256_file(report_path)
            final["artifacts"] = {
                "native": _artifact(native_path, root, native_image.size, native_image.tobytes()),
                "rendered": _artifact(rendered_path, root, rendered.size, rendered.tobytes())}
            summary["final"] = final
            summary["outputs"] = {key: value["path"] for key, value in final["artifacts"].items()}
        _check_input_integrity(plan, summary)
        _invalidate_final_for_metadata(summary, root)
        _write_json(root / "layers.json", summary)
        return summary
    finally:
        (root / _LOCK).unlink(missing_ok=True)


def edit_manifest(manifest_path: str | Path, layer_id: str, out_path: str | Path,
                  *, position: tuple[int, int] | list[int] | None = None,
                  visible: bool | None = None, index: int | None = None) -> dict[str, Any]:
    """Write a validated, changed manifest to a new file in the same directory."""
    plan = load_manifest(manifest_path)
    source = plan["manifest_path"]
    requested = Path(out_path).expanduser()
    if requested.is_symlink():
        raise ValueError("Edited manifest must not be a symbolic link")
    target = requested.resolve()
    if target.parent != source.parent or target == source:
        raise ValueError("Edited manifest must be a new file in the original manifest directory")
    if target.exists():
        raise ValueError("Edited manifest output already exists")
    document = copy.deepcopy(plan["document"])
    matches = [i for i, layer in enumerate(document["layers"]) if layer["id"] == layer_id]
    if not matches:
        raise ValueError(f"Unknown layer id: {layer_id}")
    original_index = matches[0]
    layer = document["layers"][original_index]
    changed = False
    if position is not None:
        if (not isinstance(position, (tuple, list)) or len(position) != 2
                or any(type(value) is not int for value in position)):
            raise ValueError("position must contain two integers")
        values = list(position)
        changed |= layer["position"] != values
        layer["position"] = values
    if visible is not None:
        if type(visible) is not bool:
            raise ValueError("visible must be a boolean")
        changed |= layer.get("visible", True) != visible
        layer["visible"] = visible
    if index is not None:
        if type(index) is not int or not 0 <= index < len(document["layers"]):
            raise ValueError("index must identify an existing zero-based stack position")
        changed |= original_index != index
        document["layers"].insert(index, document["layers"].pop(original_index))
    if not changed:
        raise ValueError("Edit must change the position, visibility or stack order")
    _validate_document(document, target)
    _write_json(target, document)
    return document


def _plan_output(plan: dict[str, Any]) -> dict[str, Any]:
    return {"tool": "Pixelwright", "version": VERSION, "schema_version": 1,
            "status": "plan", "qa_performed": False,
            "name": plan["document"].get("name"), "logical_size": list(plan["logical_size"]),
            "render_size": list(plan["render_size"]), "scale": plan["scale"],
            "order": "bottom_to_top", "declared_input_pixels": plan["declared_input_pixels"],
            "layers": [{key: layer[key] for key in
                        ("id", "index", "image", "logical_size", "position", "visible", "sha256")}
                       for layer in plan["layers"]]}


def _position_arg(value: str) -> tuple[int, int]:
    if re.fullmatch(r"-?[0-9]+,-?[0-9]+", value) is None:
        raise argparse.ArgumentTypeError("position must be X,Y with integer native coordinates")
    x, y = value.split(",")
    return int(x), int(y)


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    listing = sub.add_parser("list", help="Validate and list a layer plan; no PNG QA")
    composition = sub.add_parser("compose", help="Audit layers, compose and gate the final PNG")
    editing = sub.add_parser("edit", help="Save changed position, visibility or stack order")
    for command in (listing, composition, editing):
        command.add_argument("--manifest", required=True, type=Path)
    composition.add_argument("--out-dir", required=True, type=Path)
    editing.add_argument("--layer", required=True)
    editing.add_argument("--position", type=_position_arg)
    editing.add_argument("--visible", choices=("true", "false"))
    editing.add_argument("--index", type=int)
    editing.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "list":
            print(json.dumps(_plan_output(load_manifest(args.manifest)), ensure_ascii=False, indent=2))
            return 0
        if args.action == "edit":
            document = edit_manifest(args.manifest, args.layer, args.out, position=args.position,
                                     visible=None if args.visible is None else args.visible == "true",
                                     index=args.index)
            print(json.dumps({"status": "edited", "output": str(args.out), "document": document},
                             ensure_ascii=False, indent=2))
            return 0
        summary = compose(args.manifest, args.out_dir)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1 if summary["status"] == "error" else 0 if summary["status"] == "pass" else 2
    except (ValueError, OSError, MemoryError) as exc:
        print(f"Pixelwright layers error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
