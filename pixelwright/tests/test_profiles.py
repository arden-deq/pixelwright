import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pixelwright as pw


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.profile = self.root / "profile.json"
        self.contract = {"schema_version": 1, "logical_size": "2x2", "scale": 3,
                         "max_colors": 2, "alpha": "binary", "transparent_rgb": "exact"}
        self.profile.write_text(json.dumps(self.contract), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def image(self, name="input.png", color=(20, 30, 40, 255)):
        path = self.root / name
        Image.new("RGBA", (6, 6), color).save(path)
        return path

    def run_gate(self, args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return pw.run_cli(args)

    def test_strict_profile_pass_and_hashes(self):
        src = self.image()
        out = self.root / "audit"
        self.assertEqual(self.run_gate(["inspect", str(src), "--profile", str(self.profile), "--out-dir", str(out)]), 0)
        report = json.loads((out / "report.json").read_text())
        self.assertEqual(report["provenance"]["source_sha256"], pw.sha256(src))
        self.assertEqual(report["contract"], self.contract)
        self.assertEqual(report["artistic_status"], "not_reviewed")

    def test_single_sample_palette_violation_detected(self):
        src = self.image()
        arr = np.array(Image.open(src))
        arr[1, 1] = (21, 30, 40, 255)
        Image.fromarray(arr).save(src)
        self.contract["allowed_palette"] = ["#141E28"]
        self.profile.write_text(json.dumps(self.contract))
        out = self.root / "audit"
        self.assertEqual(self.run_gate(["inspect", str(src), "--profile", str(self.profile), "--out-dir", str(out)]), 2)
        report = json.loads((out / "report.json").read_text())
        self.assertEqual(report["metrics"]["outside_palette_source_pixels"], 1)
        self.assertIn("NON_SOLID_GRID_CELLS", {i["code"] for i in report["issues"]})

    def test_intentional_translucency_is_allowed_by_any_policy(self):
        src = self.image(color=(20, 30, 40, 128))
        self.contract["alpha"] = "any"
        self.profile.write_text(json.dumps(self.contract))
        self.assertEqual(self.run_gate(["inspect", str(src), "--profile", str(self.profile), "--out-dir", str(self.root / "audit")]), 0)

    def test_opaque_policy_rejects_transparent_samples(self):
        src = self.image(color=(0, 0, 0, 0))
        self.contract["alpha"] = "opaque"
        self.profile.write_text(json.dumps(self.contract))
        self.assertEqual(self.run_gate(["inspect", str(src), "--profile", str(self.profile), "--out-dir", str(self.root / "audit")]), 2)

    def test_scale_consistency_and_native_cannot_claim_profile_pass(self):
        src = self.image()
        Image.new("RGBA", (2, 2), (20, 30, 40, 255)).save(src)
        self.assertEqual(self.run_gate(["inspect", str(src), "--profile", str(self.profile), "--out-dir", str(self.root / "audit")]), 2)

    def test_batch_continues_after_corrupt_input_and_preserves_duplicate_names(self):
        src = self.image()
        bad = self.root / "bad.png"
        bad.write_bytes(b"not a png")
        out = self.root / "batch"
        self.assertEqual(self.run_gate(["batch", str(src), str(bad), str(src), "--profile", str(self.profile), "--out-dir", str(out)]), 1)
        summary = json.loads((out / "batch.json").read_text())
        self.assertEqual([r["status"] for r in summary["results"]], ["pass", "error", "pass"])
        self.assertTrue((out / "0000" / "report.json").exists())
        self.assertTrue((out / "0002" / "report.json").exists())

    def test_output_cannot_contain_or_overwrite_inputs(self):
        src = self.image()
        before = src.read_bytes()
        self.assertEqual(self.run_gate(["inspect", str(src), "--profile", str(self.profile), "--out-dir", str(self.root)]), 1)
        self.assertEqual(before, src.read_bytes())
        out = self.root / "audit"
        out.mkdir()
        marker = out / "keep.txt"
        marker.write_text("keep")
        self.assertEqual(self.run_gate(["inspect", str(src), "--profile", str(self.profile), "--out-dir", str(out)]), 1)
        self.assertEqual(marker.read_text(), "keep")

    def test_misspelled_or_weak_contract_rejected(self):
        for change in ({"scale": 1}, {"scale": True}, {"alpha": "guess"}, {"max_colors": 0},
                       {"schema_version": True}, {"allowd_palette": ["#000000"]},
                       {"allowed_palette": ["#GG0000"]}, {"allowed_palette": ["# 0 0 0"]}):
            with self.subTest(change=change):
                self.profile.write_text(json.dumps(self.contract | change))
                with self.assertRaises(ValueError):
                    pw.load_profile(self.profile)

    def test_duplicate_constraints_cannot_silently_override_contract(self):
        self.profile.write_text('{"schema_version":1,"logical_size":"2x2","scale":3,"scale":4}')
        with self.assertRaises(ValueError):
            pw.load_profile(self.profile)

    def test_visible_policy_canonicalizes_transparent_palette(self):
        report = {"issues": [], "metrics": {}}
        image = Image.new("RGBA", (6, 6), (20, 30, 40, 0))
        contract = self.contract | {"allowed_palette": ["#11223300"], "transparent_rgb": "visible"}
        pw.enforce_profile(report, image, contract)
        self.assertEqual(report["status"], "pass")
        pw.enforce_profile({"issues": [], "metrics": {}}, image, self.contract)


if __name__ == "__main__":
    unittest.main()
