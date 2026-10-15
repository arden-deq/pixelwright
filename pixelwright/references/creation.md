# Logical-first creation

Read this when authoring indexed artwork with `scripts/pixel_build.py`.

Use JSON with `schema_version: 1`, either an inline `palette` or a `palette_file`, rectangular `rows`, and integer `scale >= 2`. An inline palette maps token names to `#RRGGBB`, `#RRGGBBAA`, or `transparent`. Logical dimensions are each 1..4096 and the rendered area is at most 12,000,000 samples. Each array entry represents exactly one logical cell. Character strings are a compact alternative only when every token is one character. Token arrays avoid ambiguous multi-character names.

```json
{
  "schema_version": 1,
  "scale": 8,
  "palette": {".": "transparent", "a": "#202030", "b": "#F4BD52"},
  "rows": [
    [".", "a", "."],
    ["a", "b", "a"],
    [".", "a", "."]
  ]
}
```

For a reusable library, replace `palette` with `"palette_file": "palette.json"` and use its `colors` token names in `rows`. The path is relative to the artwork JSON's directory, uses POSIX `/` separators, and must resolve within that directory. Absolute paths and parent traversal are rejected. Keep the library beside the artwork or in a subdirectory; do not supply both palette fields. Read [palettes.md](palettes.md) for the library schema, extraction, ramps, and remapping. The bundled `examples/palette-demo/artwork.json` demonstrates a file-backed palette.

Draw subject-specific silhouettes, outlines and shading directly as cells. Keep rows rectangular, use intentional contiguous clusters, and preserve small distinguishing features at native resolution. When changing an asset, edit its matrix and palette. Do not resample a rendered candidate and present it as independent grid evidence.

`native.png` has one physical sample per logical cell. `rendered.png` repeats every native sample into an exact `S×S` square using nearest-neighbor enlargement. Fully transparent colors are canonicalized to `(0,0,0,0)` before rendering; other alpha values are preserved. For binary-alpha profiles, use only opaque colors and transparency. The builder validates dimensions and bounds before exporting and refuses a nonempty output directory.

`build.json` records the original JSON hash, logical grid, scale, normalized palette, output hashes and decoded pixel hashes. A file-backed palette also records the library's source hash. It describes deterministic construction; it does not substitute for audit of the saved PNG. Run a strict profile audit on `rendered.png`, inspect the actual exported images, and retain the source JSON and its referenced palette so visual changes remain reproducible.

For the bundled 16×16 lantern:

```sh
python scripts/pixel_build.py --spec examples/lantern.json --out-dir build-v1
python scripts/pixelwright.py inspect build-v1/rendered.png --profile examples/item-profile.json --out-dir audit-v1
```

For generative imagery, keep the original and its audit. A tool may return an incompatible size even when prompted otherwise. Decide whether to redraw into a matrix, explicitly project a compatible candidate, or ask for another design. Visual generation support depends on the host; this package makes no image API calls.
