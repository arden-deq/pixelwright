# Reusable palettes and named ramps

Read this for `scripts/pixel_palette.py` or a builder specification using `palette_file`. A library supplies named RGBA colors; the project profile still defines grid, scale, alpha, and final acceptance.

## Library format

Use UTF-8 JSON:

```json
{
  "schema_version": 1,
  "name": "Item colors",
  "colors": {
    "transparent": "#00000000",
    "metal_dark": "#283040FF",
    "metal_mid": "#68788CFF",
    "metal_light": "#C8D8E8FF"
  },
  "ramps": {
    "metal": ["metal_dark", "metal_mid", "metal_light"]
  }
}
```

`schema_version` is `1`; optional `name` is a 1..256-character string. `colors` maps 1..256 tokens to distinct `#RRGGBB` (opaque) or `#RRGGBBAA` values. Tokens and ramp names contain 1..64 ASCII letters, digits, `_`, or `-`, starting with a letter or digit. Optional `ramps` maps up to 64 names to ordered lists of 2..256 distinct existing color tokens. Order carries the intended shading sequence; it does not automatically place shadows or choose a light source. Include the needed transparent RGBA values explicitly. Use token arrays in artwork rows when names contain multiple characters.

The builder accepts `palette_file` as an alternative to inline `palette`; its path is confined to the artwork JSON's directory. See [creation.md](creation.md). Libraries are capped at 1 MiB; duplicate JSON fields, duplicate normalized RGBA values, and unknown fields are rejected. A library is not a profile: loading it does not change the project's `allowed_palette` or color budget.

## Extract observed colors

```sh
python scripts/pixel_build.py --spec examples/lantern.json --out-dir build-lantern-v1
python scripts/pixel_palette.py extract build-lantern-v1/rendered.png --max-colors 16 --name observed-items --out-dir palette-extract-v1
```

Extraction counts full decoded RGBA colors, sorts by descending frequency and then by RGBA channel values to break ties, and keeps at most `--max-colors` (default 256). It reports whether the list was truncated. These are observed colors, not synthesized cluster centers; a small cap can omit a rare but important eye, highlight, or transparent color. Inspect the swatches and extraction report before choosing a project palette.

`--transparent-rgb exact` is the default and counts hidden RGB under alpha zero. Explicit `--transparent-rgb visible` canonicalizes those invisible RGB values for extraction; disclose that choice. Extraction neither infers nor certifies a logical grid, and command success is not source QA PASS.

## Build a named ramp

```sh
python scripts/pixel_palette.py ramp --start '#283040' --end '#C8D8E8' --steps 5 --name metal --out-dir palette-ramp-v1
python scripts/pixel_palette.py ramp --start '#283040' --end '#C8D8E8' --steps 5 --name metal5 --palette examples/palette-demo/palette.json --out-dir palette-extend-v1
```

Endpoints must have the same alpha. The tool interpolates encoded sRGB byte values with integer half-up rounding, includes both endpoints, and accepts 2..256 distinct steps. It refuses duplicate shades rather than silently shortening the ramp. `--name` supplies a new ramp key; an existing ramp name is rejected. With `--palette`, it creates a new library while preserving its name and existing colors, reusing matching shades or adding tokens; the original library remains intact. Choose endpoints and order for the material, then visually review the ramp. This reproducible interpolation does not account for perceptual spacing or choose artistic shading.

## Remap a valid grid

```sh
python scripts/pixel_palette.py remap build-lantern-v1/rendered.png --palette examples/palette-demo/palette.json --profile examples/palette-demo/profile.json --out-dir palette-remap-v1
python scripts/pixel_palette.py remap build-lantern-v1/rendered.png --palette examples/palette-demo/palette.json --profile examples/palette-demo/profile.json --ramp metal --out-dir palette-metal-v1
```

Remapping uses the declared grid and keeps dimensions, cell scale, alpha values, and cell positions. For each source color, it selects the target with the smallest squared distance in encoded sRGB byte values among colors with the same alpha; the first target wins distance ties. Optional `--ramp metal` selects that named ramp plus all library entries with alpha zero, preserving transparent cells alongside a material ramp. Every source alpha still needs a matching target alpha; semitransparent cells need their own corresponding-alpha shades.

The source may fail `max_colors` or `allowed_palette` before conversion, but its geometry, exact per-cell uniformity, and alpha must already satisfy the profile. Remapping refuses an invalid grid or alpha instead of repairing it, resizing, or weakening the profile. Use [quality-contract.md](quality-contract.md) and the separate grid repair workflow for those issues.

The result must pass the original profile and belong to the selected target palette. Unused library colors outside `allowed_palette` do not invalidate the asset; actually using such a color makes final QA fail. A broader library or a newly interpolated ramp does not authorize expanding the profile after conversion. Check compatibility before running. Remapping can merge important color distinctions even when the result passes technical QA.

## Review and deliver

Use a fresh output directory for every command. Keep the input PNG, library, and profile unchanged. Extraction and ramp commands write `palette.json`, `palette_report.json`, and `swatch.png`. Remapping writes `palette_report.json`, `source/` and `final/` QA, `comparison.png`, a logical `changed_cells.png` mask, and provenance. Only a final technical PASS produces accepted top-level `native.png` and `rendered.png`; `candidate/` files from a failed conversion are diagnostic.

When source structure/alpha fails or a matching target alpha is missing, no remapped candidate or final audit is created. `extract` and `ramp` return `0` on successful palette creation, with statuses `extracted`/`created`; this is not artwork acceptance. `remap` returns `0` for final technical PASS, `2` for QA failure or unavailable matching alpha, and `1` for invalid input/execution errors. All commands return `1` for caught input/execution errors; argparse misuse uses its conventional `2`.

Inspect source and final status separately, the comparison, changed cells, and clean native-size artwork. Check whether outlines, text, facial details, and material ramps still read. Show the clean output and the final checker's actual grid overlay under the existing delivery rules. Report conversion losses and artistic review separately from technical acceptance.
