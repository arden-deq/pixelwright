#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reproduce assisted observations of THIS artwork; not general recognition.

The observer selected separation lines and features from coordinate previews of
the actual exported cells. Boundaries at touching parts have about one-cell
uncertainty. No generation pose targets or skeleton coordinates are used.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pixelwright/scripts"))
import pixel_sequence as sequence

# Reference, then the six actual generated frames: left/core boundary,
# core/right boundary, core/tail boundary. Values are cell coordinates.
BOUNDARIES = [(23, 44, 42), (23, 43, 41), (24, 43, 36), (26, 44, 34),
              (24, 43, 35), (23, 43, 40), (25, 44, 35)]
FEATURES = [
    [(39, 30), (21, 22), (46, 25), (25, 53), (23, 29), (25, 29), (45, 32), (43, 32)],
    [(37, 31), (18, 28), (45, 25), (23, 53), (22, 30), (24, 30), (44, 32), (42, 32)],
    [(38, 27), (21, 19), (45, 19), (29, 49), (23, 27), (25, 27), (44, 28), (42, 28)],
    [(38, 24), (20, 16), (47, 20), (40, 45), (25, 24), (27, 24), (45, 26), (43, 26)],
    [(38, 26), (18, 21), (46, 22), (36, 46), (23, 25), (25, 25), (44, 28), (42, 28)],
    [(37, 31), (18, 26), (45, 29), (27, 52), (22, 31), (24, 31), (43, 34), (41, 34)],
    [(38, 27), (20, 21), (46, 22), (27, 48), (24, 28), (26, 28), (45, 28), (43, 28)],
]
NAMES = ["eye", "left_tip", "right_tip", "tail_tip", "left_root", "core_left", "right_root", "core_right"]


def observe(pixels, boundaries, features):
    visible = pixels[:, :, 3] > 0
    yy, xx = np.indices(visible.shape)
    left, right, tail = boundaries
    regions = {"core": visible & (xx >= left) & (xx < right) & (yy < tail),
               "left_vane": visible & (xx < left) & (yy < tail),
               "right_vane": visible & (xx >= right) & (yy < tail),
               "tail": visible & (yy >= tail)}
    parts = {}
    for name, mask in regions.items():
        runs = []
        for y, row in enumerate(mask):
            starts = np.flatnonzero(np.diff(np.r_[False, row, False].astype(int)) == 1)
            ends = np.flatnonzero(np.diff(np.r_[False, row, False].astype(int)) == -1)
            runs.extend([[y, int(a), int(b)] for a, b in zip(starts, ends)])
        measurements = {}
        if name == "core":
            widest = max(runs, key=lambda item: item[2] - item[1])
            y, start, end = widest
            measurements["width"] = [[start, y], [end - 1, y]]
        elif name != "tail":
            y, x = np.where(mask)
            points = np.column_stack((x, y))
            distance = np.sum((points[:, None] - points[None, :]) ** 2, axis=2)
            a, b = np.unravel_index(np.argmax(distance), distance.shape)
            measurements["span"] = [points[a].tolist(), points[b].tolist()]
        parts[name] = {"visibility": "visible", "mask": runs, "measurements": measurements}
    landmarks = {}
    y, x = np.where(visible)
    points = np.column_stack((x, y))
    for name, approximate in zip(NAMES, features):
        nearest = points[np.argmin(np.sum((points - approximate) ** 2, axis=1))]
        if np.linalg.norm(nearest - approximate) > 1.5:
            raise ValueError(f"Reinspect feature {name}: selected point is not on artwork")
        landmarks[name] = nearest.tolist()
    return {"parts": parts, "landmarks": landmarks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    _, contract, manifest = sequence.load_run(root / "run")
    if (manifest["frozen"]["contract.json"] != "2c4facee8d5ea7f2c04575e4856b5843dc2612e725d5da74a5144b68fdec6e8e"
            or manifest["states"]["hover"]["sha256"] != "effd1f4fb2e43cce76c4735c853f40535c6a194cb042af8456d3931787cd94d4"):
        raise ValueError("These observations only describe the original frozen example")
    result = sequence.observation_template(root / "run")
    result["method"] = ("Assistant inspection of actual native-cell coordinate previews; manually selected region boundaries and features; "
        "visible pixels split by those boundaries, widths/spans measured from masks; at most 1.5-cell feature snap to visible cells. "
        "Touching-part boundaries have about one-cell uncertainty. Not automatic semantic recognition or human approval.")
    reference = np.array(Image.open(root / "run/reference-native.png").convert("RGBA"))
    raw = sequence.qa.open_rgba(root / "run/raw/hover.png")
    sampled, _ = sequence._logical(raw, (192, 128), contract["spec"]["derivation"])
    sheet, _ = sequence._nearest(sampled, contract["palette"])
    result["reference"] = observe(reference, BOUNDARIES[0], FEATURES[0])
    result["states"]["hover"]["frames"] = [
        observe(sheet[(i // 3) * 64:(i // 3 + 1) * 64, (i % 3) * 64:(i % 3 + 1) * 64], BOUNDARIES[i + 1], FEATURES[i + 1])
        for i in range(6)]
    result["states"]["hover"]["review"] = {
        "status": "changes_needed", "reviewer": "Codex artwork inspection; no user approval",
        "observations": [
            "The teal core, cream eye, copper vanes and violet tail remain recognizable across all six frames.",
            "The tail jumps between left and right silhouettes; the high pose to following pose and the loop need timing review.",
            "Core facet patterns and the eye placement change across poses. Vane and tail visible areas need redraw or justified occlusion review.",
            "The exported 64-cell art is a fixed projection of a nongrid raw image. Uniform output cells do not prove raw pixel quality."]}
    sequence.sprite._write_new(args.out, sequence.json_bytes(result))


if __name__ == "__main__":
    main()
