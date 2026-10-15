# SPDX-License-Identifier: Apache-2.0
"""Run: python -m unittest discover -s tests -v (from skill folder)."""
import json
import io
import hashlib
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pixel_qa as pqa


class GridAuditTests(unittest.TestCase):
    def setUp(self):
        self.stdout = patch("sys.stdout", new=io.StringIO())
        self.stderr = patch("sys.stderr", new=io.StringIO())
        self.stdout.start()
        self.stderr.start()
        self.addCleanup(self.stdout.stop)
        self.addCleanup(self.stderr.stop)
        self.native = np.zeros((8, 8, 4), dtype=np.uint8)
        self.native[:, :, 3] = 0
        self.native[2:6, 2:6] = [210, 50, 70, 255]
        self.native[3:5, 3:5] = [40, 90, 215, 255]
        self.image = Image.fromarray(self.native, "RGBA").resize((32, 32), Image.Resampling.NEAREST)

    def test_valid_nearest_neighbor_score_100(self):
        audit = pqa.inspect_image(self.image, (8, 8))
        self.assertEqual(audit.result["metrics"]["grid_score"], 100)
        self.assertEqual(audit.result["metrics"]["off_grid_logical_cells"], 0)
        self.assertEqual(audit.result["metrics"]["uniform_rgba_cells"], 64)
        self.assertEqual(audit.result["metrics"]["nonuniform_rgba_cells"], 0)
        self.assertTrue(audit.result["metrics"]["square_cell_geometry"])
        self.assertEqual(audit.result["status"], "pass")

    def test_random_intra_cell_changes_detected(self):
        px = np.array(self.image)
        px[9, 9] = [85, 112, 23, 255]
        audit = pqa.inspect_image(Image.fromarray(px, "RGBA"), (8, 8))
        self.assertLess(audit.result["metrics"]["grid_score"], 100)
        self.assertGreater(audit.result["metrics"]["off_grid_logical_cells"], 0)
        self.assertEqual(audit.result["status"], "fail")
        self.assertEqual(audit.result["metrics"]["nonuniform_rgba_cells"], 1)
        self.assertIn("NON_SOLID_GRID_CELLS", {i["code"] for i in audit.result["issues"]})

    def test_single_level_color_difference_is_strictly_rejected(self):
        pixels = np.array(self.image)
        pixels[9, 9, 0] += 1  # even one channel changed by 1 is off-grid
        bad = Image.fromarray(pixels, "RGBA")
        audit = pqa.inspect_image(bad, (8, 8), tolerance=8, min_grid_score=98)
        self.assertEqual(audit.result["metrics"]["nonuniform_rgba_cells"], 1)
        self.assertEqual(audit.result["status"], "fail")

    def test_exact_RGBA_alpha_differences_rejected(self):
        pixels = np.array(self.image)
        pixels[9, 9, 3] = 254
        audit = pqa.inspect_image(Image.fromarray(pixels, "RGBA"), (8, 8))
        self.assertEqual(audit.result["metrics"]["nonuniform_rgba_cells"], 1)
        self.assertEqual(audit.result["status"], "fail")

    def test_shift_detects_violations(self):
        original = np.asarray(self.image).copy()
        shifted = np.roll(original, 1, axis=1)
        audit = pqa.inspect_image(Image.fromarray(shifted, "RGBA"), (8, 8))
        self.assertLess(audit.result["metrics"]["grid_score"], 100)
        self.assertGreater(audit.result["metrics"]["off_grid_logical_cells"], 0)

    def test_native_grid_not_measurable(self):
        native = Image.fromarray(self.native, "RGBA")
        audit = pqa.inspect_image(native, (8, 8))
        self.assertIsNone(audit.result["metrics"]["grid_score"])
        self.assertFalse(audit.result["metrics"]["grid_measurable"])

    def test_transparent_hidden_rgb_ignored(self):
        raw = np.array(self.image)
        raw[0, 0, :3] = [255, 123, 65]  # transparent, same visible color
        audit = pqa.inspect_image(Image.fromarray(raw, "RGBA"), (8, 8), transparent_rgb="visible")
        self.assertEqual(audit.result["metrics"]["grid_score"], 100)

    def test_transparent_hidden_rgb_rejected_by_default_exact_policy(self):
        raw = np.array(self.image)
        raw[0, 0, :3] = [255, 123, 65]
        audit = pqa.inspect_image(Image.fromarray(raw, "RGBA"), (8, 8))
        self.assertEqual(audit.result["status"], "fail")
        self.assertEqual(audit.result["metrics"]["nonuniform_rgba_cells"], 1)
        self.assertEqual(audit.result["settings"]["transparent_rgb"], "exact")

    def test_noninteger_dimensions_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot be evenly divided"):
            pqa.inspect_image(Image.new("RGBA", (31, 32)), (8, 8))

    def test_geometry_validation_integer_and_square(self):
        good = pqa.grid_geometry((512, 768), (64, 96), (512, 768))
        self.assertEqual(good["status"], "pass")
        self.assertEqual(good["integer_scale"], 8)
        wrong_divisor = pqa.grid_geometry((1086, 1448), (96, 128))
        self.assertEqual(wrong_divisor["status"], "fail")
        self.assertIn("NON_INTEGER_PIXEL_SCALE", [i["code"] for i in wrong_divisor["issues"]])
        rectangular = pqa.grid_geometry((64, 96), (8, 8))
        self.assertEqual(rectangular["status"], "fail")
        self.assertIn("NON_SQUARE_CELL", [i["code"] for i in rectangular["issues"]])

    def test_grid_layer_is_drawn_on_exact_pixel_boundaries(self):
        layer = pqa.create_grid_lines((32, 32), (8, 8))
        self.assertGreater(layer.getpixel((4, 2))[3], 0)  # vertical grid boundary x=4
        self.assertGreater(layer.getpixel((3, 8))[3], 0)  # horizontal grid boundary y=8
        self.assertEqual(layer.getpixel((3, 2))[3], 0)  # cell interior stays transparent

    def assert_every_actual_grid_boundary(self, layer, logical_size, scale):
        self.assertEqual(layer.mode, "RGBA")
        width, height = layer.size
        self.assertEqual((width, height), tuple(n * scale for n in logical_size))
        alpha = np.array(layer)[:, :, 3]
        # These scanlines cross cell interiors, so horizontal lines cannot hide
        # missing vertical boundaries, or vice versa.
        vertical = np.flatnonzero(alpha[1, :] > 0)
        horizontal = np.flatnonzero(alpha[:, 1] > 0)
        self.assertEqual(len(vertical), logical_size[0])
        self.assertEqual(len(horizontal), logical_size[1])
        np.testing.assert_array_equal(vertical, np.arange(0, width, scale))
        np.testing.assert_array_equal(horizontal, np.arange(0, height, scale))
        np.testing.assert_array_equal(np.diff(vertical), np.full(len(vertical) - 1, scale))
        np.testing.assert_array_equal(np.diff(horizontal), np.full(len(horizontal) - 1, scale))
        self.assertEqual(vertical[-1], width - scale)
        self.assertEqual(horizontal[-1], height - scale)
        self.assertTrue(np.all(alpha[:, vertical] > 0))
        self.assertTrue(np.all(alpha[horizontal, :] > 0))
        self.assertTrue(np.all(alpha[1::scale, 1::scale] == 0))
        # The outer boundary is at width/height, outside the image. It must not
        # be clamped onto the final interior pixel and create a narrower cell.
        self.assertEqual(alpha[-1, -1], 0)

    def test_dense_grid_draws_every_cell_in_both_axes_without_sampling(self):
        for logical, scale in (((320, 224), 4), ((224, 320), 4), ((512, 300), 2)):
            with self.subTest(logical_size=logical, scale=scale):
                rendered = tuple(n * scale for n in logical)
                layer = pqa.create_grid_lines(rendered, logical)
                self.assert_every_actual_grid_boundary(layer, logical, scale)

    def test_saved_dense_audit_grid_matches_actual_square_cells(self):
        logical, scale = (320, 224), 4
        native = Image.new("RGBA", logical, (20, 30, 40, 255))
        source = native.resize(tuple(n * scale for n in logical), Image.Resampling.NEAREST)
        audit = pqa.inspect_image(source, logical, max_colors=1)
        self.assertEqual(audit.result["status"], "pass")
        with tempfile.TemporaryDirectory() as td:
            paths = pqa.write_audit(audit, Path(td) / "audit")
            with Image.open(paths["grid_lines"]) as layer:
                self.assert_every_actual_grid_boundary(layer, logical, scale)
            with Image.open(paths["overlay"]) as overlay:
                displayed = np.array(overlay.convert("RGB"))
            plain = np.array(source.convert("RGB"))
            changed = np.any(displayed != plain, axis=2)
            np.testing.assert_array_equal(np.flatnonzero(changed[1, :]), np.arange(0, source.width, scale))
            np.testing.assert_array_equal(np.flatnonzero(changed[:, 1]), np.arange(0, source.height, scale))

    def test_geometry_mismatch_creates_overlay_and_error_report(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            image_path = td / "source.png"
            Image.new("RGBA", (65, 96), "red").save(image_path)
            out = td / "audit"
            code = pqa.run_cli([
                "inspect", str(image_path), "--logical-size", "8x12",
                "--out-dir", str(out),
            ])
            self.assertEqual(code, 2)
            self.assertTrue((out / "grid_overlay.png").exists())
            self.assertTrue((out / "grid_lines.png").exists())
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["status"], "fail")
            self.assertIsNone(report["metrics"]["grid_score"])

    def test_render_size_predeclared_enforced(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            image_path = td / "source.png"
            self.image.save(image_path)
            out = td / "audit"
            code = pqa.run_cli([
                "inspect", str(image_path), "--logical-size", "8x8",
                "--render-size", "64x64", "--out-dir", str(out),
            ])
            self.assertEqual(code, 2)
            report = json.loads((out / "report.json").read_text())
            self.assertIn("RENDER_SIZE_MISMATCH", [i["code"] for i in report["issues"]])

    def test_non_square_cells_flagged(self):
        audit = pqa.inspect_image(Image.new("RGBA", (32, 64), "red"), (8, 8))
        self.assertEqual(audit.result["status"], "fail")
        self.assertIn("NON_SQUARE_CELL", [x["code"] for x in audit.result["issues"]])

    def test_palette_limit(self):
        image = Image.fromarray(np.tile(np.array([[[i*25, 0, 0, 255] for i in range(8)]], dtype=np.uint8), (8, 1, 1)), "RGBA")
        up = image.resize((32, 32), Image.Resampling.NEAREST)
        audit = pqa.inspect_image(up, (8, 8), max_colors=4)
        self.assertEqual(audit.result["status"], "fail")
        self.assertEqual(audit.result["metrics"]["visible_rgb_colors_logical_preview"], 8)

    def test_fix_has_uniform_grid_and_preserves_original(self):
        image = np.array(self.image)
        image[11, 11] = [111, 222, 33, 255]
        changed = Image.fromarray(image, "RGBA")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            original_path = out / "input.png"
            changed.save(original_path)
            original_bytes = original_path.read_bytes()
            audit = pqa.inspect_image(changed, (8, 8))
            generated = pqa.fix_image(audit, out, palette=2, hard_alpha=True)
            fixed = pqa.open_rgba(Path(generated["fixed_upscaled"]))
            assert pqa.inspect_image(fixed, (8, 8)).result["metrics"]["grid_score"] == 100
            self.assertEqual(original_path.read_bytes(), original_bytes)
            self.assertLessEqual(pqa.count_visible_colors(np.asarray(fixed)), 2)

    def test_alpha_review_and_strict_failure(self):
        arr = np.asarray(self.image).copy()
        arr[9, 9, 3] = 120
        sample = Image.fromarray(arr, "RGBA")
        report = pqa.inspect_image(sample, (8, 8))
        # A mixed-alpha cell fails exact RGBA uniformity even when alpha itself
        # is only a review-level warning.
        self.assertEqual(report.result["status"], "fail")
        self.assertGreater(report.result["metrics"]["partial_alpha_source_pixels"], 0)
        strict = pqa.inspect_image(sample, (8, 8), strict_alpha=True)
        self.assertEqual(strict.result["status"], "fail")

    def test_cli_fix_writes_impact_report(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source = td / "in.png"
            self.image.save(source)
            out = td / "corrected"
            code = pqa.run_cli(["fix", str(source), "--logical-size", "8x8", "--out-dir", str(out)])
            self.assertEqual(code, 0)
            impact = json.loads((out / "fix_review.json").read_text())
            self.assertEqual(impact["post_projection_grid_score"], 100)
            self.assertEqual(impact["changed_source_pixels"], 0)
            self.assertTrue((out / "comparison.png").is_file())

    def test_cli_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            image = td / "input.png"
            self.image.save(image)
            out = td / "output"
            status = pqa.run_cli(["inspect", str(image), "--logical-size", "8x8", "--out-dir", str(out)])
            self.assertEqual(status, 0)
            for name in ("report.json", "grid_overlay.png", "grid_lines.png", "logical_preview.png", "violation_mask.png", "correction_prompt.txt"):
                self.assertTrue((out / name).is_file())
            obj = json.loads((out / "report.json").read_text())
            self.assertEqual(obj["status"], "pass")

    def test_cli_mixed_cell_fails_in_default_strict_mode(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            image_path = td / "source.png"
            pixels = np.array(self.image)
            pixels[9, 9] = [85, 112, 23, 255]
            Image.fromarray(pixels, "RGBA").save(image_path)
            out = td / "audit"
            code = pqa.run_cli([
                "inspect", str(image_path), "--logical-size", "8x8",
                "--out-dir", str(out),
            ])
            self.assertEqual(code, 2)
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["metrics"]["nonuniform_rgba_cells"], 1)
            self.assertEqual(report["status"], "fail")

    def test_exact_failure_overlay_and_mask_survive_diagnostic_tolerance(self):
        pixels = np.array(self.image)
        pixels[9, 9, 0] += 1
        audit = pqa.inspect_image(Image.fromarray(pixels, "RGBA"), (8, 8), tolerance=8)
        self.assertEqual(audit.result["metrics"]["grid_score"], 100)
        self.assertEqual(audit.result["status"], "fail")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            pqa.write_audit(audit, out / "bad")
            pqa.write_audit(pqa.inspect_image(self.image, (8, 8)), out / "good")
            with Image.open(out / "bad" / "violation_mask.png") as mask:
                self.assertEqual(mask.size, (8, 8))
                self.assertEqual(mask.getpixel((2, 2)), 255)
                self.assertEqual(mask.getpixel((0, 0)), 0)
            with Image.open(out / "bad" / "grid_overlay.png") as bad, Image.open(out / "good" / "grid_overlay.png") as good:
                self.assertGreater(bad.getpixel((10, 10))[0], good.getpixel((10, 10))[0])

    def test_source_palette_budget_cannot_be_hidden_by_projection(self):
        pixels = np.array(self.image)
        pixels[9, 9] = [211, 50, 70, 255]
        audit = pqa.inspect_image(Image.fromarray(pixels, "RGBA"), (8, 8),
                                  tolerance=8, strict_cells=False, max_colors=2)
        self.assertEqual(audit.result["metrics"]["visible_rgb_colors_logical_preview"], 2)
        self.assertEqual(audit.result["metrics"]["visible_rgb_colors_source"], 3)
        self.assertEqual(audit.result["status"], "fail")
        self.assertIn("PALETTE_OVER_BUDGET", {i["code"] for i in audit.result["issues"]})

    def test_full_mask_preserves_failures_beyond_bounded_report_samples(self):
        pixels = np.array(self.image)
        pixels[::4, ::4] = [1, 2, 3, 255]
        audit = pqa.inspect_image(Image.fromarray(pixels, "RGBA"), (8, 8))
        self.assertEqual(audit.result["metrics"]["nonuniform_rgba_cells"], 64)
        self.assertEqual(len(audit.result["nonuniform_rgba_cell_samples"]), 20)
        self.assertTrue(audit.result["nonuniform_rgba_cell_samples_truncated"])
        with tempfile.TemporaryDirectory() as td:
            outputs = pqa.write_audit(audit, Path(td))
            with Image.open(outputs["violation_mask"]) as mask:
                self.assertEqual(mask.getextrema(), (255, 255))

    def test_loader_rejects_non_png_and_sixteen_bit_png(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            jpeg = td / "misnamed.png"
            self.image.convert("RGB").save(jpeg, format="JPEG")
            with self.assertRaisesRegex(ValueError, "PNG"):
                pqa.open_rgba(jpeg)
            sixteen = td / "sixteen.png"
            Image.fromarray(np.array([[256, 257]], dtype=np.uint16)).save(sixteen)
            with self.assertRaisesRegex(ValueError, "16-bit"):
                pqa.open_rgba(sixteen)

    def test_loader_rejects_invalid_or_oversize_ihdr_before_chunks_and_decode(self):
        stream = io.BytesIO()
        self.image.save(stream, format="PNG")
        header = bytearray(stream.getvalue()[:33])
        cases = [
            ((0, 32), "dimensions must be positive"),
            ((32, 0), "dimensions must be positive"),
            ((pqa.MAX_PIXELS + 1, 1), "too large"),
            ((100_000, 100_000), "too large"),
        ]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "oversize.png"
            for dimensions, error in cases:
                with self.subTest(dimensions=dimensions):
                    header[16:24] = struct.pack(">II", *dimensions)
                    # Header-only data proves rejection precedes chunk scanning.
                    source.write_bytes(header)
                    with patch.object(pqa.Image, "open", side_effect=Image.DecompressionBombError("unexpected decode")) as decoder:
                        with self.assertRaisesRegex(ValueError, error):
                            pqa.open_rgba(source)
                        decoder.assert_not_called()

    def test_loader_accepts_pixel_budget_boundary_and_rejects_one_over(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "boundary.png"
            self.image.save(source)
            pixels = self.image.width * self.image.height
            with patch.object(pqa, "MAX_PIXELS", pixels):
                self.assertEqual(pqa.open_rgba(source).size, self.image.size)
            with patch.object(pqa, "MAX_PIXELS", pixels - 1):
                with self.assertRaisesRegex(ValueError, "too large"):
                    pqa.open_rgba(source)

    def test_loader_rejects_animation_instead_of_auditing_first_frame(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "animated.png"
            other = Image.new("RGBA", self.image.size, "blue")
            self.image.save(source, save_all=True, append_images=[other], duration=100, loop=0)
            with self.assertRaisesRegex(ValueError, "Animated PNG"):
                pqa.open_rgba(source)

    def test_lossless_low_bit_png_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            one = td / "binary.png"
            Image.new("1", (8, 8), 1).save(one)
            self.assertEqual(pqa.open_rgba(one).getpixel((0, 0)), (255, 255, 255, 255))
            palette = td / "palette.png"
            source = Image.new("P", (8, 8), 1)
            source.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
            source.save(palette, bits=2)
            self.assertEqual(pqa.open_rgba(palette).getpixel((0, 0)), (255, 0, 0, 255))

    def test_loader_preserves_stored_coordinates_ignoring_exif_orientation(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "orientation.png"
            original = Image.new("RGBA", (8, 12), "red")
            exif = Image.Exif()
            exif[274] = 6
            original.save(source, exif=exif)
            self.assertEqual(pqa.open_rgba(source).size, (8, 12))

    def test_direct_api_validates_dimensions_resource_limits_and_settings(self):
        for logical in ((0, 8), (8, -1), (8.0, 8), (True, 8), (4097, 8)):
            with self.subTest(logical=logical), self.assertRaises(ValueError):
                pqa.inspect_image(self.image, logical)
        for score in (float("nan"), float("inf"), -1, 101):
            with self.subTest(score=score), self.assertRaises(ValueError):
                pqa.inspect_image(self.image, (8, 8), min_grid_score=score)
        with patch.object(pqa, "MAX_PIXELS", 100), self.assertRaisesRegex(ValueError, "too large"):
            pqa.inspect_image(self.image, (8, 8))
        with self.assertRaisesRegex(ValueError, "transparent_rgb"):
            pqa.inspect_image(self.image, (8, 8), transparent_rgb="guess")

    def test_input_filename_collision_is_rejected_without_changing_input(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source = td / "grid_overlay.png"
            self.image.save(source)
            before = source.read_bytes()
            code = pqa.run_cli(["inspect", str(source), "--logical-size", "8x8", "--out-dir", str(td)])
            self.assertEqual(code, 1)
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse((td / "report.json").exists())

    def test_reusing_nonempty_output_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source = td / "source.png"
            self.image.save(source)
            out = td / "audit"
            out.mkdir()
            existing = out / "report.json"
            existing.write_text("prior evidence", encoding="utf-8")
            code = pqa.run_cli(["inspect", str(source), "--logical-size", "8x8", "--out-dir", str(out)])
            self.assertEqual(code, 1)
            self.assertEqual(existing.read_text(), "prior evidence")

    def test_low_level_audit_writer_preflights_all_destinations(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "grid_lines.png").write_bytes(b"original bytes")
            with self.assertRaisesRegex(ValueError, "already exists"):
                pqa.write_audit(pqa.inspect_image(self.image, (8, 8)), out)
            self.assertFalse((out / "report.json").exists())
            self.assertEqual((out / "grid_lines.png").read_bytes(), b"original bytes")

    def test_cli_provenance_and_post_report_identify_exact_files(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source = td / "source.png"
            pixels = np.array(self.image)
            pixels[9, 9, 0] += 1
            Image.fromarray(pixels, "RGBA").save(source)
            before = source.read_bytes()
            out = td / "fix"
            code = pqa.run_cli(["fix", str(source), "--logical-size", "8x8", "--out-dir", str(out)])
            self.assertEqual(code, 0)
            original = json.loads((out / "report.json").read_text())
            post = json.loads((out / "post_report.json").read_text())
            self.assertEqual(original["status"], "fail")
            self.assertEqual(post["status"], "pass")
            self.assertEqual(original["schema_version"], 1)
            self.assertEqual(original["tool"], "Pixelwright")
            self.assertEqual(original["provenance"]["source_sha256"], hashlib.sha256(before).hexdigest())
            self.assertEqual(post["provenance"]["source_sha256"], hashlib.sha256((out / "fixed_upscaled.png").read_bytes()).hexdigest())
            self.assertEqual(source.read_bytes(), before)
            with Image.open(out / post["violation_mask"]["file"]) as mask:
                self.assertEqual(mask.getextrema(), (0, 0))

    def test_fix_exit_fails_when_final_alpha_contract_still_fails(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source = td / "source.png"
            Image.new("RGBA", (32, 32), (50, 90, 20, 128)).save(source)
            out = td / "fix"
            code = pqa.run_cli(["fix", str(source), "--logical-size", "8x8",
                                "--strict-alpha", "--out-dir", str(out)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads((out / "post_report.json").read_text())["status"], "fail")

    def test_preview_uses_bounded_integer_enlargement(self):
        with tempfile.TemporaryDirectory() as td, patch.object(pqa, "MAX_PREVIEW_DIMENSION", 24):
            path = Path(td) / "preview.png"
            pqa.save_preview(self.native, path)
            with Image.open(path) as preview:
                self.assertEqual(preview.size, (24, 24))


if __name__ == "__main__":
    unittest.main()
