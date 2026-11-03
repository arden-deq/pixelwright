# Game contracts

Read this when assets are made for a game, or when a game's screen should be checked. A profile describes one PNG; a game contract describes what every asset and every frame of one game shares. `scripts/pixel_game.py` reads it.

## Why one contract

A pixel-art game looks consistent when everything uses one pixel size. The game renders at one base resolution, for example 320×240, and the whole screen is enlarged by one whole number with bars filling the rest of the window. Every sprite, tile, effect, UI element and font is drawn at 1×: one image pixel is one game pixel. An enlarged `rendered.png` from the builder is a review image and is never imported into an engine. Dropping 4×, 6× and 8× renders into one scene mixes pixel sizes (mixels), which no single-asset audit can see.

## Gather the style first

Before drawing anything for a game, collect these decisions from the user or the existing game, write them into `game.json`, and print the brief. Ask about the ones that change the result; propose stated defaults for the rest.

| Decision | Field | Example |
| --- | --- | --- |
| Base resolution and tile size | `base_resolution`, `tile_size` | `320x240`, `16` |
| Palette and color budget | `palette_file` or `allowed_palette`, `max_colors` | 26 named colors plus transparency, with ramps; at most 16 per asset |
| Transparency | `alpha` | `binary` |
| Bars around the scaled screen | `letterbox` | `#000000` |
| Sizes per kind of asset | `categories` | character 24×32, tile 16×16; `"outline": false` exempts map chips and terrain from the outline rule |
| Genre, mood, notes | `style.genre`, `style.mood`, `style.notes` | side-scrolling platformer |
| Camera view | `style.perspective` | `side`, `top-down`, `three-quarter`, `isometric`, `front`, `other` |
| Light | `style.light_direction` | `upper-left`, `upper-right`, `top`, `left`, `right`, `front`, `none` |
| Shading | `style.shading` | `flat`, `cel`, `soft`, `other` |
| Outline | `style.outline` | `{"mode": "dark", "width": 1, "colors": ["outline"]}`; modes `none`, `dark`, `colored`, `selective` |
| Dithering, anti-aliasing | `style.dithering`, `style.anti_aliasing` | `none`/`limited`/`allowed`; `none`/`manual` |
| Assets that set the look | `style.references` | an approved tile and character, 1× PNGs |
| Text | `font` | `{"name": "...", "size_px": 8, "line_height_px": 10}` |
| Motion | `animation.fps` | `12` |
| Rotation | `rotation` | `{"mode": "prerendered", "directions": 8}`; or `none`, `quarter_turns` |
| Effects | `effects.blending` | `opaque` (palette colors only) or `palette_alpha` (translucency reviewed on screen) |
| Engine | `engine` | `unity`, `godot`, `phaser`, `pixi`, `web`, `love`, `gamemaker`, `other` |

Unknown fields and values fail validation. Paths (`palette_file`, `style.references`, `font.file`) are relative to the contract and stay inside its directory. The bundled [`examples/game/game.json`](../examples/game/game.json), an RPG Maker 2000-style map kit, declares all of them; `tools/generate_game_example.py` in the source repository regenerates its art.

```sh
python scripts/pixel_game.py brief --contract game.json
```

The brief restates the contract as rules: the screen and pixel size, the exact palette and ramps, style, sizes, text, motion, effects, rotation and the reference assets with their hashes. Follow it for every asset, include it in prompts to an image generator, and pass it to anyone drawing for the game.

## Check 1× assets

```sh
python scripts/pixel_game.py asset hero.png --category character --contract game.json --out-dir asset-check-v1
python scripts/pixel_game.py asset tiles/*.png --contract game.json --out-dir tiles-check-v1
```

| Code | Severity | Meaning |
| --- | --- | --- |
| `COARSE_PIXELS` | fail with at least 8 color edges per axis; review with 3 to 7 | Every column edge keeps a spacing of w and every row edge a spacing of h, with w or h above 1: the asset is drawn with w×h dots, usually an enlarged or stretched export |
| `COARSE_REGION` | review | Part of the asset shows only dots larger than one pixel; it may be enlarged, or coarse by design |
| `COLOR_OUTSIDE_PALETTE`, `TOO_MANY_COLORS` | fail | Colors beyond the game palette or budget |
| `PARTIAL_ALPHA`, `NON_OPAQUE_ALPHA` | fail | Transparency outside the contract |
| `CATEGORY_SIZE`, `EMPTY_ASSET` | fail | Size rules |
| `ASSET_LARGER_THAN_SCREEN` | review | Checked without a category and larger than the base resolution; check backgrounds and tilesets under a category whose size allows them |
| `DITHERING_FOUND` | review | At least 16 pixels form 3×3 two-color checkerboards while the style declares no dithering |
| `OUTLINE_INCOMPLETE` | review | Less than 90% of silhouette pixels use the declared outline colors |
| `OUTLINE_TOO_THICK` | review | More than half of a declared 1-pixel outline is two pixels deep |

Dot width is the largest spacing that every column color edge keeps, and dot height the same for rows; transparent pixels count as one background. Measuring the axes separately also catches stretched, non-square dots. Plain 1× art can sit on a coarse lattice too: a tile of 4×4 checks or a flat square with a 2-pixel outline has only a few edges, all 4 or 2 apart. That is why fewer than 8 edges per axis give REVIEW, never FAIL, and fewer than 3 are not measured. `COARSE_REGION` tests every window position (tile size, at least 8), so an enlarged element is found wherever it sits; the report gives the bounding box of each flagged region. A window counts only when its dots are wider and taller than one pixel, because sparse 1× content often lines up on one axis by chance; an element stretched in one direction only is caught by the whole-asset measurement, not inside a screenshot. Outline checks treat the image border as covered, so tiles and cropped art have no silhouette there. Light direction, shading quality and mood are not measured. `asset_overlay.png` marks off-palette pixels red, coarse windows orange and dither windows blue.

## Compare a new asset with the game

```sh
python scripts/pixel_game.py intake new_enemy.png --category character --contract game.json --out-dir intake-v1
```

The new asset is placed beside the contract's reference assets (or `--reference` files) at 1× on a neutral background, and the whole row is enlarged by one whole number into `side_by_side.png`. Look at it: sizes, outline weight and detail density should read as one game. The report adds `PIXEL_SIZE_DIFFERS` when the measured dot sizes differ (fail when both measurements have at least 8 edges per axis, otherwise review), `COLORS_NOT_IN_REFERENCES` (review) for palette colors no reference uses, and `OUTLINE_WIDTH_DIFFERS` (review) when outline depth differs by more than 40 points from the references.

## Check a screenshot

```sh
python scripts/pixel_game.py viewport 1920x1080 1366x768 2560x1440 --contract game.json
python scripts/pixel_game.py screen capture.png --contract game.json --out-dir screen-check-v1
```

`viewport` prints the largest whole-number scale and the centered bars for each window size. `screen` assumes that layout unless `--scale` and `--offset X,Y` declare the viewport. Capture a lossless PNG from the engine's own screenshot function at the window's native size; screen recorders and JPEG change pixels.

| Code | Severity | What it catches in the game |
| --- | --- | --- |
| `LETTERBOX_NOT_UNIFORM` | fail | Bars that are not the letterbox color: a non-integer scale or drawing outside the viewport |
| `CELL_NOT_UNIFORM` | fail | Game pixels that are not one color across their screen block: sub-pixel positions or camera, runtime rotation, non-integer scaling, linear filtering or mipmaps, lossy capture |
| `COLOR_OUTSIDE_PALETTE` | fail (`opaque` effects) or review (`palette_alpha`) | Translucent or additive effects, tinting, lighting or color grading |
| `COARSE_REGION` | review | A sprite, font or UI element drawn at 2× or more inside the 1× screen |
| `WINDOW_SMALLER_THAN_BASE` | fail | The window cannot show the base resolution |

`screen_overlay.png` shows the screen at base resolution: red game pixels are non-uniform, magenta outlines mark off-palette colors and orange boxes mark coarse windows. Check several scenes, including a moving camera, effects, dialogue and menus. A color-managed or gamma-converting capture can shift every color; then palette results need review rather than repair.

All commands require a fresh output directory. Exit codes: `0` pass, `2` fail or review, `1` invalid contract, input or execution error. Technical PASS does not judge appeal; record art review separately.
