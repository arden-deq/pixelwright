"""The profile gate's core guarantee: every declared condition is checked on every sample."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pixelwright as pw

INK = [(30, 26, 43, 255), (200, 64, 74, 255), (240, 192, 144, 255), (63, 124, 196, 255)]


def art(width, height, *, transparent_border=True, seed=7):
    """Random 1x art: every column and row has color edges, so the dot lattice is 1x1."""
    rng = np.random.default_rng(seed)
    arr = np.array(INK, dtype=np.uint8)[rng.integers(0, len(INK), (height, width))]
    if transparent_border:
        arr[0, :] = arr[-1, :] = arr[:, 0] = arr[:, -1] = 0
    return arr


def enlarge(arr, scale):
    return np.repeat(np.repeat(arr, scale, axis=0), scale, axis=1)


class ConditionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.count = 0

    def tearDown(self):
        self.tmp.cleanup()

    def audit(self, arr, profile):
        self.count += 1
        case = self.root / str(self.count)
        case.mkdir()
        Image.fromarray(np.ascontiguousarray(arr, dtype=np.uint8), "RGBA").save(case / "in.png")
        (case / "profile.json").write_text(json.dumps({"schema_version": 1, **profile}), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = pw.run_cli(["inspect", str(case / "in.png"), "--profile", str(case / "profile.json"),
                               "--out-dir", str(case / "out")])
        report_path = case / "out" / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
        return code, report

    @staticmethod
    def check(report, check_id):
        return next(c for c in report["checks"] if c["id"] == check_id)["status"]

    @staticmethod
    def codes(report):
        return {i["code"] for i in report["issues"] if i["severity"] in ("fail", "review")}

    def test_every_declared_condition_appears_as_a_check(self):
        code, report = self.audit(enlarge(art(16, 16), 4), {
            "kind": "sprite", "logical_size": "16x16", "scale": 4, "max_colors": 4,
            "allowed_palette": ["#00000000"] + [pw.rgba_hex(c) for c in INK]})
        self.assertEqual(code, 0)
        self.assertEqual([c["id"] for c in report["checks"]],
                         ["image_size", "cell_uniformity", "dot_size", "content", "kind", "alpha",
                          "color_budget", "allowed_palette"])
        self.assertTrue(all(c["status"] == "pass" for c in report["checks"]), report["checks"])
        self.assertEqual(report["layout"]["grid_box"], [0, 0, 63, 63])

    def test_image_size_alone_derives_the_cell_size(self):
        code, report = self.audit(enlarge(art(16, 16), 4), {"kind": "sprite", "logical_size": "16x16", "image_size": "64x64"})
        self.assertEqual(code, 0)
        self.assertEqual(report["contract"]["scale"], 4)

    def test_contradictory_sizes_are_a_profile_error(self):
        for profile in ({"kind": "sprite", "logical_size": "16x16", "image_size": "60x60"},
                        {"kind": "sprite", "logical_size": "16x16", "image_size": "64x48"},
                        {"kind": "sprite", "logical_size": "16x16", "scale": 4, "image_size": "60x60"},
                        {"kind": "sprite", "logical_size": "16x16", "scale": 4, "origin": [2, 2]},
                        {"kind": "sprite", "logical_size": "16x16"},
                        {"kind": "sprite", "logical_size": "16x16", "scale": 1},
                        {"kind": "sprite", "alpha": "opaque", "logical_size": "16x16", "scale": 4},
                        {"kind": "icon", "logical_size": "16x16", "scale": 4},
                        {"logical_size": "16x16", "scale": 4},
                        {"kind": "sprite", "logical_size": "16x16", "scale": 4,
                         "sheet": {"frame_size": "8x8", "columns": 2, "rows": 2}},
                        {"kind": "sheet", "logical_size": "16x16", "scale": 4},
                        {"kind": "sheet", "logical_size": "16x16", "scale": 4,
                         "sheet": {"frame_size": "8x8", "columns": 3, "rows": 2}},
                        {"kind": "sheet", "scale": 4, "alpha": "opaque",
                         "sheet": {"frame_size": "8x8", "columns": 2, "rows": 2, "frame_count": 3}},
                        {"kind": "sheet", "scale": 4, "sheet": {"frame_size": "8x8", "columns": 2}}):
            with self.subTest(profile=profile):
                code, report = self.audit(enlarge(art(16, 16), 4), profile)
                self.assertEqual(code, 1)
                self.assertIsNone(report)

    def test_wrong_png_size_fails_and_hints_at_the_drawn_grid(self):
        code, report = self.audit(enlarge(art(16, 16), 5), {"kind": "sprite", "logical_size": "16x16", "scale": 4})
        self.assertEqual(code, 2)
        self.assertEqual(self.check(report, "image_size"), "fail")
        self.assertEqual(self.check(report, "cell_uniformity"), "not_measured")
        self.assertEqual(report["detected_grid"]["dot_width"], 5)

    def test_one_stray_sample_fails_its_cell(self):
        arr = enlarge(art(16, 16), 4)
        arr[21, 22, 0] ^= 1
        code, report = self.audit(arr, {"kind": "sprite", "logical_size": "16x16", "scale": 4})
        self.assertEqual(code, 2)
        self.assertEqual(report["metrics"]["nonuniform_rgba_cells"], 1)
        self.assertEqual(report["nonuniform_rgba_cell_samples"][0]["source_box"], [20, 20, 23, 23])

    def test_art_coarser_than_the_declared_resolution_fails(self):
        # Declared 32x32 dots at 4 px, but drawn as 16x16 dots of 8 px.
        code, report = self.audit(enlarge(art(16, 16), 8), {"kind": "sprite", "logical_size": "32x32", "scale": 4})
        self.assertEqual(code, 2)
        self.assertEqual(self.check(report, "cell_uniformity"), "pass")
        self.assertEqual(self.check(report, "dot_size"), "fail")
        self.assertIn("logical_size 16x16 with scale 8", next(
            i["detail"] for i in report["issues"] if i["code"] == "COARSER_THAN_DECLARED"))

    def test_coarse_art_with_few_edges_needs_review(self):
        code, report = self.audit(enlarge(art(6, 6, transparent_border=False), 2), {
            "kind": "image", "logical_size": "12x12", "scale": 1, "max_colors": 4})
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "review")
        self.assertEqual(self.check(report, "dot_size"), "review")

    def test_sprite_needs_a_transparent_background(self):
        opaque = enlarge(art(16, 16, transparent_border=False), 4)
        code, report = self.audit(opaque, {"kind": "sprite", "logical_size": "16x16", "scale": 4})
        self.assertEqual(code, 2)
        self.assertIn("SPRITE_WITHOUT_TRANSPARENCY", self.codes(report))
        code, report = self.audit(opaque, {"kind": "image", "logical_size": "16x16", "scale": 4})
        self.assertEqual(code, 0)

    def test_image_is_opaque_unless_alpha_says_otherwise(self):
        sprite_like = enlarge(art(16, 16), 4)
        code, report = self.audit(sprite_like, {"kind": "image", "logical_size": "16x16", "scale": 4})
        self.assertEqual(code, 2)
        self.assertIn("NON_OPAQUE_ALPHA", self.codes(report))
        code, _ = self.audit(sprite_like, {"kind": "image", "alpha": "binary", "logical_size": "16x16", "scale": 4})
        self.assertEqual(code, 0)

    def test_empty_image_fails(self):
        code, report = self.audit(np.zeros((64, 64, 4), np.uint8), {"kind": "sprite", "logical_size": "16x16", "scale": 4})
        self.assertEqual(code, 2)
        self.assertIn("EMPTY_IMAGE", self.codes(report))

    def test_grid_starts_at_the_declared_origin(self):
        canvas = np.zeros((70, 69, 4), np.uint8)
        canvas[3:67, 2:66] = enlarge(art(16, 16), 4)
        profile = {"kind": "sprite", "logical_size": "16x16", "scale": 4, "image_size": "69x70", "origin": [2, 3]}
        code, report = self.audit(canvas, profile)
        self.assertEqual(code, 0, report["issues"])
        self.assertEqual(report["layout"]["grid_box"], [2, 3, 65, 66])
        code, report = self.audit(canvas, {**profile, "origin": [3, 3]})
        self.assertEqual(code, 2)
        self.assertEqual(self.check(report, "cell_uniformity"), "fail")
        self.assertEqual(report["detected_grid"]["origin"], [2, 3])
        canvas[0, 68] = INK[1]
        code, report = self.audit(canvas, profile)
        self.assertEqual(code, 2)
        self.assertEqual(self.check(report, "margin"), "fail")
        self.assertEqual(report["metrics"]["margin_stray_sample"], [{"x": 68, "y": 0}])

    def test_palette_rules_cover_the_whole_png(self):
        arr = enlarge(art(16, 16), 4)
        palette = ["#00000000"] + [pw.rgba_hex(c) for c in INK]
        code, report = self.audit(arr, {"kind": "sprite", "logical_size": "16x16", "scale": 4, "allowed_palette": palette[:-1]})
        self.assertEqual(code, 2)
        self.assertEqual(report["outside_palette_colors"], [palette[-1]])
        code, report = self.audit(arr, {"kind": "sprite", "logical_size": "16x16", "scale": 4, "max_colors": 3})
        self.assertEqual(self.check(report, "color_budget"), "fail")
        canvas = np.zeros((66, 66, 4), np.uint8)
        canvas[:] = (9, 9, 9, 255)
        canvas[1:65, 1:65] = arr
        code, report = self.audit(canvas, {"kind": "sprite", "logical_size": "16x16", "scale": 4, "image_size": "66x66",
                                           "origin": [1, 1], "allowed_palette": palette})
        self.assertEqual(code, 2)
        self.assertEqual(report["outside_palette_colors"], ["#090909FF"])

    def test_native_1x_asset_checks_palette_and_dot_size(self):
        native = art(32, 32)
        code, report = self.audit(native, {"kind": "sprite", "logical_size": "32x32", "scale": 1, "max_colors": 4})
        self.assertEqual(code, 0, report["issues"])
        self.assertEqual(self.check(report, "cell_uniformity"), "not_applicable")
        self.assertGreaterEqual(report["grid_preview"]["magnification"], 4)
        blurred = native.copy()
        blurred[5, 5, :3] = (128, 128, 128)
        code, report = self.audit(blurred, {"kind": "sprite", "logical_size": "32x32", "scale": 1, "max_colors": 4})
        self.assertEqual(self.check(report, "color_budget"), "fail")

    def test_hidden_rgb_follows_the_transparent_rgb_policy(self):
        arr = enlarge(art(16, 16), 4)
        arr[0, 1, :3] = (1, 2, 3)  # invisible RGB inside a transparent cell
        code, report = self.audit(arr, {"kind": "sprite", "logical_size": "16x16", "scale": 4})
        self.assertEqual(self.check(report, "cell_uniformity"), "fail")
        code, report = self.audit(arr, {"kind": "sprite", "logical_size": "16x16", "scale": 4, "transparent_rgb": "visible"})
        self.assertEqual(code, 0)


class SheetTests(ConditionTests):
    """kind sheet: frame slots from the declared layout, each frame a sprite."""

    SHEET = {"frame_size": "6x6", "columns": 3, "rows": 2, "margin": 1, "spacing": 1, "frame_count": 5}
    SIZE = (2 * 1 + 3 * 6 + 2 * 1, 2 * 1 + 2 * 6 + 1 * 1)  # 22x15 dots

    def sheet_cells(self):
        cells = np.zeros((self.SIZE[1], self.SIZE[0], 4), np.uint8)
        for index in range(5):
            x, y = 1 + (index % 3) * 7, 1 + (index // 3) * 7
            cells[y:y + 6, x:x + 6] = art(6, 6, seed=index)
        return cells

    def profile(self, **changes):
        return {"kind": "sheet", "sheet": {**self.SHEET, **changes}, "scale": 4}

    def test_valid_sheet_derives_its_size_and_reports_frames(self):
        code, report = self.audit(enlarge(self.sheet_cells(), 4), self.profile())
        self.assertEqual(code, 0, report["issues"])
        self.assertEqual(report["contract"]["logical_size"], "22x15")
        self.assertEqual(len(report["sheet"]["frames"]), 5)
        self.assertEqual(report["sheet"]["frames"][4]["box"], {"x": 8, "y": 8, "width": 6, "height": 6})
        self.assertEqual(self.check(report, "kind"), "pass")

    def test_logical_size_must_agree_with_the_layout(self):
        code, _ = self.audit(enlarge(self.sheet_cells(), 4), {**self.profile(), "logical_size": "22x15"})
        self.assertEqual(code, 0)
        code, report = self.audit(enlarge(self.sheet_cells(), 4), {**self.profile(), "logical_size": "21x15"})
        self.assertEqual(code, 1)
        self.assertIsNone(report)

    def test_dots_in_gutters_and_unused_slots_fail(self):
        cells = self.sheet_cells()
        cells[0, 5] = INK[0]  # outer margin
        code, report = self.audit(enlarge(cells, 4), self.profile())
        self.assertIn("GUTTER_NOT_EMPTY", self.codes(report))
        cells = self.sheet_cells()
        cells[10, 17] = INK[0]  # sixth slot, beyond frame_count 5
        code, report = self.audit(enlarge(cells, 4), self.profile())
        self.assertEqual(code, 2)
        self.assertIn("UNUSED_SLOT_NOT_EMPTY", self.codes(report))
        self.assertEqual(self.check(report, "kind"), "fail")

    def test_each_frame_needs_dots_and_a_transparent_background(self):
        cells = self.sheet_cells()
        cells[1:7, 8:14] = 0
        code, report = self.audit(enlarge(cells, 4), self.profile())
        self.assertEqual(report["status"], "review")
        self.assertIn("EMPTY_FRAME", self.codes(report))
        cells = self.sheet_cells()
        cells[1:7, 8:14] = INK[2]
        code, report = self.audit(enlarge(cells, 4), self.profile())
        self.assertIn("FRAME_WITHOUT_TRANSPARENCY", self.codes(report))

    def test_edge_margin_catches_clipped_art(self):
        cells = self.sheet_cells()
        code, report = self.audit(enlarge(cells, 4), self.profile(edge_margin=1))
        self.assertEqual(code, 0, report["issues"])
        cells[3, 1] = INK[1]  # first frame's left edge
        code, report = self.audit(enlarge(cells, 4), self.profile(edge_margin=1))
        self.assertIn("EDGE_MARGIN_VIOLATION", self.codes(report))


if __name__ == "__main__":
    unittest.main()
