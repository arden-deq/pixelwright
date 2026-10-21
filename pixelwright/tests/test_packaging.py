# SPDX-License-Identifier: Apache-2.0
"""Portable archive boundaries and distribution metadata regression tests."""
import sys
import tempfile
import unittest
import zipfile
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

    def test_installation_includes_palette_and_sprite_resources(self):
        entries = package.collect(package.ROOT / "pixelwright", "pixelwright", include_tests=False)
        for name in ("LICENSE", "NOTICE", "SECURITY.md"):
            entries[f"pixelwright/{name}"] = (package.ROOT / name).read_bytes()
        package.write_zip(self.archive, entries, "pixelwright")
        self.assertTrue(package.verify(self.archive)["verified"])
        with zipfile.ZipFile(self.archive) as archive:
            members = set(archive.namelist())
        for relative in ("scripts/pixel_palette.py", "references/palettes.md",
                         "examples/palette-demo/palette.json", "examples/palette-demo/profile.json",
                         "examples/palette-demo/artwork.json", "scripts/pixel_sprite.py",
                         "references/sprites.md", "examples/sprite-walk/spec.json",
                         "examples/sprite-walk/profile.json", "examples/sprite-lever/spec.json",
                         "examples/sprite-lever/profile.json", "scripts/pixel_sequence.py",
                         "references/sequences.md", "examples/sequence-orbit/spec.json",
                         "examples/sequence-orbit/reference.png", "examples/sequence-orbit/sheet.png",
                         "examples/sequence-orbit/observed-pixels.json", "examples/sequence-orbit/observe_fixture.py"):
            with self.subTest(relative=relative):
                self.assertIn(f"pixelwright/{relative}", members)
        self.assertFalse(any(name.startswith("pixelwright/tests/") for name in members))

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
