# SPDX-License-Identifier: Apache-2.0
"""Independent 2D artwork fixtures and adversarial sequence checks, with no rig."""
import base64
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pixel_sequence as sequence


def fixture():
    """An impossible floating two-part device, authored directly as RGBA cells."""
    frames, observations = [], []
    offsets = [(-1, -1), (0, 0), (1, 1), (0, 2), (-1, 1), (-2, 0)]
    blue, gold, ink = (40, 110, 200, 255), (245, 190, 60, 255), (28, 24, 50, 255)
    for dx, dy in offsets:
        frame = np.zeros((24, 24, 4), dtype=np.uint8)
        shell = [[y, 7, 13] for y in range(10, 16)]
        fin = [[y + dy, 15 + dx, 18 + dx] for y in range(10, 13)]
        frame[10:16, 7:13] = blue
        frame[11:15, 8:12] = ink
        frame[10 + dy:13 + dy, 15 + dx:18 + dx] = gold
        frame[11 + dy, 16 + dx] = ink
        observations.append({"parts": {
            "shell": {"visibility": "visible", "mask": shell, "measurements": {"span": [[7, 10], [12, 10]]}},
            "floating_fin": {"visibility": "visible", "mask": fin,
                             "measurements": {"span": [[15 + dx, 10 + dy], [17 + dx, 10 + dy]]}}},
            "landmarks": {"latch": [12, 12], "fin_latch": [15 + dx, 11 + dy], "fin_tip": [17 + dx, 11 + dy]}})
        frames.append(frame)
    spec = {"schema_version": 1, "name": "Orbit seed", "description": "A fictional blue rune capsule with a gold magnetic floating fin.",
        "frame_size": "24x24", "scale": 4, "max_colors": 3, "derivation": {"mode": "strict"},
        "limits": {"edge_margin": 1, "area_ratio": [0.8, 1.2], "color_distance": 20, "max_bad_color_fraction": 0.05},
        "parts": {"shell": {"description": "Blue capsule and dark inset; never changes size.", "measurements": {"span": 0.1}},
                  "floating_fin": {"description": "Gold fin with one dark central marking.", "measurements": {"span": 0.1}}},
        "landmarks": {"latch": {"description": "Capsule magnetic latch", "part": "shell"},
                      "fin_latch": {"description": "Fin's near end", "part": "floating_fin"},
                      "fin_tip": {"description": "Fin's far end", "part": "floating_fin"}},
        "ratios": {"fin_to_shell": {"numerator": ["floating_fin", "span"], "denominator": ["shell", "span"], "tolerance": 0.1}},
        "states": {"orbit": {"intent": "Fin makes a small closed floating orbit while the capsule stays still.",
            "poses": ["Fin rises left", "Fin crosses center", "Fin moves right", "Fin dips", "Fin moves left", "Fin returns upward"],
            "columns": 3, "loop": True, "durations_ms": [100] * 6,
            "motion": {"latch": {"min_travel": 0, "max_speed": 0},
                       "fin_latch": {"relative_to": "latch", "min_travel": 3, "max_speed": 30, "max_acceleration": 400},
                       "fin_tip": {"relative_to": "latch", "min_travel": 3, "max_speed": 30, "max_acceleration": 400}},
            "attachments": [{"a": "latch", "b": "fin_latch", "max_distance": 5}],
            "distances": [{"a": "fin_latch", "b": "fin_tip", "minimum": 2, "maximum": 2}]}}}
    return spec, frames, observations


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.spec, self.frames, self.data = fixture()
        self.run = self.root / "run"
        self.reference = self.root / "reference.png"
        self.spec_path = self.root / "spec.json"
        self.raw = self.root / "sheet.png"
        self.number = 0

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self):
        self.spec_path.write_bytes(sequence.json_bytes(self.spec))
        Image.fromarray(self.frames[0]).save(self.reference)
        sequence.prepare(self.spec_path, self.reference, self.run)

    def save_sheet(self):
        # Independent fixed-slot placement, not the sequence renderer/checker.
        sheet = np.zeros((48, 72, 4), dtype=np.uint8)
        for index, frame in enumerate(self.frames):
            x, y = (index % 3) * 24, (index // 3) * 24
            sheet[y:y + 24, x:x + 24] = frame
        Image.fromarray(sheet).save(self.raw)

    def import_sheet(self, replace=False):
        self.save_sheet()
        return sequence.import_image(self.run, "orbit", self.raw, producer="independently_authored_RGBA_test_fixture", replace=replace)

    def observed(self):
        value = sequence.observation_template(self.run)
        value["method"] = "Independent authored-cell fixture with known visible regions; not copied guide coordinates"
        value["reference"] = copy.deepcopy(self.data[0])
        value["states"]["orbit"]["frames"] = copy.deepcopy(self.data)
        value["states"]["orbit"]["review"] = {"status": "accepted", "reviewer": "Fixture specification, not human approval",
            "observations": ["The fixed capsule and floating marked fin retain their authored dots across the six positions."]}
        return value

    def check(self, observations=True):
        self.number += 1
        if observations is True:
            observations = self.observed()
        path = None
        if observations is not None:
            path = self.root / f"observed-{self.number}.json"
            path.write_bytes(sequence.json_bytes(observations))
        return sequence.check(self.run, self.root / f"audit-{self.number}", path, preview_scale=2)

    def codes(self, report):
        return {issue["code"] for issue in report["issues"]}

    def test_end_to_end_arbitrary_parts_without_skeleton_and_read_back_exports(self):
        self.prepare()
        self.import_sheet()
        report = self.check()
        self.assertEqual(report["status"], "pass", report["issues"])
        self.assertFalse(report["skeleton_required"])
        self.assertFalse(report["human_approval_recorded"])
        with Image.open(self.root / "audit-1/orbit/native.png") as image:
            np.testing.assert_array_equal(np.array(image)[:24, :24], self.frames[0])
        with Image.open(self.root / "audit-1/orbit/rendered.png") as image:
            expected = np.repeat(np.repeat(np.array(Image.open(self.raw)), 4, axis=0), 4, axis=1)
            np.testing.assert_array_equal(np.array(image), expected)
        with Image.open(self.root / "audit-1/orbit/pixel-audit/animations/orbit.gif") as gif:
            self.assertEqual(gif.n_frames, 6)
            self.assertEqual(gif.info["loop"], 0)
            self.assertEqual(gif.info["duration"], 100)

    def test_unobserved_and_occluded_never_pass(self):
        self.prepare()
        self.import_sheet()
        report = self.check(None)
        self.assertEqual(report["status"], "review")
        self.assertIn("MOTION_UNVERIFIED", self.codes(report))
        observed = self.observed()
        observed["states"]["orbit"]["frames"][2]["parts"]["floating_fin"] = {"visibility": "occluded", "reason": "Not measurable in the actual picture"}
        report = self.check(observed)
        self.assertEqual(report["status"], "review")
        self.assertIn("PART_OCCLUDED", self.codes(report))

    def test_frozen_animation_detected_despite_exact_colors_and_grid(self):
        self.prepare()
        self.frames = [self.frames[0].copy() for _ in self.frames]
        self.data = [copy.deepcopy(self.data[0]) for _ in self.data]
        self.import_sheet()
        report = self.check()
        self.assertIn("REQUIRED_MOTION_MISSING", self.codes(report))
        self.assertEqual(report["states"]["orbit"]["pixel_status"], "pass")

    def test_whole_object_translation_does_not_count_as_relative_articulation(self):
        self.spec["states"]["orbit"]["motion"]["fin_tip"]["relative_to"] = "latch"
        self.spec["states"]["orbit"]["motion"]["latch"]["max_speed"] = 40
        base_frame, base_data = self.frames[0].copy(), copy.deepcopy(self.data[0])
        for index, dx in enumerate((0, 1, 2, 3, 2, 1)):
            self.frames[index] = np.roll(base_frame, dx, axis=1)
            item = copy.deepcopy(base_data)
            for part in item["parts"].values():
                part["mask"] = [[y, start + dx, end + dx] for y, start, end in part["mask"]]
                for pair in part["measurements"].values():
                    for endpoint in pair:
                        endpoint[0] += dx
            for endpoint in item["landmarks"].values():
                endpoint[0] += dx
            self.data[index] = item
        self.prepare()
        self.import_sheet()
        report = self.check()
        failures = [issue for issue in report["issues"] if issue["code"] == "REQUIRED_MOTION_MISSING"]
        self.assertTrue(any(issue["landmark"] == "fin_tip" for issue in failures))
        self.assertEqual(report["states"]["orbit"]["motion"]["landmarks"]["fin_tip"]["travel"], 0)

    def test_relative_articulation_with_missing_anchor_stays_review(self):
        self.spec["states"]["orbit"]["motion"]["fin_tip"]["relative_to"] = "latch"
        self.prepare()
        self.import_sheet()
        observations = self.observed()
        observations["states"]["orbit"]["frames"][2]["landmarks"]["latch"] = None
        report = self.check(observations)
        self.assertEqual(report["status"], "review")
        self.assertNotIn("fin_tip", report["states"]["orbit"]["motion"]["landmarks"])

    def test_changed_color_detected_before_project_palette_remap(self):
        self.spec["derivation"]["mode"] = "project"
        self.prepare()
        self.frames[2][self.frames[2][:, :, 3] > 0] = [0, 255, 0, 255]
        self.import_sheet()
        report = self.check()
        self.assertIn("SOURCE_COLORS_CHANGED", self.codes(report))
        self.assertIn("PART_COLOR_CHANGED", self.codes(report))
        self.assertEqual(report["states"]["orbit"]["pixel_status"], "pass")

    def test_changed_design_with_identical_shape_and_palette_detected(self):
        self.prepare()
        # Move a center marking to a corner, retaining exact area and histogram.
        self.frames[2][12, 17] = [245, 190, 60, 255]
        self.frames[2][11, 16] = [28, 24, 50, 255]
        self.import_sheet()
        report = self.check()
        self.assertIn("PART_DESIGN_CHANGED", self.codes(report))
        fin = report["states"]["orbit"]["frames"][2]["parts"]["floating_fin"]
        self.assertEqual(fin["color_overlap"], 1)
        self.assertEqual(fin["shape_match"], 1)

    def test_projection_is_whole_canvas_uniform_even_for_noninteger_provider_size(self):
        self.spec["derivation"]["mode"] = "project"
        self.prepare()
        self.save_sheet()
        with Image.open(self.raw) as image:
            image.resize((150, 100), Image.Resampling.NEAREST).save(self.raw)
        sequence.import_image(self.run, "orbit", self.raw)
        report = self.check(None)
        self.assertEqual(report["states"]["orbit"]["derivation"]["sampling"], "nearest_whole_canvas")
        self.assertEqual(report["states"]["orbit"]["derivation"]["original_grid_status"], "not_certified_projection_source")
        self.assertNotIn("SOURCE_LAYOUT_INVALID", self.codes(report))

    def test_size_proportion_and_ratio_changes_detected(self):
        self.prepare()
        self.frames[2][10:14, 16:21] = [245, 190, 60, 255]
        item = self.data[2]["parts"]["floating_fin"]
        item["mask"] = [[y, 16, 21] for y in range(10, 14)]
        item["measurements"]["span"] = [[16, 10], [20, 10]]
        self.import_sheet()
        report = self.check()
        self.assertTrue({"PART_SIZE_CHANGED", "PART_PROPORTION_CHANGED", "PART_RATIO_CHANGED"} <= self.codes(report))

    def test_detachment_and_feature_distance_detected(self):
        self.prepare()
        observed_data = self.data[2]
        mask = sequence._runs_mask(observed_data["parts"]["floating_fin"]["mask"], (24, 24))
        self.frames[2][mask] = 0
        self.frames[2][11:14, 20:23] = [245, 190, 60, 255]
        observed_data["parts"]["floating_fin"]["mask"] = [[y, 20, 23] for y in range(11, 14)]
        observed_data["parts"]["floating_fin"]["measurements"]["span"] = [[20, 11], [22, 11]]
        observed_data["landmarks"].update(fin_latch=[20, 12], fin_tip=[21, 12])
        self.import_sheet()
        report = self.check()
        self.assertTrue({"PART_DETACHED", "FEATURE_DISTANCE_CHANGED"} <= self.codes(report))

    def test_time_aware_loop_speed_and_acceleration(self):
        self.spec["states"]["orbit"]["durations_ms"][-1] = 10
        self.prepare()
        self.import_sheet()
        report = self.check()
        errors = [item for item in report["issues"] if item["code"] == "MOTION_SPEED_EXCEEDED"]
        self.assertTrue(any(item["loop_boundary"] for item in errors))
        self.assertIn("MOTION_ACCELERATION_EXCEEDED", self.codes(report))

    def test_contact_sliding_and_ground_mismatch(self):
        self.spec["states"]["orbit"]["contacts"] = [
            {"landmark": "fin_latch", "frames": [0, 1], "max_drift": 0, "ground_y": 10, "max_ground_error": 0}]
        self.prepare()
        self.import_sheet()
        report = self.check()
        self.assertTrue({"CONTACT_SLIDING", "CONTACT_GROUND_MISMATCH"} <= self.codes(report))

    def test_in_place_contact_restores_declared_root_motion(self):
        state = self.spec["states"]["orbit"]
        first = self.data[0]["landmarks"]["fin_latch"]
        state["root_offsets"] = [[first[0] - item["landmarks"]["fin_latch"][0], first[1] - item["landmarks"]["fin_latch"][1]] for item in self.data]
        state["contacts"] = [{"landmark": "fin_latch", "frames": list(range(6)), "max_drift": 0}]
        self.prepare()
        self.import_sheet()
        self.assertNotIn("CONTACT_SLIDING", self.codes(self.check()))

    def test_stale_observations_rejected_after_preserved_regeneration(self):
        self.prepare()
        previous = self.import_sheet()
        observed = self.observed()
        original = self.raw.read_bytes()
        self.frames[1][11, 8] = [40, 110, 200, 255]
        replaced = self.import_sheet(replace=True)
        self.assertNotEqual(previous["sha256"], replaced["sha256"])
        folder = self.run / replaced["history"][0]["path"]
        self.assertEqual((folder / "image.png").read_bytes(), original)
        self.assertEqual(sequence.read_json(folder / "generation.json")["sha256"], previous["sha256"])
        with self.assertRaisesRegex(ValueError, "Stale"):
            self.check(observed)

    def test_contract_reference_and_prompt_tampering_block_generation_before_network(self):
        for name in ("contract.json", "reference-native.png", "prompts/orbit.txt"):
            with self.subTest(name=name):
                if not self.run.exists():
                    self.prepare()
                path = self.run / name
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                with patch("urllib.request.build_opener") as network:
                    with self.assertRaises(ValueError):
                        sequence.generate(self.run, "orbit", model="test-image-model", api_key="test-secret")
                    network.assert_not_called()
                path.write_bytes(original)

    def test_host_import_requires_explicit_replace_and_preserves_reference(self):
        self.prepare()
        expected = (self.run / "reference-source.png").read_bytes()
        self.import_sheet()
        with self.assertRaisesRegex(ValueError, "exists"):
            self.import_sheet()
        self.assertEqual((self.run / "reference-source.png").read_bytes(), expected)

    def test_api_request_uses_only_selected_design_and_frozen_prompt(self):
        self.prepare()
        self.save_sheet()
        response = io.BytesIO(json.dumps({"data": [{"b64_json": base64.b64encode(self.raw.read_bytes()).decode()}]}).encode())
        with patch("urllib.request.build_opener") as make:
            make.return_value.open.return_value = response
            result = sequence.generate(self.run, "orbit", model="test-image-model", api_key="test-secret")
            request = make.return_value.open.call_args.args[0]
        self.assertIn((self.run / "reference-native.png").read_bytes(), request.data)
        self.assertIn((self.run / "prompts/orbit.txt").read_bytes(), request.data)
        self.assertIn(b"Fin's far end", request.data)
        self.assertIn(b"relative to latch", request.data)
        self.assertEqual(request.data.count(b'name="image[]"'), 1)
        self.assertEqual(result["producer"]["method"], "images_edits_http")
        self.assertNotIn(b'name="background"', request.data)
        self.assertNotIn("test-secret", (self.run / "run.json").read_text())

    def test_explicit_provider_background_is_preserved(self):
        self.prepare()
        self.save_sheet()
        response = io.BytesIO(json.dumps({"data": [{"b64_json": base64.b64encode(self.raw.read_bytes()).decode()}]}).encode())
        with patch("urllib.request.build_opener") as make:
            make.return_value.open.return_value = response
            result = sequence.generate(self.run, "orbit", model="test-image-model", background="transparent", api_key="test-secret")
            request = make.return_value.open.call_args.args[0]
        self.assertIn(b'name="background"\r\n\r\ntransparent', request.data)
        self.assertEqual(result["producer"]["background"], "transparent")

    def test_api_failure_leaves_old_image_and_manifest_unchanged(self):
        self.prepare()
        self.import_sheet()
        raw, manifest = (self.run / "raw/orbit.png").read_bytes(), (self.run / "run.json").read_bytes()
        with patch("urllib.request.build_opener") as make:
            make.return_value.open.side_effect = sequence.urllib.error.URLError("private error detail")
            with self.assertRaisesRegex(RuntimeError, "connection failed"):
                sequence.generate(self.run, "orbit", model="test-image-model", api_key="test-secret", replace=True)
        self.assertEqual(raw, (self.run / "raw/orbit.png").read_bytes())
        self.assertEqual(manifest, (self.run / "run.json").read_bytes())
        self.assertFalse((self.run / "history").exists())

    def test_unsafe_endpoints_rejected_without_a_request(self):
        self.prepare()
        for endpoint in ("http://example.com/v1", "https://secret@example.com/v1", "https://example.com/v1?key=secret"):
            with patch("urllib.request.build_opener") as make:
                with self.assertRaises(ValueError):
                    sequence.generate(self.run, "orbit", model="test", api_key="test-secret", base_url=endpoint)
                make.assert_not_called()

    def test_invalid_numbers_and_names_rejected(self):
        for value in (True, "3", float("nan"), float("inf")):
            spec = copy.deepcopy(self.spec)
            spec["states"]["orbit"]["motion"]["fin_tip"]["max_speed"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                sequence.validate_spec(spec)
        self.spec["parts"]["../escape"] = self.spec["parts"].pop("shell")
        with self.assertRaises(ValueError):
            sequence.validate_spec(self.spec)

    def test_missing_review_cannot_be_promoted_by_numeric_pass(self):
        self.prepare()
        self.import_sheet()
        observed = self.observed()
        observed["states"]["orbit"]["review"] = {"status": "not_reviewed", "reviewer": "", "observations": []}
        report = self.check(observed)
        self.assertEqual(report["technical_status"], "pass", report["issues"])
        self.assertEqual(report["status"], "review")

    def test_masks_and_landmarks_must_describe_actual_visible_pixels(self):
        self.prepare()
        self.import_sheet()
        observed = self.observed()
        observed["states"]["orbit"]["frames"][2]["parts"]["floating_fin"]["mask"].append([0, 0, 1])
        observed["states"]["orbit"]["frames"][2]["landmarks"]["fin_tip"] = [0, 0]
        report = self.check(observed)
        self.assertTrue({"MASK_ON_TRANSPARENT", "LANDMARK_OFF_ART"} <= self.codes(report))

    def test_feature_cannot_move_onto_another_visible_part(self):
        self.prepare()
        self.import_sheet()
        observed = self.observed()
        observed["states"]["orbit"]["frames"][2]["landmarks"]["fin_tip"] = [8, 11]
        self.assertIn("LANDMARK_ON_WRONG_PART", self.codes(self.check(observed)))

    def test_strict_nonuniform_cell_source_is_a_failure_even_when_derivative_is_uniform(self):
        self.prepare()
        self.save_sheet()
        with Image.open(self.raw) as native:
            image = native.resize((144, 96), Image.Resampling.NEAREST)
        image.putpixel((14, 20), (0, 255, 0, 255))
        image.save(self.raw)
        sequence.import_image(self.run, "orbit", self.raw)
        self.assertIn("SOURCE_GRID_INVALID", self.codes(self.check(None)))

    def test_wrong_sheet_aspect_is_never_stretched_or_fitted(self):
        self.spec["derivation"]["mode"] = "project"
        self.prepare()
        self.save_sheet()
        with Image.open(self.raw) as native:
            native.resize((100, 100)).save(self.raw)
        sequence.import_image(self.run, "orbit", self.raw)
        report = self.check(None)
        self.assertIn("SOURCE_LAYOUT_INVALID", self.codes(report))
        self.assertFalse((self.root / "audit-1/orbit/native.png").exists())


if __name__ == "__main__":
    unittest.main()
