# SPDX-License-Identifier: Apache-2.0
"""Portable archive boundaries and distribution metadata regression tests."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import package_skill as package


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.archive = Path(self.temp.name) / "skill.zip"
        self.entries = {"pixelwright/SKILL.md": b"name: pixelwright",
                        "pixelwright/LICENSE": b"Apache License 2.0",
                        "pixelwright/NOTICE": b"Pixelwright",
                        "pixelwright/SECURITY.md": b"Security policy"}

    def tearDown(self):
        self.temp.cleanup()

    def test_manifest_covers_legal_and_runtime_files(self):
        package.write_zip(self.archive, self.entries, "pixelwright")
        self.assertTrue(package.verify(self.archive)["verified"])

    def test_unsafe_paths_and_unexpected_roots_are_rejected(self):
        for member in ("pixelwright/C:/payload.py", "pixelwright/../payload.py"):
            with self.subTest(member=member):
                package.write_zip(self.archive, self.entries | {member: b"unexpected"}, "pixelwright")
                with self.assertRaises(ValueError):
                    package.verify(self.archive)
        package.write_zip(self.archive, self.entries | {"pixelwright/payload.py": b"unexpected"}, "pixelwright")
        self.archive.write_bytes(self.archive.read_bytes().replace(b"pixelwright/payload.py", b"pixelwright\\payload.py"))
        with self.assertRaises(ValueError):
            package.verify(self.archive)
        entries = {name.replace("pixelwright/", "unexpected/", 1): value for name, value in self.entries.items()}
        package.write_zip(self.archive, entries, "unexpected")
        with self.assertRaisesRegex(ValueError, "Unexpected package root"):
            package.verify(self.archive)

    def test_missing_license_fails(self):
        package.write_zip(self.archive, {k: v for k, v in self.entries.items() if not k.endswith("/LICENSE")}, "pixelwright")
        with self.assertRaisesRegex(ValueError, "LICENSE"):
            package.verify(self.archive)


if __name__ == "__main__":
    unittest.main()
