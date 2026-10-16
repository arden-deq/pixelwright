"""Palette-library contracts and accepted-export regression tests."""
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pixel_palette as palettes
import pixel_build as builder
import pixelwright as project


def rgba(value):
    return project.parse_rgba(value)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PaletteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Match production's canonical paths, including Windows 8.3 temp aliases.
        self.root = Path(self.tmp.name).resolve()
        self.palette_path = self.root / "colors.json"
        self.profile_path = self.root / "profile.json"

    def write_palette(self, colors=None, *, ramps=None, name="Test palette", path=None):
        document = {"schema_version": 1, "name": name,
                    "colors": colors or {"dark": "#000000FF", "light": "#FFFFFFFF"}}
        if ramps is not None:
            document["ramps"] = ramps
        path = path or self.palette_path
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def write_profile(self, *, allowed=None, alpha="binary", max_colors=256,
                      logical="2x2", scale=3, transparent_rgb="exact"):
        document = {"schema_version": 1, "logical_size": logical, "scale": scale,
                    "max_colors": max_colors, "alpha": alpha,
                    "transparent_rgb": transparent_rgb}
        if allowed is not None:
            document["allowed_palette"] = allowed
        self.profile_path.write_text(json.dumps(document), encoding="utf-8")
        return self.profile_path

    def image(self, native, *, name="source.png", scale=3):
        pixels = np.array(native, dtype=np.uint8)
        enlarged = np.repeat(np.repeat(pixels, scale, axis=0), scale, axis=1)
        path = self.root / name
        Image.fromarray(enlarged).save(path)
        return path

    def solid(self, color, *, name="source.png", scale=3):
        return self.image([[color, color], [color, color]], name=name, scale=scale)

    def read_png(self, path):
        with Image.open(path) as image:
            return np.array(image.convert("RGBA"))

    def read_generated_palette(self, out):
        candidates = []
        for path in out.rglob("*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(document, dict) and isinstance(document.get("colors"), dict):
                candidates.append((path, document))
        self.assertEqual(len(candidates), 1, "A palette operation must save one reusable library")
        return candidates[0]

    def remap(self, source, out, *, ramp=None):
        return palettes.remap_image(source, self.palette_path, self.profile_path, out, ramp=ramp)

    def assert_no_accepted_images(self, out):
        self.assertFalse((out / "native.png").exists())
        self.assertFalse((out / "rendered.png").exists())

    def assert_approved_under_original_profile(self, out):
        saved = out / "rendered.png"
        self.assertTrue(saved.is_file(), "PASS must produce an accepted rendered PNG")
        audit_dir = self.root / (out.name + "-independent-audit")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = project.run_cli(["inspect", str(saved), "--profile", str(self.profile_path),
                                    "--out-dir", str(audit_dir)])
        self.assertEqual(code, 0, "The saved export must pass the unchanged project contract")
        audit = json.loads((audit_dir / "report.json").read_text())
        self.assertEqual(audit["artistic_status"], "not_reviewed")
        self.assertEqual(audit["provenance"]["source_sha256"], digest(saved))
        return saved

    def test_palette_keeps_order_and_distinguishes_hidden_transparent_rgb(self):
        document = {"schema_version": 1,
                    "colors": {"red": "#ff0000", "clearA": "#00000000", "clearB": "#11223300"},
                    "ramps": {"fade": ["clearA", "clearB"]}}
        result = palettes.validate_palette(document)
        self.assertEqual(list(result["colors"]), ["red", "clearA", "clearB"])
        self.assertEqual([rgba(v) for v in result["colors"].values()],
                         [(255, 0, 0, 255), (0, 0, 0, 0), (17, 34, 51, 0)])
        self.assertEqual(result["ramps"]["fade"], ["clearA", "clearB"])

    def test_normalized_duplicate_colors_are_rejected(self):
        with self.assertRaises(ValueError):
            palettes.validate_palette({"schema_version": 1,
                                       "colors": {"a": "#ff0000", "b": "#FF0000FF"}})

    def test_palette_rejects_misspellings_invalid_tokens_and_bad_rgba(self):
        base = {"schema_version": 1, "colors": {"ok": "#010203FF"}}
        changes = [{"schema_version": True}, {"schema_version": 2}, {"name": 7},
                   {"colours": {"a": "#000000"}}, {"colors": {}},
                   {"colors": {"_bad": "#000000"}}, {"colors": {"a b": "#000000"}},
                   {"colors": {"한글": "#000000"}}, {"colors": {"a" * 65: "#000000"}},
                   {"colors": {"a": "#GG0000"}}, {"colors": {"a": "transparent"}}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                palettes.validate_palette(base | change)

    def test_palette_and_ramp_capacity_and_reference_constraints(self):
        colors = {f"c{i}": f"#{i:06X}FF" for i in range(256)}
        self.assertEqual(len(palettes.validate_palette({"schema_version": 1, "colors": colors})["colors"]), 256)
        with self.assertRaises(ValueError):
            palettes.validate_palette({"schema_version": 1, "colors": colors | {"extra": "#010000FF"}})
        for ramp in ([], ["c0"], ["c0", "c0"], ["c0", "missing"]):
            with self.subTest(ramp=ramp), self.assertRaises(ValueError):
                palettes.validate_palette({"schema_version": 1, "colors": colors,
                                           "ramps": {"shade": ramp}})

    def test_duplicate_json_keys_cannot_override_palette_or_ramp(self):
        for text in ('{"schema_version":1,"schema_version":2,"colors":{"a":"#000000"}}',
                     '{"schema_version":1,"colors":{"a":"#000000","a":"#FFFFFF"}}',
                     '{"schema_version":1,"colors":{"a":"#000000","b":"#FFFFFF"},'
                     '"ramps":{"shade":["a","b"],"shade":["b","a"]}}'):
            with self.subTest(text=text):
                self.palette_path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    palettes.load_palette(self.palette_path)

    def test_extraction_is_rgba_exact_frequency_sorted_and_source_preserving(self):
        opaque = (20, 30, 40, 255)
        hidden = (20, 30, 40, 0)
        clear = (0, 0, 0, 0)
        source = self.image([[opaque, hidden], [opaque, clear]])
        original = source.read_bytes()
        out = self.root / "extracted"
        report = palettes.extract_palette(source, out)
        _, palette = self.read_generated_palette(out)
        self.assertEqual([rgba(c) for c in palette["colors"].values()], [opaque, clear, hidden])
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(report["status"], "extracted")

    def test_visible_extraction_canonicalizes_only_explicit_hidden_rgb_policy(self):
        source = self.image([[(1, 2, 3, 0), (4, 5, 6, 0)],
                             [(7, 8, 9, 0), (10, 11, 12, 255)]])
        out = self.root / "visible"
        palettes.extract_palette(source, out, transparent_rgb="visible")
        _, palette = self.read_generated_palette(out)
        self.assertEqual([rgba(c) for c in palette["colors"].values()],
                         [(0, 0, 0, 0), (10, 11, 12, 255)])
        with self.assertRaises(ValueError):
            palettes.extract_palette(source, self.root / "invalid-policy", transparent_rgb="guess")

    def test_repeated_extraction_produces_identical_reusable_libraries(self):
        source = self.image([[(1, 2, 3, 255), (4, 5, 6, 128)],
                             [(7, 8, 9, 0), (1, 2, 3, 255)]])
        first, second = self.root / "extract-first", self.root / "extract-second"
        palettes.extract_palette(source, first)
        palettes.extract_palette(source, second)
        a, _ = self.read_generated_palette(first)
        b, _ = self.read_generated_palette(second)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(palettes.load_palette(a), palettes.load_palette(b))

    def test_truncation_includes_transparency_and_discloses_lost_colors(self):
        source = self.image([[(0, 0, 0, 0), (0, 0, 0, 0)],
                             [(1, 2, 3, 255), (4, 5, 6, 255)]])
        out = self.root / "truncated"
        report = palettes.extract_palette(source, out, max_colors=2)
        _, palette = self.read_generated_palette(out)
        self.assertEqual([rgba(c) for c in palette["colors"].values()],
                         [(0, 0, 0, 0), (1, 2, 3, 255)])
        self.assertTrue(report["metrics"]["truncated"])
        self.assertEqual(report["metrics"]["distinct_rgba_colors"], 3)
        self.assertEqual(report["metrics"]["selected_colors"], 2)
        self.assertEqual(report["metrics"]["omitted_source_pixels"], 9)

    def test_remap_uses_nearest_rgb_and_palette_order_for_ties(self):
        self.write_palette({"first": "#020000FF", "second": "#000000FF"})
        self.write_profile(allowed=["#020000FF", "#000000FF"])
        source = self.solid((1, 0, 0, 255))
        out = self.root / "tie"
        report = self.remap(source, out)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["source"]["status"], "fail")
        self.assertEqual(report["final"]["status"], "pass")
        saved = self.assert_approved_under_original_profile(out)
        self.assertTrue(np.all(self.read_png(saved) == (2, 0, 0, 255)))
        self.assertEqual(report["metrics"]["changed_source_pixels"], 36)
        self.assertEqual(report["metrics"]["changed_logical_cells"], 4)
        self.assertEqual(report["metrics"]["alpha_changed_source_pixels"], 0)
        self.assertEqual(report["mappings"], [{"from": "#010000FF", "to": "#020000FF", "logical_cells": 4}])
        with Image.open(out / "changed_cells.png") as changed_cells:
            np.testing.assert_array_equal(np.array(changed_cells), np.full((2, 2), 255, dtype=np.uint8))

    def test_remap_preserves_binary_and_partial_alpha_with_matching_candidates(self):
        self.write_palette({"hidden": "#10203000", "shadow": "#01020380", "solid": "#A0B0C0FF"})
        self.write_profile(allowed=["#10203000", "#01020380", "#A0B0C0FF"], alpha="any")
        source = self.image([[(2, 3, 4, 0), (5, 6, 7, 128)],
                             [(8, 9, 10, 255), (5, 6, 7, 128)]])
        out = self.root / "alpha"
        report = self.remap(source, out)
        self.assertEqual(report["status"], "pass")
        saved = self.assert_approved_under_original_profile(out)
        np.testing.assert_array_equal(self.read_png(saved)[:, :, 3], self.read_png(source)[:, :, 3])
        np.testing.assert_array_equal(self.read_png(saved)[::3, ::3],
                                     np.array([[(16, 32, 48, 0), (1, 2, 3, 128)],
                                               [(160, 176, 192, 255), (1, 2, 3, 128)]], dtype=np.uint8))

    def test_remap_never_chooses_different_alpha_to_get_a_closer_rgb(self):
        self.write_palette({"wrongAlpha": "#01020380", "sameAlpha": "#FFFFFFFE"})
        self.write_profile(allowed=["#01020380", "#FFFFFFFE"], alpha="any")
        source = self.solid((1, 2, 3, 254))
        out = self.root / "alpha-distance"
        report = self.remap(source, out)
        self.assertEqual(report["status"], "pass")
        saved = self.assert_approved_under_original_profile(out)
        self.assertTrue(np.all(self.read_png(saved) == (255, 255, 255, 254)))

    def test_missing_alpha_candidate_does_not_emit_accepted_images(self):
        self.write_palette({"solid": "#000000FF"})
        self.write_profile(alpha="any")
        source = self.solid((0, 0, 0, 128))
        out = self.root / "missing-alpha"
        report = self.remap(source, out)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["source"]["status"], "pass")
        self.assertEqual(report["issues"][0]["code"], "NO_ALPHA_MATCH")
        self.assertEqual(report["issues"][0]["alpha_values"], [128])
        self.assert_no_accepted_images(out)

    def test_remap_does_not_conceal_one_source_sample_grid_defect(self):
        self.write_palette({"black": "#000000FF"})
        self.write_profile(allowed=["#000000FF"])
        source = self.solid((1, 1, 1, 255))
        damaged = self.read_png(source)
        damaged[1, 1] = (2, 2, 2, 255)
        Image.fromarray(damaged).save(source)
        before = source.read_bytes()
        out = self.root / "nonuniform"
        report = self.remap(source, out)
        self.assertEqual(report["status"], "fail")
        self.assert_no_accepted_images(out)
        self.assertEqual(source.read_bytes(), before)
        self.assertTrue(any(out.rglob("*report.json")), "Rejected source must retain audit diagnostics")

    def test_remap_does_not_conceal_hidden_rgb_defect_under_exact_contract(self):
        self.write_palette({"clear": "#00000000"})
        self.write_profile(allowed=["#00000000"])
        source = self.solid((1, 2, 3, 0))
        damaged = self.read_png(source)
        damaged[1, 1] = (4, 5, 6, 0)
        Image.fromarray(damaged).save(source)
        out = self.root / "hidden-defect"
        report = self.remap(source, out)
        self.assertEqual(report["status"], "fail")
        self.assert_no_accepted_images(out)

    def test_remap_does_not_conceal_wrong_geometry_or_alpha_policy(self):
        self.write_palette({"clear": "#00000000", "black": "#000000FF"})
        for case, color, scale, alpha in (("geometry", (1, 1, 1, 255), 2, "binary"),
                                          ("opaque", (1, 1, 1, 0), 3, "opaque"),
                                          ("binary", (1, 1, 1, 128), 3, "binary")):
            with self.subTest(case=case):
                self.write_profile(alpha=alpha)
                source = self.solid(color, name=case + ".png", scale=scale)
                out = self.root / case
                report = self.remap(source, out)
                self.assertEqual(report["status"], "fail")
                self.assert_no_accepted_images(out)

    def test_original_profile_palette_mismatch_cannot_be_weakened(self):
        self.write_palette({"red": "#FF0000FF"})
        self.write_profile(allowed=["#000000FF"])
        source = self.solid((200, 0, 0, 255))
        before_profile = self.profile_path.read_bytes()
        out = self.root / "contract-mismatch"
        report = self.remap(source, out)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["final"]["status"], "fail")
        self.assertEqual(report["contract"], json.loads(before_profile))
        self.assert_no_accepted_images(out)
        self.assertEqual(self.profile_path.read_bytes(), before_profile)
        self.assertTrue((out / "candidate" / "rendered.png").is_file())

    def test_unused_shared_library_colors_do_not_invalidate_an_allowed_export(self):
        self.write_palette({"black": "#000000FF", "red": "#FF0000FF"})
        self.write_profile(allowed=["#000000FF"])
        source = self.solid((20, 20, 20, 255))
        out = self.root / "shared-library"
        report = self.remap(source, out)
        self.assertEqual(report["status"], "pass")
        saved = self.assert_approved_under_original_profile(out)
        self.assertTrue(np.all(self.read_png(saved) == (0, 0, 0, 255)))

    def test_final_color_budget_failure_cannot_produce_accepted_images(self):
        self.write_palette({"black": "#000000FF", "white": "#FFFFFFFF"})
        self.write_profile(allowed=["#000000FF", "#FFFFFFFF"], max_colors=1)
        source = self.image([[(1, 1, 1, 255), (254, 254, 254, 255)],
                             [(1, 1, 1, 255), (254, 254, 254, 255)]])
        out = self.root / "budget"
        report = self.remap(source, out)
        self.assertEqual(report["status"], "fail")
        self.assert_no_accepted_images(out)

    def test_remap_preserves_inputs_and_is_reproducible(self):
        self.write_palette({"black": "#000000FF", "white": "#FFFFFFFF"})
        self.write_profile(allowed=["#000000FF", "#FFFFFFFF"])
        source = self.solid((30, 30, 30, 255))
        paths = [source, self.palette_path, self.profile_path]
        before = {path: path.read_bytes() for path in paths}
        first, second = self.root / "first", self.root / "second"
        a, b = self.remap(source, first), self.remap(source, second)
        self.assertEqual((a["status"], b["status"]), ("pass", "pass"))
        self.assertEqual((first / "rendered.png").read_bytes(), (second / "rendered.png").read_bytes())
        for path in paths:
            self.assertEqual(path.read_bytes(), before[path])
        recorded_inputs = {Path(item["path"]): item["sha256"] for item in a["provenance"]["inputs"]}
        self.assertEqual(recorded_inputs, {path: digest(path) for path in paths})
        self.assertEqual(a["source_decoded_rgba_sha256"], hashlib.sha256(self.read_png(source).tobytes()).hexdigest())
        self.assertEqual(a["output_decoded_rgba_sha256"], hashlib.sha256(self.read_png(first / "rendered.png").tobytes()).hexdigest())
        self.assertEqual(a["artistic_status"], "not_reviewed")
        self.assert_approved_under_original_profile(first)

    def test_output_collisions_and_nonempty_directories_leave_inputs_untouched(self):
        self.write_palette()
        self.write_profile()
        source = self.solid((20, 20, 20, 255))
        paths = [source, self.palette_path, self.profile_path]
        before = {path: path.read_bytes() for path in paths}
        existing = self.root / "existing"
        existing.mkdir()
        marker = existing / "keep.txt"
        marker.write_text("keep")
        for out in (self.root, existing):
            with self.subTest(out=out), self.assertRaises(ValueError):
                self.remap(source, out)
        self.assertEqual(marker.read_text(), "keep")
        for path in paths:
            self.assertEqual(path.read_bytes(), before[path])

    def test_partial_promotion_write_failure_removes_both_owned_accepted_exports(self):
        self.write_palette()
        self.write_profile()
        source = self.solid((20, 20, 20, 255))
        out = self.root / "write-failure"
        original_open = Path.open

        class PartialWriter:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self.stream.__exit__(*exc)

            def write(self, data):
                self.stream.write(data[:max(1, len(data) // 2)])
                raise OSError("simulated disk write failure")

        def partial_open(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            if path == out / "rendered.png" and args == ("xb",):
                return PartialWriter(stream)
            return stream

        with mock.patch.object(Path, "open", new=partial_open), self.assertRaisesRegex(OSError, "simulated disk"):
            self.remap(source, out)
        self.assert_no_accepted_images(out)
        self.assertTrue((out / "candidate" / "rendered.png").is_file())
        self.assertFalse((out / ".pixelwright-palette.lock").exists())

    def test_racing_export_file_is_preserved_when_exclusive_promotion_fails(self):
        self.write_palette()
        self.write_profile()
        source = self.solid((20, 20, 20, 255))
        out = self.root / "racing-export"
        original_write = palettes._write
        unrelated = b"another writer owns this file"

        def race_before_promotion(path, data):
            if path == out / "rendered.png":
                path.write_bytes(unrelated)
            return original_write(path, data)

        with mock.patch.object(palettes, "_write", side_effect=race_before_promotion), self.assertRaises(FileExistsError):
            self.remap(source, out)
        self.assertEqual((out / "rendered.png").read_bytes(), unrelated)
        self.assertFalse((out / "native.png").exists())
        self.assertFalse((out / "palette_report.json").exists())

    def test_profile_change_after_final_audit_prevents_accepted_export(self):
        self.write_palette()
        self.write_profile()
        source = self.solid((20, 20, 20, 255))
        out = self.root / "changed-profile"
        original = self.profile_path.read_bytes()
        original_audit = project.audit_one

        def change_profile_after_final(image_path, profile, profile_path, audit_dir):
            result = original_audit(image_path, profile, profile_path, audit_dir)
            if Path(audit_dir).name == "final":
                self.profile_path.write_bytes(original + b"\n")
            return result

        with mock.patch.object(project, "audit_one", side_effect=change_profile_after_final), self.assertRaisesRegex(ValueError, "Input changed"):
            self.remap(source, out)
        self.assert_no_accepted_images(out)
        self.assertTrue((out / "final" / "report.json").is_file())

    def test_palette_change_after_promotion_removes_accepted_exports(self):
        self.write_palette()
        self.write_profile()
        source = self.solid((20, 20, 20, 255))
        out = self.root / "changed-palette"
        original = self.palette_path.read_bytes()
        original_write = palettes._write

        def change_palette_after_export(path, data):
            original_write(path, data)
            if path == out / "rendered.png":
                self.palette_path.write_bytes(original + b"\n")

        with mock.patch.object(palettes, "_write", side_effect=change_palette_after_export), self.assertRaisesRegex(ValueError, "Input changed"):
            self.remap(source, out)
        self.assert_no_accepted_images(out)
        self.assertTrue((out / "candidate" / "rendered.png").is_file())

    def test_symlink_output_is_rejected_even_when_target_is_empty(self):
        self.write_palette()
        self.write_profile()
        source = self.solid((20, 20, 20, 255))
        target = self.root / "real-output"
        target.mkdir()
        link = self.root / "linked-output"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlink creation is unavailable: {exc}")
        with self.assertRaises(ValueError):
            self.remap(source, link)
        self.assertEqual(list(target.iterdir()), [])

    def test_extraction_and_ramp_refuse_nonempty_output_without_rewriting_files(self):
        source = self.solid((20, 30, 40, 255))
        before = source.read_bytes()
        out = self.root / "existing-palette"
        out.mkdir()
        marker = out / "palette.json"
        marker.write_text("preserve me")
        with self.assertRaises(ValueError):
            palettes.extract_palette(source, out)
        with self.assertRaises(ValueError):
            palettes.generate_ramp("#000000", "#FFFFFF", 3, "shade", out)
        self.assertEqual(marker.read_text(), "preserve me")
        self.assertEqual(source.read_bytes(), before)

    def test_ramp_endpoints_steps_alpha_and_reusable_named_subset(self):
        out = self.root / "ramp"
        report = palettes.generate_ramp("#00000080", "#FFFFFF80", 3, "shade", out)
        path, palette = self.read_generated_palette(out)
        self.assertEqual(report["status"], "created")
        ramp_name = next(iter(palette["ramps"]))
        colors = [rgba(palette["colors"][token]) for token in palette["ramps"][ramp_name]]
        self.assertEqual(len(colors), 3)
        self.assertEqual((colors[0], colors[-1]), ((0, 0, 0, 128), (255, 255, 255, 128)))
        self.assertTrue(all(c[3] == 128 for c in colors))
        self.assertEqual(colors[1], (128, 128, 128, 128))
        self.palette_path = path
        self.write_profile(allowed=list(palette["colors"].values()), alpha="any")
        source = self.solid((20, 20, 20, 128))
        remapped = self.root / "ramp-remap"
        result = self.remap(source, remapped, ramp=ramp_name)
        self.assertEqual(result["status"], "pass")
        self.assert_approved_under_original_profile(remapped)

    def test_ramp_can_extend_a_library_without_changing_existing_tokens_or_name(self):
        path = self.write_palette({"red": "#FF0000FF", "clear": "#00000000"}, name="Existing library")
        before = path.read_bytes()
        out = self.root / "extended"
        palettes.generate_ramp("#000000FF", "#FFFFFFFF", 3, "metal", out, palette_path=path)
        _, palette = self.read_generated_palette(out)
        self.assertEqual(palette["name"], "Existing library")
        self.assertEqual(rgba(palette["colors"]["red"]), (255, 0, 0, 255))
        self.assertEqual(rgba(palette["colors"]["clear"]), (0, 0, 0, 0))
        self.assertEqual(len(palette["ramps"]["metal"]), 3)
        self.assertEqual(path.read_bytes(), before)

    def test_builder_reuses_extracted_and_generated_libraries_with_recorded_identity(self):
        source = self.image([[(0, 0, 0, 0), (20, 30, 40, 255)],
                             [(50, 60, 70, 255), (20, 30, 40, 255)]])
        for operation in ("extract", "ramp"):
            with self.subTest(operation=operation):
                library_out = self.root / ("library-" + operation)
                if operation == "extract":
                    palettes.extract_palette(source, library_out)
                else:
                    palettes.generate_ramp("#00000080", "#FFFFFF80", 3, "metal", library_out)
                library_path, library = self.read_generated_palette(library_out)
                tokens = list(library["colors"])
                rows = [[tokens[0], tokens[1]], [tokens[2], tokens[1]]]
                spec = self.root / ("art-" + operation + ".json")
                spec.write_text(json.dumps({"schema_version": 1, "scale": 3, "rows": rows,
                                             "palette_file": library_path.relative_to(self.root).as_posix()}))
                before = {path: path.read_bytes() for path in (source, library_path, spec)}
                out = self.root / ("library-build-" + operation)
                report = builder.build_from_spec(spec, out)
                expected = np.array([[rgba(library["colors"][token]) for token in row] for row in rows], dtype=np.uint8)
                np.testing.assert_array_equal(self.read_png(out / "native.png"), expected)
                self.assertEqual(report["palette_source"]["sha256"], digest(library_path))
                self.write_profile(allowed=list(library["colors"].values()), alpha="any")
                self.assert_approved_under_original_profile(out)
                for path, data in before.items():
                    self.assertEqual(path.read_bytes(), data)

    def test_builder_library_paths_are_confined_and_inline_palette_cannot_override_them(self):
        self.write_palette()
        valid = {"schema_version": 1, "scale": 3, "rows": [["dark", "light"], ["light", "dark"]],
                 "palette_file": self.palette_path.name}
        references = ["../colors.json", str(self.palette_path), "folder\\colors.json", "folder/../colors.json"]
        for index, reference in enumerate(references):
            with self.subTest(reference=reference):
                spec = self.root / f"unsafe-{index}.json"
                spec.write_text(json.dumps(valid | {"palette_file": reference}))
                out = self.root / f"unsafe-build-{index}"
                with self.assertRaises(builder.SpecError):
                    builder.build_from_spec(spec, out)
                self.assertFalse(out.exists())
        spec = self.root / "ambiguous.json"
        spec.write_text(json.dumps(valid | {"palette": {"dark": "#FF0000", "light": "#00FF00"}}))
        with self.assertRaises(builder.SpecError):
            builder.build_from_spec(spec, self.root / "ambiguous-build")

    def test_ramp_remap_uses_only_named_members_even_when_other_color_is_exact(self):
        self.write_palette({"black": "#000000FF", "white": "#FFFFFFFF", "red": "#FF0000FF"},
                           ramps={"gray": ["black", "white"]})
        self.write_profile(allowed=["#000000FF", "#FFFFFFFF", "#FF0000FF"])
        source = self.solid((255, 0, 0, 255))
        out = self.root / "subset"
        report = self.remap(source, out, ramp="gray")
        self.assertEqual(report["status"], "pass")
        saved = self.assert_approved_under_original_profile(out)
        self.assertTrue(np.all(self.read_png(saved) == (0, 0, 0, 255)))

    def test_opaque_named_ramp_retains_library_transparency_for_sprite_holes(self):
        self.write_palette({"clear": "#00000000", "black": "#000000FF", "white": "#FFFFFFFF",
                            "red": "#FF0000FF"}, ramps={"gray": ["black", "white"]})
        self.write_profile(allowed=["#00000000", "#000000FF", "#FFFFFFFF", "#FF0000FF"])
        source = self.image([[(0, 0, 0, 0), (30, 30, 30, 255)],
                             [(230, 230, 230, 255), (0, 0, 0, 0)]])
        out = self.root / "transparent-ramp"
        report = self.remap(source, out, ramp="gray")
        self.assertEqual(report["status"], "pass")
        saved = self.assert_approved_under_original_profile(out)
        np.testing.assert_array_equal(self.read_png(saved)[:, :, 3], self.read_png(source)[:, :, 3])
        self.assertNotIn("red", report["target_tokens"])
        self.assertIn("clear", report["target_tokens"])

    def test_cli_distinguishes_success_qa_failure_and_invalid_palette(self):
        self.write_palette({"black": "#000000FF"})
        self.write_profile(allowed=["#000000FF"])
        good = self.solid((20, 20, 20, 255), name="good.png")
        bad = self.solid((20, 20, 20, 255), name="bad.png")
        pixels = self.read_png(bad)
        pixels[0, 0] = (21, 20, 20, 255)
        Image.fromarray(pixels).save(bad)
        for source, label, expected in ((good, "cli-good", 0), (bad, "cli-qa-fail", 2)):
            with self.subTest(expected=expected), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = palettes.run_cli(["remap", str(source), "--palette", str(self.palette_path),
                                         "--profile", str(self.profile_path), "--out-dir", str(self.root / label)])
            self.assertEqual(code, expected)
        self.palette_path.write_text('{"schema_version":1,"colors":{"black":"not-a-color"}}')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = palettes.run_cli(["remap", str(good), "--palette", str(self.palette_path),
                                     "--profile", str(self.profile_path), "--out-dir", str(self.root / "cli-error")])
        self.assertEqual(code, 1)

    def test_ramp_rejects_mixed_alpha_invalid_steps_and_rounded_duplicates(self):
        cases = [("#000000FF", "#FFFFFF80", 3), ("#000000", "#FFFFFF", 1),
                 ("#000000", "#FFFFFF", True), ("#000000", "#FFFFFF", 257),
                 ("#000000", "#000001", 3)]
        for index, (start, end, steps) in enumerate(cases):
            with self.subTest(start=start, end=end, steps=steps), self.assertRaises(ValueError):
                palettes.generate_ramp(start, end, steps, "shade", self.root / f"bad-ramp-{index}")


if __name__ == "__main__":
    unittest.main()
