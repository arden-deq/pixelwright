"""Independent checks for layer composition and its acceptance gate.

Fixtures are generated in temporary directories. Expected composites are built
from explicit RGBA samples rather than by calling the compositor itself.
"""
import contextlib
import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pixel_layers as layers


TRANSPARENT = (0, 0, 0, 0)
RED = (160, 32, 48, 255)
BLUE = (32, 80, 176, 255)
GOLD = (240, 192, 64, 255)
PALETTE = ["#00000000", "#A02030", "#2050B0", "#F0C040"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.profile_path = self.root / "profile.json"
        self.manifest_path = self.root / "scene.json"
        self.contract = {
            "schema_version": 1,
            "logical_size": "4x3",
            "scale": 3,
            "max_colors": 3,
            "alpha": "binary",
            "transparent_rgb": "exact",
            "allowed_palette": PALETTE[:],
        }
        self.document = {
            "schema_version": 1,
            "name": "Temporary composition",
            "profile": "profile.json",
            "layers": [],
        }
        self.flush()

    def tearDown(self):
        self.tmp.cleanup()

    def flush(self):
        self.profile_path.write_text(json.dumps(self.contract), encoding="utf-8")
        self.manifest_path.write_text(json.dumps(self.document), encoding="utf-8")

    def add_layer(self, layer_id, native, position=(0, 0), visible=True, scale=None):
        if isinstance(native, tuple):
            native = np.array([[native]], dtype=np.uint8)
        native = np.asarray(native, dtype=np.uint8)
        height, width = native.shape[:2]
        scale = self.contract["scale"] if scale is None else scale
        rendered = np.repeat(np.repeat(native, scale, axis=0), scale, axis=1)
        path = self.root / (layer_id + ".png")
        Image.fromarray(rendered).save(path)
        self.document["layers"].append({
            "id": layer_id,
            "image": path.name,
            "logical_size": f"{width}x{height}",
            "position": list(position),
            "visible": visible,
        })
        self.flush()
        return path

    def solid(self, width, height, color):
        return np.full((height, width, 4), color, dtype=np.uint8)

    def run_cli(self, arguments):
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                code = layers.run_cli([str(value) for value in arguments])
        self.last_stdout = stdout.getvalue()
        self.last_stderr = stderr.getvalue()
        return code

    def compose(self, name="output", expected_code=0):
        out = self.root / name
        code = self.run_cli([
            "compose", "--manifest", self.manifest_path, "--out-dir", out,
        ])
        self.assertEqual(code, expected_code, self.last_stderr)
        return out

    def read_json(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def read_png(self, path):
        with Image.open(path) as image:
            return np.array(image.convert("RGBA"))

    def assert_no_accepted_images(self, out):
        self.assertFalse((out / "native.png").exists())
        self.assertFalse((out / "rendered.png").exists())

    def layer_report(self, out, index=0):
        return self.read_json(out / "layers" / f"{index:04d}" / "qa" / "report.json")

    def assert_failure(self, report, code):
        self.assertEqual(report["status"], "fail")
        self.assertIn(code, {issue["code"] for issue in report["issues"]})

    def test_binary_overlay_uses_native_position_and_transparent_holes(self):
        background = self.solid(4, 3, RED)
        foreground = np.array([[BLUE, TRANSPARENT], [TRANSPARENT, GOLD]], dtype=np.uint8)
        self.add_layer("background", background)
        self.add_layer("foreground", foreground, (1, 1))
        out = self.compose()
        expected = background.copy()
        expected[1, 1] = BLUE
        expected[2, 2] = GOLD
        np.testing.assert_array_equal(self.read_png(out / "native.png"), expected)
        np.testing.assert_array_equal(
            self.read_png(out / "rendered.png"),
            np.repeat(np.repeat(expected, 3, axis=0), 3, axis=1),
        )
        summary = self.read_json(out / "layers.json")
        self.assertEqual(summary["status"], "pass")
        self.assertEqual([item["status"] for item in summary["results"]], ["pass", "pass"])
        self.assertEqual(summary["final"]["status"], "pass")
        self.assertEqual(summary["manifest"]["sha256"], digest(self.manifest_path))
        self.assertEqual(summary["profile"]["sha256"], digest(self.profile_path))
        for item in summary["results"] + [summary["final"]]:
            report_path = out / item["report"]
            self.assertTrue(report_path.is_file())
            self.assertEqual(item["report_sha256"], digest(report_path))
        for name in ("native", "rendered"):
            artifact = summary["final"]["artifacts"][name]
            self.assertEqual(artifact["path"], name + ".png")
            self.assertEqual(artifact["sha256"], digest(out / artifact["path"]))
            decoded = self.read_png(out / artifact["path"]).tobytes()
            self.assertEqual(artifact["decoded_rgba_sha256"], hashlib.sha256(decoded).hexdigest())
        final = self.read_json(out / "final" / "report.json")
        self.assertEqual(final["status"], "pass")
        self.assertEqual(final["artistic_status"], "not_reviewed")
        self.assertEqual(final["provenance"]["source_sha256"], digest(out / "rendered.png"))
        self.assertEqual(final["acceptance_mode"], "strict_final_contract")
        self.assertEqual(final["provenance"]["source_path_base"], "output_directory")
        self.assertEqual(final["provenance"]["profile_path_base"], "output_directory")
        self.assertEqual(self.layer_report(out)["provenance"]["source_path_base"], "manifest_directory")
        for role, source in (("manifest", self.manifest_path), ("profile", self.profile_path)):
            integrity = summary["input_integrity"][role]
            self.assertIs(integrity["unchanged_during_checks"], True)
            self.assertEqual(integrity["sha256_before"], digest(source))
            self.assertEqual(integrity["sha256_after"], digest(source))
            self.assertGreaterEqual(integrity["check_count"], 2)

    def test_array_order_is_bottom_to_top(self):
        self.add_layer("lower", self.solid(4, 3, RED))
        self.add_layer("upper", BLUE, (2, 1))
        first = self.compose("first")
        self.assertEqual(tuple(self.read_png(first / "native.png")[1, 2]), BLUE)
        self.document["layers"].reverse()
        self.flush()
        second = self.compose("second")
        np.testing.assert_array_equal(self.read_png(second / "native.png"), self.solid(4, 3, RED))

    def test_hidden_layer_is_audited_but_not_composited(self):
        self.add_layer("background", self.solid(4, 3, RED))
        self.add_layer("hidden", BLUE, (1, 1), visible=False)
        out = self.compose()
        np.testing.assert_array_equal(self.read_png(out / "native.png"), self.solid(4, 3, RED))
        summary = self.read_json(out / "layers.json")
        self.assertFalse(summary["results"][1]["visible"])
        self.assertEqual(summary["results"][1]["status"], "pass")
        self.assertEqual(self.layer_report(out, 1)["status"], "pass")

    def test_omitted_visibility_defaults_to_visible(self):
        self.add_layer("sample", BLUE, (2, 1))
        del self.document["layers"][0]["visible"]
        self.flush()
        out = self.compose()
        self.assertEqual(tuple(self.read_png(out / "native.png")[1, 2]), BLUE)

    def test_hidden_nonuniform_sample_blocks_final_composition(self):
        self.add_layer("background", self.solid(4, 3, RED))
        path = self.add_layer("hidden", BLUE, visible=False)
        samples = self.read_png(path)
        samples[1, 1] = GOLD
        Image.fromarray(samples).save(path)
        out = self.compose(expected_code=2)
        self.assert_failure(self.layer_report(out, 1), "NON_SOLID_GRID_CELLS")
        self.assertEqual(self.read_json(out / "layers.json")["final"]["status"], "not_composed")
        self.assert_no_accepted_images(out)
        self.assertFalse((out / "candidate" / "rendered.png").exists())

    def test_final_palette_union_can_fail_after_every_layer_passes(self):
        self.contract["max_colors"] = 1
        self.add_layer("left", self.solid(2, 3, RED))
        self.add_layer("right", self.solid(2, 3, BLUE), (2, 0))
        out = self.compose(expected_code=2)
        self.assertEqual(self.layer_report(out, 0)["status"], "pass")
        self.assertEqual(self.layer_report(out, 1)["status"], "pass")
        self.assert_failure(self.read_json(out / "final" / "report.json"), "PALETTE_OVER_BUDGET")
        self.assert_no_accepted_images(out)
        self.assertEqual(self.read_json(out / "layers.json")["final"]["accepted"], False)

    def test_final_color_budget_counts_composited_colors_after_occlusion(self):
        self.contract["max_colors"] = 1
        self.add_layer("covered", self.solid(4, 3, RED))
        self.add_layer("cover", self.solid(4, 3, BLUE))
        out = self.compose()
        np.testing.assert_array_equal(self.read_png(out / "native.png"), self.solid(4, 3, BLUE))

    def test_final_opaque_contract_allows_transparent_foreground_layer(self):
        self.contract["alpha"] = "opaque"
        self.add_layer("background", self.solid(4, 3, RED))
        self.add_layer("foreground", np.array([[BLUE, TRANSPARENT]], dtype=np.uint8), (1, 1))
        out = self.compose()
        self.assertEqual(self.layer_report(out, 1)["status"], "pass")
        self.assertTrue(np.all(self.read_png(out / "rendered.png")[:, :, 3] == 255))

    def test_unfilled_final_canvas_fails_opaque_contract(self):
        self.contract["alpha"] = "opaque"
        self.add_layer("incomplete", self.solid(2, 2, RED))
        out = self.compose(expected_code=2)
        self.assertEqual(self.layer_report(out)["status"], "pass")
        self.assert_failure(self.read_json(out / "final" / "report.json"), "NON_OPAQUE_ALPHA")
        self.assert_no_accepted_images(out)

    def test_partial_alpha_layer_is_rejected_before_blending(self):
        self.add_layer("translucent", (160, 32, 48, 128))
        out = self.compose(expected_code=2)
        self.assert_failure(self.layer_report(out), "PARTIAL_ALPHA")
        self.assert_no_accepted_images(out)

    def test_hidden_transparent_rgb_is_compared_exactly_with_shared_palette(self):
        self.add_layer("background", self.solid(4, 3, RED))
        self.add_layer("hidden", (7, 9, 11, 0), visible=False)
        out = self.compose(expected_code=2)
        report = self.layer_report(out, 1)
        self.assert_failure(report, "COLOR_OUTSIDE_ALLOWED_PALETTE")
        self.assertEqual(report["metrics"]["outside_palette_source_pixels"], 9)
        self.assert_no_accepted_images(out)

    def test_declared_scale_is_required_without_resampling_or_input_mutation(self):
        path = self.add_layer("wrong_scale", RED, scale=4)
        before = digest(path)
        out = self.compose(expected_code=2)
        self.assertEqual(self.layer_report(out)["status"], "fail")
        self.assertEqual(digest(path), before)
        self.assert_no_accepted_images(out)

    def test_two_integer_scales_have_exact_uniform_outputs(self):
        for scale in (3, 4):
            with self.subTest(scale=scale):
                self.contract["scale"] = scale
                self.document["layers"] = []
                native = self.solid(4, 3, RED)
                native[1, 2] = BLUE
                self.add_layer("sample", native)
                out = self.compose(f"scale-{scale}")
                expected = np.repeat(np.repeat(native, scale, axis=0), scale, axis=1)
                np.testing.assert_array_equal(self.read_png(out / "rendered.png"), expected)

    def test_matching_hash_pin_passes_and_one_changed_sample_fails(self):
        path = self.add_layer("pinned", RED)
        self.document["layers"][0]["sha256"] = digest(path)
        self.flush()
        self.compose("matching")
        samples = self.read_png(path)
        samples[0, 0] = BLUE
        Image.fromarray(samples).save(path)
        out = self.compose("changed", expected_code=2)
        self.assert_no_accepted_images(out)
        self.assert_failure(self.layer_report(out), "SHA256_MISMATCH")

    def test_corrupt_input_continues_auditing_other_layers(self):
        bad = self.add_layer("bad", RED)
        self.add_layer("good", self.solid(4, 3, BLUE))
        bad.write_bytes(b"not a PNG")
        out = self.compose(expected_code=1)
        summary = self.read_json(out / "layers.json")
        self.assertEqual([item["status"] for item in summary["results"]], ["error", "pass"])
        self.assertEqual(self.layer_report(out, 1)["status"], "pass")
        self.assert_no_accepted_images(out)

    def test_repeat_composition_is_deterministic_and_inputs_are_unchanged(self):
        self.add_layer("background", self.solid(4, 3, RED))
        self.add_layer("foreground", BLUE, (2, 1))
        inputs = [self.manifest_path, self.profile_path, self.root / "background.png", self.root / "foreground.png"]
        before = {path: digest(path) for path in inputs}
        first, second = self.compose("first"), self.compose("second")
        for name in ("native.png", "rendered.png"):
            self.assertEqual(digest(first / name), digest(second / name))
        self.assertEqual(before, {path: digest(path) for path in inputs})

    def test_manifest_change_after_layer_qa_blocks_composition(self):
        self.add_layer("sample", self.solid(4, 3, RED))
        original_bytes = self.manifest_path.read_bytes()
        original_hash = digest(self.manifest_path)
        original_write_audit = layers.qa.write_audit
        mutated = []

        def mutate_after_layer_audit(audit, out_dir):
            result = original_write_audit(audit, out_dir)
            if Path(out_dir).name == "qa" and not mutated:
                self.manifest_path.write_bytes(original_bytes + b"\n")
                mutated.append(True)
            return result

        with mock.patch.object(layers.qa, "write_audit", side_effect=mutate_after_layer_audit):
            out = self.compose(expected_code=2)
        self.assertEqual(mutated, [True])
        summary = self.read_json(out / "layers.json")
        self.assertEqual(summary["results"][0]["status"], "pass")
        self.assertEqual(summary["final"]["status"], "not_composed")
        self.assertIn("MANIFEST_CHANGED", {issue["code"] for issue in summary["issues"]})
        integrity = summary["input_integrity"]["manifest"]
        self.assertIs(integrity["unchanged_during_checks"], False)
        self.assertEqual(integrity["sha256_before"], original_hash)
        self.assertEqual(integrity["sha256_after"], digest(self.manifest_path))
        self.assertIs(summary["input_integrity"]["profile"]["unchanged_during_checks"], True)
        self.assert_no_accepted_images(out)
        self.assertFalse((out / "candidate" / "rendered.png").exists())

    def test_profile_change_after_final_qa_retains_only_failed_candidates(self):
        self.add_layer("sample", self.solid(4, 3, RED))
        original_bytes = self.profile_path.read_bytes()
        original_hash = digest(self.profile_path)
        original_write_audit = layers.qa.write_audit
        mutated = []

        def mutate_after_final_audit(audit, out_dir):
            result = original_write_audit(audit, out_dir)
            if Path(out_dir).name == "final":
                self.profile_path.write_bytes(original_bytes + b"\n")
                mutated.append(True)
            return result

        with mock.patch.object(layers.qa, "write_audit", side_effect=mutate_after_final_audit):
            out = self.compose(expected_code=2)
        self.assertEqual(mutated, [True])
        summary = self.read_json(out / "layers.json")
        self.assertEqual(summary["results"][0]["status"], "pass")
        self.assertIs(summary["final"]["accepted"], False)
        final = self.read_json(out / "final" / "report.json")
        self.assert_failure(final, "PROFILE_CHANGED")
        self.assertEqual(final["acceptance_mode"], "strict_final_contract")
        self.assertEqual(final["provenance"]["source_path"], "candidate/rendered.png")
        integrity = summary["input_integrity"]["profile"]
        self.assertIs(integrity["unchanged_during_checks"], False)
        self.assertEqual(integrity["sha256_before"], original_hash)
        self.assertEqual(integrity["sha256_after"], digest(self.profile_path))
        self.assertEqual(final["contract"], self.contract)
        self.assert_no_accepted_images(out)
        np.testing.assert_array_equal(self.read_png(out / "candidate" / "native.png"), self.solid(4, 3, RED))
        self.assertEqual(summary["final"]["report_sha256"], digest(out / "final" / "report.json"))

    def test_metadata_change_after_export_promotion_demotes_accepted_images(self):
        self.add_layer("sample", self.solid(4, 3, RED))
        original_bytes = self.profile_path.read_bytes()
        original_artifact = layers._artifact
        mutated = []

        def mutate_after_promoted_export(path, *args, **kwargs):
            result = original_artifact(path, *args, **kwargs)
            if path.name == "rendered.png" and path.parent.name != "candidate":
                self.assertTrue((path.parent / "native.png").is_file())
                self.profile_path.write_bytes(original_bytes + b"\n")
                mutated.append(True)
            return result

        with mock.patch.object(layers, "_artifact", side_effect=mutate_after_promoted_export):
            out = self.compose(expected_code=2)
        self.assertEqual(mutated, [True])
        summary = self.read_json(out / "layers.json")
        self.assertIs(summary["final"]["accepted"], False)
        self.assert_no_accepted_images(out)
        for name in ("native", "rendered"):
            artifact = summary["final"]["artifacts"][name]
            self.assertEqual(artifact["path"], f"candidate/{name}.png")
            self.assertEqual(artifact["sha256"], digest(out / artifact["path"]))
            self.assertEqual(summary["outputs"][name], artifact["path"])
        final = self.read_json(out / "final" / "report.json")
        self.assert_failure(final, "PROFILE_CHANGED")
        self.assertEqual(final["acceptance_mode"], "strict_final_contract")
        self.assertIs(final["provenance"]["accepted_export_sha256_verified"], False)
        self.assertEqual(final["provenance"]["source_path"], "candidate/rendered.png")
        self.assertEqual(summary["final"]["report_sha256"], digest(out / "final" / "report.json"))

    def test_manifest_paths_resolve_relative_to_manifest_not_working_directory(self):
        self.add_layer("background", self.solid(4, 3, RED))
        previous = Path.cwd()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        try:
            os.chdir(elsewhere)
            out = self.compose()
        finally:
            os.chdir(previous)
        np.testing.assert_array_equal(self.read_png(out / "native.png"), self.solid(4, 3, RED))

    def test_compose_refuses_existing_output_without_rewriting_it(self):
        self.add_layer("background", self.solid(4, 3, RED))
        out = self.compose()
        before = {path.relative_to(out): digest(path) for path in out.rglob("*") if path.is_file()}
        self.compose(expected_code=1)
        after = {path.relative_to(out): digest(path) for path in out.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_compose_output_cannot_contain_input_manifest_or_pngs(self):
        path = self.add_layer("sample", RED)
        before = {source: digest(source) for source in (path, self.profile_path, self.manifest_path)}
        self.assertEqual(self.run_cli([
            "compose", "--manifest", self.manifest_path, "--out-dir", self.root,
        ]), 1)
        self.assertEqual(before, {source: digest(source) for source in before})

    def test_list_does_not_run_qa_or_modify_sources(self):
        path = self.add_layer("bad", RED)
        path.write_bytes(b"not a PNG")
        before = {p.name: digest(p) for p in self.root.iterdir() if p.is_file()}
        self.assertEqual(self.run_cli(["list", "--manifest", self.manifest_path]), 0, self.last_stderr)
        listing = json.loads(self.last_stdout)
        self.assertIn("bad", self.last_stdout)
        self.assertEqual(listing["status"], "plan")
        self.assertIs(listing["qa_performed"], False)
        after = {p.name: digest(p) for p in self.root.iterdir() if p.is_file()}
        self.assertEqual(before, after)

    def test_edit_changes_position_visibility_and_order_in_fresh_manifest(self):
        self.add_layer("bottom", self.solid(4, 3, RED))
        self.add_layer("middle", BLUE)
        self.add_layer("top", GOLD)
        original = self.manifest_path.read_bytes()
        target = self.root / "revised.json"
        self.assertEqual(self.run_cli([
            "edit", "--manifest", self.manifest_path, "--layer", "middle",
            "--position", "2,1", "--visible", "false", "--index", "0", "--out", target,
        ]), 0, self.last_stderr)
        revised = self.read_json(target)
        self.assertEqual([item["id"] for item in revised["layers"]], ["middle", "bottom", "top"])
        self.assertEqual(revised["layers"][0]["position"], [2, 1])
        self.assertIs(revised["layers"][0]["visible"], False)
        self.assertEqual(self.manifest_path.read_bytes(), original)
        self.assertEqual(revised["layers"][1:], self.document["layers"][0:1] + self.document["layers"][2:3])
        layers.load_manifest(target)
        self.manifest_path = target
        out = self.compose("edited-output")
        expected = self.solid(4, 3, RED)
        expected[0, 0] = GOLD
        np.testing.assert_array_equal(self.read_png(out / "native.png"), expected)

    def test_edit_refuses_overwrite_and_relocation_that_would_change_relative_paths(self):
        self.add_layer("sample", RED)
        original = self.manifest_path.read_bytes()
        nested = self.root / "nested"
        nested.mkdir()
        for target in (self.manifest_path, nested / "scene.json"):
            with self.subTest(target=target):
                self.assertEqual(self.run_cli([
                    "edit", "--manifest", self.manifest_path, "--layer", "sample",
                    "--position", "1,1", "--out", target,
                ]), 1)
        self.assertEqual(self.manifest_path.read_bytes(), original)
        self.assertFalse((nested / "scene.json").exists())

    def test_invalid_edit_does_not_write_new_manifest(self):
        self.add_layer("sample", self.solid(2, 2, RED))
        for flags in (["--position", "3,2"], ["--index", "1"], ["--visible", "maybe"]):
            with self.subTest(flags=flags):
                target = self.root / "invalid.json"
                with contextlib.redirect_stderr(io.StringIO()):
                    try:
                        code = self.run_cli([
                            "edit", "--manifest", self.manifest_path, "--layer", "sample",
                            *flags, "--out", target,
                        ])
                    except SystemExit as error:
                        code = error.code
                self.assertNotEqual(code, 0)
                self.assertFalse(target.exists())

    def test_layer_positions_must_be_integer_cells_and_fully_in_bounds(self):
        self.add_layer("sample", self.solid(2, 2, RED))
        for position in ([1.5, 0], [True, 0], [-1, 0], [3, 0], [0, 2], [0], "1,1"):
            with self.subTest(position=position):
                self.document["layers"][0]["position"] = position
                self.flush()
                with self.assertRaises(ValueError):
                    layers.load_manifest(self.manifest_path)
        self.document["layers"][0]["position"] = [2, 1]
        self.flush()
        self.compose()

    def test_unsafe_relative_image_and_profile_paths_are_rejected(self):
        self.add_layer("sample", RED)
        for field in ("image", "profile"):
            for value in ("../outside.png", "/absolute.png", "C:/absolute.png", "folder\\sample.png", "https://example.com/sample.png"):
                with self.subTest(field=field, value=value):
                    if field == "image":
                        self.document["layers"][0]["image"] = value
                    else:
                        self.document["layers"][0]["image"] = "sample.png"
                        self.document["profile"] = value
                    self.flush()
                    with self.assertRaises(ValueError):
                        layers.load_manifest(self.manifest_path)
            self.document["profile"] = "profile.json"

    def test_symlink_source_outside_manifest_directory_is_rejected(self):
        self.add_layer("sample", RED)
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "outside.png"
            Image.new("RGBA", (3, 3), RED).save(outside)
            link = self.root / "escape.png"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"Symlinks unavailable on this host: {error}")
            self.document["layers"][0]["image"] = link.name
            self.flush()
            with self.assertRaises(ValueError):
                layers.load_manifest(self.manifest_path)

    def test_unknown_fields_and_duplicate_layer_ids_are_rejected(self):
        self.add_layer("sample", RED)
        self.document["unexpected"] = True
        self.flush()
        with self.assertRaises(ValueError):
            layers.load_manifest(self.manifest_path)
        del self.document["unexpected"]
        self.document["layers"][0]["blend"] = "normal"
        self.flush()
        with self.assertRaises(ValueError):
            layers.load_manifest(self.manifest_path)
        del self.document["layers"][0]["blend"]
        self.document["layers"].append(self.document["layers"][0].copy())
        self.flush()
        with self.assertRaises(ValueError):
            layers.load_manifest(self.manifest_path)

    def test_duplicate_json_fields_cannot_override_constraints(self):
        self.add_layer("sample", RED)
        base = self.manifest_path.read_text(encoding="utf-8")
        for text in (
            base.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'),
            base.replace('"image": "sample.png"', '"image": "sample.png", "image": "sample.png"'),
        ):
            with self.subTest(text=text):
                self.manifest_path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    layers.load_manifest(self.manifest_path)

    def test_strict_manifest_types_and_hash_syntax(self):
        self.add_layer("sample", RED)
        original = self.document["layers"][0].copy()
        for change in ({"id": ""}, {"id": 1}, {"logical_size": [1, 1]},
                       {"visible": "false"}, {"visible": 0}, {"sha256": "x" * 64},
                       {"sha256": "a" * 63}, {"sha256": 0}, {"sha256": None}):
            with self.subTest(change=change):
                self.document["layers"][0] = original | change
                self.flush()
                with self.assertRaises(ValueError):
                    layers.load_manifest(self.manifest_path)
        self.document["layers"][0] = original
        for change in ({"schema_version": True}, {"schema_version": 2}, {"name": 1}, {"layers": []}):
            with self.subTest(change=change):
                self.manifest_path.write_text(json.dumps(self.document | change), encoding="utf-8")
                with self.assertRaises(ValueError):
                    layers.load_manifest(self.manifest_path)

    def test_layers_require_palette_budget_and_exact_binary_contract(self):
        self.add_layer("sample", RED)
        original = self.contract.copy()
        for change in ({"transparent_rgb": "visible"}, {"alpha": "any"},
                       {"allowed_palette": None}, {"max_colors": None}):
            with self.subTest(change=change):
                self.contract = original | change
                self.flush()
                with self.assertRaises(ValueError):
                    layers.load_manifest(self.manifest_path)

    def test_layer_count_and_declared_total_pixel_caps_reject_before_decode(self):
        self.add_layer("sample", RED)
        first = self.document["layers"][0].copy()
        self.document["layers"] = [first | {"id": f"layer-{index}"} for index in range(64)]
        self.flush()
        self.assertEqual(len(layers.load_manifest(self.manifest_path)["layers"]), 64)
        self.document["layers"] = [first | {"id": f"layer-{index}"} for index in range(65)]
        self.flush()
        with self.assertRaises(ValueError):
            layers.load_manifest(self.manifest_path)
        self.contract["logical_size"] = "512x512"
        self.document["layers"] = [first | {"id": f"layer-{index}", "logical_size": "512x512"} for index in range(22)]
        self.flush()
        with self.assertRaises(ValueError):
            layers.load_manifest(self.manifest_path)

    def test_actual_header_pixel_cap_cannot_be_bypassed_with_tiny_declared_sizes(self):
        image = self.add_layer("sample", RED)
        first = self.document["layers"][0].copy()
        self.document["layers"] = [first | {"id": f"layer-{index}"} for index in range(5)]
        self.flush()
        # This deliberately corrupt header requests 12M pixels per entry.
        # The first four are ordinary decode errors; the fifth must hit the
        # cumulative resource gate before decoder acceptance is considered.
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 4000, 3000))
        out = self.compose(expected_code=1)
        results = self.read_json(out / "layers.json")["results"]
        self.assertEqual([item["status"] for item in results], ["error"] * 5)
        self.assertIn("48,000,000", results[4]["error"])
        self.assert_no_accepted_images(out)


if __name__ == "__main__":
    unittest.main()
