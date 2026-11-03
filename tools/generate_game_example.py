#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Write the bundled example game: an RPG Maker 2000-style map kit drawn cell by cell.

Every tile, the tree, the pond and the hero are hand-placed token rows; the pond
is generated from a rounded rectangle and the water tile's waves. This writes
palette.json and one artwork JSON per asset into pixelwright/examples/game/;
build each with pixel_build.py to get the 1x PNGs in build/.
"""
import argparse
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "pixelwright" / "examples" / "game"
PALETTE = {
    ".": ("transparent", "#00000000"),
    "o": ("outline", "#2B1B24FF"),
    "h": ("hair_dark", "#6B3420FF"), "H": ("hair", "#A8552AFF"), "i": ("hair_light", "#DD8A44FF"),
    "s": ("skin", "#F8D3A8FF"), "S": ("skin_shade", "#D99B70FF"),
    "b": ("cloth_dark", "#23417AFF"), "B": ("cloth", "#3C6CC0FF"), "c": ("cloth_light", "#79A6E6FF"),
    "l": ("leather_dark", "#4A2A18FF"), "L": ("leather", "#7E4C2AFF"),
    "r": ("red", "#B8383AFF"), "w": ("white", "#F4F1E4FF"),
    "g": ("grass_dark", "#3D7A2EFF"), "G": ("grass", "#5EA83AFF"), "k": ("grass_light", "#8ED04EFF"),
    "d": ("dirt_dark", "#9A6A3CFF"), "D": ("dirt", "#C4925AFF"), "e": ("dirt_light", "#E2BC80FF"),
    "u": ("water_dark", "#2A5AA6FF"), "U": ("water", "#4A8AD8FF"), "v": ("water_light", "#9CCEF2FF"),
    "f": ("leaf_dark", "#1E5A2AFF"), "F": ("leaf", "#2E8A3AFF"), "t": ("leaf_light", "#5AB84AFF"),
    "y": ("yellow", "#F2D24AFF"),
}

GRASS = [
    "GGGGGGGGGGGGGGGG",
    "GGGGGGGGGGkGGGGG",
    "GGkGGGGGGGgkGGGG",
    "GGgkGGGGGGGGGGGG",
    "GGGGGGGGGGGGGGGG",
    "GGGGGGGkGGGGGGGG",
    "GGGGGGGgkGGGGGkG",
    "GGGGGGGGGGGGGGgk",
    "GkGGGGGGGGGGGGGG",
    "GgkGGGGGGGGGGGGG",
    "GGGGGGGGGGkGGGGG",
    "GGGGGGGGGGgkGGGG",
    "GGGGkGGGGGGGGGGG",
    "GGGGgkGGGGGGGGGG",
    "GGGGGGGGGGGGGkGG",
    "GGGGGGGGGGGGGgkG",
]
FLOWERS = [
    "GGGGGGGGGGGGGGGG",
    "GGGwGGGGGGGGGGGG",
    "GGwywGGGGGGkGGGG",
    "GGGwGGGGGGGgkGGG",
    "GGGgGGGGGGGGGGGG",
    "GGGGGGGGGGrGGGGG",
    "GGGGGGGGGrywGGGG",
    "GkGGGGGGGGrGGGGG",
    "GgkGGGGGGGgGGGGG",
    "GGGGGGGGGGGGGGGG",
    "GGGGGGwGGGGGGGkG",
    "GGGGGwywGGGGGGgk",
    "GGGGGGwGGGGGGGGG",
    "GGkGGGgGGGGGGGGG",
    "GGgkGGGGGGGGGGGG",
    "GGGGGGGGGGGGGGGG",
]
PATH = [
    "DDDDDDDDDDDDDDDD",
    "DDDDDDDDDDDDDDDD",
    "DDeDDDDDDDDDDDDD",
    "DDdDDDDDDDDeDDDD",
    "DDDDDDDDDDDdDDDD",
    "DDDDDDDDDDDDDDDD",
    "DDDDDDeDDDDDDDDD",
    "DDDDDDdDDDDDDDeD",
    "DDDDDDDDDDDDDDdD",
    "DeDDDDDDDDDDDDDD",
    "DdDDDDDDDDeDDDDD",
    "DDDDDDDDDDdDDDDD",
    "DDDDDeDDDDDDDDDD",
    "DDDDDdDDDDDDDDDD",
    "DDDDDDDDDDDDDeDD",
    "DDDDDDDDDDDDDdDD",
]
WATER = [
    "UUUUUUUUUUUUUUUU",
    "UUUUUUUUUUUUUUUU",
    "UUvvvUUUUUUUUUUU",
    "UUUUuuUUUUUUUUUU",
    "UUUUUUUUUUUvvvUU",
    "UUUUUUUUUUUUUuuU",
    "UUUUUUUUUUUUUUUU",
    "UUUUUUvvvUUUUUUU",
    "UUUUUUUUuuUUUUUU",
    "UUUUUUUUUUUUUUUU",
    "UvvvUUUUUUUUUUUU",
    "UUUuuUUUUUUUvvvU",
    "UUUUUUUUUUUUUUuu",
    "UUUUUUUUUUUUUUUU",
    "UUUUUUUvvvUUUUUU",
    "UUUUUUUUUuuUUUUU",
]
TREE = [
    "................................",
    "...........oooooooooo...........",
    "........oootttttFFFFFooo........",
    "......ootttttttFFFFFFFFFoo......",
    ".....ottttkttttFFFFFFFFFFFo.....",
    "....otttkkttttFFFFFFFFFFFFFo....",
    "...ottttttttFFFFFFFFFFFFFFFFo...",
    "...otttttttFFFFFFfFFFFFFFFFFo...",
    "..ottttttFFFFFFFfffFFFFFFFFFFo..",
    "..otttttFFFFFFFFFFFFFFFFFFfFFo..",
    "..ottttFFFFFFFFFFFFFFFFFFfffFo..",
    ".otttttFFFFFtFFFFFFFFFFFFFFFFFo.",
    ".ottttFFFFFttFFFFFFFFFFFFFFFFFo.",
    ".otttFFFFFFFFFFFFFFFFfFFFFFFFFo.",
    ".ottFFFFFFFFFFFFFFFFfffFFFFFFFo.",
    ".otFFFFFfFFFFFFFFFFFFFFFFFFFFfo.",
    ".oFFFFFfffFFFFFFFFFFFFFFFFFFffo.",
    ".oFFFFFFFFFFFFFFFFFFFFFFFFFfffo.",
    "..oFFFFFFFFFFFFFFFFFFFFFFFffffo.",
    "..oFFFFFFFFFFFFFFFFFFFFFFfffffo.",
    "..offFFFFFFFFFFFFFFFFFFFffffo...",
    "...offfFFFFFFFFFFFFFFFffffffo...",
    "....offffFFFFFFFFFFFfffffoo.....",
    ".....oooffffffffffffffooo.......",
    "........oooooLLlooooo...........",
    "............oLLlo...............",
    "............oLLlo...............",
    "............oLLlo...............",
    "...........oLLLllo..............",
    "..........oLLlLLllo.............",
    "...........ooooooo..............",
    "................................",
]
_HERO_CORE = [
    "....oooooooo....",
    "...oiiiHHHHHo...",
    "..oiHHHHHHHHHo..",
    ".oiHHHHHHHHHHHo.",
    ".oHHHHHHHHHHHho.",
    ".ohHHhHHHHhHHho.",
    ".ohhsshhhhsshho.",
    ".ohssssssssssho.",
    ".ohssossssossho.",
    ".ohssossssossho.",
    ".ohSssssssssSho.",
    "..oSssssSsssSo..",
    "...oooSSSSooo...",
    "...ocrrsSrrbo...",
    "..ocBBrrrrBBbo..",
    ".ocBoBBBBBBoBbo.",
    ".ocBoBcBBBBoBbo.",
    ".ocBoLLyLLLoBbo.",
    ".osSobBBBBbosSo.",
    "..oo.obBBbo.oo..",
    ".....obbbbo.....",
    "....obbobbo.....",
    "....obbobbo.....",
    "....oLLoLLo.....",
    "...olLLoLLlo....",
    "...ooooooooo....",
]
HERO = ["." * 24] * (32 - len(_HERO_CORE)) + ["...." + row + "...." for row in _HERO_CORE]


def _pond(width=80, height=64, radius=10):
    """A pond drawn as one object: grass-dark lip, sand shore, dark water edge, waves from the water tile."""
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            # Depth inside a rounded rectangle: straight sides use the edge distance, corners the arc.
            cx = min(max(x, radius), width - 1 - radius)
            cy = min(max(y, radius), height - 1 - radius)
            if x == cx or y == cy:
                d = min(x, y, width - 1 - x, height - 1 - y)
            else:
                d = radius - ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if d < 0:
                row.append(".")
            elif d < 1:
                row.append("g")
            elif d < 3:
                row.append("e" if y < height - 3 else "D")
            elif d < 4:
                row.append("u")
            else:
                row.append(WATER[y % 16][x % 16])
        rows.append("".join(row))
    return rows


POND = _pond()
ASSETS = {"grass": GRASS, "flowers": FLOWERS, "path": PATH, "water": WATER, "tree": TREE, "pond": POND, "hero": HERO}
RAMPS = {"hair": ["hair_dark", "hair", "hair_light"], "skin": ["skin_shade", "skin"],
         "cloth": ["cloth_dark", "cloth", "cloth_light"], "grass": ["grass_dark", "grass", "grass_light"],
         "dirt": ["dirt_dark", "dirt", "dirt_light"], "water": ["water_dark", "water", "water_light"],
         "leaf": ["leaf_dark", "leaf", "leaf_light"], "leather": ["leather_dark", "leather"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=OUT)
    out = parser.parse_args().out_dir
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in ASSETS.items():
        if len({len(row) for row in rows}) != 1:
            raise ValueError(f"{name} rows differ in width")
    colors = {token: value for token, value in PALETTE.values()}
    palette = {"schema_version": 1, "name": "Hollow Glen palette (example)", "colors": colors, "ramps": RAMPS}
    (out / "palette.json").write_text(json.dumps(palette, indent=2) + "\n", encoding="utf-8", newline="\n")
    for name, rows in ASSETS.items():
        spec = {"schema_version": 1, "scale": 8, "palette_file": "palette.json",
                "rows": [[PALETTE[cell][0] for cell in row] for row in rows]}
        text = json.dumps(spec, indent=2)
        text = re.sub(r"\[\s+(\"[^\]]*?)\s+\]",
                      lambda m: "[" + ", ".join(part.strip() for part in m.group(1).split(",")) + "]", text)
        (out / f"{name}.json").write_text(text + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
