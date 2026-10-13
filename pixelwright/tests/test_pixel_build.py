"""Run: python -m unittest discover -s tests -v (from the skill folder)."""
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pixel_build as pb


class PixelBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.document = {
            "schema_version": 1,
            "palette": {".": "transparent", "R": "#DE344A", "B": "#204878FF"},
            "rows": [[".", "R", "B"], ["B", "R", "."]],
            "scale": 4,
        }
        self.spec = self.root / "artwork.json"

    def write_spec(self, document=None):
        self.spec.write_text(json.dumps(self.document if document is None else document), encoding="utf-8")
        return self.spec

    def build(self, name="output"):
        return pb.build_from_spec(self.write_spec(), self.root / name)

    def test_every_rendered_block_is_exactly_one_complete_native_square(self):
        self.build()
        with Image.open(self.root / "output" / "native.png") as image:
            native = np.asarray(image.convert("RGBA"))
        with Image.open(self.root / "output" / "rendered.png") as image:
            rendered = np.asarray(image.convert("RGBA"))
        self.assertEqual(native.shape, (2, 3, 4))
        self.assertEqual(rendered.shape, (8, 12, 4))
        np.testing.assert_array_equal(rendered, np.repeat(np.repeat(native, 4, axis=0), 4, axis=1))
        self.assertEqual(set(map(tuple, native.reshape(-1, 4))), {(0, 0, 0, 0), (222, 52, 74, 255), (32, 72, 120, 255)})

    def test_manifest_records_source_and_png_and_decoded_pixel_hashes(self):
        source = self.write_spec()
        before = source.read_bytes()
        manifest = pb.build_from_spec(source, self.root / "output")
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(manifest["input"]["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(manifest["input"]["path"], str(source.resolve()))
        saved = json.loads((self.root / "output" / "build.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, manifest)
        for name in ("native.png", "rendered.png"):
            path = self.root / "output" / name
            self.assertEqual(manifest["outputs"][name]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            with Image.open(path) as image:
                self.assertEqual(manifest["outputs"][name]["pixel_rgba_sha256"], hashlib.sha256(image.tobytes()).hexdigest())
        self.assertFalse(manifest["construction"]["artistic_quality_assessed"])

    def test_transparent_rgb_is_normalized_and_partial_alpha_is_preserved(self):
        self.document["palette"] = {".": "#FECA0100", "R": "#DE344A80", "B": "#204878"}
        manifest = self.build()
        self.assertEqual(manifest["palette"]["."], "#00000000")
        self.assertEqual(manifest["palette"]["R"], "#DE344A80")
        with Image.open(self.root / "output" / "native.png") as image:
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 0))
            self.assertEqual(image.getpixel((1, 0)), (222, 52, 74, 128))

    def test_character_string_rows_and_array_tokens(self):
        self.document["rows"] = [".RB", "BR."]
        self.assertEqual(pb.parse_spec(self.document).rows[0], (".", "R", "B"))
        self.document["palette"] = {"background": "transparent", "red": "#FF0000"}
        self.document["rows"] = [["background", "red"]]
        self.assertEqual(pb.parse_spec(self.document).width, 2)

    def test_ambiguous_string_rows_are_rejected(self):
        self.document["palette"]["RR"] = "#112233"
        self.document["rows"] = ["RR"]
        with self.assertRaisesRegex(pb.SpecError, "ambiguous"):
            pb.parse_spec(self.document)

    def test_invalid_palette_values_are_rejected(self):
        for value in ("#123", "#1234567", "#123456789", "#XY1234", [1, 2, 3], None, True):
            with self.subTest(value=value):
                self.document["palette"]["R"] = value
                with self.assertRaisesRegex(pb.SpecError, "Palette token"):
                    pb.parse_spec(self.document)

    def test_ragged_unknown_empty_and_non_token_rows_are_rejected(self):
        cases = (
            ([["R", "B"], ["R"]], "ragged"),
            ([["unknown"]], "Unknown palette token"),
            ([], "nonempty"),
            ([[]], "nonempty"),
            ([[None]], "Unknown palette token"),
        )
        for rows, message in cases:
            with self.subTest(rows=rows):
                self.document["rows"] = rows
                with self.assertRaisesRegex(pb.SpecError, message):
                    pb.parse_spec(self.document)

    def test_invalid_scales_do_not_create_output(self):
        for scale in (0, 1, -4, 2.0, "4", True):
            with self.subTest(scale=scale):
                self.document["scale"] = scale
                self.write_spec()
                with self.assertRaisesRegex(pb.SpecError, "integer >= 2"):
                    pb.build_from_spec(self.spec, self.root / "output")
                self.assertFalse((self.root / "output").exists())

    def test_schema_version_missing_and_unknown_fields_are_rejected(self):
        self.document["schema_version"] = True
        with self.assertRaisesRegex(pb.SpecError, "integer 1"):
            pb.parse_spec(self.document)
        self.document["schema_version"] = 1
        self.document["scales"] = 8
        with self.assertRaisesRegex(pb.SpecError, "Unknown specification fields"):
            pb.parse_spec(self.document)
        del self.document["scale"]
        with self.assertRaisesRegex(pb.SpecError, "Missing required fields"):
            pb.parse_spec(self.document)

    def test_duplicate_palette_key_is_rejected_before_build(self):
        self.spec.write_text('{"schema_version":1,"scale":2,"palette":{"R":"#FF0000","R":"#000000"},"rows":["R"]}', encoding="utf-8")
        with self.assertRaisesRegex(pb.SpecError, "Duplicate JSON object key"):
            pb.build_from_spec(self.spec, self.root / "output")
        self.assertFalse((self.root / "output").exists())

    def test_nonempty_output_directory_is_never_overwritten(self):
        self.build()
        output = self.root / "output"
        before = {path.name: path.read_bytes() for path in output.iterdir()}
        self.document["palette"]["R"] = "#ABCDEF"
        self.write_spec()
        with self.assertRaisesRegex(pb.SpecError, "not empty"):
            pb.build_from_spec(self.spec, output)
        self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, before)

    def test_empty_output_directory_is_supported_without_lock_residue(self):
        output = self.root / "output"
        output.mkdir()
        self.build()
        self.assertEqual({path.name for path in output.iterdir()}, {"native.png", "rendered.png", "build.json"})

    def test_output_containing_input_is_rejected(self):
        self.write_spec()
        before = self.spec.read_bytes()
        with self.assertRaisesRegex(pb.SpecError, "contain or replace"):
            pb.build_from_spec(self.spec, self.root)
        self.assertEqual(self.spec.read_bytes(), before)

    def test_input_path_cannot_be_used_as_output(self):
        self.write_spec()
        before = self.spec.read_bytes()
        with self.assertRaisesRegex(pb.SpecError, "contain or replace"):
            pb.build_from_spec(self.spec, self.spec)
        self.assertEqual(self.spec.read_bytes(), before)

    def test_size_limit_is_checked_before_creating_artifacts(self):
        self.document["scale"] = 100_000
        self.write_spec()
        with self.assertRaisesRegex(pb.SpecError, "limit"):
            pb.build_from_spec(self.spec, self.root / "output")
        self.assertFalse((self.root / "output").exists())

    def test_repeat_build_produces_same_png_bytes_and_manifest(self):
        first = self.build("first")
        second = pb.build_from_spec(self.spec, self.root / "second")
        self.assertEqual(first, second)
        for name in ("native.png", "rendered.png", "build.json"):
            self.assertEqual((self.root / "first" / name).read_bytes(), (self.root / "second" / name).read_bytes())

    def test_logical_dimensions_match_auditor_limits(self):
        document = {"schema_version": 1, "palette": {"a": "#112233"},
                    "rows": ["a" * 4097], "scale": 2}
        with self.assertRaisesRegex(pb.SpecError, "4096"):
            pb.parse_spec(document)

    def test_cli_errors_are_short_and_have_nonzero_exit_status(self):
        self.document["scale"] = 1
        self.write_spec()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = pb.main(["--spec", str(self.spec), "--out-dir", str(self.root / "output")])
        self.assertEqual(code, 2)
        self.assertIn("scale must be", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
