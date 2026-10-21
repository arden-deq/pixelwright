#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Rig the README knight and write mace swing, shield block and walk specs.

The 8 px knight (128x192 logical cells) is cut into ten parts along its plate
seams. Each part keeps its exact dots: rigid parts move by whole cells, bone
parts turn about their joints using a RotSprite-style resampler that only
copies existing colors. Where a moving part could uncover cells hidden under a
part drawn in front of it, the hidden part is extended under that front part
by repeating its own interior dots; the rest pose therefore stays identical to
the published artwork. The specs carry color rows, part maps and joints and
are accepted only after `pixel_sprite.py check`.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ARTWORK = ROOT / "docs" / "examples" / "knight" / "8px" / "artwork.json"
OUT = ROOT / "docs" / "examples" / "knight-animation"
FRAME = (192, 240)
OFFSET = (48, 40)  # Room for the raised and extended mace.
SPECK = 4  # Rotation can leave tiny islands of dots; smaller pieces are dropped.

# Assignment order matters: earlier polygons win; remaining dots are torso.
POLYGONS = {
    "head": [(52, 0), (82, 0), (82, 26), (79, 31), (56, 31), (52, 26)],
    "shield": [(86, 54), (96, 49), (108, 47), (118, 51), (127, 57), (127, 94), (124, 110), (116, 126),
               (106, 140), (96, 140), (93, 124), (88, 108), (85, 92), (84, 62)],
    "mace": [(0, 101), (31, 101), (31, 142), (0, 142)],
    "forearm": [(14, 71), (44, 71), (37, 102), (37, 110), (14, 110)],
    "upper_arm": [(24, 58), (46, 58), (46, 63), (44, 71), (24, 71)],
    "thigh_r": [(34, 104), (59, 104), (59, 125), (34, 125)],
    "shin_r": [(20, 126), (62, 126), (62, 192), (20, 192)],
    "thigh_l": [(60, 104), (93, 104), (93, 127), (64, 127)],
    "shin_l": [(64, 128), (115, 128), (115, 192), (64, 192)],
}
JOINTS = {"crown": (66, 4), "neck": (67, 32), "pelvis": (64, 104), "shoulder": (42, 47), "elbow": (31, 71), "hand": (28, 97),
          "mace_head": (13, 127), "grip": (108, 83), "hip_r": (47, 104), "knee_r": (45, 125),
          "ankle_r": (44, 163), "hip_l": (72, 104), "knee_l": (81, 127), "ankle_l": (95, 173)}


def unit(vector):
    length = math.hypot(*vector)
    return vector[0] / length, vector[1] / length


def toward(a, b):
    return unit((JOINTS[b][0] - JOINTS[a][0], JOINTS[b][1] - JOINTS[a][1]))


# Back to front. Extensions grow a part under the parts drawn in front of it.
PARTS = [
    # Arm pieces turn far; their hidden extensions stay between their own joints
    # so nothing pokes out past the shoulder or through the fist.
    {"id": "mace", "token": "m", "motion": "bone", "bone": ["hand", "mace_head"], "parent": "forearm",
     "extend": [(toward("mace_head", "hand"), 10)], "span": True},
    {"id": "upper_arm", "token": "u", "motion": "bone", "bone": ["shoulder", "elbow"], "parent": "torso",
     "extend": [(toward("elbow", "shoulder"), 18), (toward("shoulder", "elbow"), 6)], "span": True},
    {"id": "forearm", "token": "f", "motion": "bone", "bone": ["elbow", "hand"], "parent": "upper_arm",
     "extend": [], "span": True},
    {"id": "shin_l", "token": "k", "motion": "bone", "bone": ["knee_l", "ankle_l"], "parent": "thigh_l",
     "extend": [(toward("ankle_l", "knee_l"), 6), ((1, 0), 6)]},
    {"id": "thigh_l", "token": "l", "motion": "bone", "bone": ["hip_l", "knee_l"], "parent": "torso",
     "extend": [((0, -1), 8), ((1, 0), 6)]},
    {"id": "shin_r", "token": "s", "motion": "bone", "bone": ["knee_r", "ankle_r"], "parent": "thigh_r",
     "extend": [((0, -1), 6)]},
    {"id": "thigh_r", "token": "r", "motion": "bone", "bone": ["hip_r", "knee_r"], "parent": "torso",
     "extend": [((0, -1), 8)]},
    {"id": "torso", "token": "b", "motion": "bone", "bone": ["pelvis", "neck"], "extend": []},
    {"id": "head", "token": "h", "motion": "bone", "bone": ["neck", "crown"], "parent": "torso", "extend": []},
    {"id": "shield", "token": "d", "motion": "rigid", "pivot": "grip", "parent": "torso", "extend": []},
]


def load_knight():
    art = json.loads(ARTWORK.read_text(encoding="utf-8"))
    palette = {token: tuple(int(value[i:i + 2], 16) for i in (1, 3, 5, 7)) for token, value in art["palette"].items()}
    rgba = np.array([[palette[token] for token in row] for row in art["rows"]], dtype=np.uint8)
    return art["palette"], palette, rgba


def segment(rgba):
    height, width = rgba.shape[:2]
    opaque = rgba[:, :, 3] > 0
    label = np.full((height, width), "", dtype=object)
    for name, points in POLYGONS.items():
        image = Image.new("L", (width, height), 0)
        ImageDraw.Draw(image).polygon(points, fill=1, outline=1)
        mask = np.asarray(image).astype(bool) & opaque & (label == "")
        label[mask] = name
    label[(label == "") & opaque] = "torso"
    return label


def layers(rgba, label):
    """Return each part's full RGBA layer, including cells hidden under front parts."""
    depth = {part["id"]: z for z, part in enumerate(PARTS)}
    owner_z = np.full(label.shape, -1)
    for name, z in depth.items():
        owner_z[label == name] = z
    height, width = label.shape
    result = {}
    for part in PARTS:
        mask = label == part["id"]
        layer = np.zeros_like(rgba)
        layer[mask] = rgba[mask]
        covered = owner_z > depth[part["id"]]
        if part.get("span"):
            (ax, ay), (bx, by) = JOINTS[part["bone"][0]], JOINTS[part["bone"][1]]
            yy, xx = np.mgrid[0:height, 0:width]
            along = ((xx - ax) * (bx - ax) + (yy - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)
            covered &= (along >= 0) & (along <= 1)
        grown = mask.copy()
        for direction, reach in part["extend"]:
            dx, dy = unit(direction)
            for y, x in np.argwhere(mask):
                # Repeat dots from three cells inside the edge, not the outline itself.
                sx, sy = round(x - 3 * dx), round(y - 3 * dy)
                source = (sy, sx) if 0 <= sx < width and 0 <= sy < height and mask[sy, sx] else (y, x)
                for step in range(1, reach + 1):
                    cx, cy = round(x + step * dx), round(y + step * dy)
                    if not (0 <= cx < width and 0 <= cy < height) or not (mask[cy, cx] or covered[cy, cx]):
                        break
                    if not grown[cy, cx]:
                        grown[cy, cx] = True
                        layer[cy, cx] = rgba[source]
        result[part["id"]] = layer
    return result


def components(mask):
    """8-connected pieces of a mask as lists of (y, x)."""
    seen = np.zeros_like(mask, dtype=bool)
    pieces = []
    height, width = mask.shape
    for y, x in np.argwhere(mask):
        if seen[y, x]:
            continue
        seen[y, x] = True
        stack, piece = [(int(y), int(x))], []
        while stack:
            cy, cx = stack.pop()
            piece.append((cy, cx))
            for ny in range(max(0, cy - 1), min(height, cy + 2)):
                for nx in range(max(0, cx - 1), min(width, cx + 2)):
                    if mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        pieces.append(piece)
    return pieces


def keys_of(rgba):
    return np.ascontiguousarray(rgba).view(np.uint32).reshape(rgba.shape[:2])


def scale2x(image):
    """EPX/Scale2x on packed RGBA keys: enlarges without inventing colors."""
    padded = np.pad(image, 1, mode="edge")
    h, w = image.shape
    up, right, left, down = padded[0:h, 1:w + 1], padded[1:h + 1, 2:w + 2], padded[1:h + 1, 0:w], padded[2:h + 2, 1:w + 1]
    out = np.empty((2 * h, 2 * w), dtype=image.dtype)
    out[0::2, 0::2] = np.where((left == up) & (left != down) & (up != right), up, image)
    out[0::2, 1::2] = np.where((up == right) & (up != left) & (right != down), right, image)
    out[1::2, 0::2] = np.where((down == left) & (down != right) & (left != up), left, image)
    out[1::2, 1::2] = np.where((right == down) & (right != up) & (down != left), down, image)
    return out


class Sampler:
    """Turn a part about a joint and place it in frame coordinates (RotSprite style)."""

    def __init__(self, layer):
        ys, xs = np.nonzero(layer[:, :, 3])
        self.x0, self.y0 = int(xs.min()) - 1, int(ys.min()) - 1
        crop = np.zeros((ys.max() - ys.min() + 3, xs.max() - xs.min() + 3, 4), dtype=np.uint8)
        crop[1:-1, 1:-1] = layer[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        self.exact = crop
        self.pieces = len(components(crop[:, :, 3] > 0))
        big = keys_of(crop)
        for _ in range(3):
            big = scale2x(big)
        self.big = big.view(np.uint8).reshape(big.shape + (4,))

    def render(self, origin, target, degrees):
        """Cells whose source maps through rotation about origin, then onto target."""
        fw, fh = FRAME
        out = np.zeros((fh, fw, 4), dtype=np.uint8)
        h, w = self.exact.shape[:2]
        dx, dy = target[0] - origin[0], target[1] - origin[1]
        if abs(degrees) < 1e-9 and float(dx).is_integer() and float(dy).is_integer():
            x, y = self.x0 + int(dx) + OFFSET[0], self.y0 + int(dy) + OFFSET[1]
            region = self.exact
            out_slice = out[max(0, y):min(fh, y + h), max(0, x):min(fw, x + w)]
            src = region[max(0, -y):max(0, -y) + out_slice.shape[0], max(0, -x):max(0, -x) + out_slice.shape[1]]
            visible = src[:, :, 3] > 0
            out_slice[visible] = src[visible]
            return out
        radians = math.radians(degrees)
        cos, sin = math.cos(radians), math.sin(radians)
        fy, fx = np.mgrid[0:fh, 0:fw]
        # Frame cell centers back to original coordinates, then into the 8x crop.
        px, py = fx - OFFSET[0] - target[0], fy - OFFSET[1] - target[1]
        sx = origin[0] + cos * px + sin * py
        sy = origin[1] - sin * px + cos * py
        bx = np.floor((sx - self.x0 + 0.5) * 8).astype(np.int64)
        by = np.floor((sy - self.y0 + 0.5) * 8).astype(np.int64)
        inside = (bx >= 0) & (bx < w * 8) & (by >= 0) & (by < h * 8)
        out[inside] = self.big[by[inside], bx[inside]]
        for piece in components(out[:, :, 3] > 0):
            if len(piece) < SPECK:
                ys, xs = zip(*piece)
                out[list(ys), list(xs)] = 0
        return out


def angle(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def ahead(origin, degrees, length):
    radians = math.radians(degrees)
    return origin[0] + length * math.cos(radians), origin[1] + length * math.sin(radians)


def knee_for(hip, ankle, thigh, shin, rest_knee, forward):
    """Two-bone IK keeping both lengths; pick the bend nearest the requested side."""
    dx, dy = ankle[0] - hip[0], ankle[1] - hip[1]
    reach = min(math.hypot(dx, dy), thigh + shin - 1e-6)
    a = (thigh ** 2 - shin ** 2 + reach ** 2) / (2 * reach)
    h = math.sqrt(max(thigh ** 2 - a ** 2, 0.0))
    ux, uy = dx / math.hypot(dx, dy), dy / math.hypot(dx, dy)
    base = hip[0] + a * ux, hip[1] + a * uy
    options = [(base[0] - h * uy, base[1] + h * ux), (base[0] + h * uy, base[1] - h * ux)]
    if forward:
        return min(options, key=lambda knee: knee[0])
    return min(options, key=lambda knee: math.hypot(knee[0] - rest_knee[0], knee[1] - rest_knee[1]))


REST = {"upper": angle(JOINTS["shoulder"], JOINTS["elbow"]), "fore": angle(JOINTS["elbow"], JOINTS["hand"]),
        "mace": angle(JOINTS["hand"], JOINTS["mace_head"])}
LENGTH = {"upper": math.dist(JOINTS["shoulder"], JOINTS["elbow"]), "fore": math.dist(JOINTS["elbow"], JOINTS["hand"]),
          "mace": math.dist(JOINTS["hand"], JOINTS["mace_head"]),
          "thigh_r": math.dist(JOINTS["hip_r"], JOINTS["knee_r"]), "shin_r": math.dist(JOINTS["knee_r"], JOINTS["ankle_r"]),
          "thigh_l": math.dist(JOINTS["hip_l"], JOINTS["knee_l"]), "shin_l": math.dist(JOINTS["knee_l"], JOINTS["ankle_l"])}


def pose_joints(pose):
    """Joint positions in original artwork coordinates for one pose."""
    bx, by = pose.get("body", (0, 0))
    sx, sy = pose.get("shield", (0, 0))
    joints = {name: (JOINTS[name][0] + bx, JOINTS[name][1] + by) for name in ("crown", "neck", "pelvis", "shoulder")}
    joints["grip"] = (JOINTS["grip"][0] + bx + sx, JOINTS["grip"][1] + by + sy)
    swing = pose.get("swing", 0)
    upper, fore, mace = pose.get("arm", (REST["upper"] + swing, REST["fore"] + swing, REST["mace"] + swing))
    joints["elbow"] = ahead(joints["shoulder"], upper, LENGTH["upper"])
    joints["hand"] = ahead(joints["elbow"], fore, LENGTH["fore"])
    joints["mace_head"] = ahead(joints["hand"], mace, LENGTH["mace"])
    for side in ("r", "l"):
        hip = JOINTS[f"hip_{side}"]
        lift = pose.get("feet", {}).get(side, (0, 0))
        ankle = (JOINTS[f"ankle_{side}"][0] + lift[0], JOINTS[f"ankle_{side}"][1] + lift[1])
        joints[f"hip_{side}"] = hip
        joints[f"ankle_{side}"] = ankle
        joints[f"knee_{side}"] = (JOINTS[f"knee_{side}"] if lift == (0, 0) else
                                  knee_for(hip, ankle, LENGTH[f"thigh_{side}"], LENGTH[f"shin_{side}"],
                                           JOINTS[f"knee_{side}"], forward=side == "r"))
    return joints


def settle(pose, samplers):
    """Nudge arm angles by up to 3 degrees so turned parts stay in one piece.

    The nudged angles are written back to the pose, so the declared joints
    always describe exactly the drawn dots.
    """
    if "arm" not in pose and not pose.get("swing"):
        return pose
    settled = dict(pose)
    swing = pose.get("swing", 0)
    angles = list(pose.get("arm", (REST["upper"] + swing, REST["fore"] + swing, REST["mace"] + swing)))
    for index, part_id in enumerate(("upper_arm", "forearm", "mace")):
        part = next(item for item in PARTS if item["id"] == part_id)
        start, end = part["bone"]
        best = None
        for nudge in (0, 1, -1, 2, -2, 3, -3):
            trial = list(angles)
            trial[index] += nudge
            joints = pose_joints({**settled, "arm": tuple(trial)})
            turn = angle(joints[start], joints[end]) - angle(JOINTS[start], JOINTS[end])
            image = samplers[part_id].render(JOINTS[start], joints[start], turn)
            pieces = len(components(image[:, :, 3] > 0))
            if best is None or pieces < best[0]:
                best = (pieces, trial)
            if pieces <= samplers[part_id].pieces:
                break
        angles = best[1]
    settled["arm"] = tuple(angles)
    settled.pop("swing", None)
    return settled


def render_pose(pose, samplers):
    joints = pose_joints(pose)
    fw, fh = FRAME
    canvas = np.zeros((fh, fw, 4), dtype=np.uint8)
    owner = np.full((fh, fw), ".", dtype="<U1")
    for part in PARTS:
        if part["motion"] == "rigid":
            pivot = part["pivot"]
            image = samplers[part["id"]].render(JOINTS[pivot], joints[pivot], 0)
        else:
            start, end = part["bone"]
            turn = angle(joints[start], joints[end]) - angle(JOINTS[start], JOINTS[end])
            image = samplers[part["id"]].render(JOINTS[start], joints[start], turn)
        visible = image[:, :, 3] > 0
        canvas[visible] = image[visible]
        owner[visible] = part["token"]
    return canvas, owner, joints


# Degrees are screen angles (y down): 90 points down, 180 left, 270 up.
ANIMATIONS = {
    "swing": {
        "name": "Knight mace swing", "loop": True,
        "durations_ms": [240, 90, 110, 170, 50, 70, 140, 120],
        "poses": [
            {},
            {"body": (1, 0), "arm": (165, 215, 262)},
            {"body": (1, 0), "arm": (240, 278, 315)},
            {"body": (1, 0), "arm": (250, 292, 340)},
            {"body": (0, 0), "arm": (215, 205, 200)},
            {"body": (-1, 1), "arm": (178, 170, 128)},
            {"body": (-1, 1), "arm": (140, 128, 108)},
            {"body": (0, 0), "arm": (125, 108, 112)},
        ],
    },
    "block": {
        "name": "Knight shield block", "loop": True,
        "durations_ms": [240, 70, 70, 110, 320, 130],
        "poses": [
            {},
            {"body": (0, 1), "shield": (-5, -1), "arm": (122, 135, 185)},
            {"body": (0, 2), "shield": (-10, -3), "arm": (128, 160, 215)},
            {"body": (0, 2), "shield": (-7, -3), "arm": (128, 160, 215)},
            {"body": (0, 2), "shield": (-10, -3), "arm": (128, 160, 215)},
            {"body": (0, 1), "shield": (-5, -1), "arm": (120, 125, 165)},
        ],
    },
    "walk": {
        "name": "Knight walk cycle", "loop": True,
        "durations_ms": [120] * 8,
        "poses": [
            {},
            {"body": (1, -1), "feet": {"r": (-2, -5)}, "swing": -6},
            {"body": (1, -1), "feet": {"r": (-4, -10)}, "swing": -12, "shield": (-1, 0)},
            {"body": (1, 0), "feet": {"r": (-3, -5)}, "swing": -6},
            {"body": (0, 1)},
            {"body": (-1, -1), "feet": {"l": (-2, -5)}, "swing": 6},
            {"body": (-1, -1), "feet": {"l": (-3, -10)}, "swing": 12, "shield": (-1, -1)},
            {"body": (-1, 0), "feet": {"l": (-2, -5)}, "swing": 6},
        ],
    },
}


def frame_joints(joints):
    return {name: [round(value + OFFSET[i], 3) for i, value in enumerate(joints[name])] for name in JOINTS}


def compact(document) -> str:
    text = json.dumps(document, ensure_ascii=False, indent=2)
    return re.sub(r"\[\s+([-0-9.,\s]+?)\s+\]",
                  lambda match: "[" + ", ".join(part.strip() for part in match.group(1).split(",")) + "]", text) + "\n"


def write_animation(animation_id, out_root, tokens, palette_rgba, samplers):
    config = ANIMATIONS[animation_id]
    inverse = {rgba: token for token, rgba in palette_rgba.items()}
    frames = []
    for pose in config["poses"]:
        canvas, owner, joints = render_pose(settle(pose, samplers), samplers)
        rows = ["".join(inverse[tuple(int(v) for v in cell)] for cell in row) for row in canvas]
        entry = {"rows": rows, "parts": ["".join(row) for row in owner], "joints": frame_joints(joints)}
        hidden = [part["id"] for part in PARTS if not (owner == part["token"]).any()]
        if hidden:
            entry["hidden"] = hidden
        frames.append(entry)
    count = len(frames)
    parts = {}
    for part in PARTS:
        record = {"token": part["token"], "motion": part["motion"]}
        if part["motion"] == "bone":
            record["bone"] = part["bone"]
        else:
            record["pivot"] = part["pivot"]
        if part.get("parent"):
            record["parent"] = part["parent"]
        parts[part["id"]] = record
    spec = {"schema_version": 1, "name": config["name"], "frame_size": f"{FRAME[0]}x{FRAME[1]}",
            "layout": {"columns": count, "rows": 1, "spacing": 2}, "scale": 2, "palette": tokens,
            "animations": {animation_id: {"frames": list(range(count)), "loop": config["loop"],
                                          "durations_ms": config["durations_ms"]}},
            "rig": {"joints": {name: {} for name in JOINTS}, "parts": parts},
            "frames": frames}
    out = out_root / animation_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "spec.json").write_text(compact(spec), encoding="utf-8")
    width = count * FRAME[0] + (count - 1) * 2
    colors = [value for value in tokens.values()]
    profile = {"schema_version": 1, "name": f"{config['name']} sheet", "logical_size": f"{width}x{FRAME[1]}",
               "scale": 2, "max_colors": sum(1 for value in colors if not value.endswith("00")),
               "alpha": "binary", "transparent_rgb": "exact", "allowed_palette": colors}
    (out / "profile.json").write_text(compact(profile), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=OUT)
    args = parser.parse_args()
    tokens, palette_rgba, rgba = load_knight()
    label = segment(rgba)
    samplers = {name: Sampler(layer) for name, layer in layers(rgba, label).items()}
    for animation_id in ANIMATIONS:
        write_animation(animation_id, args.out_dir, tokens, palette_rgba, samplers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
