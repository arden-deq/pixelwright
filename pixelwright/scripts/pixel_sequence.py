#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Create and audit consistent 2D sprite sequences without an anatomical rig.

prepare freezes a selected design, arbitrary part names, motion intent and a
shared pixel contract. import records a host-generated sheet; generate uses an
image-edit API with that same design. check exports sheets/GIFs and compares
independently observed artwork parts and 2D features. No Blender, bones or
human joint vocabulary is required. Unobserved appearance/motion stays REVIEW.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import hashlib
import io
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import pixel_qa as qa
import pixel_sprite as sprite
import pixelwright as project

VERSION = project.VERSION
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_RESPONSE_BYTES = 60 * 1024 * 1024
TOP_KEYS = {"schema_version", "name", "description", "frame_size", "scale", "max_colors",
            "derivation", "limits", "parts", "landmarks", "ratios", "states"}
PART_KEYS = {"description", "area_tolerance", "min_shape_match", "min_color_overlap", "min_design_match", "measurements"}
STATE_KEYS = {"intent", "poses", "columns", "loop", "durations_ms", "motion", "attachments",
              "contacts", "distances", "root_offsets"}
_fields, _int, _number, _identifier = sprite._fields, sprite._int, sprite._number, sprite._identifier


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def read_json(path):
    return sprite._read_json(Path(path))[0]


def text_value(value, name, maximum=8000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be nonempty text of at most {maximum} characters")
    return value


def point(value, name, size=None):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must be a numeric [x, y]")
    result = tuple(_number(v, name, -4096, 4096) for v in value)
    if size and not (0 <= result[0] < size[0] and 0 <= result[1] < size[1]):
        raise ValueError(f"{name} lies outside its frame")
    return result


def _named(value, name, maximum=64):
    if not isinstance(value, dict) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{name} must have 1..{maximum} named entries")
    for key in value:
        _identifier(key, name)
    return value


def validate_spec(document):
    """Validate a 2D contract; no hidden anatomy or inferred skeleton defaults."""
    spec = copy.deepcopy(_fields(document, "sequence", TOP_KEYS,
        ("schema_version", "name", "description", "frame_size", "scale", "max_colors",
         "derivation", "limits", "parts", "landmarks", "states")))
    _int(spec["schema_version"], "schema_version", 1, 1)
    text_value(spec["name"], "name", 200)
    text_value(spec["description"], "description")
    size = sprite._size(spec["frame_size"], "frame_size")
    _int(spec["scale"], "scale", 2, 32)
    _int(spec["max_colors"], "max_colors", 2, 256)
    derive = _fields(spec["derivation"], "derivation", {"mode", "alpha_threshold"}, ("mode",))
    if derive["mode"] not in ("strict", "project"):
        raise ValueError("derivation.mode must be strict or project")
    derive.setdefault("alpha_threshold", 128)
    _int(derive["alpha_threshold"], "alpha_threshold", 1, 255)
    limits = _fields(spec["limits"], "limits", {"edge_margin", "area_ratio", "color_distance", "max_bad_color_fraction"},
                     ("edge_margin", "area_ratio", "color_distance", "max_bad_color_fraction"))
    _int(limits["edge_margin"], "edge_margin", 0, min(size) // 2 - 1)
    ratio = limits["area_ratio"]
    if not isinstance(ratio, list) or len(ratio) != 2:
        raise ValueError("area_ratio must be [minimum, maximum]")
    low, high = (_number(v, "area_ratio", 0.01, 100) for v in ratio)
    if low > 1 or high < 1 or low > high:
        raise ValueError("area_ratio must contain the reference ratio 1")
    _number(limits["color_distance"], "color_distance", 0, 442)
    _number(limits["max_bad_color_fraction"], "max_bad_color_fraction", 0, 1)
    for key, part in _named(spec["parts"], "parts").items():
        _fields(part, f"part {key}", PART_KEYS, ("description",))
        text_value(part["description"], f"part {key}.description", 1000)
        for field, default in (("area_tolerance", 0.2), ("min_shape_match", 0.65),
                               ("min_color_overlap", 0.8), ("min_design_match", 0.65)):
            part.setdefault(field, default)
            _number(part[field], f"{key}.{field}", 0, 1)
        part.setdefault("measurements", {})
        if not isinstance(part["measurements"], dict) or len(part["measurements"]) > 32:
            raise ValueError("part.measurements must be an object of at most 32 tolerances")
        for name, tolerance in part["measurements"].items():
            _identifier(name, "measurement")
            _number(tolerance, "measurement tolerance", 0, 1)
    for key, description in _named(spec["landmarks"], "landmarks").items():
        if isinstance(description, dict):
            _fields(description, f"landmark {key}", {"description", "part"}, ("description", "part"))
            if description["part"] not in spec["parts"]:
                raise ValueError("Landmark names an unknown owning part")
            description = description["description"]
        text_value(description, f"landmark {key}", 1000)
    spec.setdefault("ratios", {})
    if not isinstance(spec["ratios"], dict) or len(spec["ratios"]) > 64:
        raise ValueError("ratios must be an object of at most 64 entries")
    for name, ratio in spec["ratios"].items():
        _identifier(name, "ratio")
        _fields(ratio, name, {"numerator", "denominator", "tolerance"}, ("numerator", "denominator", "tolerance"))
        for field in ("numerator", "denominator"):
            item = ratio[field]
            if (not isinstance(item, list) or len(item) != 2 or item[0] not in spec["parts"]
                    or item[1] not in spec["parts"][item[0]]["measurements"]):
                raise ValueError(f"{name}.{field} must name [part, measurement]")
        _number(ratio["tolerance"], name, 0, 1)
    for name, state in _named(spec["states"], "states", 32).items():
        _fields(state, name, STATE_KEYS, ("intent", "poses", "columns", "loop", "durations_ms", "motion"))
        text_value(state["intent"], name)
        poses = state["poses"]
        if not isinstance(poses, list) or not 2 <= len(poses) <= 128:
            raise ValueError(f"{name}.poses must have 2..128 frame descriptions")
        for pose in poses:
            text_value(pose, "pose", 2000)
        n = len(poses)
        columns = _int(state["columns"], "columns", 1, n)
        rows = math.ceil(n / columns)
        if size[0] * columns * size[1] * rows * spec["scale"] ** 2 > qa.MAX_PIXELS:
            raise ValueError("Rendered state sheet exceeds the image pixel limit")
        if type(state["loop"]) is not bool:
            raise ValueError("loop must be a boolean")
        times = state["durations_ms"]
        if not isinstance(times, list) or len(times) != n:
            raise ValueError("durations_ms must have one value per pose")
        for duration in times:
            _int(duration, "duration", 1, 60_000)
        if not isinstance(state["motion"], dict) or set(state["motion"]) != set(spec["landmarks"]):
            raise ValueError("motion must explicitly cover every named 2D landmark")
        for landmark, rule in state["motion"].items():
            _fields(rule, landmark, {"min_travel", "max_speed", "max_acceleration", "relative_to"}, ("min_travel", "max_speed"))
            if "relative_to" in rule and (rule["relative_to"] not in spec["landmarks"] or rule["relative_to"] == landmark):
                raise ValueError("relative_to must name another observed landmark")
            _number(rule["min_travel"], "min_travel", 0, 8192)
            _number(rule["max_speed"], "max_speed in cells/second", 0, 1e7)
            if "max_acceleration" in rule:
                _number(rule["max_acceleration"], "max_acceleration in cells/second²", 0, 1e10)
        for field in ("attachments", "contacts", "distances"):
            state.setdefault(field, [])
            if not isinstance(state[field], list) or len(state[field]) > 256:
                raise ValueError(f"{field} must be a list of at most 256 rules")
        for field, allowed in (("attachments", {"a", "b", "max_distance"}),
                               ("distances", {"a", "b", "minimum", "maximum"})):
            for rule in state[field]:
                _fields(rule, "distance rule", allowed, tuple(allowed))
                if rule["a"] not in spec["landmarks"] or rule["b"] not in spec["landmarks"]:
                    raise ValueError("distance rule names an unknown landmark")
                for key in allowed - {"a", "b"}:
                    _number(rule[key], key, 0, 8192)
                if "minimum" in rule and rule["minimum"] > rule["maximum"]:
                    raise ValueError("distance minimum exceeds maximum")
        state.setdefault("root_offsets", [[0, 0] for _ in poses])
        if not isinstance(state["root_offsets"], list) or len(state["root_offsets"]) != n:
            raise ValueError("root_offsets must have one 2D displacement per frame")
        for offset in state["root_offsets"]:
            point(offset, "root offset")
        for rule in state["contacts"]:
            _fields(rule, "contact", {"landmark", "frames", "max_drift", "ground_y", "max_ground_error"},
                    ("landmark", "frames", "max_drift"))
            if rule["landmark"] not in spec["landmarks"]:
                raise ValueError("contact names an unknown landmark")
            if not isinstance(rule["frames"], list) or not 2 <= len(rule["frames"]) <= n:
                raise ValueError("contact.frames must cover at least two unique frames")
            for index in rule["frames"]:
                _int(index, "contact frame", 0, n - 1)
            if len(set(rule["frames"])) != len(rule["frames"]):
                raise ValueError("contact.frames contains duplicates")
            _number(rule["max_drift"], "max_drift", 0, 8192)
            if ("ground_y" in rule) != ("max_ground_error" in rule):
                raise ValueError("ground_y and max_ground_error must be supplied together")
            if "ground_y" in rule:
                _number(rule["ground_y"], "ground_y", -4096, 4096)
                _number(rule["max_ground_error"], "max_ground_error", 0, 8192)
    return spec


def _png(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def _lock(run):
    lock = run / ".sequence.lock"
    try:
        with lock.open("x"):
            pass
    except FileExistsError:
        raise ValueError("Another operation holds the sequence run lock") from None
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _logical(image, size, derivation, *, enforce_strict=True):
    geometry = qa.grid_geometry(image.size, size)
    if derivation["mode"] == "project":
        if image.width * size[1] != image.height * size[0]:
            raise ValueError("Projection requires the declared aspect ratio; no crop, stretch or per-frame fitting is allowed")
        # One fixed whole-canvas sampling operation. Even a provider's 1254px
        # square can become a 64-cell DERIVATIVE; its raw grid is never certified.
        pixels = np.array(image.resize(size, Image.Resampling.NEAREST)).copy()
        pixels[:, :, 3] = np.where(pixels[:, :, 3] >= derivation["alpha_threshold"], 255, 0).astype(np.uint8)
        pixels[pixels[:, :, 3] == 0] = 0
        status = "not_certified_projection_source"
    else:
        if geometry["status"] != "pass":
            raise ValueError(f"Strict input needs one common integer cell scale for {size}")
        audit = qa.inspect_image(image, size, strict_cells=True, strict_alpha=True, transparent_rgb="exact")
        if enforce_strict and audit.result["status"] == "fail":
            raise ValueError("Strict input has nonuniform cells or invalid alpha; preserve it and use a new project contract for projection")
        pixels, status = audit.logical_pixels.copy(), audit.result["status"]
        if np.any(pixels[pixels[:, :, 3] == 0] != 0):
            if enforce_strict:
                raise ValueError("Strict references need canonical transparent RGBA; use a declared projection to change it")
    return pixels, {"source_size": list(image.size), "logical_size": list(size),
                    "mode": derivation["mode"], "original_grid_status": status,
                    "sampling": "nearest_whole_canvas" if derivation["mode"] == "project" else "exact_uniform_cells",
                    "native_input_has_no_measurable_within_cell_fidelity": image.size == size}


def _nearest(pixels, palette):
    visible = pixels[:, :, 3] > 0
    selected = np.array(palette, dtype=np.uint8)
    output = np.zeros_like(pixels)
    errors = np.zeros(pixels.shape[:2], dtype=float)
    # Chunk by visible cells; a 256-color palette must not allocate image×palette×RGB.
    flat = pixels[visible, :3].astype(np.int32)
    indices, distances = [], []
    for offset in range(0, len(flat), 8192):
        squared = np.sum((flat[offset:offset + 8192, None, :] - selected[None, :, :3].astype(np.int32)) ** 2, axis=2)
        choices = np.argmin(squared, axis=1)
        indices.extend(choices.tolist())
        distances.extend(np.sqrt(squared[np.arange(len(choices)), choices]).tolist())
    if indices:
        output[visible] = selected[np.array(indices)]
        errors[visible] = distances
    return output, errors


def prompt_for(spec, state_id, palette):
    state = spec["states"][state_id]
    width, height = sprite._size(spec["frame_size"], "frame_size")
    rows = math.ceil(len(state["poses"]) / state["columns"])
    return (f"Create new 2D pixel artwork for {spec['name']}: {spec['description']}\n"
        "The attached selected 2D design is the authority for identity, proportions, colors and details. "
        "No 3D model, skeleton, mesh or real-world anatomy is required. Use the object's own visible parts.\n"
        f"State: {state_id}. {state['intent']}\n"
        f"One transparent PNG sheet, {state['columns']} columns by {rows} rows, row-major. "
        f"Every slot is the same {width}x{height} logical canvas and the SAME camera and pixel scale. "
        "Do not fit, zoom or recenter individual poses. No labels, grid lines, shadows on a backdrop or extra objects. "
        "Keep unused final slots transparent. Make stepped pixel contours and deliberate color clusters.\n"
        f"Shared visible RGBA palette: {', '.join(sprite._hex(tuple(c)) for c in palette)}.\n"
        "Preserve each part's size, characteristic shape, markings and attachment; redraw convincing motion, "
        "including weight, contact, anticipation and recovery where relevant.\n"
        + "\n".join(f"Part {name}: {part['description']}" for name, part in spec["parts"].items()) + "\n"
        + "\n".join(f"Visible feature {name}: {definition['description'] if isinstance(definition, dict) else definition}"
                     for name, definition in spec["landmarks"].items()) + "\n"
        + "".join(f"Move feature {name} relative to {rule['relative_to']}; whole-object translation alone is insufficient.\n"
                  for name, rule in state["motion"].items() if "relative_to" in rule)
        + "\n".join(f"Frame {index} ({state['durations_ms'][index]} ms): {pose}" for index, pose in enumerate(state["poses"])) + "\n"
        + ("The last frame must continue naturally into the first, without a duplicated endpoint.\n" if state["loop"]
           else "This is a one-shot action; preserve preparation, action and recovery.\n"))


def prepare(spec_path, reference_path, out_dir):
    spec_path, reference_path, out = Path(spec_path).resolve(), Path(reference_path).resolve(), Path(out_dir).resolve()
    spec_data, reference_data = spec_path.read_bytes(), reference_path.read_bytes()
    spec = validate_spec(read_json(spec_path))
    reference = qa.open_rgba(reference_path)
    size = sprite._size(spec["frame_size"], "frame_size")
    native, derivation = _logical(reference, size, spec["derivation"])
    if not np.any(native[:, :, 3]):
        raise ValueError("Selected reference is empty")
    if spec["derivation"]["mode"] == "project":
        native = qa.quantize_logical_rgba(native, spec["max_colors"])
        native[native[:, :, 3] == 0] = 0
    palette = np.unique(native[native[:, :, 3] > 0], axis=0).tolist()
    if len(palette) > spec["max_colors"]:
        raise ValueError("Selected reference exceeds max_colors; do not silently extend its palette")
    contract = {"schema_version": 1, "tool_version": VERSION, "spec": spec, "palette": palette,
                "reference_source_sha256": digest(reference_data), "spec_source_sha256": digest(spec_data),
                "reference_derivation": derivation, "skeleton_required": False}
    project.require_empty_output(out, [spec_path, reference_path])
    out.mkdir(parents=True, exist_ok=True)
    files = {"contract.json": json_bytes(contract), "reference-source.png": reference_data,
             "reference-native.png": _png(Image.fromarray(native)), "source-spec.json": spec_data}
    for name in spec["states"]:
        files[f"prompts/{name}.txt"] = prompt_for(spec, name, palette).encode("utf-8")
    for name, data in files.items():
        sprite._write_new(out / name, data)
    manifest = {"schema_version": 1, "frozen": {name: digest(data) for name, data in files.items()}, "states": {}}
    _atomic(out / "run.json", json_bytes(manifest))
    return {"status": "prepared", "run": str(out), "contract_sha256": digest(files["contract.json"]),
            "states": list(spec["states"]), "skeleton_required": False}


def load_run(run):
    run = Path(run).resolve()
    manifest = read_json(run / "run.json")
    contract = read_json(run / "contract.json")
    validate_spec(contract["spec"])
    required = {"contract.json", "reference-source.png", "reference-native.png", "source-spec.json"}
    required |= {f"prompts/{name}.txt" for name in contract["spec"]["states"]}
    if set(manifest["frozen"]) != required:
        raise ValueError("Run frozen inputs are missing or unexpected")
    for name in required:
        if project.sha256(run / name) != manifest["frozen"][name]:
            raise ValueError(f"Frozen input changed: {name}; use a new run for a new contract")
    if not isinstance(manifest["states"], dict) or set(manifest["states"]) - set(contract["spec"]["states"]):
        raise ValueError("Run contains an unknown state")
    for name, entry in manifest["states"].items():
        if project.sha256(run / "raw" / f"{name}.png") != entry["sha256"]:
            raise ValueError(f"Raw image changed: {name}")
    return run, contract, manifest


def _store_image(run, state, data, producer, replace):
    run, contract, manifest = load_run(run)
    if state not in contract["spec"]["states"]:
        raise ValueError("Unknown state")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("PNG exceeds the byte limit")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
            raise ValueError("Import a static PNG sheet")
        if image.width * image.height > qa.MAX_PIXELS:
            raise ValueError("PNG exceeds the pixel limit")
        image.verify()
    target = run / "raw" / f"{state}.png"
    if target.exists() and not replace:
        raise ValueError("State exists; --replace preserves its previous original and provenance")
    history = copy.deepcopy(manifest["states"].get(state, {}).get("history", []))
    if target.exists():
        previous = manifest["states"].get(state)
        folder = f"history/{state}/{uuid.uuid4().hex}"
        sprite._write_new(run / folder / "image.png", target.read_bytes())
        sprite._write_new(run / folder / "generation.json", json_bytes(previous))
        history.append({"path": folder, "sha256": digest(target.read_bytes())})
    _atomic(target, data)
    entry = {"sha256": digest(data), "contract_sha256": manifest["frozen"]["contract.json"],
             "reference_sha256": manifest["frozen"]["reference-native.png"],
             "prompt_sha256": manifest["frozen"][f"prompts/{state}.txt"],
             "producer": producer, "history": history}
    manifest["states"][state] = entry
    _atomic(run / "run.json", json_bytes(manifest))
    return entry


def import_image(run, state, image_path, *, producer="external_host_unverified", replace=False):
    run = Path(run).resolve()
    text_value(producer, "producer", 1000)
    with _lock(run):
        return _store_image(run, state, Path(image_path).read_bytes(), {"method": producer}, replace)


def _multipart(fields, reference):
    boundary = uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="selected-design.png"\r\n'
             'Content-Type: image/png\r\n\r\n').encode() + reference
    body += f'\r\n--{boundary}--\r\n'.encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Image endpoint redirects are not followed with credentials")


def generate(run, state, *, model, size="auto", quality="high", background=None, base_url="https://api.openai.com/v1",
             timeout=600, replace=False, api_key=None):
    """Reference-conditioned image edits. The key is never stored in artifacts."""
    text_value(model, "model", 200)
    text_value(size, "API size", 100)
    if quality not in ("auto", "low", "medium", "high"):
        raise ValueError("Unknown API quality")
    if background not in (None, "auto", "transparent", "opaque"):
        raise ValueError("Unknown API background")
    _number(timeout, "timeout", 1, 3600)
    url = urllib.parse.urlsplit(base_url)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Use an HTTPS image API base URL without credentials, query or fragment")
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY is not set")
    run = Path(run).resolve()
    with _lock(run):
        run, contract, manifest = load_run(run)
        if state not in contract["spec"]["states"]:
            raise ValueError("Unknown state")
        if (run / "raw" / f"{state}.png").exists() and not replace:
            raise ValueError("State already exists; no request sent")
        fields = {"model": model, "prompt": (run / "prompts" / f"{state}.txt").read_text(encoding="utf-8"),
                  "size": size, "quality": quality, "output_format": "png", "n": 1}
        if background is not None:
            fields["background"] = background
        body, content_type = _multipart(fields, (run / "reference-native.png").read_bytes())
        request = urllib.request.Request(base_url.rstrip("/") + "/images/edits", body, method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": content_type})
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
                response_bytes = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            # Provider error bodies can echo submitted credentials or prompts.
            raise RuntimeError(f"Images API HTTP {error.code}; existing originals were preserved") from None
        except urllib.error.URLError:
            raise RuntimeError("Images API connection failed; existing originals were preserved") from None
        if len(response_bytes) > MAX_RESPONSE_BYTES:
            raise ValueError("Image API response exceeds the byte limit")
        try:
            payload = json.loads(response_bytes)
            data = base64.b64decode(payload["data"][0]["b64_json"], validate=True)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ValueError("Image API did not return a valid base64 image") from exc
        if load_run(run)[2] != manifest:
            raise ValueError("Inputs changed during image generation; result not imported")
        return _store_image(run, state, data, {"method": "images_edits_http", "model": model,
            "size": size, "quality": quality, "background": background, "endpoint_host": url.hostname}, replace)


def observation_template(run):
    run, contract, manifest = load_run(run)
    spec = contract["spec"]
    def frame():
        return {"parts": {name: None for name in spec["parts"]},
                "landmarks": {name: None for name in spec["landmarks"]}}
    return {"schema_version": 1, "contract_sha256": manifest["frozen"]["contract.json"],
        "method": "", "reference_sha256": manifest["frozen"]["reference-native.png"], "reference": frame(),
        "states": {name: {"source_sha256": manifest["states"][name]["sha256"],
            "frames": [frame() for _ in spec["states"][name]["poses"]],
            "review": {"status": "not_reviewed", "reviewer": "", "observations": []}}
            for name in manifest["states"]}}


def _review(entry, issues, state):
    entry = entry or {"status": "not_reviewed", "reviewer": "", "observations": []}
    _fields(entry, "art review", {"status", "reviewer", "observations"}, ("status", "reviewer", "observations"))
    if entry["status"] not in ("accepted", "changes_needed", "not_reviewed"):
        raise ValueError("Unknown art review status")
    if not isinstance(entry["observations"], list) or not all(isinstance(item, str) for item in entry["observations"]):
        raise ValueError("Art review observations must be text entries")
    if entry["status"] != "not_reviewed":
        text_value(entry["reviewer"], "reviewer", 500)
        if not entry["observations"] or not all(item.strip() for item in entry["observations"]):
            raise ValueError("A reviewed state needs actual visual observations")
    if entry["status"] != "accepted":
        issues.append(sprite._issue("ART_CHANGES_NEEDED" if entry["status"] == "changes_needed" else "ART_NOT_REVIEWED",
                                    "review", "Review identity, contours, timing, contact and intended movement separately.", state=state))
    return entry


def _runs_mask(runs, size):
    width, height = size
    if not isinstance(runs, list) or len(runs) > width * height:
        raise ValueError("Part mask must be a list of at most frame-area [y, x_start, x_end_exclusive] runs")
    mask = np.zeros((height, width), dtype=bool)
    for run in runs:
        if not isinstance(run, list) or len(run) != 3:
            raise ValueError("A mask run must be [y, x_start, x_end_exclusive]")
        y = _int(run[0], "mask y", 0, height - 1)
        start = _int(run[1], "mask start", 0, width - 1)
        end = _int(run[2], "mask end", start + 1, width)
        if np.any(mask[y, start:end]):
            raise ValueError("Part mask runs overlap")
        mask[y, start:end] = True
    if not mask.any():
        raise ValueError("Visible part mask is empty; use null or occluded for unobserved parts")
    return mask


def _on_mask(value, mask):
    x, y = (int(math.floor(v + 0.5)) for v in value)
    return 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and bool(mask[y, x])


def _observe_frame(entry, pixels, spec, issues, context):
    size = (pixels.shape[1], pixels.shape[0])
    entry = entry or {"parts": {}, "landmarks": {}}
    _fields(entry, "observed frame", {"parts", "landmarks"}, ("parts", "landmarks"))
    for field in ("parts", "landmarks"):
        if not isinstance(entry[field], dict) or set(entry[field]) - set(spec[field]):
            raise ValueError(f"Observed {field} contain unknown names")
    observed = {"parts": {}, "landmarks": {}}
    visible = pixels[:, :, 3] > 0
    assigned = np.zeros(visible.shape, dtype=bool)
    complete = True
    for name, rule in spec["parts"].items():
        item = entry["parts"].get(name)
        if item is None:
            issues.append(sprite._issue("PART_NOT_OBSERVED", "review", "Observe the actual artwork part; no anatomy is inferred.", part=name, **context))
            complete = False
            continue
        _fields(item, "part observation", {"visibility", "reason", "mask", "measurements"}, ("visibility",))
        if item["visibility"] == "occluded":
            text_value(item.get("reason"), "occlusion reason", 1000)
            if item.get("mask") or item.get("measurements"):
                raise ValueError("An occluded part cannot also claim visible measurements")
            issues.append(sprite._issue("PART_OCCLUDED", "review", item["reason"], part=name, **context))
            complete = False
            continue
        if item["visibility"] != "visible":
            raise ValueError("Part visibility must be visible or occluded; null means not observed")
        mask = _runs_mask(item.get("mask"), size)
        if np.any(mask & ~visible):
            issues.append(sprite._issue("MASK_ON_TRANSPARENT", "fail", "Observed part includes transparent cells.", part=name, **context))
        if np.any(mask & assigned):
            issues.append(sprite._issue("PART_MASK_OVERLAP", "fail", "A visible cell cannot belong to two parts.", part=name, **context))
        assigned |= mask
        measures = item.get("measurements", {})
        if not isinstance(measures, dict) or set(measures) - set(rule["measurements"]):
            raise ValueError("Unknown observed measurement")
        lengths = {}
        for measure in rule["measurements"]:
            pair = measures.get(measure)
            if pair is None:
                issues.append(sprite._issue("MEASUREMENT_NOT_OBSERVED", "review", "Mark both visible endpoints, or leave unobserved.",
                                            part=name, measurement=measure, **context))
                continue
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("Measurement must contain two independently observed 2D endpoints")
            a, b = (point(value, "measurement endpoint", size) for value in pair)
            if not _on_mask(a, mask) or not _on_mask(b, mask):
                issues.append(sprite._issue("MEASUREMENT_OFF_PART", "fail", "Measurement endpoints must be on this artwork part.",
                                            part=name, measurement=measure, **context))
            length = math.dist(a, b)
            if length <= 0:
                raise ValueError("Measurement endpoints must be distinct")
            lengths[measure] = length
        keys, counts = np.unique(pixels[mask & visible], axis=0, return_counts=True)
        histogram = {tuple(color): int(count) for color, count in zip(keys.tolist(), counts.tolist())}
        observed["parts"][name] = {"mask": mask, "area": int(mask.sum()), "histogram": histogram, "measurements": lengths}
    if complete and np.any(visible & ~assigned):
        issues.append(sprite._issue("VISIBLE_CELLS_UNASSIGNED", "fail", "Complete part observations must cover every visible cell.", **context))
    for name in spec["landmarks"]:
        value = entry["landmarks"].get(name)
        if value is None:
            issues.append(sprite._issue("LANDMARK_NOT_OBSERVED", "review", "Observe this feature in the actual artwork.", landmark=name, **context))
            continue
        value = point(value, "observed landmark", size)
        if not _on_mask(value, visible):
            issues.append(sprite._issue("LANDMARK_OFF_ART", "fail", "Observed feature lies outside visible artwork.", landmark=name, **context))
        definition = spec["landmarks"][name]
        if isinstance(definition, dict):
            part = observed["parts"].get(definition["part"])
            if part is None:
                issues.append(sprite._issue("LANDMARK_PART_UNVERIFIED", "review", "The feature's owning part is not observed.", landmark=name, **context))
            elif not _on_mask(value, part["mask"]):
                issues.append(sprite._issue("LANDMARK_ON_WRONG_PART", "fail", "Feature lies on another part's artwork.", landmark=name, part=definition["part"], **context))
        observed["landmarks"][name] = value
    return observed


def _appearance_match(reference, current, reference_pixels, current_pixels):
    """Rotation/translation search, NEVER size fitting. Return shape and color IoU.

    This detects pixel pattern changes within an observed part; it does not
    establish the semantic truth of a supplied part mask or visual identity.
    """
    y0, x0 = np.where(reference["mask"])
    y1, x1 = np.where(current["mask"])
    origin = np.column_stack((x0 - x0.mean(), y0 - y0.mean()))
    target_xy = np.rint(np.column_stack((x1 - x1.mean(), y1 - y1.mean()))).astype(int)
    colors0 = reference_pixels[y0, x0].tolist()
    colors1 = current_pixels[y1, x1].tolist()
    target = {tuple(xy) for xy in target_xy.tolist()}
    target_color = {(*xy, *color) for xy, color in zip(target_xy.tolist(), colors1)}
    shape, design = 0.0, 0.0
    for angle in range(0, 360, 5):
        radians = math.radians(angle)
        rotation = np.array([[math.cos(radians), -math.sin(radians)], [math.sin(radians), math.cos(radians)]])
        transformed = np.rint(origin @ rotation.T).astype(int).tolist()
        points = {tuple(xy) for xy in transformed}
        colored = {(*xy, *color) for xy, color in zip(transformed, colors0)}
        shape = max(shape, len(points & target) / len(points | target))
        design = max(design, len(colored & target_color) / len(colored | target_color))
    return shape, design


def _compare_parts(reference, current, ref_pixels, pixels, spec, issues, context):
    results = {}
    for name, part in current["parts"].items():
        baseline = reference["parts"].get(name)
        if baseline is None:
            issues.append(sprite._issue("REFERENCE_PART_UNVERIFIED", "review", "The selected design part needs independent observation.", part=name, **context))
            continue
        rule = spec["parts"][name]
        area_ratio = part["area"] / baseline["area"]
        total0, total1 = sum(baseline["histogram"].values()), sum(part["histogram"].values())
        overlap = sum(min(count / total0, part["histogram"].get(color, 0) / total1)
                      for color, count in baseline["histogram"].items()) if total0 and total1 else 0
        shape, design = _appearance_match(baseline, part, ref_pixels, pixels)
        values = {"area_ratio": area_ratio, "color_overlap": overlap, "shape_match": shape, "design_match": design,
                  "measurements": part["measurements"]}
        results[name] = values
        tests = ((abs(area_ratio - 1) > rule["area_tolerance"], "PART_SIZE_CHANGED", "Observed visible area changed beyond the frozen tolerance."),
                 (overlap < rule["min_color_overlap"], "PART_COLOR_CHANGED", "Observed part color distribution changed."),
                 (shape < rule["min_shape_match"], "PART_SHAPE_CHANGED", "Part shape changed under a rotation-only comparison."),
                 (design < rule["min_design_match"], "PART_DESIGN_CHANGED", "Part pixel pattern changed under a rotation-only comparison."))
        for failed, code, detail in tests:
            if failed:
                issues.append(sprite._issue(code, "fail", detail, part=name, metrics=values, **context))
        for measure, length in part["measurements"].items():
            original = baseline["measurements"].get(measure)
            if original is None:
                issues.append(sprite._issue("REFERENCE_MEASUREMENT_UNVERIFIED", "review", "Reference endpoints were not observed.",
                                            part=name, measurement=measure, **context))
            elif abs(length / original - 1) > rule["measurements"][measure]:
                issues.append(sprite._issue("PART_PROPORTION_CHANGED", "fail", "Observed endpoint distance changed beyond its tolerance.",
                                            part=name, measurement=measure, ratio=length / original, **context))
    for name, ratio in spec["ratios"].items():
        def value(observation):
            numerator = observation["parts"].get(ratio["numerator"][0], {}).get("measurements", {}).get(ratio["numerator"][1])
            denominator = observation["parts"].get(ratio["denominator"][0], {}).get("measurements", {}).get(ratio["denominator"][1])
            return numerator / denominator if numerator is not None and denominator else None
        original, measured = value(reference), value(current)
        if original is None or measured is None:
            issues.append(sprite._issue("RATIO_UNVERIFIED", "review", "A required part measurement is unobserved.", ratio=name, **context))
        elif abs(measured / original - 1) > ratio["tolerance"]:
            issues.append(sprite._issue("PART_RATIO_CHANGED", "fail", "Relative part proportions changed.", ratio=name,
                                        reference=original, measured=measured, **context))
    return results


def _motion_checks(state_id, state, observed, issues):
    n = len(observed)
    transitions = [(i, i + 1) for i in range(n - 1)] + ([(n - 1, 0)] if state["loop"] else [])
    result = {"landmarks": {}, "contacts": []}
    for name, rule in state["motion"].items():
        points = [frame["landmarks"].get(name) for frame in observed]
        anchor = rule.get("relative_to")
        anchors = [frame["landmarks"].get(anchor) for frame in observed] if anchor else None
        if any(value is None for value in points) or (anchors is not None and any(value is None for value in anchors)):
            issues.append(sprite._issue("MOTION_UNVERIFIED", "review", "All frames need this observed feature; missing frames are not interpolated.",
                                        state=state_id, landmark=name))
            continue
        values = np.array(points, dtype=float)
        if anchors is not None:
            values -= np.array(anchors, dtype=float)
        travel = float(np.sqrt(np.sum((values[:, None] - values[None, :]) ** 2, axis=2)).max())
        steps = []
        for a, b in transitions:
            dt = state["durations_ms"][a] / 1000
            velocity = (values[b] - values[a]) / dt
            speed = float(np.linalg.norm(velocity))
            steps.append({"from": a, "to": b, "seconds": dt, "velocity": velocity.tolist(), "speed": speed})
            if speed > rule["max_speed"] + 1e-9:
                issues.append(sprite._issue("MOTION_SPEED_EXCEEDED", "fail", "Time-aware landmark speed exceeds the contract.",
                    state=state_id, landmark=name, frame=a, next_frame=b, speed=speed, loop_boundary=b == 0))
        if travel + 1e-9 < rule["min_travel"]:
            issues.append(sprite._issue("REQUIRED_MOTION_MISSING", "fail", "This feature did not move through its required range.",
                                        state=state_id, landmark=name, measured=travel))
        accelerations = []
        if "max_acceleration" in rule:
            pairs = list(zip(steps, steps[1:])) + ([(steps[-1], steps[0])] if state["loop"] else [])
            for previous, following in pairs:
                acceleration = float(np.linalg.norm(np.array(following["velocity"]) - previous["velocity"]) /
                                     ((previous["seconds"] + following["seconds"]) / 2))
                accelerations.append(acceleration)
                if acceleration > rule["max_acceleration"] + 1e-9:
                    issues.append(sprite._issue("MOTION_ACCELERATION_EXCEEDED", "fail", "Velocity changes too abruptly for the contract.",
                                                state=state_id, landmark=name, frame=following["from"], acceleration=acceleration))
        result["landmarks"][name] = {"travel": travel, "transitions": steps, "accelerations": accelerations,
            "coordinate_system": "observed_2d_relative_to_landmark" if anchor else "observed_2d_frame",
            "relative_to": anchor}
    for kind, rules in (("attachment", state["attachments"]), ("distance", state["distances"])):
        for rule in rules:
            for index, frame in enumerate(observed):
                a, b = frame["landmarks"].get(rule["a"]), frame["landmarks"].get(rule["b"])
                if a is None or b is None:
                    issues.append(sprite._issue("CONNECTION_UNVERIFIED", "review", "Connection endpoints are unobserved.", state=state_id, frame=index))
                    continue
                distance = math.dist(a, b)
                low, high = (0, rule["max_distance"]) if kind == "attachment" else (rule["minimum"], rule["maximum"])
                if not low <= distance <= high:
                    issues.append(sprite._issue("PART_DETACHED" if kind == "attachment" else "FEATURE_DISTANCE_CHANGED", "fail",
                        "Observed 2D feature distance violates the frozen rule.", state=state_id, frame=index,
                        endpoints=[rule["a"], rule["b"]], distance=distance))
    for rule in state["contacts"]:
        values = [observed[index]["landmarks"].get(rule["landmark"]) for index in rule["frames"]]
        if any(value is None for value in values):
            issues.append(sprite._issue("CONTACT_UNVERIFIED", "review", "Contact is unobserved in a required frame.", state=state_id, landmark=rule["landmark"]))
            continue
        world = np.array(values) + np.array([state["root_offsets"][i] for i in rule["frames"]])
        drift = float(np.sqrt(np.sum((world[:, None] - world[None, :]) ** 2, axis=2)).max())
        result["contacts"].append({"landmark": rule["landmark"], "frames": rule["frames"], "drift": drift,
                                    "coordinate_system": "observed_2d_plus_declared_root_offset"})
        if drift > rule["max_drift"] + 1e-9:
            issues.append(sprite._issue("CONTACT_SLIDING", "fail", "Contact point slides in the declared movement coordinate system.",
                                        state=state_id, landmark=rule["landmark"], drift=drift))
        if "ground_y" in rule and np.any(np.abs(world[:, 1] - rule["ground_y"]) > rule["max_ground_error"] + 1e-9):
            issues.append(sprite._issue("CONTACT_GROUND_MISMATCH", "fail", "Contact point leaves the declared ground height.",
                                        state=state_id, landmark=rule["landmark"]))
    return result


def _observation_overlay(frames, observed, layout, scale, parts):
    width, height = layout.sheet_size
    scale = min(scale, max(1, int(math.sqrt(qa.MAX_PIXELS / (2 * width * height)))))
    output = Image.new("RGBA", (width * scale * 2, height * scale), (48, 52, 62, 255))
    colors = {name: sprite.PART_COLORS[index % len(sprite.PART_COLORS)] for index, name in enumerate(parts)}
    fw, fh = layout.frame_size
    for index, (pixels, observation) in enumerate(zip(frames, observed)):
        x, y = layout.origin(index)
        art = Image.fromarray(pixels).resize((fw * scale, fh * scale), Image.Resampling.NEAREST)
        output.alpha_composite(art, (x * scale, y * scale))
        masks = np.zeros_like(pixels)
        for name, part in observation["parts"].items():
            masks[part["mask"]] = (*colors[name], 255)
        output.alpha_composite(Image.fromarray(masks).resize(art.size, Image.Resampling.NEAREST),
                               (width * scale + x * scale, y * scale))
        draw = ImageDraw.Draw(output)
        for name, value in observation["landmarks"].items():
            px, py = ((x + value[0] + 0.5) * scale, (y + value[1] + 0.5) * scale)
            draw.ellipse((px - 2, py - 2, px + 2, py + 2), outline=(255, 255, 255, 255))
            draw.text((px + 3, py - 5), name, fill="white")
    return output


def _coordinate_frame(pixels):
    """A separate observation aid; coordinates are native cells, never artwork."""
    height, width = pixels.shape[:2]
    scale, margin = max(1, min(8, 512 // max(width, height))), 24
    art = Image.fromarray(pixels).resize((width * scale, height * scale), Image.Resampling.NEAREST)
    image = Image.new("RGBA", (art.width + margin, art.height + margin), (48, 52, 62, 255))
    image.alpha_composite(art, (margin, margin))
    draw = ImageDraw.Draw(image)
    interval = max(1, math.ceil(24 / scale))
    for x in range(0, width + 1, interval):
        px = margin + x * scale
        draw.line((px, margin, px, image.height), fill=(90, 110, 130, 120))
        draw.text((px, 7), str(x), fill="white")
    for y in range(0, height + 1, interval):
        py = margin + y * scale
        draw.line((margin, py, image.width, py), fill=(90, 110, 130, 120))
        draw.text((2, py), str(y), fill="white")
    return image


def check(run, out_dir, observations_path=None, *, preview_scale=4):
    run, contract, manifest = load_run(run)
    spec, out = contract["spec"], Path(out_dir).resolve()
    _int(preview_scale, "preview_scale", 1, 8)
    inputs = [run / name for name in manifest["frozen"]] + [run / "run.json"]
    inputs += [run / "raw" / f"{name}.png" for name in manifest["states"]]
    observations = None
    if observations_path is not None:
        observations_path = Path(observations_path).resolve()
        inputs.append(observations_path)
        observations = read_json(observations_path)
        _fields(observations, "observations", {"schema_version", "contract_sha256", "reference_sha256", "method", "reference", "states"},
                ("schema_version", "contract_sha256", "reference_sha256", "method", "reference", "states"))
        _int(observations["schema_version"], "observation schema", 1, 1)
        if (observations["contract_sha256"] != manifest["frozen"]["contract.json"]
                or observations["reference_sha256"] != manifest["frozen"]["reference-native.png"]):
            raise ValueError("Observations belong to a different contract or selected design")
        if not isinstance(observations["method"], str) or len(observations["method"]) > 2000:
            raise ValueError("Observation method must be text")
        if not isinstance(observations["states"], dict) or set(observations["states"]) - set(spec["states"]):
            raise ValueError("Observations contain unknown states")
        for name, entry in observations["states"].items():
            _fields(entry, "state observations", {"source_sha256", "frames", "review"}, ("source_sha256", "frames", "review"))
            if name not in manifest["states"] or entry["source_sha256"] != manifest["states"][name]["sha256"]:
                raise ValueError(f"Stale artwork observations: {name}; observe the new raw image")
            if not isinstance(entry["frames"], list) or len(entry["frames"]) != len(spec["states"][name]["poses"]):
                raise ValueError("Observation frame count differs from the frozen state")
    snapshots = {path: project.sha256(path) for path in inputs}
    project.require_empty_output(out, inputs)
    out.mkdir(parents=True, exist_ok=True)
    issues, states = [], {}
    reference_pixels = np.array(qa.open_rgba(run / "reference-native.png"))
    _coordinate_frame(reference_pixels).save(out / "reference-coordinates.png")
    ref = _observe_frame(observations["reference"] if observations else None, reference_pixels, spec, issues, {"reference": True})
    if observations is None or not observations["method"].strip():
        issues.append(sprite._issue("OBSERVATION_METHOD_MISSING", "review", "Record how actual artwork was independently observed."))
    reference_area = int(np.sum(reference_pixels[:, :, 3] > 0))
    fw, fh = sprite._size(spec["frame_size"], "frame_size")
    for name, state in spec["states"].items():
        if name not in manifest["states"]:
            issues.append(sprite._issue("STATE_NOT_GENERATED", "review", "No raw image has been imported for this state.", state=name))
            continue
        root = out / name
        root.mkdir()
        n, columns = len(state["poses"]), state["columns"]
        rows = math.ceil(n / columns)
        raw = qa.open_rgba(run / "raw" / f"{name}.png")
        try:
            original, derivation = _logical(raw, (fw * columns, fh * rows), spec["derivation"], enforce_strict=False)
        except ValueError as error:
            issues.append(sprite._issue("SOURCE_LAYOUT_INVALID", "fail", str(error), state=name))
            states[name] = {"status": "fail", "source_sha256": manifest["states"][name]["sha256"]}
            continue
        if spec["derivation"]["mode"] == "strict" and derivation["original_grid_status"] == "fail":
            issues.append(sprite._issue("SOURCE_GRID_INVALID", "fail", "Raw cells or alpha violate the strict input contract.", state=name))
        mapped, errors = _nearest(original, contract["palette"])
        native = mapped if spec["derivation"]["mode"] == "project" else original
        native_image = Image.fromarray(native)
        native_image.save(root / "native.png")
        native_image.resize((fw * columns * spec["scale"], fh * rows * spec["scale"]), Image.Resampling.NEAREST).save(root / "rendered.png")
        sprite_spec = {"schema_version": 1, "name": spec["name"], "frame_size": spec["frame_size"], "frame_count": n,
            "layout": {"columns": columns, "rows": rows}, "edge_margin": spec["limits"]["edge_margin"], "scale": spec["scale"],
            "animations": {name: {"frames": list(range(n)), "loop": state["loop"], "durations_ms": state["durations_ms"]}}}
        profile = {"schema_version": 1, "name": spec["name"], "logical_size": f"{fw * columns}x{fh * rows}", "scale": spec["scale"],
            "max_colors": spec["max_colors"], "alpha": "binary", "transparent_rgb": "exact",
            "allowed_palette": ["#00000000"] + [sprite._hex(tuple(color)) for color in contract["palette"]]}
        sprite._write_new(root / "sprite-spec.json", json_bytes(sprite_spec))
        sprite._write_new(root / "profile.json", json_bytes(profile))
        pixel_report = sprite.check_sheet(root / "sprite-spec.json", root / "rendered.png", root / "profile.json", root / "pixel-audit", scale=preview_scale)
        for issue in pixel_report["issues"]:
            issues.append({**issue, "state": name})
        if pixel_report["sheet_audit"]["status"] != "pass":
            issues.append(sprite._issue("OUTPUT_PIXEL_CONTRACT_FAILED", "fail", "Exported pixels violate the frozen profile.", state=name))
        plan = sprite.parse_spec(sprite_spec)
        artwork, frame_records, _, _ = sprite._check_frames(native, plan.layout)
        entry = observations["states"].get(name) if observations else None
        observed, records = [], []
        for index, frame in enumerate(artwork):
            context = {"state": name, "frame": index}
            (root / "frames").mkdir(exist_ok=True)
            Image.fromarray(frame).save(root / "frames" / f"{index:03}.native.png")
            _coordinate_frame(frame).save(root / "frames" / f"{index:03}.coordinates.png")
            observation = _observe_frame(entry["frames"][index] if entry else None, frame, spec, issues, context)
            observed.append(observation)
            values = _compare_parts(ref, observation, reference_pixels, frame, spec, issues, context)
            x, y = plan.layout.origin(index)
            original_frame = original[y:y + fh, x:x + fw]
            visible = original_frame[:, :, 3] > 0
            bad_color_fraction = float(np.mean(errors[y:y + fh, x:x + fw][visible] > spec["limits"]["color_distance"])) if np.any(visible) else 0
            area_ratio = float(np.sum(visible) / reference_area)
            if bad_color_fraction > spec["limits"]["max_bad_color_fraction"]:
                issues.append(sprite._issue("SOURCE_COLORS_CHANGED", "fail", "Pre-remap source colors differ from the shared selected palette.",
                                            bad_color_fraction=bad_color_fraction, **context))
            if not spec["limits"]["area_ratio"][0] <= area_ratio <= spec["limits"]["area_ratio"][1]:
                issues.append(sprite._issue("FRAME_SCALE_CHANGED", "fail", "Visible frame area differs from the fixed design scale.", area_ratio=area_ratio, **context))
            records.append({"frame": index, "area_ratio": area_ratio, "bad_color_fraction": bad_color_fraction, "parts": values})
        motion = _motion_checks(name, state, observed, issues)
        review = _review(entry["review"] if entry else None, issues, name)
        overlay = _observation_overlay(artwork, observed, plan.layout, preview_scale, spec["parts"])
        overlay.save(root / "observation-overlay.png")
        states[name] = {"source_sha256": manifest["states"][name]["sha256"], "derivation": derivation,
                        "pixel_status": pixel_report["status"], "frames": records, "motion": motion, "art_review": review,
                        "outputs": {"native": f"{name}/native.png", "rendered": f"{name}/rendered.png",
                            "grid": f"{name}/pixel-audit/sheet/grid_overlay.png", "observations": f"{name}/observation-overlay.png",
                            "gif": f"{name}/pixel-audit/animations/{name}.gif"}}
    if any(project.sha256(path) != sha for path, sha in snapshots.items()):
        issues.append(sprite._issue("INPUT_CHANGED", "fail", "An audited input changed during the check."))
    for name, state in states.items():
        state["status"] = sprite._worst([issue for issue in issues if issue.get("state") == name])
    technical = [issue for issue in issues if not issue["code"].startswith("ART_")]
    report = {"schema_version": 1, "tool": "Pixelwright 2D sequence", "version": VERSION,
        "status": sprite._worst(issues), "technical_status": sprite._worst(technical), "skeleton_required": False,
        "scope": "frozen_2d_contract_and_independently_supplied_artwork_observations",
        "human_approval_recorded": False, "contract_sha256": manifest["frozen"]["contract.json"],
        "reference_sha256": manifest["frozen"]["reference-native.png"],
        "observations_sha256": snapshots.get(observations_path), "states": states, "issues": issues,
        "issue_counts": {level: sum(issue["severity"] == level for issue in issues) for level in ("fail", "review", "info")},
        "limitations": ["Named part masks and features are supplied observations, not automatic semantic recognition.",
            "Part area, rotation-only shape/pattern and color checks do not prove identity or natural movement.",
            "Foreshortening, occlusion, flexible parts and pose-dependent shading require a recorded visual review.",
            "Projection is a declared derivative; a compliant exported PNG does not certify the raw generator's pixel grid."]}
    sprite._write_new(out / "report.json", json_bytes(report))
    sprite._write_new(out / "observations-template.json", json_bytes(observation_template(run)))
    redraw = {name: {"prompt": (run / "prompts" / f"{name}.txt").read_text(encoding="utf-8"),
                    "findings": [issue for issue in issues if issue.get("state") == name and issue["severity"] != "info"],
                    "raw_sha256": manifest["states"][name]["sha256"], "new_observations_required_after_replacement": True}
              for name in states if states[name]["status"] != "pass"}
    sprite._write_new(out / "redraw-requests.json", json_bytes(redraw))
    return report


def run_cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="Freeze a selected 2D design and sequence contract")
    prepare_parser.add_argument("--spec", type=Path, required=True)
    prepare_parser.add_argument("--reference", type=Path, required=True)
    prepare_parser.add_argument("--out-dir", type=Path, required=True)
    for command in ("import", "generate", "observations", "check"):
        sub = commands.add_parser(command)
        sub.add_argument("--run", type=Path, required=True)
        if command in ("import", "generate"):
            sub.add_argument("--state", required=True)
            sub.add_argument("--replace", action="store_true")
        if command == "import":
            sub.add_argument("--image", type=Path, required=True)
            sub.add_argument("--producer", default="external_host_unverified")
        if command == "generate":
            sub.add_argument("--model", required=True, help="Explicit image model supported by your provider")
            sub.add_argument("--size", default="auto")
            sub.add_argument("--quality", default="high", choices=("auto", "low", "medium", "high"))
            sub.add_argument("--background", choices=("auto", "transparent", "opaque"),
                             help="Optional provider-supported parameter; omitted by default")
            sub.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
            sub.add_argument("--timeout", type=float, default=600)
        if command == "observations":
            sub.add_argument("--out", type=Path, required=True)
        if command == "check":
            sub.add_argument("--observations", type=Path)
            sub.add_argument("--out-dir", type=Path, required=True)
            sub.add_argument("--preview-scale", type=int, default=4)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.spec, args.reference, args.out_dir)
        elif args.command == "import":
            result = import_image(args.run, args.state, args.image, producer=args.producer, replace=args.replace)
        elif args.command == "generate":
            result = generate(args.run, args.state, model=args.model, size=args.size, quality=args.quality,
                              background=args.background, base_url=args.base_url, timeout=args.timeout, replace=args.replace)
        elif args.command == "observations":
            result = observation_template(args.run)
            sprite._write_new(args.out, json_bytes(result))
            result = {"status": "template_only_not_observed", "path": str(args.out)}
        else:
            result = check(args.run, args.out_dir, args.observations, preview_scale=args.preview_scale)
        summary = {key: value for key, value in result.items() if key in
                   ("status", "technical_status", "contract_sha256", "sha256", "states", "run", "path", "issue_counts")}
        if args.command == "check":
            summary["states"] = {name: {key: state[key] for key in ("status", "pixel_status") if key in state}
                                 for name, state in result["states"].items()}
            summary["report"] = str(args.out_dir.resolve() / "report.json")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2 if result.get("status") in ("fail", "review") else 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, Image.DecompressionBombError) as error:
        print(f"Sequence error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
