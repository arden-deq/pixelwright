#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Design a 2D character first, then retarget a bare 3D skeleton to that design.

Image generation is external (prompts.json). No armor, volume render, mesh mask
or 3D material is ever an identity input or an artwork acceptance target.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import knight_rig_3d as rig
import knight_sheet_3d as sheets

SIZE = (128, 128)
REQUIRED_JOINTS = {joint for pair in rig.BONES.values() for joint in pair}
REVIEW_JOINTS = ("neck", "pelvis", "hand_r", "mace_head", "ankle_r", "ankle_l", "shield_top")


def initialize(out, prompt, reference=None):
    sheets.fresh(out)
    for name in ("raw", "references", "guides"):
        (out / name).mkdir()
    images = []
    if reference:
        with Image.open(reference) as image:
            image.convert("RGBA").save(out / "references" / "input.png")
        images.append("references/input.png")
    brief = {"schema_version": 1, "workflow": "2d-design-first", "prompt": prompt,
             "frame_size": list(SIZE), "scale": 4, "palette_budget": 24,
             "registration": {"full_character_height": 88, "floor_y": 112, "center_x": 64},
             "identity_inputs": images, "stage": "design"}
    text = ("Create one finished original hand-pixeled 2D game character design. " + prompt +
            " This is the first identity stage; no 3D model is supplied or to be imitated. "
            "One full character, relaxed ready stance, three-quarter view slightly facing screen left. "
            "128x128 logical canvas enlarged to 1024x1024. Full character about 88 logical pixels high, "
            "soles at y=112, center x=64, generous empty margins. Coherent pixel clusters, clean dark "
            "stepped outlines, simple material ramps, at most 24 opaque colors, no tiny texture noise, "
            "antialiasing or smooth gradients. Plain exact #FF00FF background, no floor, shadow, text or grid.")
    sheets.write_json(out / "design-brief.json", brief)
    sheets.write_json(out / "prompts.json", {"design": {"images": images, "size": "1024x1024",
                      "background": "opaque", "output": "raw/design.png", "prompt": text}})
    sheets.write_json(out / "poses.json", {"canvas": [1024, 1024]})
    return {"status": "design_pending", "run_dir": str(out.resolve())}


def select_design(run, source):
    """Register the chosen 2D design once against its own canvas, before a rig exists."""
    if (run / "identity.json").exists() or (run / "contract.json").exists():
        raise ValueError("Identity is already selected; use a new run to change the character")
    brief = json.loads((run / "design-brief.json").read_text())
    raw = run / "raw" / "design.png"
    if raw.resolve() != source.resolve():
        if raw.exists():
            raise ValueError("Preserve raw/design.png; select it or use a new run")
        shutil.copy2(source, raw)
    with Image.open(raw) as image:
        colors, mask = sheets.snap_cells(image, SIZE)
        source_size = list(image.size)
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[:, :, :3] = colors; rgba[:, :, 3] = mask * 255; rgba[~mask] = 0
    native = Image.fromarray(rgba)
    box = native.getbbox()
    if box is None:
        raise ValueError("The 2D design has no visible pixels")
    registration = brief["registration"]
    ratio = registration["full_character_height"] / (box[3] - box[1])
    width = round((box[2] - box[0]) * ratio)
    if width > SIZE[0] - 4:
        raise ValueError("The design is too wide for the declared registration")
    crop = native.crop(box).resize((width, registration["full_character_height"]), Image.Resampling.NEAREST)
    pixels = np.asarray(crop); visible = pixels[:, :, 3] > 0
    strip = Image.fromarray(pixels[:, :, :3][visible][None])
    indexed = strip.quantize(colors=brief["palette_budget"], method=Image.Quantize.MEDIANCUT,
                             dither=Image.Dither.NONE)
    rgb = crop.convert("RGB").quantize(palette=indexed, dither=Image.Dither.NONE).convert("RGBA")
    rgb.putalpha(crop.getchannel("A"))
    origin = (registration["center_x"] - width // 2,
              registration["floor_y"] - registration["full_character_height"])
    native = Image.new("RGBA", SIZE); native.alpha_composite(rgb, origin)
    pixels = np.asarray(native).copy(); pixels[pixels[:, :, 3] == 0] = 0
    native = Image.fromarray(pixels)
    native.save(run / "references" / "design-native.png")
    native.resize((1024, 1024), Image.Resampling.NEAREST).save(run / "references" / "design.png")
    palette = sorted({tuple(c) for c in pixels[:, :, :3][pixels[:, :, 3] > 0]})
    sheets.write_json(run / "references" / "palette.json", {"colors": ["#%02X%02X%02X" % c for c in palette]})
    record = {"workflow": "2d-design-first", "source_sha256": sheets.digest(raw),
              "brief_sha256": sheets.digest(run / "design-brief.json"),
              "native_sha256": sheets.digest(run / "references" / "design-native.png"),
              "reference_sha256": sheets.digest(run / "references" / "design.png"),
              "palette_sha256": sheets.digest(run / "references" / "palette.json"),
              "source_size": source_size, "source_box": box, "uniform_design_scale": ratio,
              "origin": origin, "identity_authority": "selected_2d_design",
              "rig_used_for_design": False, "artistic_status": "not_reviewed",
              "disclosure": "Lossy global grid projection and one uniform design registration; original preserved. No mesh fitting."}
    sheets.write_json(run / "identity.json", record)
    return {"status": "selected_not_human_approved", "identity": str(run / "references" / "design.png")}


def rotation_between(start, end):
    """Shortest proper rotation; length is never part of the transform."""
    a, b = rig.unit(start), rig.unit(end)
    v = np.cross(a, b); c = float(np.clip(np.dot(a, b), -1, 1))
    if c < -1 + 1e-9:
        axis = rig.unit(np.cross(a, np.eye(3)[int(np.argmin(np.abs(a)))]))
        return 2 * np.outer(axis, axis) - np.eye(3)
    skew = np.array(((0, -v[2], v[1]), (v[2], 0, -v[0]), (-v[1], v[0], 0)))
    return np.eye(3) + skew + skew @ skew / (1 + c)


def bone_basis(vector):
    along = rig.unit(vector)
    front = np.array((0., -1., 0.))
    front -= along * np.dot(front, along)
    if np.linalg.norm(front) < 1e-7:
        front = np.array((0., 0., 1.)) - along * along[2]
    across = rig.unit(np.cross(along, rig.unit(front)))
    return np.stack((across, along, np.cross(across, along)), axis=1)


def retarget(landmarks):
    """Lift manually identified 2D joints to 3D, then transfer rotations, not meshes.

    Authored depth offsets disambiguate overlapping limbs. Bone lengths come
    from the selected design; the library rig supplies only motion rotations.
    """
    if set(landmarks["joints"]) != REQUIRED_JOINTS:
        raise ValueError("Design landmarks must name every skeleton joint exactly once")
    dimensions = landmarks.get("part_dimensions", {})
    if not dimensions:
        raise ValueError("Measure at least one stable part on the selected 2D design")
    for value in dimensions.values():
        a = np.asarray(value, dtype=float)
        if a.ndim != 1 or not 1 <= a.size <= 2 or not np.isfinite(a).all() or np.any(a <= 0):
            raise ValueError("Design part dimensions must be one or two finite positive measurements")
    camera = copy.deepcopy(landmarks.get("camera", rig.CAMERA))
    right, up, forward = rig.camera_basis(camera)
    unit = camera["ortho_scale"] / SIZE[1]
    rest = {}
    for name, point in landmarks["joints"].items():
        x, y = point["xy"]
        depth = point["depth_offset_m"]
        if not np.isfinite((x, y, depth)).all() or not (0 <= x < SIZE[0] and 0 <= y < SIZE[1]):
            raise ValueError("Design landmark coordinates must be finite and inside the canvas")
        rest[name] = (np.asarray(camera["target"]) + right * (x - SIZE[0] / 2) * unit
                      - up * (y - SIZE[1] / 2) * unit + forward * depth)
    data = rig.contract()
    data.update({"kind": "pixelwright-design-first-skeleton", "camera": camera,
                 "identity_authority": "selected_2d_design", "appearance_meshes": False,
                 "design": {"source": "manually_annotated_2d_design", "landmarks": landmarks},
                 "acceptance": {"world_length_tolerance_m": 1e-6,
                                "artwork_joint_error_max_cells": 5.0,
                                "part_dimension_relative_error_max": .15,
                                "artistic_review": "required"}})
    data["bone_lengths_m"] = {name: float(np.linalg.norm(rest[b] - rest[a])) for name, (a, b) in rig.BONES.items()}
    if min(data["bone_lengths_m"].values()) < .01:
        raise ValueError("Design landmarks contain a zero or implausibly short bone")
    old_rest = rig.pose()
    motion_settings = {"leg_trajectory_gain": .85, "walk_crouch_m": .07, "attack_brace_m": .04,
                       **landmarks.get("motion", {})}
    if any(not np.isfinite(v) or v < 0 for v in motion_settings.values()):
        raise ValueError("Motion settings must be finite and nonnegative")
    data["motion_settings"] = motion_settings
    for state, animation in data["animations"].items():
        for index, frame in enumerate(animation["frames"]):
            motion = rig.pose(state, index)
            joints = {"pelvis": rest["pelvis"] + motion["pelvis"] - old_rest["pelvis"]}
            joints["pelvis"][2] -= motion_settings["walk_crouch_m"] if state == "walk" else (
                motion_settings["attack_brace_m"] if state == "attack" else 0)
            for name in ("torso", "head", "clavicle_r", "clavicle_l", "hip_r", "hip_l"):
                a, b = rig.BONES[name]
                rotation = rotation_between(old_rest[b] - old_rest[a], motion[b] - motion[a])
                joints[b] = joints[a] + rotation @ (rest[b] - rest[a])
            # The design has its own rest angles. Copying library limb rotations
            # directly can leave an "overhead" wrist below the crown. Transfer
            # wrist/ankle trajectories and solve fixed-length 3D chains instead.
            for side in ("r", "l"):
                for start, middle, end in ((f"shoulder_{side}", f"elbow_{side}", f"hand_{side}"),
                                           (f"hip_{side}", f"knee_{side}", f"ankle_{side}")):
                    hint = rest[middle] + motion[middle] - old_rest[middle]
                    upper = float(np.linalg.norm(rest[middle] - rest[start]))
                    lower = float(np.linalg.norm(rest[end] - rest[middle]))
                    if end.startswith("ankle"):
                        target = rest[end] + (motion[end] - old_rest[end]) * motion_settings["leg_trajectory_gain"]
                    else:
                        # Match the design's ready direction, then transfer the
                        # whole-arm direction and fractional extension. This
                        # keeps overhead controls overhead without extending a
                        # differently proportioned forearm to reach old metres.
                        old_vector = old_rest[end] - old_rest[start]
                        current = motion[end] - motion[start]
                        old_length = float(np.linalg.norm(old_vector))
                        old_reach = (np.linalg.norm(old_rest[middle] - old_rest[start])
                                     + np.linalg.norm(old_rest[end] - old_rest[middle]))
                        new_length = float(np.linalg.norm(rest[end] - rest[start]))
                        current_length = float(np.linalg.norm(current))
                        if current_length >= old_length:
                            gain = (current_length - old_length) / (old_reach - old_length)
                            distance = new_length + gain * (upper + lower - new_length)
                        else:
                            distance = new_length * current_length / old_length
                        direction = rotation_between(old_vector, rest[end] - rest[start]) @ rig.unit(current)
                        target = joints[start] + direction * distance
                    try:
                        joints[middle] = rig.two_bone(joints[start], target, upper, lower, hint)
                    except ValueError as error:
                        raise ValueError(f"{state}/{index} {start}->{end}: {error}") from error
                    joints[end] = target
            for name in ("mace", "shield", "foot_r", "foot_l"):
                a, b = rig.BONES[name]
                rotation = bone_basis(motion[b] - motion[a]) @ bone_basis(old_rest[b] - old_rest[a]).T
                joints[b] = joints[a] + rotation @ (rest[b] - rest[a])
            names = list(joints); xy, depth = rig.project([joints[n] for n in names], camera, SIZE)
            frame["joints_world"] = {n: joints[n].tolist() for n in names}
            frame["joints_image"] = {n: p.tolist() for n, p in zip(names, xy)}
            frame["joint_depth_m"] = {n: float(d) for n, d in zip(names, depth)}
    data["animations"]["attack"]["frames"][2]["description"] = "wind up with the mace high behind and above the head"
    data["animations"]["attack"]["frames"][3]["description"] = "foreshortened forward swing in the same three-quarter camera; do not turn into a side view"
    check = rig.validate_contract(data)
    if check["status"] != "pass":
        raise ValueError(check)
    return data


def bare_guide(frame, contract, scale=4):
    """Project only colored bone lines, joints and depth; never armor silhouettes."""
    image = Image.new("RGB", (SIZE[0] * scale, SIZE[1] * scale), sheets.BACKGROUND[:3])
    draw = ImageDraw.Draw(image)
    depth = frame["joint_depth_m"]
    order = sorted(contract["bones"].items(), key=lambda item: sum(depth[n] for n in item[1]), reverse=True)
    for name, (a, b) in order:
        color = (105, 190, 255) if name.endswith("_r") or name == "mace" else (
            (255, 120, 135) if name.endswith("_l") or name == "shield" else (245, 210, 95))
        points = [tuple(v * scale for v in frame["joints_image"][n]) for n in (a, b)]
        draw.line(points, fill=color, width=max(1, scale))
        for x, y in points:
            draw.ellipse((x - scale, y - scale, x + scale, y + scale), fill=color)
    return image


def verify_identity(run):
    identity = json.loads((run / "identity.json").read_text())
    checks = {"design-brief.json": identity["brief_sha256"], "raw/design.png": identity["source_sha256"],
              "references/design.png": identity["reference_sha256"],
              "references/design-native.png": identity["native_sha256"],
              "references/palette.json": identity["palette_sha256"]}
    for relative, expected in checks.items():
        if sheets.digest(run / relative) != expected:
            raise ValueError(f"Frozen 2D identity changed: {relative}")
    return identity


def prepare_poses(run, landmark_path):
    if (run / "contract.json").exists():
        raise ValueError("Poses are already frozen; use a new run to change them")
    identity = verify_identity(run)
    landmarks = json.loads(landmark_path.read_text())
    if landmarks.get("design_sha256") != identity["native_sha256"]:
        raise ValueError("Landmarks must identify the exact selected 2D design")
    data = retarget(landmarks)
    data["design_sha256"] = identity["native_sha256"]
    sheets.write_json(run / "design-landmarks.json", landmarks)
    # Repeat the selected 2D identity at the final sheet's actual scale. This
    # prevents a square portrait reference from encouraging fresh per-slot zoom.
    # It is an input layout, never a fit or warp of generated motion frames.
    anchor = Image.open(run / "references" / "design-native.png").convert("RGBA")
    identity_sheet = Image.new("RGBA", (384, 256), (255, 0, 255, 255))
    for index in range(6):
        identity_sheet.alpha_composite(anchor, (index % 3 * 128, index // 3 * 128))
    identity_sheet.convert("RGB").resize((1536, 1024), Image.Resampling.NEAREST).save(run / "references" / "design-sheet.png")
    prompts = json.loads((run / "prompts.json").read_text())
    for state, animation in data["animations"].items():
        sheet = Image.new("RGB", (1536, 1024), sheets.BACKGROUND[:3])
        previews = []
        for index, frame in enumerate(animation["frames"]):
            image = bare_guide(frame, data)
            sheet.paste(image, (index % 3 * 512, index // 3 * 512))
            previews.append(image.resize(SIZE, Image.Resampling.NEAREST))
        sheet.save(run / "guides" / f"{state}-skeleton.png")
        previews[0].save(run / "guides" / f"{state}-skeleton.gif", save_all=True, append_images=previews[1:],
                         duration=[f["duration_ms"] for f in animation["frames"]], loop=0)
        descriptions = "; ".join(f"{f['index'] + 1}: {f['description']}" for f in animation["frames"])
        coordinates = [{n: [round(v, 1) for v in frame["joints_image"][n]]
                        for n in ("crown", *REVIEW_JOINTS)} for frame in animation["frames"]]
        prompts[state] = {"images": ["references/design-sheet.png", f"guides/{state}-skeleton.png"],
                         "output": f"raw/{state}.png", "size": "1536x1024", "background": "opaque",
                         "prompt": (
            "Animate the six repeated 2D character sprites in image 1 into a NEW hand-pixeled animation sheet. "
            "Image 1 is the sole CHARACTER DESIGN authority, already at the exact final slot scale and position. "
            "Preserve its tall body proportions, head dimensions and placement, helmet shape and red plume, "
            "armor curves, red tabard, gold emblem, palette, shield shape and emblem, leather boots and mace. "
            "Image 2 contains ONLY projected 3D BONES: use joint positions, camera and depth ordering as "
            "motion guidance. It contains no character appearance, costume, material or silhouette to copy. "
            "Blue limbs are the mace arm/right leg, pink limbs the shield arm/left leg; yellow is the torso/head. "
            "Redraw image 1 as appealing original 2D animation in those poses. Cloth and plume move naturally; "
            "preserve consistent head/body/equipment dimensions and the same shared pixel grid. "
            "Keep the anchor's small head and long torso/legs; do not redesign it with a bigger head or shorter body. "
            f"State {state}, six poses in row-major order: {descriptions}. "
            "Exact 1536x1024 canvas: 3 columns x 2 rows, every slot 512x512, representing 128x128 logical "
            "pixels enlarged 4x. Keep each figure at its guide joint positions and scale, with all empty "
            "margins intact. No per-frame zoom, recentering, fitting or cropping. Each drawn dot is a "
            "consistent 4x4 square, clean one-native-pixel outlines, coherent 2D shading clusters, at most "
            "24 shared colors. No 3D/voxel/low-poly look, gradients, antialiasing, texture noise or tiny detail. "
            "Solid exact #FF00FF in every empty region. No guide dots/lines, slot borders, floor, shadows, "
            "text, labels, effects or extra figures. The result is six readable 2D sprites, not a drawing of a skeleton. "
            f"Measured design part dimensions in native pixels: {json.dumps(landmarks['part_dimensions'])}. "
            "Match these dimensions from image 1; do not enlarge the helmet or weapon to add detail. "
            f"Per-slot joint targets in logical (x,y) pixels, ordered 1-6: {json.dumps(coordinates, separators=(',', ':'))}.")}
    sheets.write_json(run / "contract.json", data)
    sheets.write_json(run / "prompts.json", prompts)
    sheets.write_json(run / "run.json", {
        "workflow": "2d-design-first", "name": "2D knight design animated with a bare 3D skeleton",
        "contract_sha256": sheets.digest(run / "contract.json"),
        "identity_sha256": sheets.digest(run / "identity.json"),
        "pixel_palette_size": 24, "frame_scale": 4,
        "audit_scope": "exact_pixel_grid_and_independently_annotated_2d_artwork_not_mesh_silhouette",
        "limitations": ["Artwork joints and part dimensions require independent manual annotations.",
                        "A valid 3D skeleton does not certify that the generated artwork follows it.",
                        "Cloth, contour quality, identity and occlusion require a separate artistic review."],
        "guide_sha256": {str(p.relative_to(run)): sheets.digest(p) for p in
                         [*sorted((run / "guides").glob("*.png")), run / "references" / "design-sheet.png"]}})
    return {"status": "poses_frozen", "rig_check": rig.validate_contract(data), "jobs": list(data["animations"])}


def load_run(run):
    settings = json.loads((run / "run.json").read_text())
    identity = verify_identity(run)
    checks = {"contract.json": settings["contract_sha256"], "identity.json": settings["identity_sha256"],
              "design-brief.json": identity["brief_sha256"], "raw/design.png": identity["source_sha256"],
              "references/design.png": identity["reference_sha256"],
              "references/design-native.png": identity["native_sha256"],
              "references/palette.json": identity["palette_sha256"], **settings["guide_sha256"]}
    for relative, expected in checks.items():
        if sheets.digest(run / relative) != expected:
            raise ValueError(f"Frozen design/pose input changed: {relative}")
    data = json.loads((run / "contract.json").read_text())
    sheets.validate_layout(data)
    if rig.validate_contract(data)["status"] != "pass":
        raise ValueError("Retargeted skeleton failed world/projection checks")
    return settings, data, run


def check_artwork(frame, contract, annotation, pixels=None):
    """Compare independent observations; never invent part labels from guide bones."""
    if annotation is None:
        return {"status": "review", "issues": [{"code": "ARTWORK_ANNOTATIONS_REQUIRED", "severity": "review"}],
                "scope": "unverified_artwork_pose_not_inferred_from_valid_rig"}
    issues, errors, dimensions = [], {}, {}
    for name in REVIEW_JOINTS:
        value = annotation.get("joints", {}).get(name)
        if value is None or np.asarray(value).shape != (2,) or not np.isfinite(value).all():
            issues.append({"code": "MISSING_ARTWORK_JOINT", "severity": "review", "joint": name})
            continue
        error = float(np.linalg.norm(np.asarray(value) - frame["joints_image"][name]))
        errors[name] = error
        if pixels is not None:
            x, y = np.rint(value).astype(int)
            mask = pixels[:, :, 3] > 0
            if not (0 <= x < mask.shape[1] and 0 <= y < mask.shape[0]) or not sheets.dilate(mask, 2)[y, x]:
                issues.append({"code": "ARTWORK_JOINT_OUTSIDE_DRAWING", "severity": "fail", "joint": name})
        if error > contract["acceptance"]["artwork_joint_error_max_cells"]:
            issues.append({"code": "ARTWORK_POSE_DRIFT", "severity": "fail", "joint": name, "error_cells": error})
    for name, reference in contract["design"]["landmarks"]["part_dimensions"].items():
        observed = annotation.get("part_dimensions", {}).get(name)
        if observed is None:
            issues.append({"code": "MISSING_ARTWORK_DIMENSION", "severity": "review", "part": name})
            continue
        a, b = np.asarray(observed, dtype=float), np.asarray(reference, dtype=float)
        if a.shape != b.shape or not np.isfinite(a).all() or np.any(a <= 0):
            raise ValueError("Observed part dimensions must be finite positive measurements")
        error = float(np.max(np.abs(a / b - 1)))
        dimensions[name] = {"observed": observed, "reference": reference, "relative_error": error}
        if error > contract["acceptance"]["part_dimension_relative_error_max"]:
            issues.append({"code": "ARTWORK_PART_SIZE_CHANGED", "severity": "fail", "part": name, "relative_error": error})
    status = "fail" if any(i["severity"] == "fail" for i in issues) else "review" if issues else "pass"
    return {"status": status, "joint_error_cells": errors, "part_dimensions": dimensions, "issues": issues,
            "scope": "manual_artwork_landmarks_and_dimensions_not_automatic_semantic_segmentation"}


def export(run, out, annotations=None):
    _, contract, _ = load_run(run)
    observed = None
    if annotations:
        observed = json.loads(annotations.read_text())
        if observed.get("contract_sha256") != sheets.digest(run / "contract.json"):
            raise ValueError("Artwork annotations belong to a different pose contract")
        for state in contract["animations"]:
            if observed["source_sha256"].get(state) != sheets.digest(run / "raw" / f"{state}.png"):
                raise ValueError(f"Artwork annotations are stale: {state}")
        if not observed.get("method") or not observed.get("reviewer"):
            raise ValueError("Identify how and by whom artwork annotations were made")
    def inspect(state, index, pixels, frame, data):
        records = observed["animations"].get(state, []) if observed else []
        annotation = records[index] if index < len(records) else None
        return check_artwork(frame, data, annotation, pixels)
    result = sheets.process(run, out, run / "references" / "palette.json", loader=load_run, frame_inspector=inspect)
    if annotations:
        shutil.copy2(annotations, out / "artwork-annotations.json")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init"); init.add_argument("--out-dir", type=Path, required=True)
    init.add_argument("--prompt", required=True); init.add_argument("--reference", type=Path)
    select = commands.add_parser("select"); select.add_argument("--run-dir", type=Path, required=True)
    select.add_argument("--source", type=Path, required=True)
    poses = commands.add_parser("poses"); poses.add_argument("--run-dir", type=Path, required=True)
    poses.add_argument("--landmarks", type=Path, required=True)
    check = commands.add_parser("check"); check.add_argument("--run-dir", type=Path, required=True)
    check.add_argument("--out-dir", type=Path, required=True); check.add_argument("--annotations", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "init": result = initialize(args.out_dir, args.prompt, args.reference)
        elif args.command == "select": result = select_design(args.run_dir, args.source)
        elif args.command == "poses": result = prepare_poses(args.run_dir, args.landmarks)
        else: result = export(args.run_dir, args.out_dir, args.annotations)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(str(error), file=sys.stderr); return 1
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["status"] in ("fail", "review") else 0


if __name__ == "__main__":
    raise SystemExit(main())
