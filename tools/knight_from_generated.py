#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Turn generated knight frames into grid-exact, rig-checked sprite sheets.

Input is the pose kit written by tools/knight_pose_guides.py plus one image per
frame at generated/<animation>/frame_NN.png (normally 1024x1536). The palette is
taken from the anchor frame alone: its cells are reduced to 31 colors plus
transparent, the size of the README knight's palette, and every frame is held to
it. Each frame is projected onto the 192x288 logical grid: every cell takes its
most common palette color, or becomes transparent when background dominates it.
Every opaque cell goes to the frontmost part whose capsule around its bone holds
it, the shield to the kite drawn around the shield hand, and a cell outside every
capsule to the nearest one. The skeleton in poses.json stays the
contract: `pixel_sprite.py check` decides whether the generated dots follow it.
Projection is lossy; generated frames remain candidates until that check passes
and the frames are reviewed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pixelwright" / "scripts"))
import pixel_sprite as sprite  # noqa: E402

POSES = ROOT / "docs" / "examples" / "knight-animation" / "poses"
OUT = ROOT / "docs" / "examples" / "knight-animation" / "generated"
SPECK = 4
COLORS = 31
TRANSPARENT = "0"
TOKENS = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# Back to front: part, token, the bone pixel_sprite checks, and the capsules
# (joint, joint, radius in cells) inside which the part owns dots.
PARTS = [
    ("mace", "m", ["hand_r", "mace_head"], [("hand_r", "mace_head", 3), ("mace_head", "mace_head", 10)]),
    ("upper_arm", "u", ["shoulder_r", "elbow_r"], [("shoulder_r", "elbow_r", 6)]),
    ("forearm", "f", ["elbow_r", "hand_r"], [("elbow_r", "hand_r", 6)]),
    ("shin_l", "k", ["knee_l", "ankle_l"], [("knee_l", "ankle_l", 6)]),
    ("foot_l", "e", ["ankle_l", "toe_l"], [("ankle_l", "toe_l", 5)]),
    ("thigh_l", "l", ["hip_l", "knee_l"], [("hip_l", "knee_l", 7)]),
    ("shin_r", "s", ["knee_r", "ankle_r"], [("knee_r", "ankle_r", 6)]),
    ("foot_r", "o", ["ankle_r", "toe_r"], [("ankle_r", "toe_r", 5)]),
    ("thigh_r", "r", ["hip_r", "knee_r"], [("hip_r", "knee_r", 7)]),
    ("torso", "b", ["pelvis", "neck"], [("neck", "pelvis", 10)]),
    # The shield forearm is strapped behind the kite, so its dots go to the shield.
    ("upper_arm_l", "v", ["shoulder_l", "elbow_l"], [("shoulder_l", "elbow_l", 6)]),
    ("head", "h", ["neck", "crown"], [("crown", "neck", 12)]),
    ("shield", "d", None, []),
]
PARENTS = {"mace": "forearm", "forearm": "upper_arm", "upper_arm": "torso", "shin_l": "thigh_l", "thigh_l": "torso",
           "foot_l": "shin_l", "foot_r": "shin_r", "shin_r": "thigh_r", "thigh_r": "torso", "upper_arm_l": "torso", "head": "torso",
           "shield": "upper_arm_l"}
# Projecting a freshly drawn 3-cell mace shaft onto the grid moves its dots up to
# 1.21 cells even when it lies exactly on its bone; 1 cell would fail clean frames.
TOLERANCES = {"mace": {"max_drift": 1.5}}
# The torso also owns its shoulder-to-hip outline, grown by this many cells.
TORSO = (["shoulder_r", "neck", "shoulder_l", "hip_l", "pelvis", "hip_r"], 3)
# The kite drawn in each pose guide, in logical cells around the shield hand.
KITE = [(-22, -30), (16, -34), (18, 10), (-4, 50), (-22, 20)]


def load_canvas(path: Path, canvas):
    """Return RGB pixels and a background mask (transparent or the #FF00FF key)."""
    image = Image.open(path).convert("RGBA")
    if image.size != tuple(canvas):
        image = image.resize(tuple(canvas), Image.Resampling.LANCZOS)
    pixels = np.asarray(image, dtype=np.float64)
    rgb, alpha = pixels[:, :, :3], pixels[:, :, 3]
    key = (rgb[:, :, 0] > 200) & (rgb[:, :, 1] < 90) & (rgb[:, :, 2] > 200)
    return rgb, (alpha < 128) | key


def cell_bounds(frame_size, canvas):
    fw, fh = frame_size
    xs = np.floor(np.arange(fw + 1) * canvas[0] / fw).astype(int)
    ys = np.floor(np.arange(fh + 1) * canvas[1] / fh).astype(int)
    return xs, ys


def anchor_palette(path: Path, frame_size, canvas):
    """Reduce the anchor frame's cell colors to COLORS entries, darkest first."""
    rgb, background = load_canvas(path, canvas)
    xs, ys = cell_bounds(frame_size, canvas)
    # Each cell is sampled at its center, where a cell-sized pixel shows its own color.
    cy, cx = np.ix_((ys[:-1] + ys[1:]) // 2, (xs[:-1] + xs[1:]) // 2)
    votes = cell_votes(background.astype(np.int64), 2, frame_size, canvas)
    opaque = votes[..., 0] > votes[..., 1]
    samples = rgb[cy, cx][opaque & ~background[cy, cx]]
    if not len(samples):
        raise ValueError(f"Anchor frame has no opaque cells: {path}")
    strip = Image.fromarray(samples.astype(np.uint8)[None, :, :], "RGB")
    reduced = strip.quantize(colors=COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    used = np.unique(np.asarray(reduced)).tolist()
    flat = reduced.getpalette()[:3 * (max(used) + 1)]
    colors = sorted({tuple(flat[3 * i:3 * i + 3]) for i in used}, key=lambda c: (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2], c))
    tokens = {TRANSPARENT: "#00000000"}
    tokens.update({TOKENS[i]: "#%02X%02X%02XFF" % color for i, color in enumerate(colors)})
    return tokens, list(tokens)[1:], np.array(colors, dtype=np.float64)


def cell_votes(codes, levels, frame_size, canvas):
    """Count, for every cell, the pixels carrying each code in 0..levels-1."""
    fw, fh = frame_size
    xs, ys = cell_bounds(frame_size, canvas)
    row = np.searchsorted(ys, np.arange(canvas[1]), side="right") - 1
    col = np.searchsorted(xs, np.arange(canvas[0]), side="right") - 1
    index = (row[:, None] * fw + col[None, :]) * levels + codes
    return np.bincount(index.ravel(), minlength=fw * fh * levels).reshape(fh, fw, levels)


def project(path: Path, frame_size, canvas, palette_rgb):
    """Return palette indices per logical cell, -1 where background dominates."""
    rgb, background = load_canvas(path, canvas)
    # Perceptual weights keep warm trim and dark steel from swapping places.
    weights = np.array([0.30, 0.59, 0.11]) ** 0.5
    flat = (rgb * weights).reshape(-1, 3).astype(np.float32)
    targets = (palette_rgb * weights).astype(np.float32)
    # Squared distance minus the pixel's own constant |p|^2 ranks palette colors the same way.
    nearest = np.argmin((targets ** 2).sum(axis=1)[None, :] - 2 * flat @ targets.T, axis=1).reshape(background.shape)
    count = len(palette_rgb)
    votes = cell_votes(np.where(background, count, nearest), count + 1, frame_size, canvas)
    colored = votes[..., :count]
    cells = np.where(colored.sum(axis=2) > votes[..., count], np.argmax(colored, axis=2), -1)
    # Generation noise far from the figure becomes isolated specks; drop them.
    for piece in sprite_components(cells >= 0):
        if len(piece) < SPECK:
            for cy, cx in piece:
                cells[cy, cx] = -1
    return cells


def sprite_components(mask):
    seen = np.zeros_like(mask, dtype=bool)
    pieces = []
    h, w = mask.shape
    for y, x in np.argwhere(mask):
        if seen[y, x]:
            continue
        seen[y, x] = True
        stack, piece = [(int(y), int(x))], []
        while stack:
            cy, cx = stack.pop()
            piece.append((cy, cx))
            for ny in range(max(0, cy - 1), min(h, cy + 2)):
                for nx in range(max(0, cx - 1), min(w, cx + 2)):
                    if mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        pieces.append(piece)
    return pieces


def segment_distance(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy or 1e-9
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / length2, 0, 1)
    return np.hypot(px - (ax + t * dx), py - (ay + t * dy))


def polygon_distance(px, py, points, frame_size):
    """Distance to a polygon's outline outside it, zero inside."""
    mask = Image.new("L", tuple(frame_size), 0)
    ImageDraw.Draw(mask).polygon([tuple(p) for p in points], fill=1)
    edges = np.min([segment_distance(px, py, a, b) for a, b in zip(points, points[1:] + points[:1])], axis=0)
    return np.where(np.asarray(mask).astype(bool), 0.0, edges)


def label(cells, joints, frame_size):
    """Give each opaque cell to the frontmost part whose capsule holds it, else to the nearest capsule."""
    fw, fh = frame_size
    py, px = np.mgrid[0:fh, 0:fw]
    hx, hy = joints["hand_l"]
    surfaces = []
    for name, _, _, capsules in PARTS:
        if name == "shield":
            surface = polygon_distance(px, py, [(hx + dx, hy + dy) for dx, dy in KITE], frame_size) - 1
        else:
            surface = np.min([segment_distance(px, py, joints[a], joints[b]) - radius for a, b, radius in capsules], axis=0)
        if name == "torso":
            outline, grow = TORSO
            surface = np.minimum(surface, polygon_distance(px, py, [joints[j] for j in outline], frame_size) - grow)
        surfaces.append(surface)
    surfaces = np.stack(surfaces)
    tokens = np.array([token for _, token, _, _ in PARTS])
    opaque = cells >= 0
    inside = surfaces <= 0
    # Front parts claim first; argmax over the reversed stack finds the frontmost holder.
    front = len(PARTS) - 1 - np.argmax(inside[::-1], axis=0)
    owner_index = np.where(inside.any(axis=0), front, np.argmin(surfaces, axis=0))
    return np.where(opaque, tokens[owner_index], ".")


def compact(document) -> str:
    text = json.dumps(document, ensure_ascii=False, indent=2)
    return re.sub(r"\[\s+([-0-9.,\s]+?)\s+\]",
                  lambda match: "[" + ", ".join(part.strip() for part in match.group(1).split(",")) + "]", text) + "\n"


def write_animation(name, kit, poses_dir, out_root, tokens, visible_tokens, palette_rgb):
    record = kit["animations"][name]
    frame_size, canvas = kit["frame_size"], kit["canvas"]
    frames = []
    for index, joints in enumerate(record["joints"]):
        source = poses_dir / "generated" / name / f"frame_{index:02d}.png"
        if not source.is_file():
            raise ValueError(f"Missing generated frame: {source}")
        cells = project(source, frame_size, canvas, palette_rgb)
        owner = label(cells, joints, frame_size)
        rows = ["".join(TRANSPARENT if value < 0 else visible_tokens[value] for value in row) for row in cells]
        entry = {"rows": rows, "parts": ["".join(row) for row in owner],
                 "joints": {joint: [round(v, 3) for v in xy] for joint, xy in joints.items()}}
        hidden = [part for part, token, _, _ in PARTS if not (owner == token).any()]
        if hidden:
            entry["hidden"] = hidden
        frames.append(entry)
    # Parts are compared against the first frame, which every other frame was redrawn from, unless
    # it shows less than half of what another frame shows; a part never seen is left out.
    seen = {token: [sum(row.count(token) for row in frame["parts"]) for frame in frames] for _, token, _, _ in PARTS}
    parts = {}
    for part, token, bone, _ in PARTS:
        if not any(seen[token]):
            continue
        parts[part] = {"token": token, "motion": "bone", "bone": bone} if bone else {"token": token, "motion": "free"}
        counts = seen[token]
        parts[part]["reference_frame"] = 0 if counts[0] * 2 >= max(counts) else int(np.argmax(counts))
        parts[part].update(TOLERANCES.get(part, {}))
        if part in PARENTS and PARENTS[part] in parts:
            parts[part]["parent"] = PARENTS[part]
    for frame in frames:
        hidden = [part for part in parts if part in frame.get("hidden", [])]
        frame.pop("hidden", None)
        if hidden:
            frame["hidden"] = hidden
    count = len(frames)
    spec = {"schema_version": 1, "name": f"Generated knight {name}", "frame_size": f"{frame_size[0]}x{frame_size[1]}",
            "layout": {"columns": count, "rows": 1, "spacing": 2}, "scale": 2, "palette": tokens,
            "animations": {name: {"frames": list(range(count)), "loop": True, "durations_ms": record["durations_ms"]}},
            "rig": {"joints": {joint: {} for joint in record["joints"][0]}, "parts": parts}, "frames": frames}
    out = out_root / name
    out.mkdir(parents=True)
    (out / "spec.json").write_text(compact(spec), encoding="utf-8")
    width = count * frame_size[0] + (count - 1) * 2
    profile = {"schema_version": 1, "name": f"Generated knight {name} sheet", "logical_size": f"{width}x{frame_size[1]}",
               "scale": 2, "max_colors": len(visible_tokens), "alpha": "binary", "transparent_rgb": "exact",
               "allowed_palette": list(tokens.values())}
    (out / "profile.json").write_text(compact(profile), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poses", type=Path, default=POSES, help="Pose kit with generated/<animation>/frame_NN.png")
    parser.add_argument("--out-dir", type=Path, default=OUT, help="Fresh output directory; one subdirectory per animation")
    parser.add_argument("--animation", action="append", help="Limit to these animations (default: all)")
    args = parser.parse_args()
    kit = json.loads((args.poses / "poses.json").read_text(encoding="utf-8"))
    tokens, visible_tokens, palette_rgb = anchor_palette(args.poses / kit["anchor"], kit["frame_size"], kit["canvas"])
    for name in args.animation or kit["animations"]:
        if (args.out_dir / name).exists():
            raise SystemExit(f"Output already exists, use a fresh --out-dir: {args.out_dir / name}")
        out = write_animation(name, kit, args.poses, args.out_dir, tokens, visible_tokens, palette_rgb)
        spec, profile = out / "spec.json", out / "profile.json"
        build = out / "build"
        sprite.build_sheet(spec, build)
        summary = sprite.check_sheet(spec, build / "rendered.png", profile, out / "check", scale=2)
        print(json.dumps({"animation": name, "status": summary["status"], "issue_counts": summary["issue_counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
