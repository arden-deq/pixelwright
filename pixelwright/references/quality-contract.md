# Strict static PNG contract

## Project profile

Use UTF-8 JSON. Unknown fields fail validation to catch misspelled constraints.

| Field | Rule |
| --- | --- |
| `schema_version` | Required integer `1` |
| `name` | Optional descriptive string |
| `logical_size` | Required `WIDTHxHEIGHT`, each 1..4096 |
| `scale` | Required integer 2..4096; rendered area at most 12,000,000 samples |
| `max_colors` | Optional 1..256 visible RGB colors in the actual source, not a sampled preview |
| `alpha` | `binary` (default): only 0 or 255; `opaque`: only 255; `any`: intentional translucency allowed |
| `transparent_rgb` | `exact` (default): compare every decoded RGBA channel; `visible`: normalize alpha-zero RGB to zero before comparison |
| `allowed_palette` | Optional array of 1..256 `#RRGGBB` or `#RRGGBBAA` colors. Every decoded sample must belong, including transparency; include `#00000000` if needed |

`render_size` is computed from `logical_size × scale`; it cannot conflict with a separately declared size. Audit does not infer a new grid, crop borders, rotate from EXIF, or resize input. The image origin is `(0,0)`. For a padded atlas, explicitly create and record separate frame crops first; atlas and animation validation are outside this release.

Input is a static PNG decodable losslessly into RGBA8, including low-bit indexed/grayscale PNG. Animated PNG, non-PNG, and 16-bit channel PNG are rejected instead of silently inspecting a frame or dropping precision. The contract concerns decoded channel values, not gamma-corrected appearance or encoded PNG compression bytes. The source SHA-256 identifies the encoded bytes.

## Acceptance

`pass`: every declared technical rule holds. `review`: a measurement is inconclusive or needs a decision. `fail`: at least one technical rule fails. `error` is a batch item/aggregate execution error, not an art assessment.

Every exact nonuniform cell fails regardless of mean grid score or diagnostic tolerance. The profile interface always uses strict cells with zero tolerance. The ad hoc checker offers `--tolerance`, `--min-grid-score`, and `--relaxed-grid` for diagnosis; these settings cannot certify strict profile acceptance. Native 1× inputs require review because intra-cell fidelity has no independent samples. A controlled builder can supply construction evidence, while the final enlarged PNG still needs independent auditing.

`alpha: any` permits uniform semitransparent blocks. It does not permit different alpha values inside a cell. A visible RGB palette budget counts RGB separately from opacity; use `allowed_palette` to constrain full RGBA combinations.

## Artifacts and coordinates

- `report.json`: status, settings or contract, geometry, exact violation count, bounded coordinate samples, and source/profile hashes when the corresponding entrypoint supplies them.
- `grid_overlay.png`: original-size diagnostic, exact invalid cells highlighted in red. Invalid geometry uses orange approximate boundaries and no cell-color verdict.
- `grid_lines.png`: transparent reference layer. Dense overlays may sample lines for legibility; every cell is still audited.
- `violation_mask.png`: logical-size binary mask; white marks every exact invalid cell. Produced for valid geometry, including a black mask for 1× inputs.
- `logical_preview.png`: representative-cell preview for visual review. It is a derived diagnostic, not evidence that the original passed.
- `correction_prompt.txt`: targeted redesign guidance.
- `batch.json`: aggregate status and an entry for every explicit input; numeric subdirectories avoid duplicate-basename collisions.

Coordinates are zero-based from the top-left. Existing `source_box` arrays use inclusive end coordinates: `[x0,y0,x1,y1]`. Cell `(x,y)` spans `[x*S,(x+1)*S)` and `[y*S,(y+1)*S)` in half-open notation. Masks supply all invalid cells even when JSON samples are capped.

Show the clean PNG alongside `grid_overlay.png` by default. Include a short caption with logical size, cell size, and technical status so the user can judge cell alignment visually. The cyan grid shows intended boundaries; exact invalid cells are red; geometry failures use orange approximate lines. A diagnostic overlay changes displayed colors, so use the underlying PNG's report for exact RGBA equality. Dense sampled grid lines should be identified as a reference, not a complete visual map.

Explicit `pixel_qa.py fix` additionally writes native/enlarged corrected PNGs, a comparison, an impact report and a post-repair report. It chooses a representative observed color in each cell, then enlarges it. Optional palette quantization and alpha thresholding can remove design details. Record both original and corrected statuses and visually review before adoption. Hashes and changed-pixel fractions establish provenance, not artistic safety.

All CLIs require an empty or nonexistent output directory. Choose a new run directory for each attempt. Input/output collisions and existing artifacts are rejected. Do not write unrelated files inside the output directory before auditing.

## Exit codes

| Command | 0 | 1 | 2 |
| --- | --- | --- | --- |
| `pixelwright.py inspect/batch` | All technical statuses pass | Invalid input, profile, or execution error | At least one fail/review, with no execution error |
| `pixel_qa.py inspect` | Pass; review unless `--fail-on-violation` | Execution error | Fail; review with `--fail-on-violation` |
| `pixel_qa.py fix` | Corrected technical pass; review unless strict exit requested | Execution error | Corrected fail, or review with strict exit requested |
| `pixel_build.py` | Export succeeded | — | Validation, execution, or argument parsing error |

For CI use the profile interface. A `fix` exit code concerns the corrected candidate, and must not be cited as the original's status. CLI argument misuse may also return argparse's conventional code 2.
