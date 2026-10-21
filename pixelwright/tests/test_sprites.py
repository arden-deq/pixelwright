# SPDX-License-Identifier: Apache-2.0
"""Independent checks for sprite sheets, animations and declared part rigs.

Fixture sheets are composed here from explicit RGBA cells and repeated with
NumPy, not by the sprite builder. Each rig test changes one property of a
consistent two-frame motion and expects the corresponding issue code.
"""
import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import generate_knight_animations as knight
import generate_sprite_examples as examples
import pixel_sprite as sprite

COLORS = {"A": (160, 32, 48, 255), "B": (32, 80, 176, 255), "C": (240, 192, 64, 255), "D": (40, 160, 90, 255)}
HEX = {key: "#%02X%02X%02X" % value[:3] for key, value in COLORS.items()}
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
KNIGHT_ANIMATIONS = Path(__file__).resolve().parents[2] / "docs" / "examples" / "knight-animation"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frame(size, cells):
    """Return RGBA cells and the matching part map for {(x, y): (part, color)}."""
    width, height = size
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    parts = [["."] * width for _ in range(height)]
    for (x, y), (token, color) in cells.items():
        pixels[y, x] = COLORS[color]
        parts[y][x] = token
    return pixels, ["".join(row) for row in parts]


def standard_motion():
    """A fixed floor, a box moving one cell with its pivot, an arm turning 90 degrees."""
    first, second = {}, {}
    for cells in (first, second):
        for x in range(10):
            cells[(x, 9)] = ("g", "A")
    for x in (1, 2):
        for y in (1, 2):
            first[(x, y)] = ("x", "B")
            second[(x + 1, y)] = ("x", "B")
    for x in range(4, 9):
        for y in (2, 3):
            first[(x, y)] = ("r", "C")
    for x in (4, 5):
        for y in range(2, 7):
            second[(x, y)] = ("r", "C")
    joints = [{"p": [1, 1], "s": [4, 2.5], "e": [8, 2.5]},
              {"p": [2, 1], "s": [4.5, 2], "e": [4.5, 6]}]
    rig = {"joints": {"p": {}, "s": {}, "e": {}},
           "parts": {"floor": {"token": "g", "motion": "fixed"},
                     "box": {"token": "x", "motion": "rigid", "pivot": "p"},
                     "arm": {"token": "r", "motion": "bone", "bone": ["s", "e"]}}}
    return [first, second], joints, rig


class SpriteCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Resolve aliases such as Windows 8.3 temp paths before comparing provenance.
        self.root = Path(self.tmp.name).resolve()
        self.runs = 0

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, frames, *, joints=None, rig=None, size=(10, 10), columns=None, rows=1,
                   spacing=1, margin=0, scale=2, frame_count=None, animations=None, hidden=None,
                   depths=None, extra=None, sheet_hook=None, profile_extra=None):
        natives, maps = zip(*(frame(size, cells) for cells in frames))
        count = frame_count or len(frames)
        columns = columns or count
        width = 2 * margin + columns * size[0] + (columns - 1) * spacing
        height = 2 * margin + rows * size[1] + (rows - 1) * spacing
        sheet = np.zeros((height, width, 4), dtype=np.uint8)
        for index, native in enumerate(natives):
            x = margin + (index % columns) * (size[0] + spacing)
            y = margin + (index // columns) * (size[1] + spacing)
            sheet[y:y + size[1], x:x + size[0]] = native
        if sheet_hook:
            sheet_hook(sheet)
        Image.fromarray(np.repeat(np.repeat(sheet, scale, axis=0), scale, axis=1), "RGBA").save(self.root / "sheet.png")
        spec = {"schema_version": 1, "frame_size": f"{size[0]}x{size[1]}",
                "layout": {"columns": columns, "rows": rows, "spacing": spacing, "margin": margin}}
        if frame_count:
            spec["frame_count"] = frame_count
        if animations is not None:
            spec["animations"] = animations
        if rig is not None:
            spec["rig"] = rig
            spec["frames"] = []
            for index in range(len(frames)):
                entry = {"parts": maps[index], "joints": joints[index]}
                if hidden and hidden.get(index):
                    entry["hidden"] = hidden[index]
                if depths and depths.get(index):
                    entry["z"] = depths[index]
                spec["frames"].append(entry)
        spec.update(extra or {})
        profile = {"schema_version": 1, "logical_size": f"{width}x{height}", "scale": scale,
                   "max_colors": 4, "alpha": "binary", "transparent_rgb": "exact",
                   "allowed_palette": ["#00000000"] + list(HEX.values())}
        profile.update(profile_extra or {})
        (self.root / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        (self.root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        return spec

    def check(self):
        self.runs += 1
        return sprite.check_sheet(self.root / "spec.json", self.root / "sheet.png",
                                  self.root / "profile.json", self.root / f"run-{self.runs}")

    @staticmethod
    def codes(summary, severities=("fail", "review")):
        return {(issue["code"], issue.get("frame"), issue.get("part"))
                for issue in summary["issues"] if issue["severity"] in severities}


class LayoutAndBuildTests(SpriteCase):
    def test_layout_geometry_counts_margin_and_spacing(self):
        layout = sprite.Layout((16, 24), 3, 2, 2, 1, 5, 0)
        self.assertEqual(layout.sheet_size, (2 * 2 + 3 * 16 + 2, 2 * 2 + 2 * 24 + 1))
        self.assertEqual([layout.origin(i) for i in range(5)],
                         [(2, 2), (19, 2), (36, 2), (2, 27), (19, 27)])

    def test_build_places_frames_and_keeps_gutters_transparent(self):
        spec = {"schema_version": 1, "frame_size": "3x2", "layout": {"columns": 2, "rows": 2, "spacing": 1, "margin": 1},
                "frame_count": 3, "scale": 3,
                "palette": {".": "transparent", "a": HEX["A"], "b": HEX["B"]},
                "frames": [{"rows": ["ab.", ".ba"]}, {"rows": ["aaa", "bbb"]}, {"rows": ["...", "..b"]}]}
        path = self.root / "build-spec.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        before = digest(path)
        manifest = sprite.build_sheet(path, self.root / "build")
        expected = np.zeros((7, 9, 4), dtype=np.uint8)
        cells = {(1, 1): "A", (2, 1): "B", (2, 2): "B", (3, 2): "A",
                 (5, 1): "A", (6, 1): "A", (7, 1): "A", (5, 2): "B", (6, 2): "B", (7, 2): "B",
                 (3, 5): "B"}
        for (x, y), color in cells.items():
            expected[y, x] = COLORS[color]
        with Image.open(self.root / "build" / "native.png") as native:
            np.testing.assert_array_equal(np.asarray(native.convert("RGBA")), expected)
        with Image.open(self.root / "build" / "rendered.png") as rendered:
            np.testing.assert_array_equal(np.asarray(rendered.convert("RGBA")),
                                          np.repeat(np.repeat(expected, 3, axis=0), 3, axis=1))
        recorded = json.loads((self.root / "build" / "build.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded, manifest)
        self.assertEqual(manifest["layout"]["frame_origins"], [[1, 1], [5, 1], [1, 4]])
        for name in ("native.png", "rendered.png"):
            self.assertEqual(manifest["outputs"][name]["sha256"], digest(self.root / "build" / name))
        self.assertEqual(digest(path), before)
        self.assertEqual(sorted(p.name for p in (self.root / "build").iterdir()),
                         ["build.json", "native.png", "rendered.png"])

    def test_build_reuses_a_palette_library_for_every_frame(self):
        (self.root / "palette.json").write_text(json.dumps({
            "schema_version": 1, "colors": {"clear": "#00000000", "red": HEX["A"] + "FF"}, "ramps": {}}), encoding="utf-8")
        spec = {"schema_version": 1, "frame_size": "2x1", "layout": {"columns": 2, "rows": 1}, "scale": 2,
                "palette_file": "palette.json",
                "frames": [{"rows": [["red", "clear"]]}, {"rows": [["clear", "red"]]}]}
        (self.root / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        manifest = sprite.build_sheet(self.root / "spec.json", self.root / "build")
        self.assertEqual(manifest["palette_source"]["sha256"], digest(self.root / "palette.json"))
        with Image.open(self.root / "build" / "native.png") as native:
            pixels = np.asarray(native.convert("RGBA"))
        np.testing.assert_array_equal(pixels[0, [0, 3]], [COLORS["A"], COLORS["A"]])
        self.assertEqual(int(pixels[0, 1, 3]) + int(pixels[0, 2, 3]), 0)

    def test_build_rejects_wrong_frame_size_and_missing_scale(self):
        spec = {"schema_version": 1, "frame_size": "2x1", "layout": {"columns": 1, "rows": 1}, "scale": 2,
                "palette": {"a": HEX["A"]}, "frames": [{"rows": ["aaa"]}]}
        (self.root / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "frame_size"):
            sprite.build_sheet(self.root / "spec.json", self.root / "out")
        del spec["scale"]
        spec["frames"] = [{"rows": ["aa"]}]
        (self.root / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "scale"):
            sprite.build_sheet(self.root / "spec.json", self.root / "out")
        self.assertFalse((self.root / "out").exists())


class SheetTests(SpriteCase):
    def simple_frames(self):
        return [{(1, 1): ("a", "A"), (2, 2): ("a", "B")}, {(2, 1): ("a", "A"), (2, 2): ("a", "B")}]

    def test_clean_sheet_passes_and_writes_previews(self):
        self.write_case(self.simple_frames(), size=(4, 4),
                        animations={"blink": {"frames": [0, 1, 1], "durations_ms": [80, 120, 200]}})
        inputs = {name: digest(self.root / name) for name in ("spec.json", "sheet.png", "profile.json")}
        summary = self.check()
        self.assertEqual(summary["status"], "pass")
        self.assertEqual(summary["sheet_audit"]["status"], "pass")
        self.assertEqual(summary["checks"], {"frames": "checked", "animations": "checked", "rig": "not_declared"})
        root = self.root / "run-1"
        report = json.loads((root / "sprite_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "pass")
        self.assertEqual([f["bbox"] for f in report["frames"]], [[1, 1, 2, 2], [2, 1, 2, 2]])
        with Image.open(root / "layout_overlay.png") as overlay:
            self.assertEqual(overlay.size, (18, 8))
        with Image.open(root / "animations" / "blink.gif") as preview:
            self.assertGreaterEqual(preview.n_frames, 2)
            self.assertEqual(preview.info.get("loop"), 0)
        self.assertTrue((root / "sheet" / "grid_overlay.png").is_file())
        self.assertEqual({name: digest(self.root / name) for name in inputs}, inputs)
        self.assertFalse(any(path.name.endswith(".lock") for path in root.rglob("*")))

    def test_profile_must_describe_the_same_sheet(self):
        self.write_case(self.simple_frames(), size=(4, 4), profile_extra={"logical_size": "8x4"})
        with self.assertRaisesRegex(ValueError, "logical_size"):
            self.check()
        self.write_case(self.simple_frames(), size=(4, 4), extra={"scale": 3})
        with self.assertRaisesRegex(ValueError, "scale"):
            self.check()
        self.write_case(self.simple_frames(), size=(4, 4), profile_extra={"alpha": "opaque"})
        with self.assertRaisesRegex(ValueError, "opaque"):
            self.check()

    def test_gutter_unused_slot_and_edge_margin_violations_fail(self):
        def stray(sheet):
            sheet[0, 4] = COLORS["A"]  # spacing column between frames 0 and 1
            sheet[1, 10] = COLORS["B"]  # unused third slot
        self.write_case(self.simple_frames(), size=(4, 4), columns=3, frame_count=2, sheet_hook=stray,
                        extra={"edge_margin": 1})
        frames = self.simple_frames()
        summary = self.check()
        codes = {code for code, _, _ in self.codes(summary)}
        self.assertEqual(summary["status"], "fail")
        self.assertIn("GUTTER_NOT_EMPTY", codes)
        self.assertIn("UNUSED_SLOT_NOT_EMPTY", codes)
        self.assertNotIn("EDGE_MARGIN_VIOLATION", codes)
        frames[0][(0, 2)] = ("a", "A")
        self.write_case(frames, size=(4, 4), extra={"edge_margin": 1})
        self.assertIn(("EDGE_MARGIN_VIOLATION", 0, None), self.codes(self.check()))

    def test_nonuniform_sheet_cells_stop_frame_checks(self):
        self.write_case(self.simple_frames(), size=(4, 4))
        with Image.open(self.root / "sheet.png") as image:
            pixels = np.asarray(image.convert("RGBA")).copy()
        pixels[2, 3] = COLORS["B"]
        Image.fromarray(pixels, "RGBA").save(self.root / "sheet.png")
        summary = self.check()
        self.assertEqual(summary["status"], "fail")
        self.assertEqual(summary["sheet_audit"]["status"], "fail")
        self.assertEqual(summary["checks"]["frames"], "not_checked")
        self.assertFalse((self.root / "run-1" / "layout_overlay.png").exists())

    def test_empty_frame_and_duplicate_frames_are_reported(self):
        frames = self.simple_frames()
        frames.append({})
        frames.append(dict(frames[0]))
        self.write_case(frames, size=(4, 4), animations={"idle": {"frames": [0, 3, 2], "loop": False}})
        summary = self.check()
        self.assertEqual(summary["status"], "review")
        self.assertIn(("EMPTY_FRAME", 2, None), self.codes(summary))
        info = {issue["code"] for issue in summary["issues"] if issue["severity"] == "info"}
        self.assertTrue({"DUPLICATE_ADJACENT_FRAMES", "UNUSED_FRAMES"} <= info)

    def test_sheet_that_differs_from_spec_rows_needs_review(self):
        frames = self.simple_frames()
        self.write_case(frames, size=(4, 4), extra={
            "palette": {".": "transparent", "a": HEX["A"], "b": HEX["B"]},
            "frames": [{"rows": ["....", ".a..", "..b.", "...."]}, {"rows": ["....", "..a.", "..a.", "...."]}]})
        summary = self.check()
        self.assertIn(("SHEET_DIFFERS_FROM_SPEC_ROWS", None, None), self.codes(summary))
        self.assertIn("[1]", next(i["detail"] for i in summary["issues"] if i["code"] == "SHEET_DIFFERS_FROM_SPEC_ROWS"))


class RigTests(SpriteCase):
    def run_motion(self, mutate=None, **options):
        frames, joints, rig = standard_motion()
        if mutate:
            mutate(frames, joints, rig)
        self.write_case(frames, joints=joints, rig=rig, animations={"move": {"frames": [0, 1]}}, **options)
        return self.check()

    def test_consistent_motion_passes_with_skeleton_overlay(self):
        summary = self.run_motion()
        self.assertEqual(summary["status"], "pass", summary["issues"])
        arm = summary["rig"]["parts"]["arm"]["frames"][1]
        self.assertEqual((arm["shape_match"], arm["area_ratio"], arm["bone_length"]), (1.0, 1.0, 4.0))
        self.assertEqual(arm["drift"], {"along": 0.0, "across": 0.0})
        self.assertEqual(summary["rig"]["parts"]["box"]["frames"][1]["offset"], [1, 0])
        with Image.open(self.root / "run-1" / "rig_overlay.png") as overlay:
            self.assertGreater(overlay.width, 2 * 10)

    def test_rig_gif_pairs_art_and_part_colors_at_the_requested_scale(self):
        frames, joints, rig = standard_motion()
        self.write_case(frames, joints=joints, rig=rig, animations={"move": {"frames": [0, 1], "frame_ms": 150}})
        summary = sprite.check_sheet(self.root / "spec.json", self.root / "sheet.png", self.root / "profile.json",
                                     self.root / "scaled", scale=3)
        self.assertEqual(summary["preview_scale"], 3)
        self.assertEqual(summary["outputs"]["rig_previews"], {"move": "animations/move-rig.gif"})
        with Image.open(self.root / "scaled" / "animations" / "move.gif") as clean:
            self.assertEqual((clean.size, clean.n_frames, clean.info["duration"]), ((30, 30), 2, 150))
        with Image.open(self.root / "scaled" / "animations" / "move-rig.gif") as rig_preview:
            self.assertEqual(rig_preview.n_frames, 2)
            # Two 30 px panels side by side, separated and framed by 8 px gaps.
            self.assertEqual(rig_preview.width, 2 * 30 + 3 * 8)
            rig_preview.seek(1)
            pixels = np.asarray(rig_preview.convert("RGB"))
        part_panel = pixels[16:46, 2 * 8 + 30:2 * 8 + 60]
        # The arm cell (4, 2) in frame 1 shows the arm's part color under the skeleton lines.
        arm_color = sprite.PART_COLORS[2]
        self.assertTrue(np.any(np.all(part_panel == arm_color, axis=2)))
        with self.assertRaisesRegex(ValueError, "preview scale"):
            sprite.check_sheet(self.root / "spec.json", self.root / "sheet.png", self.root / "profile.json",
                               self.root / "bad-scale", scale=17)
        self.assertFalse((self.root / "bad-scale").exists())

    def test_part_map_must_match_the_art(self):
        def clear_arm_cell(sheet):
            sheet[2, 11 + 4] = 0
        summary = self.run_motion(sheet_hook=clear_arm_cell)
        self.assertIn(("PART_MAP_ON_TRANSPARENT", 1, None), self.codes(summary))

        def extra_dot(sheet):
            sheet[0, 11 + 9] = COLORS["D"]
        summary = self.run_motion(sheet_hook=extra_dot)
        self.assertIn(("UNASSIGNED_VISIBLE_CELLS", 1, None), self.codes(summary))

        def partial(frames, joints, rig):
            rig["coverage"] = "partial"
        summary = self.run_motion(partial, sheet_hook=extra_dot)
        self.assertEqual(summary["status"], "pass", summary["issues"])

    def test_fixed_part_must_not_change(self):
        def recolor(frames, joints, rig):
            frames[1][(0, 9)] = ("g", "D")
        self.assertIn(("FIXED_PART_CHANGED", 1, "floor"), self.codes(self.run_motion(recolor)))

    def test_rigid_part_keeps_exact_dots(self):
        def recolor(frames, joints, rig):
            frames[1][(2, 2)] = ("x", "D")
        self.assertIn(("RIGID_PART_CHANGED", 1, "box"), self.codes(self.run_motion(recolor)))

    def test_rigid_dots_must_follow_their_pivot(self):
        def lag(frames, joints, rig):
            joints[1]["p"] = [1, 1]
        codes = self.codes(self.run_motion(lag))
        self.assertIn(("PART_JOINT_MISMATCH", 1, "box"), codes)

        def fraction(frames, joints, rig):
            joints[1]["p"] = [1.5, 1]
        self.assertIn(("PART_JOINT_MISMATCH", 1, "box"), self.codes(self.run_motion(fraction)))

    def test_rigid_axis_limits_sliding_direction(self):
        def vertical(frames, joints, rig):
            rig["parts"]["box"]["axis"] = [0, 1]
        self.assertIn(("RIGID_AXIS_VIOLATION", 1, "box"), self.codes(self.run_motion(vertical)))

        def horizontal(frames, joints, rig):
            rig["parts"]["box"]["axis"] = [1, 0]
        self.assertEqual(self.run_motion(horizontal)["status"], "pass")

    def test_bone_part_dots_must_follow_the_skeleton(self):
        def wrong_pose(frames, joints, rig):
            for cell in [c for c, v in frames[1].items() if v[0] == "r"]:
                del frames[1][cell]
            for x in range(4, 9):
                for y in (5, 6):
                    frames[1][(x, y)] = ("r", "C")
        codes = self.codes(self.run_motion(wrong_pose))
        self.assertIn(("PART_OFF_SKELETON", 1, "arm"), codes)
        self.assertIn(("JOINT_OFF_PART", 1, "arm"), codes)

    def test_bone_length_must_stay_within_tolerance(self):
        def stretch(frames, joints, rig):
            joints[1]["e"] = [4.5, 8]
        self.assertIn(("BONE_LENGTH_CHANGED", 1, "arm"), self.codes(self.run_motion(stretch)))

        def tolerate(frames, joints, rig):
            joints[1]["e"] = [4.5, 6.8]
            rig["parts"]["arm"]["length_tolerance"] = 1.0
        self.assertNotIn(("BONE_LENGTH_CHANGED", 1, "arm"), self.codes(self.run_motion(tolerate)))

    def test_thickened_part_changes_area(self):
        def thicken(frames, joints, rig):
            frames[1] = {cell: value for cell, value in frames[0].items()}
            frames[1][(1, 1)] = frames[1][(2, 1)] = ("x", "B")
            joints[1] = dict(joints[0])
            for x in range(4, 9):
                frames[1][(x, 4)] = ("r", "C")
        codes = self.codes(self.run_motion(thicken))
        self.assertEqual(codes, {("PART_AREA_CHANGED", 1, "arm")})

    def test_part_drift_catches_sideways_slides(self):
        first = {(x, y): ("r", "C") for x in range(2, 9) for y in range(2, 6)}
        second = {(x, y + 2): value for (x, y), value in first.items()}
        joints = [{"s": [2, 3.5], "e": [8, 3.5]}] * 2
        rig = {"joints": {"s": {}, "e": {}},
               "parts": {"bar": {"token": "r", "motion": "bone", "bone": ["s", "e"], "min_shape_match": 0.5}}}
        self.write_case([first, second], joints=joints, rig=rig)
        summary = self.check()
        self.assertEqual(self.codes(summary), {("PART_DRIFT", 1, "bar")})
        self.assertEqual(summary["rig"]["parts"]["bar"]["frames"][1]["drift"], {"along": 0.0, "across": 2.0})

    def covered_case(self, shield_z_first, hidden=None, depths=None, shield_cells=None, arm_cells=None):
        arm = {(x, y): ("r", "C") for x in range(4, 9) for y in (2, 3)}
        shield = {(x, y): ("w", "D") for x in range(3, 10) for y in (6, 7)}
        first = {**arm, **shield}
        # The shield keeps its 14 cells; by default it lies exactly over the arm.
        second = dict(shield_cells if shield_cells is not None else
                      {(x, y): ("w", "D") for x in range(3, 10) for y in (2, 3)})
        for cell, value in (arm_cells or {}).items():
            second.setdefault(cell, value)
        parts = {"arm": {"token": "r", "motion": "bone", "bone": ["s", "e"]},
                 "shield": {"token": "w", "motion": "free"}}
        if shield_z_first:
            parts = {"shield": parts["shield"], "arm": parts["arm"]}
        rig = {"joints": {"s": {}, "e": {}}, "parts": parts}
        joints = [{"s": [4, 2.5], "e": [8, 2.5]}] * 2
        self.write_case([first, second], joints=joints, rig=rig, hidden=hidden, depths=depths)
        return self.check()

    def test_hidden_part_needs_a_part_drawn_in_front(self):
        self.assertIn(("PART_MISSING", 1, "arm"), self.codes(self.covered_case(False)))
        self.assertEqual(self.covered_case(False, hidden={1: ["arm"]})["status"], "pass")
        away = {(x, y): ("w", "D") for x in range(3, 10) for y in (6, 7)}
        summary = self.covered_case(False, hidden={1: ["arm"]}, shield_cells=away)
        self.assertIn(("OCCLUSION_WITHOUT_OCCLUDER", 1, "arm"), self.codes(summary))
        summary = self.covered_case(True, hidden={1: ["arm"]})
        self.assertIn(("OCCLUSION_WITHOUT_OCCLUDER", 1, "arm"), self.codes(summary))

    def test_partial_cover_depends_on_drawing_order(self):
        # The shield covers the arm's outer three columns in frame 1.
        partial = {(x, y): ("w", "D") for x in range(6, 10) for y in (2, 3)}
        partial.update({(x, y): ("w", "D") for x in range(6, 9) for y in (4, 5)})
        visible_arm = {(x, y): ("r", "C") for x in (4, 5) for y in (2, 3)}
        front = self.covered_case(False, shield_cells=partial, arm_cells=visible_arm)
        self.assertEqual(front["status"], "pass", front["issues"])
        behind = self.covered_case(True, shield_cells=partial, arm_cells=visible_arm)
        self.assertIn(("PART_OFF_SKELETON", 1, "arm"), self.codes(behind))
        override = self.covered_case(True, shield_cells=partial, arm_cells=visible_arm, depths={1: {"shield": 5}})
        self.assertEqual(override["status"], "pass", override["issues"])

    def test_child_must_touch_parent_unless_a_front_part_covers_the_joint(self):
        def case(cover_first):
            cells = {(1, 1): ("u", "A"), (2, 1): ("u", "A"), (1, 3): ("l", "B"), (2, 3): ("l", "B"),
                     (1, 2): ("c", "C"), (2, 2): ("c", "C")}
            parts = {"upper": {"token": "u", "motion": "free"},
                     "lower": {"token": "l", "motion": "free", "parent": "upper"},
                     "cover": {"token": "c", "motion": "free"}}
            if cover_first:
                parts = {"cover": parts["cover"], "upper": parts["upper"], "lower": parts["lower"]}
            self.write_case([cells], joints=[{}], rig={"joints": {}, "parts": parts}, size=(4, 5))
            return self.check()
        self.assertEqual(case(False)["status"], "pass")
        self.assertIn(("PART_DETACHED", 0, "lower"), self.codes(case(True)))

    def test_joint_rules_fixed_and_step(self):
        def fix(frames, joints, rig):
            rig["joints"]["s"]["fixed"] = True
        self.assertIn(("FIXED_JOINT_MOVED", 1, None), self.codes(self.run_motion(fix)))

        def limit(frames, joints, rig):
            rig["max_joint_step"] = 4
        summary = self.run_motion(limit)
        steps = {(i["frame"], i["joint"]) for i in summary["issues"] if i["code"] == "JOINT_STEP_EXCEEDED"}
        # The looping sequence also checks the wrap from frame 1 back to frame 0.
        self.assertEqual(steps, {(1, "e"), (0, "e")})

    def test_new_colors_need_review(self):
        def recolor(frames, joints, rig):
            frames[1][(4, 6)] = ("r", "D")
        summary = self.run_motion(recolor)
        self.assertEqual(summary["status"], "review")
        self.assertIn(("PART_COLOR_ADDED", 1, "arm"), self.codes(summary))

    def test_missing_rigid_part_without_hidden_declaration_fails(self):
        def remove(frames, joints, rig):
            for cell in [c for c, v in frames[1].items() if v[0] == "x"]:
                del frames[1][cell]
        self.assertIn(("PART_MISSING", 1, "box"), self.codes(self.run_motion(remove)))


class SpecValidationTests(unittest.TestCase):
    def base(self):
        frames, joints, rig = standard_motion()
        maps = [frame((10, 10), cells)[1] for cells in frames]
        return {"schema_version": 1, "frame_size": "10x10", "layout": {"columns": 2, "rows": 1, "spacing": 1},
                "animations": {"move": {"frames": [0, 1]}}, "rig": rig,
                "frames": [{"parts": maps[i], "joints": joints[i]} for i in range(2)]}

    def test_valid_spec_parses(self):
        plan = sprite.parse_spec(self.base())
        self.assertEqual(plan.layout.sheet_size, (21, 10))
        self.assertEqual([part.z for part in plan.rig.parts], [0, 1, 2])

    def test_invalid_specs_are_rejected(self):
        cases = {
            "unknown field": lambda d: d.update(colour=1),
            "schema version": lambda d: d.update(schema_version=2),
            "boolean column": lambda d: d["layout"].update(columns=True),
            "frame count": lambda d: d.update(frame_count=3),
            "sheet size": lambda d: d.update(frame_size="4096x10"),
            "edge margin": lambda d: d.update(edge_margin=5),
            "duplicate token": lambda d: d["rig"]["parts"]["box"].update(token="g"),
            "reserved token": lambda d: d["rig"]["parts"]["box"].update(token="."),
            "rigid without pivot": lambda d: d["rig"]["parts"]["box"].pop("pivot"),
            "pivot on bone": lambda d: d["rig"]["parts"]["arm"].update(pivot="p"),
            "bone joints": lambda d: d["rig"]["parts"]["arm"].update(bone=["s", "s"]),
            "bone list": lambda d: d["rig"]["parts"]["arm"].update(bone=[["s"], "e"]),
            "unknown parent": lambda d: d["rig"]["parts"]["arm"].update(parent="hand"),
            "parent cycle": lambda d: (d["rig"]["parts"]["arm"].update(parent="box"),
                                       d["rig"]["parts"]["box"].update(parent="arm")),
            "missing joint": lambda d: d["frames"][1]["joints"].pop("e"),
            "joint outside": lambda d: d["frames"][1]["joints"].update(e=[12, 2]),
            "nan joint": lambda d: d["frames"][1]["joints"].update(e=[float("nan"), 2]),
            "short part row": lambda d: d["frames"][0]["parts"].__setitem__(0, "...."),
            "undeclared token": lambda d: d["frames"][0]["parts"].__setitem__(0, "Q........."),
            "hidden yet shown": lambda d: d["frames"][1].update(hidden=["arm"]),
            "hidden unknown": lambda d: d["frames"][1].update(hidden=["tail"]),
            "z override": lambda d: d["frames"][1].update(z={"tail": 1}),
            "reference missing part": lambda d: (
                d["rig"]["parts"]["arm"].update(reference_frame=1),
                d["frames"][1].update(parts=[row.replace("r", ".") for row in d["frames"][1]["parts"]])),
            "short bone": lambda d: d["frames"][0]["joints"].update(e=[4.5, 2.5]),
            "animation index": lambda d: d["animations"]["move"].update(frames=[0, 2]),
            "durations": lambda d: d["animations"]["move"].update(durations_ms=[100]),
            "duration and frame_ms": lambda d: d["animations"]["move"].update(durations_ms=[1, 1], frame_ms=5),
            "animation id": lambda d: d.update(animations={"bad id": {"frames": [0]}}),
            "rows in one frame": lambda d: (d.update(palette={"a": HEX["A"]}),
                                            d["frames"][0].update(rows=["a" * 10] * 10)),
            "rows without palette": lambda d: [f.update(rows=["." * 10] * 10) for f in d["frames"]],
            "palette twice": lambda d: d.update(palette={}, palette_file="p.json"),
            "rig without frames": lambda d: d.pop("frames"),
            "parts without rig": lambda d: d.pop("rig"),
            "tolerance range": lambda d: d["rig"].update(defaults={"min_shape_match": 2}),
            "max step": lambda d: d["rig"].update(max_joint_step=0),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                document = copy.deepcopy(self.base())
                mutate(document)
                with self.assertRaises(ValueError):
                    sprite.parse_spec(json.loads(json.dumps(document)) if name != "nan joint" else document)

    def test_json_loader_rejects_duplicates_and_constants(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            for text in ('{"schema_version": 1, "schema_version": 1}', '{"schema_version": NaN}'):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    sprite.load_spec(path)


class CommandLineTests(SpriteCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sprite.run_cli([str(value) for value in argv])
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes_follow_the_project_convention(self):
        frames, joints, rig = standard_motion()
        self.write_case(frames, joints=joints, rig=rig)
        code, output, _ = self.run_cli("list", "--spec", self.root / "spec.json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["rig"]["parts"][2]["bone"], ["s", "e"])
        args = ["check", "--spec", self.root / "spec.json", "--sheet", self.root / "sheet.png",
                "--profile", self.root / "profile.json"]
        self.assertEqual(self.run_cli(*args, "--out-dir", self.root / "ok")[0], 0)
        frames[1][(0, 9)] = ("g", "D")
        self.write_case(frames, joints=joints, rig=rig)
        self.assertEqual(self.run_cli(*args, "--out-dir", self.root / "bad")[0], 2)
        code, _, error = self.run_cli(*args, "--out-dir", self.root / "bad")
        self.assertEqual(code, 1)
        self.assertIn("Output directory", error)
        (self.root / "spec.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.run_cli(*args, "--out-dir", self.root / "invalid")[0], 1)

    def test_output_directory_must_not_contain_inputs(self):
        frames, joints, rig = standard_motion()
        self.write_case(frames, joints=joints, rig=rig)
        code, _, error = self.run_cli("check", "--spec", self.root / "spec.json", "--sheet", self.root / "sheet.png",
                                      "--profile", self.root / "profile.json", "--out-dir", self.root)
        self.assertEqual(code, 1)


class BundledExampleTests(unittest.TestCase):
    def test_examples_regenerate_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            examples.walk_example(Path(tmp) / "sprite-walk")
            examples.lever_example(Path(tmp) / "sprite-lever")
            for name in ("sprite-walk", "sprite-lever"):
                for file in ("spec.json", "profile.json"):
                    with self.subTest(example=name, file=file):
                        self.assertEqual((Path(tmp) / name / file).read_bytes(), (EXAMPLES / name / file).read_bytes())

    def test_bundled_examples_build_and_pass(self):
        for name, parts in (("sprite-walk", 8), ("sprite-lever", 3)):
            with self.subTest(example=name), tempfile.TemporaryDirectory() as tmp:
                spec, profile = EXAMPLES / name / "spec.json", EXAMPLES / name / "profile.json"
                before = (digest(spec), digest(profile))
                sprite.build_sheet(spec, Path(tmp) / "build")
                summary = sprite.check_sheet(spec, Path(tmp) / "build" / "rendered.png", profile, Path(tmp) / "check")
                self.assertEqual(summary["status"], "pass", summary["issues"])
                self.assertEqual(len(summary["rig"]["parts"]), parts)
                self.assertEqual((digest(spec), digest(profile)), before)


class KnightAnimationTests(unittest.TestCase):
    def test_generator_reproduces_specs_and_keeps_the_readme_knight_at_rest(self):
        artwork = json.loads(knight.ARTWORK.read_text(encoding="utf-8"))
        x0, y0 = knight.OFFSET
        with tempfile.TemporaryDirectory() as tmp:
            subprocess_args = ["--out-dir", tmp]
            with unittest.mock.patch.object(sys, "argv", ["generate_knight_animations.py", *subprocess_args]):
                knight.main()
            for name in ("swing", "block", "walk"):
                for file in ("spec.json", "profile.json"):
                    with self.subTest(animation=name, file=file):
                        self.assertEqual((Path(tmp) / name / file).read_bytes(),
                                         (KNIGHT_ANIMATIONS / name / file).read_bytes())
                rows = json.loads((Path(tmp) / name / "spec.json").read_text(encoding="utf-8"))["frames"][0]["rows"]
                rest = [row[x0:x0 + len(artwork["rows"][0])] for row in rows[y0:y0 + len(artwork["rows"])]]
                self.assertEqual(rest, artwork["rows"])

    def test_knight_block_passes_its_rig(self):
        spec, profile = KNIGHT_ANIMATIONS / "block" / "spec.json", KNIGHT_ANIMATIONS / "block" / "profile.json"
        with tempfile.TemporaryDirectory() as tmp:
            sprite.build_sheet(spec, Path(tmp) / "build")
            summary = sprite.check_sheet(spec, Path(tmp) / "build" / "rendered.png", profile, Path(tmp) / "check",
                                         scale=1)
        self.assertEqual(summary["status"], "pass", summary["issues"])
        self.assertEqual(len(summary["rig"]["parts"]), 10)
        self.assertEqual(summary["rig"]["parts"]["shield"]["frames"][2]["offset"], [-10, -1])


if __name__ == "__main__":
    unittest.main()
