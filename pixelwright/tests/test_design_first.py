# SPDX-License-Identifier: Apache-2.0
"""Regression controls for identity-before-rig and independent artwork evidence."""
from __future__ import annotations

import copy
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import knight_design_first as design
import knight_generate_frames as generation
import knight_rig_3d as rig
import knight_sheet_3d as sheets


def landmarks():
    base = rig.contract()["animations"]["block"]["frames"][0]
    # The design deliberately has different arm and torso proportions from the
    # legacy mesh. These are authored design observations, not inferred labels.
    joints = {n: {"xy": list(p), "depth_offset_m": .03 * (i % 3)}
              for i, (n, p) in enumerate(base["joints_image"].items())}
    joints["hand_r"]["xy"][0] -= 7
    joints["mace_head"]["xy"][0] -= 7
    joints["neck"]["xy"][1] -= 3
    return {"joints": joints, "part_dimensions": {"helmet": [11, 15], "mace_head": [10]}}


class DesignFirstTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        design.initialize(self.run, "An original rounded-helmet knight")
        image = Image.new("RGBA", (128, 128), "#FF00FF")
        draw = ImageDraw.Draw(image)
        draw.rectangle((44, 26, 81, 108), fill="#698798")
        draw.rectangle((54, 54, 72, 91), fill="#A02C31")
        self.source = self.root / "source.png"
        image.resize((1024, 1024), Image.Resampling.NEAREST).save(self.source)

    def select(self):
        design.select_design(self.run, self.source)
        value = landmarks()
        value["design_sha256"] = sheets.digest(self.run / "references" / "design-native.png")
        path = self.root / "landmarks.json"; sheets.write_json(path, value)
        return path

    def prepare(self):
        design.prepare_poses(self.run, self.select())

    def test_first_generation_has_no_3d_or_pose_input(self):
        prompts = json.loads((self.run / "prompts.json").read_text())
        self.assertEqual(list(prompts), ["design"])
        self.assertEqual(prompts["design"]["images"], [])
        self.assertFalse((self.run / "contract.json").exists())

    def test_optional_user_reference_is_the_only_design_input(self):
        other = self.root / "reference-run"
        design.initialize(other, "Preserve the referenced character", self.source)
        prompts = json.loads((other / "prompts.json").read_text())
        self.assertEqual(prompts["design"]["images"], ["references/input.png"])

    def test_identity_registration_uses_no_mesh_or_skeleton(self):
        raw_sha = sheets.digest(self.source)
        self.select()
        identity = json.loads((self.run / "identity.json").read_text())
        self.assertFalse(identity["rig_used_for_design"])
        self.assertEqual(identity["identity_authority"], "selected_2d_design")
        self.assertEqual(sheets.digest(self.source), raw_sha)
        self.assertFalse((self.run / "contract.json").exists())
        self.assertEqual(Image.open(self.run / "references" / "design-native.png").size, (128, 128))
        with self.assertRaisesRegex(ValueError, "already selected"):
            design.select_design(self.run, self.source)

    def test_retarget_uses_selected_design_and_preserves_18_pose_lengths(self):
        value = landmarks(); data = design.retarget(value)
        self.assertEqual(rig.validate_contract(data)["status"], "pass")
        self.assertFalse(data["appearance_meshes"])
        ready = data["animations"]["block"]["frames"][0]
        for name, point in value["joints"].items():
            np.testing.assert_allclose(ready["joints_image"][name], point["xy"], atol=1e-10)
        self.assertNotAlmostEqual(data["bone_lengths_m"]["forearm_r"], rig.contract()["bone_lengths_m"]["forearm_r"])
        self.assertNotIn("silhouette_iou_min", data["acceptance"])
        overhead = data["animations"]["attack"]["frames"][1]["joints_image"]
        self.assertLess(overhead["hand_r"][1], overhead["crown"][1])

    def test_state_inputs_are_design_then_bare_bones(self):
        self.prepare()
        prompts = json.loads((self.run / "prompts.json").read_text())
        for state in ("walk", "attack", "block"):
            self.assertEqual(prompts[state]["images"], ["references/design-sheet.png", f"guides/{state}-skeleton.png"])
            self.assertFalse(any("volume" in name or "parts" in name for name in prompts[state]["images"]))
            self.assertIn("An original rounded-helmet knight", prompts[state]["prompt"])
            self.assertNotIn("red plume", prompts[state]["prompt"])
            self.assertNotIn("small head and long torso", prompts[state]["prompt"])
        design.load_run(self.run)

    def generate(self, *arguments, response=None, error=None):
        output = io.StringIO()
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
                patch.object(generation, "request_image", return_value=response or (self.source.read_bytes(), {}),
                             side_effect=error) as request, \
                patch.object(sys, "argv", ["knight_generate_frames.py", "--poses", str(self.run), *arguments]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = generation.main()
        return status, request, output.getvalue()

    def test_selected_design_cannot_be_force_regenerated(self):
        self.select()
        original = (self.run / "raw/design.png").read_bytes()
        status, request, message = self.generate("--animation", "design", "--force")
        self.assertEqual(status, 1)
        self.assertIn("design is frozen", message)
        request.assert_not_called()
        self.assertEqual((self.run / "raw/design.png").read_bytes(), original)

    def test_unprepared_or_unknown_animation_is_an_error_without_a_request(self):
        for state in ("walk", "wakl"):
            with self.subTest(state=state):
                status, request, message = self.generate("--animation", state)
                self.assertEqual(status, 1)
                self.assertIn("Unknown animation", message)
                request.assert_not_called()

    def test_default_force_generates_only_motion_after_selection(self):
        self.prepare()
        original = (self.run / "raw/design.png").read_bytes()
        status, request, _ = self.generate("--force")
        self.assertEqual(status, 0)
        self.assertEqual({call.args[0]["output"] for call in request.call_args_list},
                         {"raw/walk.png", "raw/attack.png", "raw/block.png"})
        self.assertEqual((self.run / "raw/design.png").read_bytes(), original)
        design.load_run(self.run)

    def test_changed_identity_or_guide_is_rejected_before_generation(self):
        self.prepare()
        for relative in ("raw/design.png", "guides/walk-skeleton.png", "contract.json"):
            with self.subTest(relative=relative):
                path = self.run / relative; original = path.read_bytes()
                path.write_bytes(original + b" ")
                status, request, message = self.generate("--animation", "walk")
                self.assertEqual(status, 1)
                self.assertIn("changed", message)
                request.assert_not_called()
                path.write_bytes(original)

    def test_state_generation_requires_frozen_poses_and_ordered_design_inputs(self):
        self.prepare()
        path = self.run / "prompts.json"; prompts = json.loads(path.read_text())
        prompts["walk"]["images"].reverse(); sheets.write_json(path, prompts)
        status, request, message = self.generate("--animation", "walk")
        self.assertEqual(status, 1)
        self.assertIn("2D design first", message)
        request.assert_not_called()
        (self.run / "run.json").unlink()
        status, request, message = self.generate("--animation", "walk")
        self.assertEqual(status, 1)
        self.assertIn("freeze its poses", message)
        request.assert_not_called()

    def test_force_keeps_replaced_raw_images_and_provenance(self):
        self.prepare()
        raw = self.run / "raw/walk.png"
        original = self.source.read_bytes(); raw.write_bytes(original)
        replacements = []
        for color in ("blue", "green"):
            stream = io.BytesIO(); Image.new("RGB", (1536, 1024), color).save(stream, "PNG")
            replacements.append(stream.getvalue())
        for replacement in replacements:
            status, _, _ = self.generate("--animation", "walk", "--force", response=(replacement, {}))
            self.assertEqual(status, 0)
        record = json.loads((self.run / "generated/manifest.json").read_text())["walk"]
        self.assertEqual(raw.read_bytes(), replacements[-1])
        self.assertEqual(len(record["history"]), 2)
        for index, expected in enumerate((original, replacements[0])):
            archive = record["history"][index]
            self.assertEqual((self.run / archive["image"]).read_bytes(), expected)
            metadata = json.loads((self.run / archive["metadata"]).read_text())
            self.assertEqual(metadata["output_sha256"], generation.sha256(expected))
            if index == 0:
                self.assertIsNone(metadata["generation"])
            else:
                self.assertTrue(metadata["generation_matches_image"])
                self.assertEqual(metadata["generation"]["output_sha256"], generation.sha256(expected))

    def test_failed_generation_keeps_current_raw_and_manifest(self):
        self.prepare()
        self.generate("--animation", "walk")
        raw = self.run / "raw/walk.png"; before = raw.read_bytes()
        manifest = self.run / "generated/manifest.json"; previous = manifest.read_bytes()
        status, _, _ = self.generate("--animation", "walk", "--force", error=RuntimeError("service unavailable"))
        self.assertEqual(status, 1)
        self.assertEqual(raw.read_bytes(), before)
        self.assertEqual(manifest.read_bytes(), previous)
        self.assertFalse((self.run / "generated/history").exists())

    def test_sheet_export_requires_artwork_review_even_with_valid_rig_and_pixels(self):
        self.prepare()
        for state in ("walk", "attack", "block"):
            image = Image.new("RGB", (384, 256), "#FF00FF")
            draw = ImageDraw.Draw(image)
            for index in range(6):
                x, y = index % 3 * 128, index // 3 * 128
                draw.rectangle((x + 44, y + 26, x + 81, y + 108), fill="#698798")
            image.resize((1536, 1024), Image.Resampling.NEAREST).save(self.run / "raw" / f"{state}.png")
        result = design.export(self.run, self.root / "audit")
        self.assertEqual(result["pixel_status"], "pass")
        self.assertEqual(result["pose_status"], "review")
        self.assertEqual(result["status"], "review")
        self.assertTrue((self.root / "audit/rig-overlay.png").exists())
        annotation = self.root / "stale.json"
        sheets.write_json(annotation, {"contract_sha256": "wrong"})
        with self.assertRaisesRegex(ValueError, "different pose contract"):
            design.export(self.run, self.root / "stale-audit", annotation)

    def test_selected_identity_and_guides_cannot_change(self):
        self.prepare()
        for relative in ("references/design-native.png", "references/palette.json", "guides/walk-skeleton.png", "contract.json"):
            path = self.run / relative; previous = path.read_bytes()
            path.write_bytes(previous + b" ")
            with self.assertRaisesRegex(ValueError, "changed"):
                design.load_run(self.run)
            path.write_bytes(previous)

    def test_landmarks_must_describe_exact_design_bytes(self):
        path = self.select(); data = json.loads(path.read_text()); data["design_sha256"] = "wrong"
        sheets.write_json(path, data)
        with self.assertRaisesRegex(ValueError, "exact selected"):
            design.prepare_poses(self.run, path)

    def test_invalid_design_dimensions_and_joints_rejected(self):
        for field, value in (("part_dimensions", {}), ("part_dimensions", {"head": [float("nan")]}), ("joints", {})):
            data = landmarks(); data[field] = value
            with self.assertRaises(ValueError): design.retarget(data)

    def test_korean_brief_round_trips_without_platform_default_encoding(self):
        brief_path = self.run / "design-brief.json"
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        brief["prompt"] = "푸른 갑옷과 흰 망토를 입은 기사"
        sheets.write_json(brief_path, brief)
        read_text = Path.read_text

        def legacy_windows_read(path, encoding=None, errors=None):
            return read_text(path, encoding=encoding or "cp1252", errors=errors)

        with patch.object(Path, "read_text", legacy_windows_read):
            self.prepare()
            design.load_run(self.run)
            prompts = json.loads((self.run / "prompts.json").read_text(encoding="utf-8"))
        self.assertIn(brief["prompt"], prompts["walk"]["prompt"])

    def test_annotation_metadata_and_frame_containers_are_validated_before_export(self):
        self.prepare()
        for state in ("walk", "attack", "block"):
            (self.run / "raw" / f"{state}.png").write_bytes(self.source.read_bytes())
        valid = {"contract_sha256": sheets.digest(self.run / "contract.json"), "method": "visual measurements",
                 "reviewer": "test reviewer", "animations": {},
                 "source_sha256": {state: sheets.digest(self.run / "raw" / f"{state}.png")
                                   for state in ("walk", "attack", "block")}}
        invalid = ([], {**valid, "reviewer": True}, {**valid, "method": []},
                   {**valid, "source_sha256": []}, {**valid, "animations": []},
                   {**valid, "animations": {"walk": {}}}, {**valid, "animations": {"walk": [None] * 7}})
        for index, document in enumerate(invalid):
            path = self.root / "annotations.json"; sheets.write_json(path, document)
            out = self.root / f"bad-audit-{index}"
            with self.subTest(document=document), self.assertRaises(ValueError):
                design.export(self.run, out, path)
            self.assertFalse(out.exists())


class IndependentArtworkTests(unittest.TestCase):
    def setUp(self):
        self.data = design.retarget(landmarks())
        self.frame = self.data["animations"]["walk"]["frames"][0]
        self.annotation = {"joints": {n: self.frame["joints_image"][n] for n in design.REVIEW_JOINTS},
                           "part_dimensions": copy.deepcopy(self.data["design"]["landmarks"]["part_dimensions"])}

    def test_valid_world_rig_cannot_accept_unobserved_artwork(self):
        self.assertEqual(rig.validate_contract(self.data)["status"], "pass")
        self.assertEqual(design.check_artwork(self.frame, self.data, None)["status"], "review")

    def test_creative_contours_are_not_compared_with_a_3d_mesh(self):
        # Decorative cloth can extend well beyond bone lines. No mesh mask or
        # silhouette metric is part of this recipe's acceptance contract.
        pixels = np.full((128, 128, 4), 255, dtype=np.uint8)
        result = design.check_artwork(self.frame, self.data, self.annotation, pixels)
        self.assertEqual(result["status"], "pass")
        self.assertNotIn("iou", result)

    def test_wrong_artwork_pose_and_part_size_fail_independently(self):
        bad = copy.deepcopy(self.annotation); bad["joints"]["mace_head"][0] += 9
        result = design.check_artwork(self.frame, self.data, bad)
        self.assertIn("ARTWORK_POSE_DRIFT", {i["code"] for i in result["issues"]})
        bad = copy.deepcopy(self.annotation); bad["part_dimensions"]["helmet"] = [18, 24]
        result = design.check_artwork(self.frame, self.data, bad)
        self.assertIn("ARTWORK_PART_SIZE_CHANGED", {i["code"] for i in result["issues"]})

    def test_guide_coordinates_on_empty_art_cannot_pass(self):
        result = design.check_artwork(self.frame, self.data, self.annotation, np.zeros((128, 128, 4), dtype=np.uint8))
        self.assertEqual(result["status"], "fail")
        self.assertIn("ARTWORK_JOINT_OUTSIDE_DRAWING", {i["code"] for i in result["issues"]})

    def test_missing_measurements_require_review(self):
        del self.annotation["part_dimensions"]["helmet"]
        self.assertEqual(design.check_artwork(self.frame, self.data, self.annotation)["status"], "review")

    def test_invalid_joint_values_are_input_errors(self):
        for value in (["1", 2], [True, 2], [float("nan"), 2], [float("inf"), 2], [1], {}):
            with self.subTest(value=value):
                bad = copy.deepcopy(self.annotation); bad["joints"]["neck"] = value
                with self.assertRaisesRegex(ValueError, "Artwork joint neck"):
                    design.check_artwork(self.frame, self.data, bad)

    def test_invalid_dimension_values_cannot_be_coerced_into_acceptance(self):
        for value in ([True, 15], ["11", "15"], [float("inf"), 15], [11], {"width": 11}):
            with self.subTest(value=value):
                bad = copy.deepcopy(self.annotation); bad["part_dimensions"]["helmet"] = value
                with self.assertRaisesRegex(ValueError, "Observed part dimension helmet"):
                    design.check_artwork(self.frame, self.data, bad)

    def test_malformed_annotation_containers_are_input_errors(self):
        for value in ([], {"joints": None}, {"part_dimensions": []}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "must be objects"):
                design.check_artwork(self.frame, self.data, value)


if __name__ == "__main__":
    unittest.main()
