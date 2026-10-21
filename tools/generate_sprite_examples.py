#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Regenerate the bundled rigged sprite examples deterministically.

Each part is drawn from its declared bone or pivot, outlined, and stacked back
to front in the order the rig lists its parts. The script writes the indexed
color rows together with the matching part map and joints, so a checker run
starts from a rig that describes the dots. Hand-authored specs use the same
format.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "pixelwright" / "examples"
OUTLINE = "o"


def capsule(start, end, radius, width, height):
    """Cells whose centers lie within radius of a segment, with along/across."""
    ax, ay = start
    bx, by = end
    length = math.hypot(bx - ax, by - ay)
    dx, dy = (bx - ax) / length, (by - ay) / length
    cells = {}
    for y in range(height):
        for x in range(width):
            rx, ry = x - ax, y - ay
            along = rx * dx + ry * dy
            across = -rx * dy + ry * dx
            t = min(max(along, 0.0), length)
            if math.hypot(rx - t * dx, ry - t * dy) <= radius:
                cells[(x, y)] = (along / length, across)
    return cells


def outline(fill, width, height):
    ring = set()
    for x, y in fill:
        for ny in range(y - 1, y + 2):
            for nx in range(x - 1, x + 2):
                if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in fill:
                    ring.add((nx, ny))
    return ring


def stack(layers, width, height):
    """Draw outlined parts back to front; report each part's hidden fraction."""
    colors = [["."] * width for _ in range(height)]
    owners = [["."] * width for _ in range(height)]
    full = {}
    for token, fill in layers:
        cells = dict(fill)
        for cell in outline(fill, width, height):
            cells[cell] = OUTLINE
        full[token] = set(cells)
        for (x, y), color in cells.items():
            colors[y][x] = color
            owners[y][x] = token
    hidden = {}
    for token, cells in full.items():
        shown = sum(1 for x, y in cells if owners[y][x] == token)
        hidden[token] = 1 - shown / len(cells)
    return ["".join(row) for row in colors], ["".join(row) for row in owners], hidden


def walk_frames():
    width, height = 24, 32
    # Degrees from straight down; positive swings toward the facing direction.
    thigh = [25, 15, 0, -15, -25, -15, 5, 20]
    shin = [20, 5, -5, -20, -30, -50, -40, 5]
    bob = [0, 1, 0, 0, 0, 1, 0, 0]
    head = ["..yyyy.",
            ".yyyyyy",
            "yyykkkk",
            "yykkkok",
            "yKkkkkk",
            ".KKkkk.",
            "..KK..."]
    frames = []
    for index in range(8):
        other = (index + 4) % 8
        hip = (11.0, 17.0 + bob[index])
        neck = (hip[0], hip[1] - 7)
        shoulder = (neck[0], neck[1] + 1)

        def point(origin, degrees, length):
            radians = math.radians(degrees)
            return (round(origin[0] + length * math.sin(radians), 3),
                    round(origin[1] + length * math.cos(radians), 3))

        knee_f = point(hip, thigh[index], 6)
        foot_f = point(knee_f, shin[index], 6)
        knee_b = point(hip, thigh[other], 6)
        foot_b = point(knee_b, shin[other], 6)
        hand_f = point(shoulder, -0.8 * thigh[other], 7)
        hand_b = point(shoulder, -0.8 * thigh[index], 7)
        joints = {"hip": hip, "neck": neck, "shoulder": shoulder, "knee_f": knee_f, "foot_f": foot_f,
                  "knee_b": knee_b, "foot_b": foot_b, "hand_f": hand_f, "hand_b": hand_b}

        def limb(start, end, radius, base, shade, tip=None, tip_from=1.0):
            cells = {}
            for cell, (along, across) in capsule(start, end, radius, width, height).items():
                cells[cell] = tip if tip and along >= tip_from else shade if across > 0.4 else base
            return cells

        def leg_lower(knee, foot, pants, boot):
            cells = limb(knee, foot, 1.1, pants, pants, boot, 0.7)
            length = math.hypot(foot[0] - knee[0], foot[1] - knee[1])
            dx, dy = (foot[0] - knee[0]) / length, (foot[1] - knee[1]) / length
            toe = (foot[0] + 2.5 * dy, foot[1] - 2.5 * dx)
            for cell in capsule(foot, toe, 1.0, width, height):
                cells[cell] = boot
            return cells

        torso = limb(hip, neck, 2.4, "u", "U")
        for cell, (along, _) in capsule(hip, neck, 2.4, width, height).items():
            if along < 0.12:
                torso[cell] = "w"
        pivot = (int(neck[0]) - 3, int(neck[1]) - 7)
        head_cells = {(pivot[0] + x, pivot[1] + y): color
                      for y, row in enumerate(head) for x, color in enumerate(row) if color != "."}
        layers = [("a", limb(shoulder, hand_b, 1.0, "V", "V", "K", 0.85)),
                  ("b", limb(hip, knee_b, 1.4, "q", "q")),
                  ("c", leg_lower(knee_b, foot_b, "q", "B")),
                  ("t", torso),
                  ("f", limb(hip, knee_f, 1.4, "p", "P")),
                  ("s", leg_lower(knee_f, foot_f, "p", "b")),
                  ("h", head_cells),
                  ("r", limb(shoulder, hand_f, 1.0, "u", "U", "k", 0.85))]
        rows, parts, hidden = stack(layers, width, height)
        frames.append({"rows": rows, "parts": parts,
                       "joints": {name: [round(x, 3), round(y, 3)] for name, (x, y) in joints.items()},
                       "hidden": hidden})
    return frames


def lever_frames():
    width, height = 18, 16
    pivot = (8, 10)
    angles = [-50, -25, 0, 25, 50]
    frames = []
    for degrees in angles:
        radians = math.radians(degrees)
        grip = (round(pivot[0] + 7 * math.sin(radians)), round(pivot[1] - 7 * math.cos(radians)))
        handle = {cell: "m" for cell in capsule(pivot, grip, 1.0, width, height)}
        knob = {(grip[0] + x, grip[1] + y): color
                for y, row in enumerate(["rRr", "RRR", "rRr"]) for x, color in enumerate(row)}
        knob = {(x - 1, y - 1): color for (x, y), color in knob.items()}
        base = {(x, y): ("g" if y < 12 else "G") for y in range(11, 14) for x in range(3, 14)}
        rows, parts, hidden = stack([("l", handle), ("b", base), ("k", knob)], width, height)
        frames.append({"rows": rows, "parts": parts,
                       "joints": {"pivot": list(pivot), "grip": list(grip)}, "hidden": hidden})
    return frames


def finish(frames, names):
    """List fully covered parts and choose each part's best-visible reference."""
    references = {}
    for token, part_id in names.items():
        order = sorted(range(len(frames)), key=lambda i: (frames[i]["hidden"][token], i))
        references[part_id] = order[0]
    for frame in frames:
        hidden = frame.pop("hidden")
        covered = [part_id for token, part_id in names.items() if hidden[token] >= 1]
        if covered:
            frame["hidden"] = covered
    return references


def sheet_size(spec) -> str:
    width, height = map(int, spec["frame_size"].split("x"))
    layout = spec["layout"]
    gap = layout.get("spacing", 0)
    return (f"{layout['columns'] * (width + gap) - gap + 2 * layout.get('margin', 0)}x"
            f"{layout['rows'] * (height + gap) - gap + 2 * layout.get('margin', 0)}")


def write(path: Path, document) -> None:
    text = json.dumps(document, ensure_ascii=False, indent=2)
    # Keep frame lists and joint coordinates on one line for readable specs.
    text = re.sub(r"\[\s+([-0-9.,\s]+?)\s+\]",
                  lambda match: "[" + ", ".join(part.strip() for part in match.group(1).split(",")) + "]", text)
    path.write_text(text + "\n", encoding="utf-8")


def walk_example(out: Path) -> None:
    frames = walk_frames()
    names = {"a": "arm_back", "b": "thigh_back", "c": "shin_back", "t": "torso",
             "f": "thigh_front", "s": "shin_front", "h": "head", "r": "arm_front"}
    references = finish(frames, names)
    # Back to front: this order is the drawing depth used for occlusion.
    parts = {
        "arm_back": {"token": "a", "motion": "bone", "bone": ["shoulder", "hand_b"], "parent": "torso"},
        "thigh_back": {"token": "b", "motion": "bone", "bone": ["hip", "knee_b"], "parent": "torso"},
        "shin_back": {"token": "c", "motion": "bone", "bone": ["knee_b", "foot_b"], "parent": "thigh_back"},
        "torso": {"token": "t", "motion": "bone", "bone": ["hip", "neck"]},
        "thigh_front": {"token": "f", "motion": "bone", "bone": ["hip", "knee_f"], "parent": "torso"},
        "shin_front": {"token": "s", "motion": "bone", "bone": ["knee_f", "foot_f"], "parent": "thigh_front"},
        "head": {"token": "h", "motion": "rigid", "pivot": "neck", "parent": "torso"},
        "arm_front": {"token": "r", "motion": "bone", "bone": ["shoulder", "hand_f"], "parent": "torso"},
    }
    for part_id, part in parts.items():
        if references[part_id]:
            part["reference_frame"] = references[part_id]
    palette = {".": "transparent", "o": "#1E1A2B", "k": "#F0C090", "K": "#C88A60", "y": "#6B3F22",
               "u": "#3F7CC4", "U": "#2C5A92", "V": "#24477A", "w": "#2A2230", "p": "#59606E",
               "P": "#454B57", "q": "#363A45", "b": "#7A4A2C", "B": "#5A3420"}
    spec = {"schema_version": 1, "name": "Rigged side-view walk cycle", "frame_size": "24x32",
            "layout": {"columns": 8, "rows": 1, "spacing": 1}, "scale": 4, "palette": palette,
            "animations": {"walk": {"frames": list(range(8)), "loop": True, "frame_ms": 110}},
            "rig": {"max_joint_step": 7, "joints": {name: {} for name in frames[0]["joints"]},
                    "parts": parts},
            "frames": frames}
    out.mkdir(parents=True, exist_ok=True)
    write(out / "spec.json", spec)
    colors = sorted(value for value in palette.values() if value != "transparent")
    write(out / "profile.json", {"schema_version": 1, "name": "Walk cycle sheet", "logical_size": sheet_size(spec),
                                 "scale": 4, "max_colors": len(colors), "alpha": "binary",
                                 "transparent_rgb": "exact", "allowed_palette": ["#00000000"] + colors})


def lever_example(out: Path) -> None:
    frames = lever_frames()
    names = {"l": "handle", "b": "base", "k": "knob"}
    references = finish(frames, names)
    parts = {
        "handle": {"token": "l", "motion": "bone", "bone": ["pivot", "grip"], "parent": "base"},
        "base": {"token": "b", "motion": "fixed"},
        "knob": {"token": "k", "motion": "rigid", "pivot": "grip", "parent": "handle"},
    }
    for part_id, part in parts.items():
        if references[part_id]:
            part["reference_frame"] = references[part_id]
    palette = {".": "transparent", "o": "#1E1A2B", "m": "#C8CDD6",
               "r": "#D8404A", "R": "#A02A34", "g": "#7A6A58", "G": "#5A4C3E"}
    spec = {"schema_version": 1, "name": "Rigged lever switch", "frame_size": "18x16",
            "layout": {"columns": 5, "rows": 1, "spacing": 1}, "edge_margin": 1, "scale": 6,
            "palette": palette,
            "animations": {"switch_on": {"frames": [0, 1, 2, 3, 4], "loop": False, "frame_ms": 90},
                           "switch_off": {"frames": [4, 3, 2, 1, 0], "loop": False, "frame_ms": 90}},
            "rig": {"max_joint_step": 4, "joints": {"pivot": {"fixed": True}, "grip": {}}, "parts": parts},
            "frames": frames}
    out.mkdir(parents=True, exist_ok=True)
    write(out / "spec.json", spec)
    colors = sorted(value for value in palette.values() if value != "transparent")
    write(out / "profile.json", {"schema_version": 1, "name": "Lever sheet", "logical_size": sheet_size(spec),
                                 "scale": 6, "max_colors": len(colors), "alpha": "binary",
                                 "transparent_rgb": "exact", "allowed_palette": ["#00000000"] + colors})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=EXAMPLES)
    args = parser.parse_args()
    walk_example(args.out_dir / "sprite-walk")
    lever_example(args.out_dir / "sprite-lever")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
