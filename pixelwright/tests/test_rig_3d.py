# SPDX-License-Identifier: Apache-2.0
"""3D geometry, fixed image registration and negative projection controls.

Blender is optional: these portable tests exercise exported contracts and image
processing. The actual Blender integration run is documented separately.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import knight_generate_frames as generation
import knight_rig_3d as rig
import knight_sheet_3d as sheets


class MetricRigTests(unittest.TestCase):
    def test_all_18_poses_keep_metric_lengths(self):
        data = rig.contract()
        self.assertEqual(sum(len(a["frames"]) for a in data["animations"].values()), 18)
        self.assertEqual(rig.validate_contract(data)["status"], "pass")
        for state in rig.DURATIONS:
            for index in range(6):
                joints = rig.pose(state, index)
                for side in ("r", "l"):
                    self.assertAlmostEqual(np.linalg.norm(joints[f"hand_{side}"] - joints[f"elbow_{side}"]), .30)
                    self.assertAlmostEqual(np.linalg.norm(joints[f"knee_{side}"] - joints[f"hip_{side}"]), .44)
                    self.assertAlmostEqual(np.linalg.norm(joints[f"ankle_{side}"] - joints[f"knee_{side}"]), .43)
                self.assertAlmostEqual(np.linalg.norm(joints["mace_head"] - joints["hand_r"]), .47)

    def test_ik_solves_nonplanar_target_without_stretching(self):
        start = np.array((1.1, -2.4, .8)); end = np.array((1.4, -1.8, 1.2))
        joint = rig.two_bone(start, end, .6, .5, (1.8, -2.3, .6))
        self.assertAlmostEqual(np.linalg.norm(joint - start), .6)
        self.assertAlmostEqual(np.linalg.norm(end - joint), .5)
        self.assertGreater(abs(np.cross(end - start, joint - start)[2]), .01)

    def test_ik_rejects_far_and_folded_targets(self):
        for target in ((0, 0, 2), (0, 0, .05), (0, 0, 0)):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "Unreachable"):
                rig.two_bone((0, 0, 0), target, .6, .5, (1, 0, 0))

    def test_orthographic_depth_does_not_change_pixel_scale(self):
        points = np.array(((-.2, 0, 1), (.2, 0, 1)))
        _, _, forward = rig.camera_basis()
        near, near_depth = rig.project(points)
        far, far_depth = rig.project(points + forward * 2)
        np.testing.assert_allclose(near, far, atol=1e-12)
        np.testing.assert_allclose(far_depth - near_depth, 2)

    def test_world_length_check_allows_real_foreshortening(self):
        data = rig.contract(); frames = data["animations"]["attack"]["frames"]
        lengths = [np.linalg.norm(np.subtract(f["joints_image"]["mace_head"], f["joints_image"]["hand_r"])) for f in frames]
        self.assertGreater(max(lengths) - min(lengths), 5)
        self.assertEqual(rig.validate_contract(data)["status"], "pass")

    def test_detects_world_bone_and_projection_tampering(self):
        for field, code in (("joints_world", "WORLD_BONE_LENGTH_CHANGED"), ("joints_image", "PROJECTION_MISMATCH")):
            data = rig.contract(); data["animations"]["attack"]["frames"][3][field]["hand_r"][0] += .1
            report = rig.validate_contract(data)
            self.assertEqual(report["status"], "fail")
            self.assertIn(code, {issue["code"] for issue in report["issues"]})

    def test_nonfinite_data_cannot_pass(self):
        data = rig.contract(); data["animations"]["walk"]["frames"][0]["joints_world"]["hand_r"][0] = float("nan")
        self.assertEqual(rig.validate_contract(data)["status"], "fail")
        data = rig.contract(); data["animations"]["walk"]["frames"][0]["joints_image"]["hand_r"][0] = float("nan")
        self.assertEqual(rig.validate_contract(data)["status"], "fail")


def fixture_ids(offset=0):
    ids = np.zeros((128, 128), dtype=np.uint8)
    ids[53:85, 50 + offset:75 + offset] = 1
    ids[35:51, 55 + offset:70 + offset] = 2
    ids[60:81, 35 + offset:40 + offset] = 3
    ids[85:113, 52 + offset:59 + offset] = 1
    ids[85:113, 68 + offset:75 + offset] = 1
    return ids


def projection_contract():
    data = rig.contract()
    data["part_colors"] = {"torso": [130, 90, 210], "head": [235, 70, 100], "mace": [255, 150, 45]}
    return data


class RegisteredProjectionTests(unittest.TestCase):
    def setUp(self):
        self.contract = projection_contract(); self.ids = fixture_ids()

    def test_exact_registered_silhouette_passes(self):
        report = sheets.inspect_pose(self.ids > 0, self.ids, self.contract)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["metrics"]["iou"], 1)

    def test_missing_weapon_fails_even_when_large_body_overlaps(self):
        report = sheets.inspect_pose((self.ids > 0) & (self.ids != 3), self.ids, self.contract)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any(issue.get("part") == "mace" for issue in report["issues"]))

    def test_moved_character_cannot_be_recentred_into_pass(self):
        report = sheets.inspect_pose(np.roll(self.ids > 0, 12, axis=1), self.ids, self.contract)
        self.assertEqual(report["status"], "fail")
        self.assertIn("HEAD_REGION_DRIFT", {issue["code"] for issue in report["issues"]})

    def test_reduced_head_fails(self):
        mask = self.ids > 0; mask[35:45, 55:70] = False
        report = sheets.inspect_pose(mask, self.ids, self.contract)
        self.assertIn("HEAD_REGION_SIZE_CHANGED", {issue["code"] for issue in report["issues"]})

    def test_already_aligned_cells_survive_projection(self):
        native = np.zeros((16, 16, 4), dtype=np.uint8)
        native[4:12, 5:10] = (40, 90, 150, 255)
        color, opaque = sheets.snap_cells(Image.fromarray(native).resize((128, 128), Image.Resampling.NEAREST), (16, 16))
        np.testing.assert_array_equal(opaque, native[:, :, 3] > 0)
        np.testing.assert_array_equal(color[opaque], native[:, :, :3][opaque])

    def test_noninteger_global_canvas_and_magenta_key(self):
        raw = np.full((1254, 1254, 4), (255, 0, 255, 255), dtype=np.uint8)
        raw[400:800, 400:800] = (40, 90, 150, 255)
        color, opaque = sheets.snap_cells(Image.fromarray(raw), (128, 128))
        self.assertEqual(opaque.shape, (128, 128))
        self.assertFalse(opaque[0, 0]); self.assertTrue(opaque[60, 60])
        np.testing.assert_array_equal(color[60, 60], (40, 90, 150))

    def test_wrong_canvas_aspect_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "aspect"):
            sheets.snap_cells(Image.new("RGBA", (512, 768)), (128, 128))

    def test_part_map_requires_exact_mesh_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.png"
            Image.new("RGB", (128, 128), (131, 90, 210)).save(path)
            with self.assertRaisesRegex(ValueError, "exact declared"):
                sheets.read_part_ids(path, self.contract["part_colors"], (128, 128))

    def test_shared_palette_cannot_expand_budget_or_add_partial_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "palette.json"
            for colors in (["#11223380"], ["#000000", "#FFFFFF", "#FF0000"], ["#112233", "#112233FF"]):
                sheets.write_json(path, {"colors": colors})
                with self.subTest(colors=colors), self.assertRaises(ValueError):
                    sheets.read_shared_palette(path, 2)

    def test_shared_palette_accepts_opaque_rgb_and_rgba(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "palette.json"; sheets.write_json(path, {"colors": ["#112233", "#445566FF"]})
            self.assertEqual(sheets.read_shared_palette(path, 2), [(17, 34, 51), (68, 85, 102)])


class SheetPipelineTests(unittest.TestCase):
    def test_unsupported_frame_counts_are_rejected(self):
        data = rig.contract(); data["animations"]["walk"]["frames"].pop()
        with self.assertRaisesRegex(ValueError, "six poses"):
            sheets.validate_layout(data)

    def test_bundled_real_sample_matches_recorded_bytes(self):
        root = ROOT / "docs/examples/knight-3d"
        review = json.loads((root / "art-review.json").read_text(encoding="utf-8"))
        for relative, expected in review["artifacts"].items():
            self.assertEqual(sheets.digest(root / relative), expected)
        native = np.asarray(Image.open(root / "sprite-sheet-native.png"))
        enlarged = np.asarray(Image.open(root / "sprite-sheet.png"))
        self.assertEqual(native.shape, (384, 768, 4))
        np.testing.assert_array_equal(enlarged, native.repeat(4, 0).repeat(4, 1))
        self.assertEqual(len(np.unique(native[native[:, :, 3] > 0], axis=0)), 19)
        self.assertTrue((native[native[:, :, 3] == 0] == 0).all())
        contract = json.loads((root / "rig.json").read_text(encoding="utf-8"))
        self.assertEqual(rig.validate_contract(contract)["status"], "pass")
        for state in rig.DURATIONS:
            with Image.open(root / f"{state}.gif") as im:
                self.assertEqual(im.n_frames, 6)
                for index, expected in enumerate(rig.DURATIONS[state]):
                    im.seek(index); self.assertEqual(im.info["duration"], expected)

    def make_run(self, root):
        rig_dir = root / "rig"; rig_dir.mkdir()
        run = root / "run"; run.mkdir(); (run / "raw").mkdir()
        contract = projection_contract()
        # Twelve independent fixture images; no Blender installation is required.
        contract["animations"].pop("attack")
        part_palette = np.array([(0, 0, 0)] + list(contract["part_colors"].values()), dtype=np.uint8)
        for state_index, (state, animation) in enumerate(contract["animations"].items()):
            raw = Image.new("RGB", (1536, 1024), "magenta")
            for index, frame in enumerate(animation["frames"]):
                ids = fixture_ids(index % 2)
                part_path = f"{state}-{index}.png"; Image.fromarray(part_palette[ids]).save(rig_dir / part_path)
                frame["parts"] = part_path
                pixels = np.full((128, 128, 3), (255, 0, 255), dtype=np.uint8)
                pixels[ids == 1] = (60 + state_index * 60, 100, 160)
                pixels[ids == 2] = (170, 190, 210)
                pixels[ids == 3] = (70, 40, 20)
                raw.paste(Image.fromarray(pixels).resize((512, 512), Image.Resampling.NEAREST),
                          (index % 3 * 512, index // 3 * 512))
            raw.save(run / "raw" / f"{state}.png")
        sheets.write_json(rig_dir / "rig.json", contract); sheets.write_json(run / "contract.json", contract)
        sheets.write_json(run / "run.json", {"rig_dir": str(rig_dir), "rig_sha256": sheets.digest(rig_dir / "rig.json"),
                                             "contract_sha256": sheets.digest(run / "contract.json"),
                                             "pixel_palette_size": 31, "frame_scale": 4})
        return run

    def test_complete_pipeline_keeps_slots_palette_and_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = self.make_run(root); out = root / "result"
            originals = {path.name: path.read_bytes() for path in (run / "raw").glob("*.png")}
            result = sheets.process(run, out)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["artistic_status"], "not_reviewed")
            native = np.asarray(Image.open(out / "sprite-sheet-native.png"))
            enlarged = np.asarray(Image.open(out / "sprite-sheet.png"))
            np.testing.assert_array_equal(enlarged, native.repeat(4, axis=0).repeat(4, axis=1))
            self.assertLessEqual(len(np.unique(native[native[:, :, 3] > 0], axis=0)), 31)
            self.assertTrue((native[native[:, :, 3] == 0] == 0).all())
            # The second state starts at its fixed row, never refitted into another slot.
            block = np.asarray(Image.open(out / "frames/block/frame_00.png"))
            np.testing.assert_array_equal(native[128:256, :128], block)
            self.assertEqual(Image.fromarray(block).getbbox(), (35, 35, 75, 113))
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["frame_layout"]["rows"]["block"][0], {"x": 0, "y": 512, "w": 512, "h": 512})
            for state in ("walk", "block"):
                with Image.open(out / f"{state}.gif") as gif:
                    self.assertEqual(gif.n_frames, 6)
                    durations = []
                    for i in range(gif.n_frames):
                        gif.seek(i); durations.append(gif.info["duration"])
                    self.assertEqual(durations, rig.DURATIONS[state])
            for name, original in originals.items():
                self.assertEqual((run / "raw" / name).read_bytes(), original)

    def test_mutated_contract_is_blocked_before_writing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = self.make_run(root)
            with (run / "contract.json").open("a") as stream: stream.write(" ")
            with self.assertRaisesRegex(ValueError, "frozen contract"):
                sheets.process(run, root / "output")
            self.assertFalse((root / "output").exists())

    def test_explicit_palette_is_shared_by_every_animation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = self.make_run(root); palette = root / "palette.json"
            sheets.write_json(palette, {"colors": ["#121212", "#808080", "#FFFFFF"]})
            result = sheets.process(run, root / "output", palette)
            self.assertEqual(result["status"], "pass")
            a = np.asarray(Image.open(root / "output/sprite-sheet-native.png"))
            self.assertLessEqual({tuple(c) for c in a[a[:, :, 3] > 0, :3]}, {(18, 18, 18), (128, 128, 128), (255, 255, 255)})

    def test_mutated_guide_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = self.make_run(root)
            guide = run / "guide.png"; Image.new("RGB", (1, 1)).save(guide)
            path = run / "run.json"; settings = json.loads(path.read_text())
            settings["guide_sha256"] = {"guide.png": sheets.digest(guide)}; sheets.write_json(path, settings)
            Image.new("RGB", (1, 1), "red").save(guide)
            with self.assertRaisesRegex(ValueError, "Frozen generation guide"):
                sheets.process(run, root / "output")

    def test_http_generation_supports_sheet_size_and_opaque_background(self):
        requests = []
        png = io.BytesIO(); Image.new("RGBA", (4, 4), "red").save(png, "PNG")

        def answer(request, timeout):
            requests.append(request)
            return contextlib.closing(io.BytesIO(json.dumps({"data": [{"b64_json": base64.b64encode(png.getvalue()).decode()}]}).encode()))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "ref.png").write_bytes(png.getvalue())
            sheets.write_json(root / "poses.json", {"canvas": [1024, 1024]})
            sheets.write_json(root / "prompts.json", {"walk": {"images": ["ref.png"], "prompt": "six poses",
                               "output": "raw/walk.png", "size": "1536x1024", "background": "opaque"}})
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), patch.object(generation.urllib.request, "urlopen", answer), \
                    patch.object(sys, "argv", ["knight_generate_frames.py", "--poses", str(root)]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(generation.main(), 0)
            manifest = json.loads((root / "generated/manifest.json").read_text())
            self.assertEqual(manifest["walk"]["size"], "1536x1024")
            self.assertEqual(manifest["walk"]["background"], "opaque")
        self.assertIn(b'name="size"\r\n\r\n1536x1024', requests[0].data)
        self.assertIn(b'name="background"\r\n\r\nopaque', requests[0].data)

    def test_prompt_only_design_uses_json_generation_without_input_fidelity(self):
        requests = []
        png = io.BytesIO(); Image.new("RGB", (4, 4), "red").save(png, "PNG")

        def answer(request, timeout):
            requests.append(request)
            payload = {"data": [{"b64_json": base64.b64encode(png.getvalue()).decode()}]}
            return contextlib.closing(io.BytesIO(json.dumps(payload).encode()))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheets.write_json(root / "poses.json", {"canvas": [1024, 1024]})
            sheets.write_json(root / "prompts.json", {"design": {"images": [], "prompt": "original 2D knight",
                              "output": "raw/design.png", "background": "opaque"}})
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
                    patch.object(generation.urllib.request, "urlopen", answer), \
                    patch.object(sys, "argv", ["knight_generate_frames.py", "--poses", str(root)]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(generation.main(), 0)
            manifest = json.loads((root / "generated/manifest.json").read_text())["design"]
            self.assertEqual(manifest["inputs"], {})
            self.assertIsNone(manifest["input_fidelity"])
            self.assertEqual(manifest["endpoint"], "/images/generations")
        self.assertEqual(requests[0].full_url, "https://api.openai.com/v1/images/generations")
        self.assertEqual(requests[0].get_header("Content-type"), "application/json")
        payload = json.loads(requests[0].data)
        self.assertEqual(payload["n"], 1)
        self.assertEqual(payload["size"], "1024x1024")
        self.assertEqual(payload["prompt"], "original 2D knight")
        self.assertNotIn("input_fidelity", payload)
        self.assertNotIn("image", payload)


if __name__ == "__main__":
    unittest.main()
