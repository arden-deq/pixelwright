# Inspect an external sprite-gen atlas

Use the main CLI's `sprite-gen` command with an existing PNG and its runtime
`manifest.json`. No generation, sprite-gen installation, skeleton, design
annotation or separately authored Pixelwright sprite spec is required.

```sh
python scripts/pixelwright.py sprite-gen --sheet sprite-sheet-alpha.png --manifest manifest.json --max-colors 32 --out-dir atlas-audit-v1
```

When the original `sprite-request.json` is available, use it for the palette
budget instead of repeating the value:

```sh
python scripts/pixelwright.py sprite-gen --sheet sprite-sheet-alpha.png --manifest manifest.json --request sprite-request.json --size-tolerance 0.10 --area-tolerance 0.25 --out-dir atlas-audit-v2
```

The Python API is `pixel_atlas.check_sprite_gen(sheet, manifest, out_dir, ...)`.
Run with Python 3.12+, Pillow and NumPy, as with the other Pixelwright tools.
These are development-source additions; rebuild the installable package from
this checkout. Previously published version 0.6.2 archives are unchanged.

## Inputs and declarations

- `manifest.frame_layout` supplies `sheetWidth`, `sheetHeight`, `cellWidth`,
  `cellHeight`, and `rows: {state: [{x, y, w, h}, ...]}`. Rectangles are read
  in their listed order and may have different positions from a regular grid.
  They must share the declared cell size, fit in the actual PNG, and not overlap.
- Optional `manifest.animation.rows` must name those same states and agree on
  each frame count. Known duplicated cell dimensions must agree too. Other
  exporter metadata is allowed. Playback and timing are not audited here.
- Palette budget: `--max-colors` first, then `request.fit.palette_size`.
  The runtime manifest alone normally does not declare a palette limit.
- Horizontal/vertical margins: `--margin-x` / `--margin-y` first, then
  `manifest.cell.safe_margin_x/y`, then the request's `cell.safe_margin_x/y`
  or shared `cell.safe_margin`. All values are **source PNG pixels**.
- Missing budgets or margins produce REVIEW, not an assumed default or PASS.
  Conflicting declarations are recorded as `CONSTRAINT_OVERRIDE` (REVIEW),
  including which value won. Zero explicitly disables that axis's margin.
- Dimensions/counts are strict integers; booleans, negative bounds, overlapping
  rectangles, duplicate JSON keys and nonfinite numbers are input errors.
  Limits are 1,024 frames, 256 states, 8 MiB per JSON, and 12 million PNG pixels.

The checker reads only the explicit input paths. It does not open `game_input`,
base images, frame paths or any other path named inside a manifest or request.

## What the checker measures

**Palette:** count distinct visible RGB colors in the actual decoded PNG,
across the whole sheet, and record per-frame counts. Colors under alpha zero
are excluded; any alpha greater than zero counts as visible. A shared-budget
violation is FAIL even if every frame individually uses fewer colors. The
report lists up to 256 observed colors and discloses truncation.

**Margins:** measure empty pixels on the left, top, right and bottom of each
frame's visible bounding box. A margin below its declared minimum is FAIL;
exactly matching the minimum passes. A fully empty character frame is FAIL.
Visible pixels outside all frame rectangles also fail the layout check.

**Size consistency:** within **each state**, compute the median visible width,
height and nontransparent pixel count from nonempty frames. Each frame records
its ratios to those medians. Default review thresholds are relative deviations
greater than **10% for width/height** or **25% for visible area**. At least three
nonempty frames are required; otherwise the size screen remains REVIEW. The
threshold arguments are finite fractions in `0..1`, where zero means exact.

Size outliers are **REVIEW**, not proof of an anatomical error. Gathering legs,
raising a weapon, occlusion, clothing or clipping can change visible bounds
without changing body scale. Conversely, unchanged bounds can conceal changed
body parts. A consistently mis-scaled whole state will match its own median.
Use selected-design observations in [sequences.md](sequences.md) for actual
part comparisons. This adapter does not certify natural motion or infer a
logical dot grid; use a separate [strict profile](quality-contract.md) for that.

## Outputs and exit status

- `report.json`: overall and per-check status, declarations and their sources,
  exact input hashes, global/per-frame palette counts, local bounds and margins,
  per-state medians, per-frame ratios, issue locations and limitations.
- `layout_overlay.png`: the actual sheet with status-colored frame boundaries,
  cyan safe-area guides, and white visible bounds.
- `frames.png`: equal-sized frame cells, up to four columns, annotated with
  measured bounds and visible area. The pixels are never scaled, recentered or
  fitted per pose. A contact board exceeding the image limit is omitted with
  an explicit reason; the full-sheet overlay remains available.

Red borders mark per-frame FAIL, amber REVIEW and green PASS. A global palette
failure remains in the report even when individual frame borders are green.
Previews are diagnostics; the input PNG and JSON files remain unchanged.
Use a new or empty output directory. Exit codes are `0` PASS, `2` FAIL/REVIEW,
and `1` invalid input or execution error.

The mounted-knight charge example in the source checkout retains the unchanged
sprite-gen output. The adapter finds 62 colors against a 32-color budget,
seven frames violating 12-pixel margins, and two silhouette-size review
candidates. Its complete run is under
`docs/examples/mounted-knight-charge-v1/manifest-audit-v1/`.
