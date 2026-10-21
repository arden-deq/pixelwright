# SPDX-License-Identifier: Apache-2.0
"""Saved GIF timing must be explicit without changing game animation timing."""
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
import pixel_sprite as sprite


class SpriteTimingRegressions(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.runs = 0

    def write_case(self, durations, *, loop=True, sequence=None, scalar=False):
        count = max(sequence) + 1 if sequence is not None else len(durations)
        sequence = list(range(count)) if sequence is None else sequence
        native = np.zeros((8, 8 * count, 4), dtype=np.uint8)
        frames, self.art_frames = [], []
        for index in range(count):
            cells = np.zeros((8, 8, 4), dtype=np.uint8)
            cells[2:4, 2 + index:4 + index] = (160, 32, 48, 255)
            native[:, index * 8:(index + 1) * 8] = cells
            self.art_frames.append(cells)
            frame_map = ["".join("x" if opacity else "." for opacity in row)
                         for row in cells[:, :, 3]]
            frames.append({"parts": frame_map, "joints": {"pivot": [2 + index, 2]}})
        animation = {"frames": sequence, "loop": loop}
        animation.update({"frame_ms": durations[0]} if scalar else {"durations_ms": durations})
        document = {"schema_version": 1, "frame_size": "8x8", "layout": {"columns": count, "rows": 1},
                    "animations": {"move": animation}, "frames": frames,
                    "rig": {"joints": {"pivot": {}},
                            "parts": {"box": {"token": "x", "motion": "rigid", "pivot": "pivot"}}}}
        profile = {"schema_version": 1, "logical_size": f"{8 * count}x8", "scale": 2,
                   "alpha": "binary", "max_colors": 1, "transparent_rgb": "exact",
                   "allowed_palette": ["#00000000", "#A02030FF"]}
        self.spec = self.root / "spec.json"
        self.profile = self.root / "profile.json"
        self.sheet = self.root / "sheet.png"
        self.spec.write_bytes((json.dumps(document) + "\n").encode())
        self.profile.write_bytes((json.dumps(profile) + "\n").encode())
        Image.fromarray(native.repeat(2, axis=0).repeat(2, axis=1)).save(self.sheet)
        self.input_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in (self.spec, self.profile, self.sheet)}

    def check(self):
        self.runs += 1
        output = self.root / f"run-{self.runs}"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = sprite.run_cli(["check", "--spec", str(self.spec), "--sheet", str(self.sheet),
                                   "--profile", str(self.profile), "--out-dir", str(output),
                                   "--preview-scale", "1"])
        summary = json.loads((output / "sprite_report.json").read_bytes())
        for path, before in self.input_hashes.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        return code, summary, output

    def assert_saved_timing(self, summary, output, requested, encoded, loop):
        animation = summary["animations"][0]
        self.assertEqual(animation["durations_ms"], requested)
        self.assertEqual(animation["total_ms"], sum(requested))
        self.assertEqual(animation["loop"], loop)
        for kind, paths_key in (("art", "animation_previews"), ("rig", "rig_previews")):
            timing = animation["preview_timing"][kind]
            path = output / summary["outputs"][paths_key]["move"]
            with Image.open(path) as gif:
                actual_loop = gif.info.get("loop") == 0
                durations = []
                for index in range(gif.n_frames):
                    gif.seek(index)
                    durations.append(gif.info.get("duration", 0))
                self.assertEqual(timing["actual_frame_count"], gif.n_frames)
            self.assertEqual(actual_loop, loop)
            self.assertEqual(durations, encoded)
            self.assertTrue(all(value >= 10 for value in durations))
            self.assertEqual(timing["requested_durations_ms"], requested)
            self.assertEqual(timing["requested_total_ms"], sum(requested))
            self.assertEqual(timing["actual_durations_ms"], encoded)
            self.assertEqual(timing["actual_total_ms"], sum(encoded))
            self.assertEqual(timing["actual_loop"], loop)
            self.assertTrue(timing["metadata_verified"])

    def test_scalar_unrepresentable_durations_are_reviewed_with_nonzero_saved_delays(self):
        for requested, expected in ((1, 10), (9, 10), (15, 20), (16, 20), (111, 110)):
            with self.subTest(requested=requested):
                self.write_case([requested, requested], scalar=True)
                code, summary, output = self.check()
                self.assertEqual((code, summary["status"]), (2, "review"))
                self.assertIn("GIF_TIMING_QUANTIZED", {issue["code"] for issue in summary["issues"]})
                self.assert_saved_timing(summary, output, [requested] * 2, [expected] * 2, True)

    def test_per_entry_game_timing_stays_exact_while_one_shot_gifs_report_rounding(self):
        self.write_case([9, 16, 111], loop=False)
        code, summary, output = self.check()
        self.assertEqual((code, summary["status"]), (2, "review"))
        self.assert_saved_timing(summary, output, [9, 16, 111], [10, 20, 110], False)

    def test_representable_timing_keeps_pass_loop_policy_and_existing_art_gif_bytes(self):
        for loop in (True, False):
            with self.subTest(loop=loop):
                self.write_case([100, 110], loop=loop)
                code, summary, output = self.check()
                self.assertEqual((code, summary["status"]), (0, "pass"))
                self.assertNotIn("GIF_TIMING_QUANTIZED", {issue["code"] for issue in summary["issues"]})
                self.assert_saved_timing(summary, output, [100, 110], [100, 110], loop)
                images = []
                for frame in self.art_frames:
                    rgba = Image.fromarray(frame)
                    images.append(Image.alpha_composite(Image.new("RGBA", rgba.size, (48, 52, 62, 255)), rgba).convert("RGB"))
                before = io.BytesIO()
                options = {"save_all": True, "append_images": images[1:], "duration": [100, 110], "disposal": 2}
                if loop:
                    options["loop"] = 0
                images[0].save(before, format="GIF", **options)
                self.assertEqual((output / "animations/move.gif").read_bytes(), before.getvalue())

    def test_coalesced_holds_report_actual_frame_count_delays_and_sequence_positions(self):
        self.write_case([100, 110, 100], sequence=[0, 0, 1])
        code, summary, output = self.check()
        self.assertEqual((code, summary["status"]), (0, "pass"))
        self.assert_saved_timing(summary, output, [100, 110, 100], [210, 100], True)
        for timing in summary["animations"][0]["preview_timing"].values():
            self.assertEqual(timing["requested_frame_count"], 3)
            self.assertEqual(timing["actual_frame_count"], 2)
            self.assertEqual(timing["source_frame_positions"], [[0, 1], [2]])
            self.assertTrue(timing["coalesced_frames"])

    def test_single_saved_hold_preserves_the_declared_loop_policy(self):
        for loop in (True, False):
            with self.subTest(loop=loop):
                self.write_case([100, 110], sequence=[0, 0], loop=loop)
                code, summary, output = self.check()
                self.assertEqual((code, summary["status"]), (0, "pass"))
                self.assert_saved_timing(summary, output, [100, 110], [210], loop)
                for timing in summary["animations"][0]["preview_timing"].values():
                    self.assertEqual(timing["source_frame_positions"], [[0, 1]])

    def test_actual_saved_loop_extension_is_checked(self):
        self.write_case([100, 110], loop=True)
        original_write = sprite._write_new

        def corrupt_saved_loop(path, payload):
            if path.name == "move.gif":
                self.assertIn(b"NETSCAPE2.0", payload)
                payload = payload.replace(b"NETSCAPE2.0", b"UNKNOWNS2.0")
            return original_write(path, payload)

        with mock.patch.object(sprite, "_write_new", side_effect=corrupt_saved_loop):
            code, summary, output = self.check()
        self.assertEqual((code, summary["status"]), (2, "fail"))
        timing = summary["animations"][0]["preview_timing"]["art"]
        self.assertTrue(timing["requested_loop"])
        self.assertFalse(timing["actual_loop"])
        self.assertFalse(timing["metadata_verified"])
        self.assertIn("GIF_PREVIEW_METADATA_MISMATCH", {issue["code"] for issue in summary["issues"]})
        with Image.open(output / "animations/move.gif") as gif:
            self.assertNotIn("loop", gif.info)

    def test_actual_saved_zero_delay_is_rejected_by_metadata_readback(self):
        self.write_case([100, 110])
        original_write = sprite._write_new

        def corrupt_saved_delay(path, payload):
            if path.name == "move.gif":
                payload = bytearray(payload)
                control = payload.index(b"\x21\xF9\x04")
                payload[control + 4:control + 6] = b"\x00\x00"
                payload = bytes(payload)
            return original_write(path, payload)

        with mock.patch.object(sprite, "_write_new", side_effect=corrupt_saved_delay):
            code, summary, output = self.check()
        self.assertEqual((code, summary["status"]), (2, "fail"))
        self.assertIn("GIF_PREVIEW_METADATA_MISMATCH", {issue["code"] for issue in summary["issues"]})
        self.assertFalse(summary["animations"][0]["preview_timing"]["art"]["metadata_verified"])
        with Image.open(output / "animations/move.gif") as gif:
            self.assertEqual(gif.info.get("duration", 0), 0)


if __name__ == "__main__":
    unittest.main()
