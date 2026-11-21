# Strict static PNG contract

## Project profile

Use UTF-8 JSON. Unknown fields fail validation to catch misspelled constraints.

| Field | Rule |
| --- | --- |
| `schema_version` | Required integer `1` |
| `name` | Optional descriptive string |
| `kind` | Optional. `sprite`: transparent background required, alpha defaults to `binary`; `image`: a general picture, alpha defaults to `opaque`. Undeclared kinds are reported as `not_declared` |
| `logical_size` | Required `WIDTHxHEIGHT` in dots, each 1..4096 |
| `scale` | Integer 1..4096: pixels per dot on both axes. Required unless `image_size` determines it |
| `image_size` | Optional `WIDTHxHEIGHT` of the whole PNG. Without `scale`, the scale is derived from it (it must divide into square whole-pixel dots); with `scale`, a larger size declares a margin |
| `origin` | Optional `[x, y]`, default `[0, 0]`: the pixel where the grid's top-left cell starts. Requires `image_size` |
| `max_colors` | Optional 1..256 visible RGB colors in the actual source, not a sampled preview |
| `alpha` | `binary`: only 0 or 255; `opaque`: only 255; `any`: intentional translucency allowed. Default follows `kind` (`binary` when undeclared) |
| `transparent_rgb` | `exact` (default): compare every decoded RGBA channel; `visible`: normalize alpha-zero RGB to zero before comparison |
| `allowed_palette` | Optional array of 1..256 `#RRGGBB` or `#RRGGBBAA` colors. Every decoded sample must belong, including transparency and margins; include `#00000000` if needed |

The grid is built only from the declaration: cell `(x, y)` covers pixels `[ox+x·S, ox+(x+1)·S) × [oy+y·S, oy+(y+1)·S)`. Audit does not infer a new grid, crop borders, rotate from EXIF, or resize input. Contradicting values (an `image_size` that cannot hold the grid, `origin` without `image_size`, a sprite with `alpha: opaque`) are profile errors. A 1× profile (`scale: 1`) must declare `max_colors` or `allowed_palette`: cell uniformity cannot be measured at 1×, so the palette rule is what catches blur and anti-aliasing. The loaded contract recorded in the report includes the derived `scale`. For sprite sheets, atlases and animations, declare the frame layout in a sprite spec and use `pixel_sprite.py check`; see [sprites.md](sprites.md). Tools other than `pixelwright.py inspect/batch` require a grid that fills the PNG from `(0,0)`.

## Checks

`report.json` has one `checks` row per condition, each with `expected`, `actual` and `status` (`pass`, `fail`, `review`, `not_applicable`, `not_measured`, `not_declared`). The CLI prints the same rows.

| Check | Rule | Issue codes |
| --- | --- | --- |
| `image_size` | The PNG is exactly the contracted size | `RENDER_SIZE_MISMATCH` |
| `margin` | With a margin, every pixel outside the grid box has one RGBA value | `MARGIN_NOT_UNIFORM` |
| `cell_uniformity` | Every sample inside each cell is the same RGBA value; one stray sample fails its cell. Not applicable at 1× | `NON_SOLID_GRID_CELLS`, `OFF_GRID_PIXELS` |
| `dot_size` | The art uses one-cell dots. The gap between color edges on the logical grid is measured per axis; if every edge keeps a spacing of k>1 cells, the art is really k× coarser than declared | `COARSER_THAN_DECLARED`: fail with at least 8 edges per axis, review with 3..7, not measured below 3 |
| `content` | At least one cell is visible | `EMPTY_IMAGE` |
| `kind` | Sprite: at least one transparent cell (a painted checkerboard is not transparency). Image: opaque unless `alpha` says otherwise | `SPRITE_WITHOUT_TRANSPARENCY`, `NON_OPAQUE_ALPHA` |
| `alpha` | Alpha policy over every sample, margins included | `PARTIAL_ALPHA`, `NON_OPAQUE_ALPHA` |
| `color_budget` | Visible RGB colors over the whole PNG at most `max_colors` | `PALETTE_OVER_BUDGET` |
| `allowed_palette` | Every RGBA sample of the whole PNG is in the palette | `COLOR_OUTSIDE_ALLOWED_PALETTE` |

When cells or size fail, `detected_grid` estimates the dot size and origin the pixels were actually drawn on, from the spacing and phase of color edges. It is a repair hint, never a reason to change the contract. `colors_used` lists the decoded RGBA values by sample count; `outside_palette_colors` names the offenders; `dot_size` and `content_box` describe the logical grid.

Input is a static PNG decodable losslessly into RGBA8, including low-bit indexed/grayscale PNG. Animated PNG, non-PNG, and 16-bit channel PNG are rejected instead of silently inspecting a frame or dropping precision. The contract concerns decoded channel values, not gamma-corrected appearance or encoded PNG compression bytes. The source SHA-256 identifies the encoded bytes.

## Acceptance

`pass`: every declared technical rule holds. `review`: a measurement is inconclusive or needs a decision. `fail`: at least one technical rule fails. `error` is a batch item/aggregate execution error, not an art assessment.

Every exact nonuniform cell fails regardless of mean grid score or diagnostic tolerance. The profile interface always uses strict cells with zero tolerance. The ad hoc checker offers `--tolerance`, `--min-grid-score`, and `--relaxed-grid` for diagnosis; these settings cannot certify strict profile acceptance. In the ad hoc checker native 1× inputs require review; a profile that declares `scale: 1` replaces cell uniformity with its required palette rule and the dot-size check. A controlled builder can supply construction evidence, while the final enlarged PNG still needs independent auditing.

`alpha: any` permits uniform semitransparent blocks. It does not permit different alpha values inside a cell. A visible RGB palette budget counts RGB separately from opacity; use `allowed_palette` to constrain full RGBA combinations.

## Artifacts and coordinates

- `report.json`: status, settings or contract, geometry, exact violation count, bounded coordinate samples, and source/profile hashes when the corresponding entrypoint supplies them.
- `grid_overlay.png`: diagnostic of the whole PNG. Cyan lines are every declared cell boundary from the origin; red fill marks cells with more than one RGBA value; a black X in a white box marks cells holding a color outside `allowed_palette`; magenta outlines the grid box when there is a margin, and red squares mark margin pixels that differ from the margin color. When cells are smaller than 4 px the overlay is enlarged by a whole number (`grid_preview.magnification`), the same on both axes. With the wrong PNG size, orange lines show where the declared grid falls, with no cell-color verdict.
- `grid_lines.png`: transparent original-size layer showing every declared cell boundary from the origin on both axes, without sampling. Outer boundaries at the image edge lie outside the half-open canvas; they are not moved inward to shorten edge cells.
- `violation_mask.png`: logical-size binary mask; white marks every exact invalid cell. Produced when the size matches, including a black mask for 1× inputs.
- `logical_preview.png`: representative-cell preview for visual review. It is a derived diagnostic, not evidence that the original passed.
- `correction_prompt.txt`: targeted redesign guidance.
- `batch.json`: aggregate status and an entry for every explicit input; numeric subdirectories avoid duplicate-basename collisions.

Coordinates are zero-based from the top-left of the PNG. `source_box` and `grid_box` arrays use inclusive end coordinates: `[x0,y0,x1,y1]`, already offset by the origin. Cell `(x,y)` spans `[ox+x*S,ox+(x+1)*S)` and `[oy+y*S,oy+(y+1)*S)` in half-open notation. Masks supply all invalid cells even when JSON samples are capped.

Show the clean PNG alongside `grid_overlay.png` by default. Include a short caption with logical size, cell size, and technical status so the user can judge cell alignment visually. The cyan grid shows every intended cell boundary; exact invalid cells are red; geometry failures use orange approximate lines. A diagnostic overlay changes displayed colors, so use the underlying PNG's report for exact RGBA equality. `grid_preview` records the unsampled per-axis spacing. For dense grids, add a nearest-neighbor crop with the same enlargement on both axes. Historical overlays that sampled axes independently can look rectangular even when the audited artwork's cells are square; regenerate those previews with the current checker.

Explicit `pixel_qa.py fix` additionally writes native/enlarged corrected PNGs, a comparison, an impact report and a post-repair report. It chooses a representative observed color in each cell, then enlarges it. Optional palette quantization and alpha thresholding can remove design details. Record both original and corrected statuses and visually review before adoption. Hashes and changed-pixel fractions establish provenance, not artistic safety.

All CLIs require an empty or nonexistent output directory. Choose a new run directory for each attempt. Input/output collisions and existing artifacts are rejected. Do not write unrelated files inside the output directory before auditing.

## Exit codes

| Command | 0 | 1 | 2 |
| --- | --- | --- | --- |
| `pixelwright.py inspect/batch` | All technical statuses pass | Invalid input, profile, or execution error | At least one fail/review, with no execution error |
| `pixel_qa.py inspect` | Pass; review unless `--fail-on-violation` | Execution error | Fail; review with `--fail-on-violation` |
| `pixel_qa.py fix` | Corrected technical pass; review unless strict exit requested | Execution error | Corrected fail, or review with strict exit requested |
| `pixel_build.py` | Export succeeded | — | Validation, execution, or argument parsing error |
| `pixel_sprite.py check` | Sheet, frames, animations and rig all pass | Invalid spec, profile, input, or execution error | At least one fail/review |
| `pixel_sprite.py list/build` | Valid plan or export written | Invalid spec, input, or execution error | Argument parsing error |

For CI use the profile interface. A `fix` exit code concerns the corrected candidate, and must not be cited as the original's status. CLI argument misuse may also return argparse's conventional code 2.
