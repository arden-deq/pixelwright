#!/usr/bin/env python3
"""Reusable, strict project contracts and a batch gate for static PNG assets."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import pixel_qa as qa

VERSION = "0.4.0"
PROFILE_KEYS = {"schema_version", "name", "logical_size", "scale", "max_colors",
                "alpha", "transparent_rgb", "allowed_palette"}


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


def load_profile(path: Path) -> dict:
    def unique_object(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError(f"Duplicate profile field: {key}")
            values[key] = value
        return values
    profile = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
    if not isinstance(profile, dict):
        raise ValueError("Profile must be a JSON object")
    unknown = set(profile) - PROFILE_KEYS
    if unknown:
        raise ValueError(f"Unknown profile fields: {', '.join(sorted(unknown))}")
    if type(profile.get("schema_version")) is not int or profile["schema_version"] != 1:
        raise ValueError("Profile schema_version must be 1")
    if "name" in profile and not isinstance(profile["name"], str):
        raise ValueError("Profile name must be a string")
    size = profile.get("logical_size")
    if not isinstance(size, str):
        raise ValueError("Profile logical_size must be WIDTHxHEIGHT")
    try:
        logical = qa.parse_size(size)
    except argparse.ArgumentTypeError as exc:
        raise ValueError(str(exc)) from exc
    scale = profile.get("scale")
    if type(scale) is not int or not 2 <= scale <= 4096:
        raise ValueError("Profile scale must be an integer in 2..4096")
    if logical[0] * logical[1] * scale * scale > qa.MAX_PIXELS:
        raise ValueError(f"Rendered contract exceeds {qa.MAX_PIXELS} pixels")
    max_colors = profile.get("max_colors")
    if max_colors is not None and (type(max_colors) is not int or not 1 <= max_colors <= 256):
        raise ValueError("max_colors must be an integer in 1..256")
    if profile.get("alpha", "binary") not in ("binary", "opaque", "any"):
        raise ValueError("alpha must be binary, opaque, or any")
    if profile.get("transparent_rgb", "exact") not in ("exact", "visible"):
        raise ValueError("transparent_rgb must be exact or visible")
    palette = profile.get("allowed_palette")
    if palette is not None:
        if not isinstance(palette, list) or not 1 <= len(palette) <= 256:
            raise ValueError("allowed_palette must contain 1..256 colors")
        for value in palette:
            parse_rgba(value)
    return profile


def contract_options(profile: dict) -> tuple[tuple[int, int], tuple[int, int]]:
    logical = qa.parse_size(profile["logical_size"])
    return logical, tuple(v * profile["scale"] for v in logical)


def enforce_profile(report: dict, image: Image.Image, profile: dict) -> None:
    """Check actual decoded samples, including colors discarded by a preview."""
    arr = np.asarray(image, dtype=np.uint8)
    policy = profile.get("transparent_rgb", "exact")
    if policy == "visible":
        arr = qa.normalize_rgba(arr)
    alpha = profile.get("alpha", "binary")
    # Deliberate cell-uniform translucency can satisfy an 'any' contract.
    if alpha == "any":
        for issue in report["issues"]:
            if issue["code"] == "PARTIAL_ALPHA":
                issue["severity"] = "info"
    if alpha == "opaque":
        count = int(np.count_nonzero(arr[:, :, 3] != 255))
        if count:
            report["issues"].append({"code": "NON_OPAQUE_ALPHA", "severity": "fail",
                                     "detail": f"{count} samples are not opaque; profile requires alpha=255."})
    allowed = profile.get("allowed_palette")
    if allowed is not None:
        colors = np.array([parse_rgba(v) for v in allowed], dtype=np.uint8)
        if policy == "visible":
            colors[colors[:, 3] == 0, :3] = 0
        # Packed RGBA keys avoid allocating a pixels x palette comparison tensor.
        keys = np.ascontiguousarray(arr).view(np.dtype("V4")).reshape(arr.shape[:2])
        allowed_keys = np.ascontiguousarray(colors).view(np.dtype("V4")).ravel()
        bad = ~np.isin(keys, allowed_keys)
        count = int(np.count_nonzero(bad))
        report.setdefault("metrics", {})["outside_palette_source_pixels"] = count
        report["outside_palette_sample"] = [{"x": int(x), "y": int(y)}
                                             for y, x in np.argwhere(bad)[:20]]
        if count:
            report["issues"].append({"code": "COLOR_OUTSIDE_ALLOWED_PALETTE", "severity": "fail",
                                     "detail": f"{count} decoded RGBA samples are outside the declared palette."})
    severities = {i["severity"] for i in report["issues"]}
    report["status"] = "fail" if "fail" in severities else "review" if "review" in severities else "pass"
    report["artistic_status"] = "not_reviewed"
    report["contract"] = profile


def require_empty_output(out_dir: Path, inputs: list[Path]) -> None:
    qa.validate_output_dir(out_dir)
    target = out_dir.resolve()
    for source in inputs:
        if source.resolve() == target or target in source.resolve().parents:
            raise ValueError("Output directory must not contain an input")


def audit_one(image_path: Path, profile: dict, profile_path: Path, out_dir: Path) -> dict:
    image = qa.open_rgba(image_path)
    logical, rendered = contract_options(profile)
    geometry = qa.grid_geometry(image.size, logical, rendered)
    if geometry["status"] == "pass":
        audit = qa.inspect_image(image, logical, max_colors=profile.get("max_colors"),
                                 strict_alpha=profile.get("alpha", "binary") == "binary",
                                 strict_cells=True, transparent_rgb=profile.get("transparent_rgb", "exact"))
        report = audit.result
        report["geometry"] = geometry
        enforce_profile(report, image, profile)
        paths = qa.write_audit(audit, out_dir)
    else:
        paths = qa.write_geometry_failure(image, logical, out_dir, geometry)
        report = json.loads(Path(paths["report"]).read_text(encoding="utf-8"))
        report["contract"] = profile
        report["artistic_status"] = "not_reviewed"
    report.setdefault("provenance", {}).update({"profile_sha256": sha256(profile_path),
                            "source_path": str(image_path.resolve()), "profile_path": str(profile_path.resolve())})
    report["provenance"].setdefault("source_sha256", sha256(image_path))
    report["schema_version"] = 1
    report["acceptance_mode"] = "strict_profile"
    Path(paths["report"]).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"input": str(image_path), "status": report["status"], "outputs": paths}


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    inspect = sub.add_parser("inspect", help="Strict reusable profile audit")
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
