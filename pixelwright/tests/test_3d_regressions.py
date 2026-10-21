# SPDX-License-Identifier: Apache-2.0
"""Nonfinite metric metadata and already registered anchor regressions."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import knight_rig_3d as rig
import knight_sheet_3d as sheets


class MetricMetadataRegressionTests(unittest.TestCase):
    def assert_invalid(self, data, code):
        report = rig.validate_contract(data)
        self.assertEqual(report["status"], "fail")
        self.assertIn(code, {issue["code"] for issue in report["issues"]})
        # Rejecting invalid input must not leak NaN/Infinity into the report.
        json.dumps(report, allow_nan=False)

    def test_reference_lengths_require_finite_positive_numbers(self):
        values = [float("nan"), float("inf"), -float("inf"), -1, 0,
                  True, "0.47", None, [], {}, 10 ** 1000]
        for value in values:
            with self.subTest(value=repr(value)):
                data = rig.contract(); data["bone_lengths_m"]["mace"] = value
                self.assert_invalid(data, "INVALID_BONE_LENGTH_REFERENCE")

    def test_tolerance_requires_finite_nonnegative_number(self):
        values = [float("nan"), float("inf"), -float("inf"), -1,
                  True, "0.000001", None, [], {}, 10 ** 1000]
        for value in values:
            with self.subTest(value=repr(value)):
                data = rig.contract(); data["acceptance"]["world_length_tolerance_m"] = value
                self.assert_invalid(data, "INVALID_WORLD_LENGTH_TOLERANCE")

    def test_missing_or_wrong_metadata_container_returns_failure(self):
        for field, code in (("bone_lengths_m", "INVALID_BONE_LENGTH_REFERENCE"),
                            ("acceptance", "INVALID_WORLD_LENGTH_TOLERANCE")):
            for value in (None, [], "invalid"):
                with self.subTest(field=field, value=value):
                    data = rig.contract(); data[field] = value
                    self.assert_invalid(data, code)

    def test_zero_tolerance_and_finite_references_are_valid(self):
        data = rig.contract()
        frame = copy.deepcopy(data["animations"]["block"]["frames"][0])
        data["animations"] = {"block": {"frames": [frame]}}
        data["acceptance"]["world_length_tolerance_m"] = 0
        self.assertEqual(rig.validate_contract(data)["status"], "pass")
        self.assertEqual(rig.validate_contract(rig.contract())["status"], "pass")

    @staticmethod
    def stretched_contract():
        data = rig.contract(); frame = data["animations"]["attack"]["frames"][3]
        frame["joints_world"]["mace_head"][0] += .35
        frame["joints_image"]["mace_head"] = rig.project(frame["joints_world"]["mace_head"])[0].tolist()
        return data

    def test_stretched_reprojected_weapon_is_not_hidden_by_nonfinite_metadata(self):
        data = self.stretched_contract()
        self.assert_invalid(data, "WORLD_BONE_LENGTH_CHANGED")
        for field, key, code in (("bone_lengths_m", "mace", "INVALID_BONE_LENGTH_REFERENCE"),
                                 ("acceptance", "world_length_tolerance_m", "INVALID_WORLD_LENGTH_TOLERANCE")):
            for value in (float("nan"), float("inf")):
                with self.subTest(field=field, value=value):
                    data = self.stretched_contract(); data[field][key] = value
                    self.assert_invalid(data, code)

    def test_json_numeric_overflow_cannot_disable_length_check(self):
        document = json.dumps(self.stretched_contract()).replace(
            '"world_length_tolerance_m": 1e-06', '"world_length_tolerance_m": 1e999')
        data = json.loads(document)
        self.assertTrue(np.isinf(data["acceptance"]["world_length_tolerance_m"]))
        self.assert_invalid(data, "INVALID_WORLD_LENGTH_TOLERANCE")


def anchor_fixture():
    ids = np.zeros((128, 128), dtype=np.uint8)
    ids[53:85, 50:75] = 1
    ids[35:51, 55:70] = 2
    ids[60:81, 35:40] = 3
    ids[85:113, 52:59] = 1
    ids[85:113, 68:75] = 1
    data = rig.contract()
    data["part_colors"] = {"torso": [130, 90, 210], "head": [235, 70, 100], "mace": [255, 150, 45]}
    return ids, data


class AnchorRegistrationRegressionTests(unittest.TestCase):
    def make_run(self, root, mask, ids, contract):
        root = root.resolve()
        rig_dir = root / "rig"; rig_dir.mkdir()
        run = root / "run"; run.mkdir()
        (run / "raw").mkdir(); (run / "references").mkdir()
        contract = copy.deepcopy(contract)
        part_map = "block-0.parts.png"
        contract["animations"]["block"]["frames"][0]["parts"] = part_map
        palette = np.asarray([(0, 0, 0)] + list(contract["part_colors"].values()), dtype=np.uint8)
        Image.fromarray(palette[ids]).save(rig_dir / part_map)
        pixels = np.zeros((128, 128, 4), dtype=np.uint8)
        pixels[mask] = (70, 110, 170, 255)
        Image.fromarray(pixels, "RGBA").resize((1024, 1024), Image.Resampling.NEAREST).save(run / "raw/anchor.png")
        sheets.write_json(rig_dir / "rig.json", contract)
        sheets.write_json(run / "contract.json", contract)
        sheets.write_json(run / "run.json", {
            "rig_dir": str(rig_dir), "rig_sha256": sheets.digest(rig_dir / "rig.json"),
            "contract_sha256": sheets.digest(run / "contract.json"),
            "pixel_palette_size": 31, "frame_scale": 4,
            "rig_image_sha256": {part_map: sheets.digest(rig_dir / part_map)}})
        return run

    def test_registered_anchor_keeps_positions_despite_one_cell_bbox_difference(self):
        ids, data = anchor_fixture()
        actual = ids > 0
        actual[33:57, 52:73] = False
        actual[36:53, 53:71] = True
        actual[51:57, 58:68] = True
        actual[:, 35] = False
        source_check = sheets.inspect_pose(actual, ids, data)
        self.assertEqual(source_check["status"], "pass")
        self.assertEqual(Image.fromarray(actual).getbbox(), (36, 36, 75, 113))
        self.assertEqual(Image.fromarray(ids > 0).getbbox(), (35, 35, 75, 113))
        with tempfile.TemporaryDirectory() as tmp:
            run = self.make_run(Path(tmp).resolve(), actual, ids, data)
            original = (run / "raw/anchor.png").read_bytes()
            frozen = (run / "contract.json").read_bytes()
            result = sheets.calibrate_anchor(run)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["uniform_base_scale"], 1)
            report = json.loads((run / "references/anchor-calibration.json").read_text())
            self.assertEqual(report["registration"], "already_registered")
            self.assertEqual(report["placed_origin"], [36, 36])
            output = np.asarray(Image.open(run / "references/anchor-native.png"))
            np.testing.assert_array_equal(output[:, :, 3] > 0, actual)
            self.assertTrue((output[output[:, :, 3] == 0] == 0).all())
            self.assertEqual((run / "raw/anchor.png").read_bytes(), original)
            self.assertEqual((run / "contract.json").read_bytes(), frozen)
            self.assertEqual(report["pose_check"]["metrics"]["head_roi_area_ratio"],
                             source_check["metrics"]["head_roi_area_ratio"])

    def test_unregistered_anchor_still_gets_uniform_calibration(self):
        ids, data = anchor_fixture()
        target = Image.fromarray((ids > 0).astype(np.uint8) * 255)
        enlarged = target.crop(target.getbbox()).resize((50, 98), Image.Resampling.NEAREST)
        source = Image.new("L", target.size); source.paste(enlarged, (30, 10))
        actual = np.asarray(source) > 0
        self.assertEqual(sheets.inspect_pose(actual, ids, data)["status"], "fail")
        with tempfile.TemporaryDirectory() as tmp:
            run = self.make_run(Path(tmp).resolve(), actual, ids, data)
            original = (run / "raw/anchor.png").read_bytes()
            result = sheets.calibrate_anchor(run)
            self.assertEqual(result["status"], "pass")
            self.assertLess(result["uniform_base_scale"], 1)
            report = json.loads((run / "references/anchor-calibration.json").read_text())
            self.assertEqual(report["registration"], "uniform_bbox_fit")
            self.assertEqual(report["source_pose_check"]["status"], "fail")
            self.assertEqual((run / "raw/anchor.png").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
