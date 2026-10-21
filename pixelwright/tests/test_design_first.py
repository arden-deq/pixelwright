# SPDX-License-Identifier: Apache-2.0
"""Regression controls for identity-before-rig and independent artwork evidence."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import knight_design_first as design
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
        design.load_run(self.run)

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


if __name__ == "__main__":
    unittest.main()
