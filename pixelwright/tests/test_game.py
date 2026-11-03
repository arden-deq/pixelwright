# SPDX-License-Identifier: Apache-2.0
"""Game contracts: 1x assets, one pixel size, style rules and screenshot audits.

Fixtures start from the bundled example game's 1x tile and hero and change one
property at a time: enlarging, shifting, filtering, blending or recoloring.
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pixel_build as builder
import pixel_game as game

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "game"
CONTRACT = EXAMPLE / "game.json"
WINDOW = (2000, 1100)
SCALE = 5


def codes(report):
    return {issue["code"] for issue in report["issues"]}


def rgba(path):
    with Image.open(path) as image:
        return image.convert("RGBA")


class GameCase(unittest.TestCase):
    def setUp(self):
        self.contract = game.load_contract(CONTRACT)
        self.tile = rgba(EXAMPLE / "build" / "tile.png")
        self.hero = rgba(EXAMPLE / "build" / "hero.png")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def asset(self, image, category=None):
        return game.measure_asset(image, self.contract, category)[0]

    def scene(self, hero=None, at=(60, 167), effect=None):
        base = Image.new("RGBA", (384, 216), (155, 212, 95, 255))
        for x in range(0, 384, 16):
            base.alpha_composite(self.tile, (x, 200))
        base.alpha_composite(hero or self.hero, at)
        if effect is not None:
            base.alpha_composite(effect, (200, 150))
        return base

    def present(self, base, resample=Image.Resampling.NEAREST, bars=(0, 0, 0, 255)):
        screen = Image.new("RGBA", WINDOW, bars)
        big = base.resize((384 * SCALE, 216 * SCALE), resample)
        screen.paste(big, ((WINDOW[0] - 384 * SCALE) // 2, (WINDOW[1] - 216 * SCALE) // 2))
        return screen

    def screen(self, image, **options):
        return game.measure_screen(image, self.contract, **options)[0]


class ContractTests(GameCase):
    def write(self, name, **changes):
        """A changed copy of the example contract beside a copy of its palette and references."""
        folder = self.root / "contract"
        if not folder.exists():
            shutil.copytree(EXAMPLE, folder)
        document = json.loads(CONTRACT.read_text(encoding="utf-8"))
        document.update(changes)
        path = folder / f"{name.replace(' ', '-')}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_example_contract_resolves_palette_outline_and_references(self):
        self.assertEqual(self.contract["base"], (384, 216))
        self.assertEqual(len(self.contract["tokens"]), 11)
        self.assertEqual(self.contract["outline_colors"], [(0x1B, 0x1F, 0x2A, 255)])
        self.assertTrue(all(path.is_file() for path in self.contract["references"]))

    def test_example_assets_are_built_from_their_sources(self):
        for name in ("tile", "hero"):
            out = self.root / name
            builder.build_from_spec(EXAMPLE / f"{name}.json", out)
            self.assertEqual(np.asarray(rgba(out / "native.png")).tobytes(),
                             np.asarray(rgba(EXAMPLE / "build" / f"{name}.png")).tobytes(), name)

    def test_invalid_contracts_are_rejected(self):
        cases = {"unknown field": {"colour": "red"}, "bad resolution": {"base_resolution": "384by216"},
                 "bad enum": {"style": {"outline": {"mode": "thick"}}},
                 "both palettes": {"allowed_palette": ["#000000"]},
                 "palette outside": {"palette_file": "../lantern.json"},
                 "translucent bars": {"letterbox": "#00000080"}}
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                game.load_contract(self.write(name, **change))

    def test_brief_carries_every_style_decision(self):
        text = game.brief(self.contract)
        for expected in ("384x216", "1x", "whole-number scales", "#000000", "nearest-neighbor", "`ink` #1B1F2AFF",
                         "Ramp `grass`", "Perspective: side", "Light comes from: upper-left", "Dithering: none",
                         "Outline: dark, 1 pixel(s) wide", "character: 8x12 to 24x32", "item: up to 16x16",
                         "native 8 px", "12 frames per second", "8 directions", "no translucent or additive",
                         "build/hero.png", "godot"):
            self.assertIn(expected, text)

    def test_viewport_uses_the_largest_whole_scale_and_centers_it(self):
        base = (384, 216)
        self.assertEqual(game.viewport((1920, 1080), base)["viewport"], [0, 0, 1920, 1080])
        self.assertEqual(game.viewport((1366, 768), base)["bars"], {"left": 107, "right": 107, "top": 60, "bottom": 60})
        self.assertEqual(game.viewport((2560, 1440), base)["scale"], 6)
        self.assertFalse(game.viewport((320, 200), base)["fits"])


class AssetTests(GameCase):
    def test_example_assets_pass(self):
        self.assertEqual(self.asset(self.hero, "character")["status"], "pass")
        self.assertEqual(self.asset(self.tile, "tile")["status"], "pass")
        metrics = self.asset(self.hero)["metrics"]
        self.assertEqual(metrics["effective_pixel_size"]["size"], 1)
        self.assertEqual(metrics["outline"]["outline_coverage"], 1.0)

    def test_enlarged_asset_has_coarse_pixels(self):
        doubled = self.hero.resize((24, 34), Image.Resampling.NEAREST)
        report = self.asset(doubled)
        self.assertEqual(report["status"], "fail")
        self.assertIn("COARSE_PIXELS", codes(report))
        self.assertEqual(report["metrics"]["effective_pixel_size"]["size"], 2)
        tripled = self.tile.resize((48, 48), Image.Resampling.NEAREST)
        self.assertEqual(self.asset(tripled)["metrics"]["effective_pixel_size"]["size"], 3)

    def test_partly_enlarged_asset_is_flagged_for_review(self):
        canvas = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
        canvas.alpha_composite(self.hero, (0, 8))
        canvas.alpha_composite(self.tile.resize((32, 32), Image.Resampling.NEAREST), (32, 0))
        report = self.asset(canvas)
        self.assertNotIn("COARSE_PIXELS", codes(report))
        self.assertIn("COARSE_REGION", codes(report))
        self.assertTrue(all(box["x"] >= 24 for box in next(i for i in report["issues"]
                                                             if i["code"] == "COARSE_REGION")["windows"]))

    def test_palette_alpha_size_and_category_rules(self):
        recolored = self.hero.copy()
        recolored.putpixel((5, 2), (250, 0, 250, 255))
        self.assertIn("COLOR_OUTSIDE_PALETTE", codes(self.asset(recolored)))
        soft = self.hero.copy()
        soft.putpixel((4, 0), (0x1B, 0x1F, 0x2A, 128))
        self.assertIn("PARTIAL_ALPHA", codes(self.asset(soft)))
        self.assertIn("CATEGORY_SIZE", codes(self.asset(self.hero, "tile")))
        self.assertIn("ASSET_LARGER_THAN_SCREEN", codes(self.asset(Image.new("RGBA", (400, 20), (0x1B, 0x1F, 0x2A, 255)))))
        self.assertIn("EMPTY_ASSET", codes(self.asset(Image.new("RGBA", (8, 8)))))
        with self.assertRaisesRegex(ValueError, "Unknown category"):
            self.asset(self.hero, "boss")

    def test_dithering_and_outline_style_rules(self):
        dithered = self.tile.copy()
        light, dark = (0x9B, 0xD4, 0x5F, 255), (0x2F, 0x6B, 0x3A, 255)
        for y in range(6, 10):
            for x in range(4, 9):
                dithered.putpixel((x, y), light if (x + y) % 2 else dark)
        self.assertIn("DITHERING_FOUND", codes(self.asset(dithered)))
        unlined = np.asarray(self.hero).copy()
        ink = np.all(unlined == (0x1B, 0x1F, 0x2A, 255), axis=2)
        unlined[ink] = (0x6C, 0x7A, 0x89, 255)
        self.assertIn("OUTLINE_INCOMPLETE", codes(self.asset(Image.fromarray(unlined, "RGBA"))))
        thick = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        thick.paste((0x1B, 0x1F, 0x2A, 255), (2, 2, 14, 14))
        thick.paste((0x6C, 0x7A, 0x89, 255), (4, 4, 12, 12))
        thick.putpixel((5, 5), (0xB8, 0xC4, 0xCF, 255))
        self.assertIn("OUTLINE_TOO_THICK", codes(self.asset(thick)))

    def test_intake_compares_new_asset_with_references(self):
        doubled = self.root / "hero2x.png"
        self.hero.resize((24, 34), Image.Resampling.NEAREST).save(doubled)
        report = game.intake(doubled, self.contract["references"], self.contract, "character", self.root / "intake")
        self.assertIn("PIXEL_SIZE_DIFFERS", codes(report))
        with Image.open(self.root / "intake" / "side_by_side.png") as sheet:
            self.assertGreater(sheet.width, sheet.height)
        tinted = self.root / "hero-cloth.png"
        hero = self.hero.copy()
        hero.putpixel((5, 8), (0x4F, 0xA3, 0x4A, 255))
        hero.save(tinted)
        report = game.intake(tinted, [EXAMPLE / "build" / "hero.png"], self.contract, "character", self.root / "intake2")
        self.assertEqual(report["status"], "review")
        self.assertEqual(codes(report), {"COLORS_NOT_IN_REFERENCES"})


class ScreenTests(GameCase):
    def test_clean_scene_passes_and_maps_the_viewport(self):
        report = self.screen(self.present(self.scene()))
        self.assertEqual(report["status"], "pass", report["issues"])
        self.assertEqual(report["viewport"]["viewport"], [40, 10, 1920, 1080])

    def test_runtime_mistakes_break_cells(self):
        shifted = self.present(self.scene(hero=Image.new("RGBA", (1, 1))))
        big = self.hero.resize((self.hero.width * SCALE, self.hero.height * SCALE), Image.Resampling.NEAREST)
        shifted.alpha_composite(big, (40 + 60 * SCALE + 2, 10 + 167 * SCALE))
        filtered = self.present(self.scene(), resample=Image.Resampling.BILINEAR)
        # An engine rotates the sprite after the screen is scaled, so the turn cuts across game pixels.
        rotated = self.present(self.scene(hero=Image.new("RGBA", (1, 1))))
        rotated.alpha_composite(big.rotate(17, expand=True), (40 + 60 * SCALE, 10 + 160 * SCALE))
        for name, image in {"sub-pixel position": shifted, "linear filter": filtered, "runtime rotation": rotated}.items():
            with self.subTest(name):
                self.assertIn("CELL_NOT_UNIFORM", codes(self.screen(image)))

    def test_enlarged_element_effect_and_bars(self):
        mixel = self.screen(self.present(self.scene(hero=self.hero.resize((24, 34), Image.Resampling.NEAREST),
                                                    at=(60, 150))))
        self.assertEqual(mixel["status"], "review")
        self.assertIn("COARSE_REGION", codes(mixel))
        glow = Image.new("RGBA", (10, 10), (255, 255, 255, 120))
        effect = self.screen(self.present(self.scene(effect=glow)))
        self.assertIn("COLOR_OUTSIDE_PALETTE", codes(effect))
        self.assertEqual(effect["status"], "fail")
        bars = self.screen(self.present(self.scene(), bars=(20, 20, 20, 255)))
        self.assertIn("LETTERBOX_NOT_UNIFORM", codes(bars))

    def test_declared_viewport_and_window_too_small(self):
        image = self.present(self.scene())
        self.assertEqual(self.screen(image, scale=5, offset=(40, 10))["status"], "pass")
        self.assertIn("CELL_NOT_UNIFORM", codes(self.screen(image, scale=5, offset=(41, 10))))
        with self.assertRaisesRegex(ValueError, "outside the screenshot"):
            self.screen(image, scale=6)
        self.assertIn("WINDOW_SMALLER_THAN_BASE", codes(self.screen(Image.new("RGBA", (300, 200), (0, 0, 0, 255)))))

    def test_cli_exit_codes_and_outputs(self):
        shot = self.root / "shot.png"
        self.present(self.scene()).save(shot)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(game.run_cli(["screen", str(shot), "--contract", str(CONTRACT),
                                           "--out-dir", str(self.root / "screen")]), 0)
            self.assertEqual(game.run_cli(["asset", str(EXAMPLE / "build" / "hero.png"), str(EXAMPLE / "build" / "tile.png"),
                                           "--contract", str(CONTRACT), "--out-dir", str(self.root / "batch")]), 0)
            doubled = self.root / "big.png"
            self.hero.resize((24, 34), Image.Resampling.NEAREST).save(doubled)
            self.assertEqual(game.run_cli(["asset", str(doubled), "--contract", str(CONTRACT),
                                           "--out-dir", str(self.root / "big")]), 2)
            self.assertEqual(game.run_cli(["brief", "--contract", str(CONTRACT)]), 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(game.run_cli(["asset", str(doubled), "--contract", str(CONTRACT),
                                           "--out-dir", str(self.root / "big")]), 1)
        for path in ("screen/report.json", "screen/screen_overlay.png", "batch/batch.json",
                     "batch/0000/asset_overlay.png", "big/report.json"):
            self.assertTrue((self.root / path).is_file(), path)


if __name__ == "__main__":
    unittest.main()
