#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A metric 3D knight rig and one camera shared by all animation states.

This module deliberately has no Blender dependency. The Blender renderer consumes
these world-space joints; the image generator consumes their rendered projections.
Projected limbs may foreshorten. Their world lengths must never change.
"""
from __future__ import annotations

import math
from numbers import Real

import numpy as np

FRAME_SIZE = (128, 128)
GUIDE_SCALE = 4
SHEET_COLUMNS = 3
CAMERA = {"type": "orthographic", "position": [3.6, -7.5, 3.1],
          "target": [0.0, 0.0, 1.25], "up": [0.0, 0.0, 1.0],
          "ortho_scale": 3.35, "clip_start": 0.1, "clip_end": 30.0}
DESIGN = {"height_m": 1.96, "upper_arm_m": 0.32, "forearm_m": 0.30,
          "thigh_m": 0.44, "shin_m": 0.43, "foot_m": 0.20,
          "mace_m": 0.47, "shield_width_m": 0.46, "shield_height_m": 0.72}
BONES = {
    "torso": ("pelvis", "neck"), "head": ("neck", "crown"),
    "clavicle_r": ("neck", "shoulder_r"), "clavicle_l": ("neck", "shoulder_l"),
    "upper_arm_r": ("shoulder_r", "elbow_r"), "forearm_r": ("elbow_r", "hand_r"),
    "mace": ("hand_r", "mace_head"),
    "upper_arm_l": ("shoulder_l", "elbow_l"), "forearm_l": ("elbow_l", "hand_l"),
    "shield": ("hand_l", "shield_top"),
    "hip_r": ("pelvis", "hip_r"), "hip_l": ("pelvis", "hip_l"),
    "thigh_r": ("hip_r", "knee_r"), "shin_r": ("knee_r", "ankle_r"),
    "foot_r": ("ankle_r", "toe_r"),
    "thigh_l": ("hip_l", "knee_l"), "shin_l": ("knee_l", "ankle_l"),
    "foot_l": ("ankle_l", "toe_l"),
}
PARENTS = {"head": "torso", "clavicle_r": "torso", "clavicle_l": "torso",
           "upper_arm_r": "clavicle_r", "forearm_r": "upper_arm_r", "mace": "forearm_r",
           "upper_arm_l": "clavicle_l", "forearm_l": "upper_arm_l", "shield": "forearm_l",
           "hip_r": "torso", "hip_l": "torso", "thigh_r": "hip_r", "thigh_l": "hip_l",
           "shin_r": "thigh_r", "shin_l": "thigh_l", "foot_r": "shin_r", "foot_l": "shin_l"}
DURATIONS = {"walk": [120] * 6, "attack": [180, 110, 150, 70, 140, 170],
             "block": [180, 90, 100, 100, 230, 130]}
DESCRIPTIONS = {
    "walk": ["right foot contact; left foot behind", "weight over right foot; left foot passes",
             "left leg reaching forward", "left foot contact; right foot behind",
             "weight over left foot; right foot passes", "right leg reaching forward"],
    "attack": ["ready stance", "raise mace overhead", "wind up behind head",
               "swing forward through shoulder height", "low impact and crouch", "recover to ready"],
    "block": ["ready stance", "raise the shield", "full guard covering the chest",
              "absorb impact behind shield", "hold full guard", "lower shield toward ready"],
}


def unit(v):
    v = np.asarray(v, dtype=float)
    length = float(np.linalg.norm(v))
    if length < 1e-10:
        raise ValueError("A direction cannot have zero length")
    return v / length


def rotate_z(v, angle):
    x, y, z = v
    c, s = math.cos(angle), math.sin(angle)
    return np.array((c * x - s * y, s * x + c * y, z), dtype=float)


def two_bone(start, end, upper, lower, bend_hint):
    """Solve a 3D two-link chain, rejecting unreachable targets rather than stretching."""
    a, b, hint = (np.asarray(x, dtype=float) for x in (start, end, bend_hint))
    d = float(np.linalg.norm(b - a))
    if d <= abs(upper - lower) + 1e-8 or d >= upper + lower - 1e-8:
        raise ValueError(f"Unreachable IK target: distance {d:.6f}, links {upper}/{lower}")
    axis = unit(b - a)
    across = hint - a - np.dot(hint - a, axis) * axis
    if np.linalg.norm(across) < 1e-8:
        fallback = np.eye(3)[int(np.argmin(np.abs(axis)))]
        across = fallback - np.dot(fallback, axis) * axis
    along = (upper * upper - lower * lower + d * d) / (2 * d)
    height = math.sqrt(max(0.0, upper * upper - along * along))
    return a + axis * along + unit(across) * height


def camera_basis(camera=CAMERA):
    forward = unit(np.asarray(camera["target"]) - camera["position"])
    right = unit(np.cross(forward, camera["up"]))
    up = unit(np.cross(right, forward))
    return right, up, forward


def project(points, camera=CAMERA, size=FRAME_SIZE):
    """Orthographic top-left pixel coordinates and camera-forward metric depth."""
    points = np.asarray(points, dtype=float)
    if points.shape[-1] != 3:
        raise ValueError("Expected world-space xyz points")
    right, up, forward = camera_basis(camera)
    delta = points - camera["target"]
    pixel_per_metre = size[1] / camera["ortho_scale"]
    xy = np.stack((size[0] / 2 + delta @ right * pixel_per_metre,
                   size[1] / 2 - delta @ up * pixel_per_metre), axis=-1)
    depth = (points - camera["position"]) @ forward
    return xy, depth


def pose(state="block", index=0):
    if state not in DURATIONS or not 0 <= index < len(DURATIONS[state]):
        raise ValueError(f"Unknown pose {state}/{index}")
    yaw, crouch, bob = 0.0, 0.0, 0.0
    hand_r = np.array((-.40, -.12, 1.08))
    hand_l = np.array((.43, -.20, 1.27))
    mace_direction = np.array((-.08, -.25, -.965))
    feet = {"r": np.array((-.17, -.08, .10)), "l": np.array((.17, .08, .10))}
    if state == "walk":
        # One same-foot stance through three samples, then a lifted return.
        foot_y = [-.27, -.07, .16, .27, .05, -.17]
        foot_z = [.10, .10, .10, .13, .27, .22]
        for side, shift in (("r", 0), ("l", 3)):
            k = (index + shift) % 6
            feet[side][1:] = (foot_y[k], foot_z[k])
        phase = math.tau * index / 6
        bob = -.014 * (1 + math.sin(2 * phase))
        hand_r += (0, .055 * math.cos(phase), -.015 * math.sin(2 * phase))
        hand_l += (0, -.025 * math.cos(phase), 0)
        mace_direction = (0, -.23 + .07 * math.cos(phase), -.97)
    elif state == "attack":
        hands = [(-.40, -.12, 1.08), (-.31, -.08, 2.08), (-.22, .19, 2.04),
                 (-.40, -.50, 1.65), (-.34, -.30, 1.08), (-.39, -.22, 1.14)]
        directions = [(-.08, -.25, -.965), (0, .10, .995), (0, .85, .53),
                      (-.12, -.99, -.04), (0, -.42, -.91), (-.06, -.32, -.95)]
        hand_r = np.array(hands[index]); mace_direction = directions[index]
        yaw = [0, -.06, -.16, .10, .10, .02][index]
        crouch = [0, .0, .0, .045, .12, .04][index]
        feet["r"][1] = -.15; feet["l"][1] = .15
    elif state == "block":
        hand_l = np.array([(.43, -.20, 1.27), (.28, -.34, 1.44), (.07, -.44, 1.53),
                           (.10, -.37, 1.51), (.07, -.44, 1.53), (.29, -.27, 1.36)][index])
        crouch = [0, .035, .07, .09, .07, .02][index]
        hand_r += (0, -.04 * math.sin(index * math.pi / 5), 0)
    # z-up, front is -Y; arms and hips are offsets of one rigid torso.
    root = np.array((0.0, 0.0, .96 - crouch + bob))
    j = {"pelvis": root}
    offsets = {"neck": (0, 0, .67), "crown": (0, 0, 1.0),
               "shoulder_r": (-.28, 0, .62), "shoulder_l": (.28, 0, .62),
               "hip_r": (-.14, 0, -.025), "hip_l": (.14, 0, -.025)}
    j.update({n: root + rotate_z(v, yaw) for n, v in offsets.items()})
    for side, hand in (("r", hand_r), ("l", hand_l)):
        hand = rotate_z(hand + (0, 0, -crouch + bob), yaw)
        j[f"hand_{side}"] = hand
        hint = rotate_z((-.56 if side == "r" else .55, -.16, 1.35 - crouch + bob), yaw)
        j[f"elbow_{side}"] = two_bone(j[f"shoulder_{side}"], hand,
                                      DESIGN["upper_arm_m"], DESIGN["forearm_m"], hint)
        ankle = feet[side]
        j[f"ankle_{side}"] = ankle
        j[f"knee_{side}"] = two_bone(j[f"hip_{side}"], ankle,
                                     DESIGN["thigh_m"], DESIGN["shin_m"],
                                     (ankle[0], -.45, .52))
        j[f"toe_{side}"] = ankle + np.array((0, -DESIGN["foot_m"], 0))
    j["mace_head"] = j["hand_r"] + rotate_z(unit(mace_direction), yaw) * DESIGN["mace_m"]
    j["shield_top"] = j["hand_l"] + rotate_z((0, 0, DESIGN["shield_height_m"]), yaw)
    return {name: np.asarray(value, dtype=float) for name, value in j.items()}


def contract():
    rest = pose()
    lengths = {n: float(np.linalg.norm(rest[b] - rest[a])) for n, (a, b) in BONES.items()}
    animations = {}
    for state, durations in DURATIONS.items():
        frames = []
        for index, duration in enumerate(durations):
            joints = pose(state, index)
            names = list(joints)
            xy, depth = project([joints[n] for n in names])
            frames.append({"index": index, "duration_ms": duration, "description": DESCRIPTIONS[state][index],
                           "joints_world": {n: joints[n].tolist() for n in names},
                           "joints_image": {n: p.tolist() for n, p in zip(names, xy)},
                           "joint_depth_m": {n: float(d) for n, d in zip(names, depth)}})
        animations[state] = {"loop": state == "walk", "frames": frames}
    return {"schema_version": 1, "kind": "pixelwright-3d-rig", "units": "metres", "up_axis": "Z",
            "frame_size": list(FRAME_SIZE), "guide_scale": GUIDE_SCALE, "sheet_columns": SHEET_COLUMNS,
            "camera": dict(CAMERA), "design": dict(DESIGN), "bones": {n: list(v) for n, v in BONES.items()},
            "bone_lengths_m": lengths, "parents": dict(PARENTS), "animations": animations,
            "acceptance": {"world_length_tolerance_m": 1e-6, "silhouette_iou_min": .60,
                           "silhouette_coverage_min": .85, "silhouette_precision_min": .85,
                           "silhouette_slack_cells": 2, "head_center_error_max_cells": 2.0,
                           "head_area_ratio": [.80, 1.20], "artistic_review": "required"}}


def validate_contract(data):
    """Check world-space invariants and independent projection, not 2D bone lengths."""
    issues, max_error, max_projection_error = [], 0.0, 0.0
    def finite_number(value, *, positive):
        if isinstance(value, bool) or not isinstance(value, Real):
            return False
        try:
            return math.isfinite(value) and (value > 0 if positive else value >= 0)
        except (OverflowError, TypeError, ValueError):
            return False

    acceptance = data.get("acceptance")
    tolerance = acceptance.get("world_length_tolerance_m") if isinstance(acceptance, dict) else None
    if not finite_number(tolerance, positive=False):
        issues.append({"code": "INVALID_WORLD_LENGTH_TOLERANCE", "expected": "finite nonnegative number"})
    references = data.get("bone_lengths_m")
    for name in data["bones"]:
        reference = references.get(name) if isinstance(references, dict) else None
        if not finite_number(reference, positive=True):
            issues.append({"code": "INVALID_BONE_LENGTH_REFERENCE", "bone": name,
                           "expected": "finite positive number"})
    if issues:
        return {"status": "fail", "max_bone_length_error_m": max_error,
                "max_projection_error_cells": max_projection_error, "issues": issues}
    for state, animation in data["animations"].items():
        for frame in animation["frames"]:
            joints = frame["joints_world"]
            if not all(np.isfinite(np.asarray(value, dtype=float)).all() for value in joints.values()):
                issues.append({"code": "NONFINITE_WORLD_JOINT", "state": state, "frame": frame["index"]})
                continue
            for name, (a, b) in data["bones"].items():
                length = float(np.linalg.norm(np.asarray(joints[b]) - joints[a]))
                error = abs(length - data["bone_lengths_m"][name])
                max_error = max(max_error, error)
                if error > tolerance:
                    issues.append({"code": "WORLD_BONE_LENGTH_CHANGED", "state": state,
                                   "frame": frame["index"], "bone": name, "error_m": error})
            for name, world in joints.items():
                xy, _ = project(world, data["camera"], data["frame_size"])
                error = float(np.linalg.norm(xy - frame["joints_image"][name]))
                max_projection_error = max(max_projection_error, error)
                if not math.isfinite(error) or error > 1e-6:
                    issues.append({"code": "PROJECTION_MISMATCH", "state": state,
                                   "frame": frame["index"], "joint": name, "error_cells": error})
    return {"status": "fail" if issues else "pass", "max_bone_length_error_m": max_error,
            "max_projection_error_cells": max_projection_error, "issues": issues}


if __name__ == "__main__":
    import json
    print(json.dumps(validate_contract(contract()), indent=2))
