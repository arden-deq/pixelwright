"""Independent pixel fixtures for the sprite-gen manifest adapter."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pixel_atlas as atlas
import pixelwright as pw


class AtlasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sheet = self.root / "sheet.png"
        self.manifest = self.root / "manifest.json"
        self.out = self.root / "audit"
        self.pixels = np.zeros((32, 96, 4), dtype=np.uint8)
        for i in range(3):
            self.pixels[10:22, i * 32 + 12:i * 32 + 20] = (180, 40, 20, 255)
        self.data = {
            "cell": {"width": 32, "height": 32, "safe_margin_x": 4, "safe_margin_y": 4},
            "animation": {"cellWidth": 32, "cellHeight": 32, "rows": {"charge": {"frames": 3, "fps": 10, "loop": True}}},
            "frame_layout": {"sheetWidth": 96, "sheetHeight": 32, "cellWidth": 32, "cellHeight": 32,
                             "rows": {"charge": [{"x": i * 32, "y": 0, "w": 32, "h": 32} for i in range(3)]}},
        }
        self.save()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        Image.fromarray(self.pixels).save(self.sheet)
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")

    def check(self, **kwargs):
        return atlas.check_sprite_gen(self.sheet, self.manifest, self.out, max_colors=kwargs.pop("max_colors", 2), **kwargs)

    def codes(self, report):
        return {i["code"] for i in report["issues"]}

    def test_pass_measures_actual_pixels_and_preserves_both_inputs(self):
        before = {p: p.read_bytes() for p in (self.sheet, self.manifest)}
        report = self.check()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["palette"]["visible_rgb_colors"], 1)
        self.assertEqual(report["frames"][0]["bbox_size"], [8, 12])
        self.assertEqual(report["frames"][0]["visible_pixels"], 96)
        self.assertEqual(report["frames"][0]["margins"], {"left": 12, "right": 12, "top": 10, "bottom": 10})
        self.assertEqual(report["states"][0]["median"], {"width": 8, "height": 12, "visible_pixels": 96})
        self.assertTrue(report["provenance"]["inputs_unchanged"])
        self.assertEqual(report["pixel_grid_status"], "not_checked")
        self.assertEqual(report["motion_status"], "not_checked")
        for p, data in before.items():
            self.assertEqual(p.read_bytes(), data)
        for name in ("report.json", "layout_overlay.png", "frames.png"):
            self.assertTrue((self.out / name).is_file())

    def test_palette_budget_is_shared_across_frames(self):
        self.pixels[10:22, 44:52] = (10, 150, 70, 255)
        self.pixels[10:22, 76:84] = (20, 50, 160, 255)
        self.save()
        report = self.check()
        self.assertEqual(report["palette"]["visible_rgb_colors"], 3)
        self.assertEqual([f["visible_rgb_colors"] for f in report["frames"]], [1, 1, 1])
        self.assertEqual(report["checks"]["palette"], "fail")
        self.assertIn("PALETTE_OVER_BUDGET", self.codes(report))

    def test_hidden_rgb_is_not_a_visible_palette_color(self):
        self.pixels[0, 0] = (1, 2, 3, 0)
        self.save()
        self.assertEqual(self.check()["palette"]["visible_rgb_colors"], 1)

    def test_translucent_visible_pixel_counts_for_palette_and_margin(self):
        self.pixels[0, 0] = (1, 2, 3, 1)
        self.save()
        report = self.check(max_colors=1)
        self.assertIn("PALETTE_OVER_BUDGET", self.codes(report))
        issue = next(i for i in report["issues"] if i["code"] == "EDGE_MARGIN_VIOLATION")
        self.assertEqual(issue["sides"], ["left", "top"])

    def test_request_supplies_palette_budget_without_reading_its_paths(self):
        request = self.root / "request.json"
        request.write_text(json.dumps({"fit": {"palette_size": 1}, "character": {"base_image": "/not/an/input.png"}}))
        report = self.check(max_colors=None, request_path=request)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["contract"]["palette"]["source"], "request.fit.palette_size")
        self.assertEqual(report["provenance"]["request"]["sha256"], pw.sha256(request))

    def test_missing_palette_or_margin_contract_remains_review(self):
        self.data.pop("cell")
        self.save()
        report = self.check(max_colors=None)
        self.assertEqual(report["status"], "review")
        self.assertIn("PALETTE_BUDGET_UNDECLARED", self.codes(report))
        self.assertIn("SAFE_MARGIN_UNDECLARED", self.codes(report))

    def test_conflicting_override_is_disclosed_and_requires_review(self):
        report = self.check(margin_x=0)
        self.assertIn("CONSTRAINT_OVERRIDE", self.codes(report))
        self.assertEqual(report["contract"]["margin_x"]["value"], 0)
        self.assertEqual(report["checks"]["margins"], "review")

    def test_exact_margin_boundary_passes_one_pixel_inside_fails(self):
        self.pixels[10:22, :32] = 0
        self.pixels[4:16, 4:12] = (180, 40, 20, 255)
        self.save()
        self.assertNotIn("EDGE_MARGIN_VIOLATION", self.codes(self.check()))
        self.pixels[4:16, 4:12] = 0
        self.pixels[3:15, 3:11] = (180, 40, 20, 255)
        self.save()
        report = atlas.check_sprite_gen(self.sheet, self.manifest, self.root / "bad-margin", max_colors=2)
        self.assertEqual(report["checks"]["margins"], "fail")

    def test_size_shrink_is_review_with_measured_ratios_not_anatomy_failure(self):
        self.pixels[:, 64:] = 0
        self.pixels[13:19, 78:82] = (180, 40, 20, 255)
        self.save()
        report = self.check()
        self.assertEqual(report["status"], "review")
        self.assertEqual(report["checks"]["size_consistency"], "review")
        frame = report["frames"][2]
        self.assertEqual(frame["size_ratios"], {"width": .5, "height": .5, "visible_pixels": .25})
        self.assertEqual(frame["size_status"], "review")
        self.assertIn("FRAME_SIZE_OUTLIER", self.codes(report))

    def test_translation_does_not_look_like_a_size_change(self):
        self.pixels[:, 64:] = 0
        self.pixels[8:20, 72:80] = (180, 40, 20, 255)
        self.save()
        self.assertEqual(self.check()["checks"]["size_consistency"], "pass")

    def test_area_change_is_detected_when_bounds_stay_the_same(self):
        self.pixels[11:21, 77:83] = 0
        self.save()
        report = self.check()
        issue = next(i for i in report["issues"] if i["code"] == "FRAME_SIZE_OUTLIER")
        self.assertEqual(issue["metrics"], ["visible_pixels"])

    def test_empty_frame_fails_and_two_visible_frames_cannot_certify_size(self):
        self.pixels[:, 64:] = 0
        self.save()
        report = self.check()
        self.assertEqual(report["status"], "fail")
        self.assertIn("EMPTY_FRAME", self.codes(report))
        self.assertIn("SIZE_REFERENCE_INSUFFICIENT", self.codes(report))

    def test_each_state_has_its_own_size_baseline(self):
        pixels = np.zeros((64, 96, 4), dtype=np.uint8)
        pixels[:32] = self.pixels
        for i in range(3):
            pixels[40:56, i * 32 + 8:i * 32 + 24] = (180, 40, 20, 255)
        self.pixels = pixels
        self.data["frame_layout"]["sheetHeight"] = 64
        self.data["frame_layout"]["rows"]["attack"] = [{"x": i * 32, "y": 32, "w": 32, "h": 32} for i in range(3)]
        self.data["animation"]["rows"]["attack"] = {"frames": 3}
        self.save()
        report = self.check()
        self.assertEqual(report["checks"]["size_consistency"], "pass")
        self.assertEqual([s["median"]["width"] for s in report["states"]], [8, 16])

    def test_size_threshold_is_inclusive_and_ratios_use_source_pixels(self):
        self.pixels[:] = 0
        for i, width in enumerate((10, 10, 11)):
            self.pixels[10:22, i * 32 + 10:i * 32 + 10 + width] = (180, 40, 20, 255)
        self.save()
        report = self.check()
        self.assertEqual(report["frames"][2]["size_ratios"]["width"], 1.1)
        self.assertEqual(report["checks"]["size_consistency"], "pass")

    def test_request_margin_fallback_and_explicit_limits(self):
        self.data.pop("cell")
        self.save()
        request = self.root / "request.json"
        request.write_text(json.dumps({"fit": {"palette_size": 2}, "cell": {"safe_margin": 4}}))
        report = self.check(max_colors=None, request_path=request)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["contract"]["margin_x"]["value"], 4)

    def test_invalid_cli_input_returns_error_without_writing_a_result(self):
        self.data["frame_layout"]["sheetWidth"] = 10
        self.save()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = pw.run_cli(["sprite-gen", "--sheet", str(self.sheet), "--manifest", str(self.manifest),
                               "--max-colors", "1", "--out-dir", str(self.out)])
        self.assertEqual(code, 1)
        self.assertFalse(self.out.exists())

    def test_uses_rectangles_in_manifest_order_not_an_assumed_grid(self):
        self.data["frame_layout"]["rows"]["charge"].reverse()
        self.save()
        report = self.check()
        self.assertEqual([f["rect"]["x"] for f in report["frames"]], [64, 32, 0])

    def test_unused_atlas_area_must_be_transparent_and_counts_in_palette(self):
        self.data["frame_layout"]["rows"]["charge"].pop()
        self.data["animation"]["rows"]["charge"]["frames"] = 2
        self.save()
        report = self.check()
        self.assertIn("VISIBLE_PIXELS_OUTSIDE_FRAMES", self.codes(report))
        self.assertEqual(report["checks"]["layout"], "fail")

    def test_invalid_or_ambiguous_manifest_is_an_input_error(self):
        mutations = []
        for field, value in (("x", True), ("x", -1), ("x", 95), ("w", 0), ("w", 31), ("y", .5)):
            item = copy.deepcopy(self.data)
            item["frame_layout"]["rows"]["charge"][0][field] = value
            mutations.append(item)
        item = copy.deepcopy(self.data)
        item["frame_layout"]["rows"]["charge"][1]["x"] = 0
        mutations.append(item)
        item = copy.deepcopy(self.data)
        item["frame_layout"]["sheetWidth"] = 95
        mutations.append(item)
        item = copy.deepcopy(self.data)
        item["animation"]["rows"]["charge"]["frames"] = 4
        mutations.append(item)
        item = copy.deepcopy(self.data)
        item["cell"]["width"] = 31
        mutations.append(item)
        for data in mutations:
            with self.subTest(data=data):
                self.manifest.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    self.check()
                self.assertFalse(self.out.exists())

    def test_duplicate_json_and_nonfinite_numbers_are_rejected(self):
        for value in ('{"frame_layout":{},"frame_layout":{}}', '{"value":NaN}', '{"value":Infinity}'):
            with self.subTest(value=value):
                self.manifest.write_text(value)
                with self.assertRaises(ValueError):
                    self.check()

    def test_invalid_tolerances_and_budget_are_not_accepted(self):
        for kwargs in ({"size_tolerance": float("nan")}, {"size_tolerance": True},
                       {"area_tolerance": -1}, {"area_tolerance": float("inf")},
                       {"margin_x": -1}, {"max_colors": True}, {"max_colors": 0}, {"max_colors": 257}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.check(**kwargs)

    def test_cli_runs_real_adapter_and_reports_qa_exit_code(self):
        self.pixels[0, 0] = (1, 2, 3, 255)
        self.save()
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = pw.run_cli(["sprite-gen", "--sheet", str(self.sheet), "--manifest", str(self.manifest),
                               "--max-colors", "1", "--out-dir", str(self.out)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout.getvalue())["checks"]["palette"], "fail")

    def test_output_cannot_overwrite_an_input_or_existing_result(self):
        before = self.sheet.read_bytes()
        with self.assertRaises(ValueError):
            atlas.check_sprite_gen(self.sheet, self.manifest, self.root, max_colors=2)
        self.out.mkdir()
        (self.out / "keep.txt").write_text("keep")
        with self.assertRaises(ValueError):
            self.check()
        self.assertEqual(self.sheet.read_bytes(), before)
        self.assertEqual((self.out / "keep.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
