#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compose skeleton keyframes for a knight and write an image-generation kit.

The skeleton comes first: arm angles use forward kinematics, legs use
two-bone IK with planted feet, and hips follow the pelvis so crouches bend the
knees. Proportions are measured from the README knight so the sprite keeps its
128x192-cell size, but no pixels of that image are reused: the first swing frame
is drawn new from its guide and a text design, and every other frame is
redrawn from that first frame and its own guide. Generated frames are
unverified candidates until they are projected onto the grid and pass
`pixel_sprite.py check`.
"""
import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "examples" / "knight-animation" / "poses"
FRAME = (192, 288)   # logical cells; 2:3 like the 1024x1536 generation canvas
OFFSET = (48, 56)    # the knight's 128x192 cells sit here at the rest pose
CANVAS = (1024, 1536)
REST = {
    "crown": (66, 4), "neck": (67, 32), "pelvis": (64, 104),
    "shoulder_r": (42, 47), "elbow_r": (31, 71), "hand_r": (28, 97), "mace_head": (13, 127),
    "shoulder_l": (88, 42), "elbow_l": (100, 64), "hand_l": (108, 83),
    "hip_r": (47, 104), "knee_r": (45, 125), "ankle_r": (44, 163), "toe_r": (30, 172),
    "hip_l": (72, 104), "knee_l": (81, 127), "ankle_l": (95, 173), "toe_l": (101, 186),
}
BONES = [  # (start, end, color) in OpenPose-like hues
    ("crown", "neck", (255, 0, 85)), ("neck", "pelvis", (255, 0, 0)),
    ("neck", "shoulder_r", (255, 85, 0)), ("shoulder_r", "elbow_r", (255, 170, 0)), ("elbow_r", "hand_r", (255, 255, 0)),
    ("hand_r", "mace_head", (200, 200, 200)),
    ("neck", "shoulder_l", (85, 255, 0)), ("shoulder_l", "elbow_l", (0, 255, 0)), ("elbow_l", "hand_l", (0, 255, 85)),
    ("pelvis", "hip_r", (0, 255, 170)), ("hip_r", "knee_r", (0, 255, 255)), ("knee_r", "ankle_r", (0, 170, 255)),
    ("ankle_r", "toe_r", (0, 85, 255)),
    ("pelvis", "hip_l", (0, 0, 255)), ("hip_l", "knee_l", (85, 0, 255)), ("knee_l", "ankle_l", (170, 0, 255)),
    ("ankle_l", "toe_l", (255, 0, 255)),
]


def dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def ang(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def ahead(p, deg, length):
    r = math.radians(deg)
    return (p[0] + length * math.cos(r), p[1] + length * math.sin(r))


L = {k: dist(REST[a], REST[b]) for k, (a, b) in {
    "upper_r": ("shoulder_r", "elbow_r"), "fore_r": ("elbow_r", "hand_r"), "mace": ("hand_r", "mace_head"),
    "upper_l": ("shoulder_l", "elbow_l"), "fore_l": ("elbow_l", "hand_l"),
    "thigh_r": ("hip_r", "knee_r"), "shin_r": ("knee_r", "ankle_r"), "foot_r": ("ankle_r", "toe_r"),
    "thigh_l": ("hip_l", "knee_l"), "shin_l": ("knee_l", "ankle_l"), "foot_l": ("ankle_l", "toe_l")}.items()}
A0 = {"upper_r": ang(REST["shoulder_r"], REST["elbow_r"]), "fore_r": ang(REST["elbow_r"], REST["hand_r"]),
      "mace": ang(REST["hand_r"], REST["mace_head"]), "foot_r": ang(REST["ankle_r"], REST["toe_r"]),
      "foot_l": ang(REST["ankle_l"], REST["toe_l"])}


def knee(hip, ankle, thigh, shin, prefer):
    dx, dy = ankle[0] - hip[0], ankle[1] - hip[1]
    d = min(math.hypot(dx, dy), thigh + shin - 1e-6)
    a = (thigh ** 2 - shin ** 2 + d ** 2) / (2 * d)
    h = math.sqrt(max(thigh ** 2 - a ** 2, 0))
    ux, uy = dx / math.hypot(dx, dy), dy / math.hypot(dx, dy)
    bx, by = hip[0] + a * ux, hip[1] + a * uy
    options = [(bx - h * uy, by + h * ux), (bx + h * uy, by - h * ux)]
    return min(options, key=lambda k: dist(k, prefer))


def pose(spec):
    """spec: body (dx,dy) moves torso+head+shoulders+hips; arm angles; shield hand; feet offsets."""
    bx, by = spec.get("body", (0, 0))
    j = {n: (REST[n][0] + bx, REST[n][1] + by) for n in ("crown", "neck", "pelvis", "shoulder_r", "shoulder_l", "hip_r", "hip_l")}
    up, fo, ma = spec.get("arm", (A0["upper_r"], A0["fore_r"], A0["mace"]))
    j["elbow_r"] = ahead(j["shoulder_r"], up, L["upper_r"])
    j["hand_r"] = ahead(j["elbow_r"], fo, L["fore_r"])
    j["mace_head"] = ahead(j["hand_r"], ma, L["mace"])
    sx, sy = spec.get("shield", (0, 0))
    j["hand_l"] = (REST["hand_l"][0] + bx + sx, REST["hand_l"][1] + by + sy)
    rest_elbow = (REST["elbow_l"][0] + bx, REST["elbow_l"][1] + by)
    j["elbow_l"] = knee(j["shoulder_l"], j["hand_l"], L["upper_l"], L["fore_l"], rest_elbow)
    for side in ("r", "l"):
        fx, fy = spec.get("feet", {}).get(side, (0, 0))
        ankle = (REST[f"ankle_{side}"][0] + fx, REST[f"ankle_{side}"][1] + fy)
        hip, reach = j[f"hip_{side}"], L[f"thigh_{side}"] + L[f"shin_{side}"] - 0.05
        if dist(hip, ankle) > reach:  # legs never stretch: a straight leg lifts the foot instead
            scale = reach / dist(hip, ankle)
            ankle = (hip[0] + (ankle[0] - hip[0]) * scale, hip[1] + (ankle[1] - hip[1]) * scale)
        prefer = (REST[f"knee_{side}"][0] + bx + (-6 if side == "r" else 2), REST[f"knee_{side}"][1] + by)
        j[f"ankle_{side}"] = ankle
        j[f"knee_{side}"] = knee(j[f"hip_{side}"], ankle, L[f"thigh_{side}"], L[f"shin_{side}"], prefer)
        tilt = spec.get("toe", {}).get(side, 0)
        j[f"toe_{side}"] = ahead(ankle, A0[f"foot_{side}"] + tilt, L[f"foot_{side}"])
    return {n: (round(x + OFFSET[0], 2), round(y + OFFSET[1], 2)) for n, (x, y) in j.items()}


# Screen degrees: 90 down, 180 left (the knight faces left), 270 up.
ANIMATIONS = {
    "swing": {"durations_ms": [220, 100, 110, 180, 50, 50, 220, 120, 120], "frames": [
        {},                                                         # ready
        {"body": (1, -1), "arm": (205, 250, 275)},                  # lift
        {"body": (2, -2), "arm": (245, 280, 320)},                  # overhead
        {"body": (2, -2), "arm": (258, 302, 355)},                  # cocked behind the head
        {"body": (0, 0), "arm": (222, 228, 240)},                   # downswing over the top
        {"body": (-2, 4), "arm": (186, 168, 165)},                  # mace falling in front
        {"body": (-3, 8), "arm": (148, 115, 98)},                   # smash: crouched, mace driven down
        {"body": (-2, 6), "arm": (140, 110, 104)},                  # settle
        {"body": (-1, 2), "arm": (124, 102, 112)},                  # recover
    ]},
    "block": {"durations_ms": [220, 70, 80, 110, 320, 130], "frames": [
        {},
        {"body": (0, 2), "shield": (-6, -4), "arm": (128, 140, 190)},
        {"body": (0, 4), "shield": (-14, -10), "arm": (135, 165, 220)},
        {"body": (1, 4), "shield": (-12, -9), "arm": (135, 165, 220)},   # impact shove
        {"body": (0, 4), "shield": (-14, -10), "arm": (135, 165, 220)},
        {"body": (0, 2), "shield": (-6, -4), "arm": (122, 128, 170)},
    ]},
    "walk": {"durations_ms": [120] * 8, "frames": [
        {"feet": {"r": (-8, 2), "l": (6, -2)}, "body": (0, 2), "arm": (120, 108, 122)},          # contact, right foot forward
        {"feet": {"r": (-6, 2), "l": (4, -6)}, "body": (0, 3), "arm": (117, 104, 119)},          # down
        {"feet": {"r": (-2, 2), "l": (-2, -10)}, "body": (0, 0), "arm": (112, 98, 116)},         # passing, left leg lifting
        {"feet": {"r": (2, 2), "l": (-8, -6)}, "body": (0, -1), "arm": (108, 92, 113)},          # up
        {"feet": {"r": (6, -2), "l": (-10, 2)}, "body": (0, 2), "arm": (104, 88, 110)},          # contact, left foot forward
        {"feet": {"r": (4, -6), "l": (-8, 2)}, "body": (0, 3), "arm": (106, 92, 112)},           # down
        {"feet": {"r": (-2, -10), "l": (-4, 2)}, "body": (0, 0), "arm": (110, 98, 115)},         # passing, right leg lifting
        {"feet": {"r": (-6, -6), "l": (2, 2)}, "body": (0, -1), "arm": (116, 104, 119)},         # up
    ]},
}


def draw(joints, k, shield=True):
    w, h = round(FRAME[0] * k), round(FRAME[1] * k)
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    P = lambda n: (joints[n][0] * k, joints[n][1] * k)
    if shield:  # kite shield outline held at the left hand
        hx, hy = P("hand_l")
        s = k
        d.polygon([(hx - 22 * s, hy - 30 * s), (hx + 16 * s, hy - 34 * s), (hx + 18 * s, hy + 10 * s), (hx - 4 * s, hy + 50 * s), (hx - 22 * s, hy + 20 * s)],
                  outline=(120, 40, 50), width=max(1, round(k)))
    for a, b, color in BONES:
        d.line([P(a), P(b)], fill=color, width=max(2, round(3 * k)))
    mx, my = P("mace_head")
    d.ellipse((mx - 9 * k, my - 9 * k, mx + 9 * k, my + 9 * k), outline=(200, 200, 200), width=max(1, round(k)))
    hx, hy = P("crown")
    nx, ny = P("neck")
    cx, cy = (hx + nx) / 2, (hy + ny) / 2
    r = dist((hx, hy), (nx, ny)) / 2
    d.ellipse((cx - r * 0.8, cy - r, cx + r * 0.8, cy + r), outline=(255, 0, 85), width=max(1, round(k)))
    for n, (x, y) in joints.items():
        d.ellipse((x * k - 2 * k, y * k - 2 * k, x * k + 2 * k, y * k + 2 * k), fill=(255, 255, 255))
    return img


DESCRIPTIONS = {
    "swing": ["ready stance, mace hanging at his right side pointing down",
              "lifting the mace forward and up, mace pointing up",
              "mace raised overhead, mace head above and slightly behind the helmet",
              "wind-up: mace cocked behind the head pointing back, body leaning back",
              "downswing: arm swinging over the top toward the front, mace pointing up and forward",
              "mace falling in front at shoulder height, arm extended forward",
              "impact: knees bent in a crouch, mace smashed straight down in front of him",
              "settling after the impact, still crouched, mace low",
              "recovering toward the ready stance"],
    "block": ["ready stance",
              "starting to raise the shield, mace drawn forward",
              "full guard: shield raised across the chest and face, knees slightly bent, mace held forward",
              "a blow lands on the shield, shield pushed back slightly",
              "holding the guard",
              "lowering the shield"],
    "walk": ["walking: right foot forward and planted, left foot behind",
             "weight settling onto the right foot",
             "passing pose: left leg lifting and swinging forward",
             "left leg reaching forward",
             "left foot forward and planted, right foot behind",
             "weight settling onto the left foot",
             "passing pose: right leg lifting and swinging forward",
             "right leg reaching forward"],
}
DESIGN = ("a knight in full steel plate armor with a closed great helm and a narrow visor slit, brass-trimmed plate "
          "edges, a brown leather belt and straps, a dark red kite shield with a steel rim and boss strapped to his left "
          "forearm, and a flanged steel mace in his right hand")
STYLE = ("Detailed pixel art with crisp square pixels about 5 canvas pixels wide (the knight is about 190 sprite pixels "
         "tall), at most 32 colors, dark outlines and lighting from the upper left; 3/4 front view facing left.")
JOINTS = ("Line every joint up with the skeleton (head, shoulders, elbows, hands, hips, knees, ankles, mace head); the "
          "dark red outline marks the shield, the gray line and circle mark the mace. The whole knight stays inside the "
          "canvas. Transparent background (flat #FF00FF if transparency is unavailable), no shadow, no ground, no text, "
          "no extra objects.")
ANCHOR = ("swing", 0)  # drawn first; every other frame is redrawn from it
ANCHOR_PROMPT = ("Image 1 is a pose skeleton on a 1024x1536 canvas. Draw a new pixel-art game sprite of " + DESIGN +
                 ", in exactly the pose of the skeleton: {pose}. " + STYLE + " The figure matches the skeleton's scale. "
                 + JOINTS)
FRAME_PROMPT = ("Image 1 is a pixel-art knight sprite; image 2 is a pose skeleton on the same canvas. Redraw the SAME "
                "knight, with identical armor, helmet, trim, straps, shield, mace, colors, palette and pixel size, in "
                "exactly the pose of the skeleton: {pose}. Keep the 3/4 front view facing left and the same body "
                "proportions and scale. " + JOINTS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=OUT)
    args = parser.parse_args()
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    k = CANVAS[0] / FRAME[0]
    anchor_output = f"generated/{ANCHOR[0]}/frame_{ANCHOR[1]:02d}.png"
    record = {"frame_size": list(FRAME), "canvas": list(CANVAS), "offset": list(OFFSET), "rest": REST,
              "bones": [[a, b] for a, b, _ in BONES], "anchor": anchor_output, "animations": {}}
    prompts = {}
    for name, animation in ANIMATIONS.items():
        poses = [pose(spec) for spec in animation["frames"]]
        record["animations"][name] = {"durations_ms": animation["durations_ms"], "joints": poses}
        (out / name).mkdir(exist_ok=True)
        previews = []
        for index, joints in enumerate(poses):
            guide = f"{name}/pose_{index:02d}.png"
            draw(joints, k).save(out / guide)
            previews.append(draw(joints, 2))
            entry = ({"images": [guide], "prompt": ANCHOR_PROMPT.format(pose=DESCRIPTIONS[name][index])}
                     if (name, index) == ANCHOR else
                     {"images": [anchor_output, guide], "prompt": FRAME_PROMPT.format(pose=DESCRIPTIONS[name][index])})
            prompts[f"{name}/{index:02d}"] = {**entry, "output": f"generated/{name}/frame_{index:02d}.png"}
        previews[0].save(out / f"{name}-skeleton.gif", save_all=True, append_images=previews[1:],
                         duration=animation["durations_ms"], loop=0)
    # The anchor is generated first because every other prompt reads it.
    prompts = {f"{ANCHOR[0]}/{ANCHOR[1]:02d}": prompts.pop(f"{ANCHOR[0]}/{ANCHOR[1]:02d}"), **prompts}
    (out / "poses.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")
    (out / "prompts.json").write_text(json.dumps(prompts, indent=2, ensure_ascii=False) + "\n",
                                      encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
