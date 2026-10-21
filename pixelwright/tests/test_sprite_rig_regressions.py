"""Independent attachment, occlusion and export-ownership regressions."""
import hashlib
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


COLORS = {"p": (200, 30, 30, 255), "c": (30, 50, 210, 255), "o": (240, 200, 40, 255)}


class SpriteRigRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.case_index = 0

    def check(self, frames, rig, poses, *, hidden=None, size=(16, 12)):
        self.case_index += 1
        base = self.root / f"case-{self.case_index}"
        base.mkdir()
        width, height = size
        sheet = np.zeros((height, 2 * width + 1, 4), dtype=np.uint8)
        entries = []
        for index, cells in enumerate(frames):
            labels = [["."] * width for _ in range(height)]
            for (x, y), token in cells.items():
                sheet[y, index * (width + 1) + x] = COLORS[token]
                labels[y][x] = token
            entries.append({"parts": ["".join(row) for row in labels], "joints": poses[index],
                            "hidden": (hidden or {}).get(index, [])})
        spec = {"schema_version": 1, "frame_size": f"{width}x{height}",
                "layout": {"columns": 2, "rows": 1, "spacing": 1},
                "rig": rig, "frames": entries}
        profile = {"schema_version": 1, "logical_size": f"{2 * width + 1}x{height}", "scale": 2,
                   "alpha": "binary", "max_colors": 3, "transparent_rgb": "exact",
                   "allowed_palette": ["#00000000"] + ["#" + bytes(c).hex() for c in COLORS.values()]}
        for filename, document in (("spec.json", spec), ("profile.json", profile)):
            (base / filename).write_text(json.dumps(document), encoding="utf-8")
        Image.fromarray(np.repeat(np.repeat(sheet, 2, axis=0), 2, axis=1)).save(base / "sheet.png")
        return sprite.check_sheet(base / "spec.json", base / "sheet.png", base / "profile.json",
                                  base / "check", scale=1)

    def translated_parent_case(self, *, hidden_parent, child_position, parent_position=(2, 2), motion="fixed"):
        rig = {"joints": {"child_pivot": {}, "cover_pivot": {}},
               "parts": {"parent": {"token": "p", "motion": motion},
                         "child": {"token": "c", "motion": "rigid", "pivot": "child_pivot", "parent": "parent"},
                         "occluder": {"token": "o", "motion": "rigid", "pivot": "cover_pivot"}}}
        if motion == "rigid":
            rig["joints"]["parent_pivot"] = {}
            rig["parts"]["parent"]["pivot"] = "parent_pivot"
        first = {(2, 2): "p", (3, 2): "c", (8, 2): "o"}
        cover_position = parent_position if hidden_parent else (1, 8)
        second = {child_position: "c", cover_position: "o"}
        if not hidden_parent:
            second[parent_position] = "p"
        poses = [{"child_pivot": [3, 2], "cover_pivot": [8, 2]},
                 {"child_pivot": list(child_position), "cover_pivot": list(cover_position)}]
        if motion == "rigid":
            poses[0]["parent_pivot"] = [2, 2]
            poses[1]["parent_pivot"] = list(parent_position)
        return self.check([first, second], rig, poses, hidden={1: ["parent"]} if hidden_parent else None)

    def test_hidden_fixed_parent_cannot_disable_child_attachment(self):
        for hidden in (False, True):
            with self.subTest(hidden_parent=hidden):
                result = self.translated_parent_case(hidden_parent=hidden, child_position=(8, 8))
                self.assertEqual(result["status"], "fail")
                self.assertIn(("PART_DETACHED", 1, "child"),
                              {(i["code"], i.get("frame"), i.get("part")) for i in result["issues"]})

    def test_hidden_fixed_and_translated_parents_allow_child_at_their_occluder(self):
        for motion, parent, child in (("fixed", (2, 2), (3, 2)), ("rigid", (5, 2), (6, 2))):
            with self.subTest(motion=motion):
                result = self.translated_parent_case(hidden_parent=True, child_position=child,
                                                     parent_position=parent, motion=motion)
                self.assertEqual(result["status"], "pass", result["issues"])

    def test_hidden_rotated_bone_parent_uses_its_current_footprint(self):
        first = {(x, 2): "p" for x in range(2, 5)}
        first[(5, 2)] = "c"
        first.update({(x, 7): "o" for x in range(7, 10)})
        rig = {"joints": {"a": {}, "b": {}, "child_pivot": {}},
               "parts": {"parent": {"token": "p", "motion": "bone", "bone": ["a", "b"]},
                         "child": {"token": "c", "motion": "rigid", "pivot": "child_pivot", "parent": "parent"},
                         "occluder": {"token": "o", "motion": "free"}}}
        for child, expected in (((2, 5), "pass"), ((8, 8), "fail")):
            with self.subTest(child=child):
                second = {(2, y): "o" for y in range(2, 5)}
                second[child] = "c"
                poses = [{"a": [2, 2], "b": [4, 2], "child_pivot": [5, 2]},
                         {"a": [2, 2], "b": [2, 4], "child_pivot": list(child)}]
                result = self.check([first, second], rig, poses, hidden={1: ["parent"]})
                self.assertEqual(result["status"], expected, result["issues"])

    def occluded_arm(self, *, valid):
        last = 8 if valid else 12
        missing = set(range(3, 6)) if valid else set(range(5, 8))
        first = {(x, 2): "p" for x in range(1, last + 1)}
        cover_x = range(3, 6) if valid else range(4, 9)
        first.update({(x, 5): "o" for x in cover_x})
        second = {(x, 2): "p" for x in range(1, last + 1) if x not in missing}
        second.update({(x, 2 if valid else 1): "o" for x in cover_x})
        rig = {"joints": {"a": {}, "b": {}},
               "parts": {"arm": {"token": "p", "motion": "bone", "bone": ["a", "b"]},
                         "occluder": {"token": "o", "motion": "free"}}}
        return self.check([first, second], rig, [{"a": [1, 2], "b": [last, 2]}] * 2)

    def test_expected_three_cell_occlusion_does_not_fragment_a_bone(self):
        result = self.occluded_arm(valid=True)
        current = result["rig"]["parts"]["arm"]["frames"][1]
        self.assertEqual(current["shape_match"], 1)
        self.assertEqual(current["area_ratio"], 1)
        self.assertEqual(result["status"], "pass", result["issues"])

    def test_unrelated_cover_detour_cannot_hide_real_fragmentation(self):
        # The foreground is one row ABOVE the missing arm dots. A flood through
        # all foreground cells would join the pieces despite no actual coverage.
        result = self.occluded_arm(valid=False)
        current = result["rig"]["parts"]["arm"]["frames"][1]
        self.assertEqual(current["shape_match"], 1)
        self.assertGreaterEqual(current["area_ratio"], 0.75)
        self.assertNotEqual(result["status"], "pass")
        self.assertIn("PART_FRAGMENTED", {i["code"] for i in result["issues"]})

    def test_reference_occlusion_does_not_weaken_later_fragmentation(self):
        arm = {(x, 2): "p" for x in range(1, 13) if x not in (6, 7)}
        first = arm | {(6, 2): "o", (7, 2): "o"}
        second = arm | {(6, 5): "o", (7, 5): "o"}
        rig = {"joints": {"a": {}, "b": {}},
               "parts": {"arm": {"token": "p", "motion": "bone", "bone": ["a", "b"]},
                         "occluder": {"token": "o", "motion": "free"}}}
        result = self.check([first, second], rig, [{"a": [1, 2], "b": [12, 2]}] * 2)
        self.assertEqual(result["status"], "review")
        self.assertIn(("PART_FRAGMENTED", 1), {(i["code"], i.get("frame")) for i in result["issues"]})

    def build_spec(self):
        path = self.root / "build-spec.json"
        path.write_text(json.dumps({"schema_version": 1, "frame_size": "2x2", "scale": 2,
                                    "layout": {"columns": 2, "rows": 1, "spacing": 1},
                                    "palette": {"r": "#CC2222", "b": "#2222CC"},
                                    "frames": [{"rows": ["rr", "rr"]}, {"rows": ["bb", "bb"]}]}), encoding="utf-8")
        return path

    def test_exclusive_build_collision_preserves_the_competing_file(self):
        source, output = self.build_spec(), self.root / "racing-build"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        external = b"another writer owns this export"
        original_write = sprite._write_new

        def inject_race(path, payload):
            if path == output / "rendered.png":
                path.write_bytes(external)
            return original_write(path, payload)

        with mock.patch.object(sprite, "_write_new", side_effect=inject_race), self.assertRaises(FileExistsError):
            sprite.build_sheet(source, output)
        self.assertTrue((output / "rendered.png").exists(), "Rollback must preserve the competing writer's file")
        self.assertEqual((output / "rendered.png").read_bytes(), external)
        self.assertFalse((output / "native.png").exists())
        self.assertFalse((output / "build.json").exists())
        self.assertFalse((output / ".pixelwright-sprite.lock").exists())
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_partial_own_export_failure_cleans_all_owned_files(self):
        source, output = self.build_spec(), self.root / "partial-build"
        original_open = Path.open

        class PartialWriter:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self.stream.__exit__(*exc)

            def write(self, payload):
                self.stream.write(payload[:max(1, len(payload) // 2)])
                raise OSError("simulated partial export write")

        def partial_open(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            return PartialWriter(stream) if path == output / "rendered.png" and args == ("xb",) else stream

        with mock.patch.object(Path, "open", new=partial_open), self.assertRaisesRegex(OSError, "simulated partial"):
            sprite.build_sheet(source, output)
        self.assertEqual(list(output.iterdir()), [])
        self.assertTrue(source.is_file())


if __name__ == "__main__":
    unittest.main()
