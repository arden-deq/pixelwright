# SPDX-License-Identifier: Apache-2.0
"""Game contracts: 1x assets, one pixel size, style rules and screenshot audits.

Fixtures start from the bundled RPG Maker-style example (16x16 chips, a 24x32
hero, 320x240 screen) and change one property at a time: enlarging,
shifting, filtering, blending or recoloring.
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import generate_game_example as example_art
import pixel_build as builder
import pixel_game as game

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "game"
CONTRACT = EXAMPLE / "game.json"
BASE = (320, 240)
WINDOW = (1700, 1000)
SCALE = 4
OFFSET = (210, 20)
HERO_AT = (148, 120)
C = {token: tuple(int(value[i:i + 2], 16) for i in (1, 3, 5, 7))
     for token, value in json.loads((EXAMPLE / "palette.json").read_text(encoding="utf-8"))["colors"].items()}


def codes(report):
    return {issue["code"] for issue in report["issues"]}


def rgba(path):
    with Image.open(path) as image:
        return image.convert("RGBA")


class GameCase(unittest.TestCase):
    def setUp(self):
        self.contract = game.load_contract(CONTRACT)
        self.tile = rgba(EXAMPLE / "build" / "grass.png")
        self.path = rgba(EXAMPLE / "build" / "path.png")
        self.tree = rgba(EXAMPLE / "build" / "tree.png")
        self.hero = rgba(EXAMPLE / "build" / "hero.png")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def asset(self, image, category=None):
        return game.measure_asset(image, self.contract, category)[0]

    def scene(self, hero=None, at=HERO_AT, effect=None):
        """A small map: grass chips, a path, a tree and the hero, at base resolution."""
        base = Image.new("RGBA", BASE)
        for y in range(0, BASE[1], 16):
            for x in range(0, BASE[0], 16):
                base.alpha_composite(self.path if 144 <= y < 176 else self.tile, (x, y))
        base.alpha_composite(self.tree, (40, 40))
        base.alpha_composite(hero or self.hero, at)
        if effect is not None:
            base.alpha_composite(effect, (200, 60))
        return base

    def present(self, base, resample=Image.Resampling.NEAREST, bars=(0, 0, 0, 255)):
        screen = Image.new("RGBA", WINDOW, bars)
        screen.paste(base.resize((BASE[0] * SCALE, BASE[1] * SCALE), resample), OFFSET)
        return screen

    def big_hero(self):
        return self.hero.resize((self.hero.width * SCALE, self.hero.height * SCALE), Image.Resampling.NEAREST)

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
        document = {key: value for key, value in document.items() if value is not None}
        path = folder / f"{name.replace(' ', '-')}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_example_contract_resolves_palette_outline_and_references(self):
        self.assertEqual(self.contract["base"], BASE)
        self.assertEqual(len(self.contract["tokens"]), len(C))
        self.assertEqual(self.contract["outline_colors"], [C["outline"]])
        self.assertTrue(all(path.is_file() for path in self.contract["references"]))

    def test_example_sources_match_their_generator(self):
        with unittest.mock.patch.object(sys, "argv", ["generate_game_example.py", "--out-dir", str(self.root / "gen")]):
            example_art.main()
        for path in sorted((self.root / "gen").iterdir()):
            self.assertEqual(path.read_bytes(), (EXAMPLE / path.name).read_bytes(), path.name)

    def test_example_assets_are_built_from_their_sources(self):
        for name in ("grass", "flowers", "path", "water", "tree", "pond", "hero"):
            out = self.root / name
            builder.build_from_spec(EXAMPLE / f"{name}.json", out)
            self.assertEqual(np.asarray(rgba(out / "native.png")).tobytes(),
                             np.asarray(rgba(EXAMPLE / "build" / f"{name}.png")).tobytes(), name)

    def test_invalid_contracts_are_rejected(self):
        cases = {"unknown field": {"colour": "red"}, "bad resolution": {"base_resolution": "384by216"},
                 "bad enum": {"style": {"outline": {"mode": "thick"}}},
                 "both palettes": {"allowed_palette": ["#000000"]},
                 "palette outside": {"palette_file": "../lantern.json"},
                 "translucent bars": {"letterbox": "#00000080"},
                 "palette entry": {"palette_file": None, "allowed_palette": ["#000000", 5]},
                 "outline string": {"style": {"outline": {"mode": "dark", "colors": "ink"}}},
                 "font outside": {"font": {"size_px": 8, "file": "../../fonts/x.png"}},
                 "references string": {"style": {"references": "build/hero.png"}},
                 "outline switch": {"categories": {"tile": {"size": "16x16", "outline": "no"}}}}
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                game.load_contract(self.write(name, **change))

    def test_brief_carries_every_style_decision(self):
        text = game.brief(self.contract)
        for expected in ("320x240", "1x", "whole-number scales", "#000000", "nearest-neighbor",
                         "`outline` #2B1B24FF", "Ramp `grass`", "Perspective: top-down", "Light comes from: upper-left",
                         "Dithering: none", "Outline: dark, 1 pixel(s) wide", "character: 24x32",
                         "tile: 16x16 (map chips; they tile seamlessly); no outline", "item: up to 16x16",
                         "native 12 px", "8 frames per second", "4 directions", "no translucent or additive",
                         "build/hero.png", "RPG Maker 2000"):
            self.assertIn(expected, text)

    def test_viewport_uses_the_largest_whole_scale_and_centers_it(self):
        self.assertEqual(game.viewport((1920, 1080), BASE)["viewport"], [320, 60, 1280, 960])
        self.assertEqual(game.viewport((1366, 768), BASE)["bars"], {"left": 203, "right": 203, "top": 24, "bottom": 24})
        self.assertEqual(game.viewport((2560, 1440), BASE)["scale"], 6)
        self.assertEqual(game.viewport((640, 480), BASE)["viewport"], [0, 0, 640, 480])
        self.assertFalse(game.viewport((300, 200), BASE)["fits"])


class AssetTests(GameCase):
    def test_example_assets_pass(self):
        for name, category in (("grass", "tile"), ("flowers", "tile"), ("path", "tile"), ("water", "tile"),
                               ("tree", "object"), ("pond", "terrain"), ("hero", "character")):
            with self.subTest(name):
                self.assertEqual(self.asset(rgba(EXAMPLE / "build" / f"{name}.png"), category)["status"], "pass")
        metrics = self.asset(self.hero)["metrics"]
        self.assertEqual(metrics["effective_pixel_size"]["size"], 1)
        self.assertEqual(metrics["outline"]["outline_coverage"], 1.0)

    def test_enlarged_asset_has_coarse_pixels(self):
        doubled = self.hero.resize((48, 64), Image.Resampling.NEAREST)
        report = self.asset(doubled)
        self.assertEqual(report["status"], "fail")
        self.assertIn("COARSE_PIXELS", codes(report))
        self.assertEqual(report["metrics"]["effective_pixel_size"]["size"], 2)
        tripled = self.tile.resize((48, 48), Image.Resampling.NEAREST)
        self.assertEqual(self.asset(tripled)["metrics"]["effective_pixel_size"]["size"], 3)

    def test_partly_enlarged_asset_is_flagged_for_review(self):
        canvas = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
        canvas.alpha_composite(self.hero, (0, 0))
        canvas.alpha_composite(self.tree.crop((8, 0, 24, 16)).resize((32, 32), Image.Resampling.NEAREST), (32, 0))
        report = self.asset(canvas)
        self.assertNotIn("COARSE_PIXELS", codes(report))
        self.assertIn("COARSE_REGION", codes(report))
        boxes = next(i for i in report["issues"] if i["code"] == "COARSE_REGION")["windows"]
        # The flagged region holds the enlarged canopy and stops short of the 1x hero (columns 0-19).
        self.assertTrue(all(box["x"] >= 20 and box["x"] + box["width"] == 64 for box in boxes), boxes)

    def test_coarse_detection_does_not_depend_on_position(self):
        icon = self.hero.crop((8, 6, 16, 14)).resize((16, 16), Image.Resampling.NEAREST)
        for at in ((96, 96), (100, 100), (96, 100), (5, 223), (303, 3)):
            with self.subTest(at=at):
                base = self.scene()
                base.alpha_composite(icon, at)
                report = self.screen(self.present(base))
                self.assertIn("COARSE_REGION", codes(report))
                box = next(i for i in report["issues"] if i["code"] == "COARSE_REGION")["windows"][0]
                self.assertLessEqual((box["x"], box["y"]), at)

    def test_stretched_and_plain_patterns(self):
        wide = self.asset(self.hero.resize((48, 32), Image.Resampling.NEAREST))
        self.assertIn("COARSE_PIXELS", codes(wide))
        self.assertEqual(wide["metrics"]["effective_pixel_size"]["x"], 2)
        self.assertEqual(wide["metrics"]["effective_pixel_size"]["y"], 1)
        # Plain 1x art with few edges can sit on a coarse lattice: review, never a hard failure.
        checks = Image.new("RGBA", (16, 16), C["grass"])
        for y in range(0, 16, 4):
            for x in range(0, 16, 4):
                if (x + y) // 4 % 2:
                    checks.paste(C["grass_dark"], (x, y, x + 4, y + 4))
        report = self.asset(checks, "tile")
        self.assertEqual(report["status"], "review")
        self.assertEqual(codes(report), {"COARSE_PIXELS"})

    def test_large_assets_follow_their_category(self):
        wide = Image.new("RGBA", (640, 240))
        for y in range(0, 240, 16):
            for x in range(0, 640, 16):
                wide.alpha_composite(self.path if y >= 208 else self.tile, (x, y))
        self.assertEqual(codes(self.asset(wide)), {"ASSET_LARGER_THAN_SCREEN"})
        self.assertEqual(self.asset(wide)["status"], "review")
        self.contract["document"]["categories"]["background"] = {"size": "640x240", "outline": False}
        self.assertEqual(self.asset(wide, "background")["status"], "pass")

    def test_palette_alpha_size_and_category_rules(self):
        recolored = self.hero.copy()
        recolored.putpixel((12, 20), (250, 0, 250, 255))
        self.assertIn("COLOR_OUTSIDE_PALETTE", codes(self.asset(recolored)))
        soft = self.hero.copy()
        soft.putpixel((8, 6), C["outline"][:3] + (128,))
        self.assertIn("PARTIAL_ALPHA", codes(self.asset(soft)))
        self.assertIn("CATEGORY_SIZE", codes(self.asset(self.hero, "tile")))
        self.assertIn("ASSET_LARGER_THAN_SCREEN", codes(self.asset(Image.new("RGBA", (400, 20), C["outline"]))))
        self.assertIn("EMPTY_ASSET", codes(self.asset(Image.new("RGBA", (8, 8)))))
        with self.assertRaisesRegex(ValueError, "Unknown category"):
            self.asset(self.hero, "boss")

    def test_dithering_and_outline_style_rules(self):
        patch = self.tile.copy()
        for y in range(6, 9):
            for x in range(4, 8):
                patch.putpixel((x, y), C["grass_light"] if (x + y) % 2 else C["grass_dark"])
        self.assertNotIn("DITHERING_FOUND", codes(self.asset(patch)))
        dithered = self.tile.copy()
        light, dark = C["grass_light"], C["grass_dark"]
        for y in range(6, 10):
            for x in range(4, 9):
                dithered.putpixel((x, y), light if (x + y) % 2 else dark)
        self.assertIn("DITHERING_FOUND", codes(self.asset(dithered)))
        unlined = np.asarray(self.hero).copy()
        ink = np.all(unlined == C["outline"], axis=2)
        unlined[ink] = C["cloth"]
        self.assertIn("OUTLINE_INCOMPLETE", codes(self.asset(Image.fromarray(unlined, "RGBA"))))
        thick = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        thick.paste(C["outline"], (2, 2, 14, 14))
        thick.paste(C["cloth"], (4, 4, 12, 12))
        thick.putpixel((5, 5), C["cloth_light"])
        self.assertIn("OUTLINE_TOO_THICK", codes(self.asset(thick)))
        # Map pieces are drawn without outlines; their category turns the outline rule off.
        pond = rgba(EXAMPLE / "build" / "pond.png")
        self.assertIn("OUTLINE_INCOMPLETE", codes(self.asset(pond)))
        self.assertEqual(self.asset(pond, "terrain")["status"], "pass")

    def test_intake_compares_new_asset_with_references(self):
        doubled = self.root / "hero2x.png"
        self.hero.resize((48, 64), Image.Resampling.NEAREST).save(doubled)
        report = game.intake(doubled, self.contract["references"], self.contract, "character", self.root / "intake")
        self.assertIn("PIXEL_SIZE_DIFFERS", codes(report))
        with Image.open(self.root / "intake" / "side_by_side.png") as sheet:
            self.assertGreater(sheet.width, sheet.height)
        tinted = self.root / "hero-cloth.png"
        hero = self.hero.copy()
        hero.putpixel((12, 20), C["water"])
        hero.save(tinted)
        report = game.intake(tinted, [EXAMPLE / "build" / "hero.png"], self.contract, "character", self.root / "intake2")
        self.assertEqual(report["status"], "review")
        self.assertEqual(codes(report), {"COLORS_NOT_IN_REFERENCES"})
        # A plain reference whose few edges only suggest larger dots cannot fail a 1x asset.
        stone = self.root / "stone.png"
        plain = Image.new("RGBA", (16, 16), C["grass"])
        plain.paste(C["dirt"], (5, 5, 11, 11))
        plain.save(stone)
        report = game.intake(EXAMPLE / "build" / "hero.png", [stone], self.contract, "character", self.root / "intake3")
        self.assertEqual(report["status"], "review")
        self.assertEqual(next(i for i in report["issues"] if i["code"] == "PIXEL_SIZE_DIFFERS")["severity"], "review")


class ScreenTests(GameCase):
    def test_clean_scene_passes_and_maps_the_viewport(self):
        report = self.screen(self.present(self.scene()))
        self.assertEqual(report["status"], "pass", report["issues"])
        self.assertEqual(report["viewport"]["viewport"], [*OFFSET, BASE[0] * SCALE, BASE[1] * SCALE])

    def test_runtime_mistakes_break_cells(self):
        shifted = self.present(self.scene(hero=Image.new("RGBA", (1, 1))))
        big = self.big_hero()
        at = (OFFSET[0] + HERO_AT[0] * SCALE, OFFSET[1] + HERO_AT[1] * SCALE)
        shifted.alpha_composite(big, (at[0] + 2, at[1]))
        filtered = self.present(self.scene(), resample=Image.Resampling.BILINEAR)
        # An engine rotates the sprite after the screen is scaled, so the turn cuts across game pixels.
        rotated = self.present(self.scene(hero=Image.new("RGBA", (1, 1))))
        rotated.alpha_composite(big.rotate(17, expand=True), (at[0], at[1] - 8 * SCALE))
        for name, image in {"sub-pixel position": shifted, "linear filter": filtered, "runtime rotation": rotated}.items():
            with self.subTest(name):
                self.assertIn("CELL_NOT_UNIFORM", codes(self.screen(image)))

    def test_enlarged_element_effect_and_bars(self):
        mixel = self.screen(self.present(self.scene(hero=self.hero.resize((48, 64), Image.Resampling.NEAREST),
                                                    at=(60, 100))))
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
        self.assertEqual(self.screen(image, scale=SCALE, offset=OFFSET)["status"], "pass")
        self.assertIn("CELL_NOT_UNIFORM", codes(self.screen(image, scale=SCALE, offset=(OFFSET[0] + 1, OFFSET[1]))))
        with self.assertRaisesRegex(ValueError, "outside the screenshot"):
            self.screen(image, scale=SCALE + 1)
        with self.assertRaisesRegex(ValueError, "at least 1"):
            self.screen(image, scale=0)
        self.assertIn("WINDOW_SMALLER_THAN_BASE", codes(self.screen(Image.new("RGBA", (300, 200), (0, 0, 0, 255)))))

    def test_cli_exit_codes_and_outputs(self):
        shot = self.root / "shot.png"
        self.present(self.scene()).save(shot)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(game.run_cli(["screen", str(shot), "--contract", str(CONTRACT),
                                           "--out-dir", str(self.root / "screen")]), 0)
            self.assertEqual(game.run_cli(["asset", str(EXAMPLE / "build" / "hero.png"), str(EXAMPLE / "build" / "grass.png"),
                                           "--contract", str(CONTRACT), "--out-dir", str(self.root / "batch")]), 0)
            doubled = self.root / "big.png"
            self.hero.resize((48, 64), Image.Resampling.NEAREST).save(doubled)
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
