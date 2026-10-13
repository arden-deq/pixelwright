# Optional layered creation

Read this when a complex image benefits from independent changes to its background, characters, items, UI, or text. Keep a single artwork for simpler requests. Group parts with strong visual dependencies: a character, armor, hands, and held props often need one coherent pose, light source, and contact points.

## Plan and create

Agree on the final logical canvas, scale, shared RGBA palette, layout, lighting, and drawing order. Use the user's established contract. Plan sufficient layer margins so every declared layer fits on the canvas. Separate text is useful for exact wording and a controlled color; review letter shapes and readability at native size.

Each input is an enlarged static PNG built or repaired for the same scale. Its `logical_size` can be smaller than the final canvas. Maintain editable source matrices or generation records alongside it. A newly generated layer remains unverified until its saved PNG is audited. Replacing a layer must preserve the common palette and grid; never silently weaken the final contract to admit it.

## Manifest

Save UTF-8 JSON next to the shared profile and layer files. A manifest is the layout record, not an image-generation prompt:

```json
{
  "schema_version": 1,
  "name": "Castle scene",
  "profile": "profile.json",
  "layers": [
    {
      "id": "background",
      "image": "layers/background.png",
      "logical_size": "96x64",
      "position": [0, 0]
    },
    {
      "id": "character",
      "image": "layers/character.png",
      "logical_size": "24x40",
      "position": [20, 24],
      "visible": true
    }
  ]
}
```

The corresponding final profile uses the existing strict profile schema:

```json
{
  "schema_version": 1,
  "logical_size": "96x64",
  "scale": 8,
  "max_colors": 3,
  "alpha": "binary",
  "transparent_rgb": "exact",
  "allowed_palette": ["#00000000", "#202030FF", "#F4BD52FF", "#F9E6B8FF"]
}
```

| Manifest field | Meaning |
| --- | --- |
| `schema_version` | Required integer `1`; unknown fields are rejected |
| `name` | Optional scene description, at most 256 characters |
| `profile` | Path to the final canvas profile |
| `layers` | 1..64 layers in bottom-to-top order; each has a unique `id` of 1..64 ASCII letters, digits, `_` or `-`, starting with a letter or digit |
| `image` | Relative POSIX path to the enlarged static PNG |
| `logical_size` | Layer width and height in logical cells |
| `position` | `[x, y]`, nonnegative integers from the canvas top-left; the full declared layer must fit |
| `visible` | Optional boolean, default `true`; hidden layers are still audited |
| `sha256` | Optional 64-character hexadecimal hash of the encoded input PNG; a mismatch rejects the input |

Paths resolve from the manifest's directory, not the command's working directory. Use forward slashes; absolute paths, parent traversal, and paths resolving outside that directory are rejected. Manifest and profile files are capped at 1 MiB each. The aggregate declared layer input size is capped at 48,000,000 rendered pixels. Normal per-image PNG limits also apply.

For layer composition, the shared profile must explicitly provide `allowed_palette` and `max_colors`, use `transparent_rgb: "exact"`, and use `alpha: "binary"` or `"opaque"`. Every layer uses this scale, palette, and visible RGB budget with its own logical dimensions and binary alpha. Transparent input RGBA values must be declared in the shared palette and must be uniform inside each cell, including their hidden RGB. The empty final canvas starts at `#00000000`; include this value if the final image will have uncovered space. An opaque final canvas can still have transparent foreground layers. `max_colors` counts visible RGB, so 32 RGBA colors with one transparent entry normally means `max_colors: 31`.

## List, edit, and compose

Run from the skill directory, or resolve these script paths from it:

```sh
python scripts/pixel_layers.py list --manifest examples/layered-scene/scene.json
python scripts/pixel_layers.py compose --manifest examples/layered-scene/scene.json --out-dir scene-v1
```

`list` shows the validated layout; it performs no PNG QA and cannot establish PASS. To move, hide, or reorder a layer, write a new manifest in the same directory as the original:

```sh
python scripts/pixel_layers.py edit --manifest examples/layered-scene/scene.json --layer title --position 16,28 --visible true --index 3 --out examples/layered-scene/scene-v2.json
python scripts/pixel_layers.py compose --manifest examples/layered-scene/scene-v2.json --out-dir scene-v2
```

`--index` is the zero-based position in bottom-to-top drawing order. Supply only the changes needed. `edit` preserves source PNGs and refuses to overwrite the original or an existing destination; keeping the manifest directory fixed preserves relative path meaning. Use an empty or nonexistent output directory for each composition run.

The compositor first runs strict QA on all declared PNGs, including hidden layers. It then places their native cells at integer coordinates and overwrites the canvas only where a visible input cell is opaque. All alpha-zero cells leave lower layers untouched. It repeats the completed native canvas at the shared integer scale and independently audits the saved final candidate. No resizing, rotation, clipping, semitransparent blending, or automatic palette conversion occurs during composition.

## Acceptance and review

Inspect `layers.json`, every layer's report and grid overlay, and the final audit. Per-layer PASS cannot substitute for final PASS: a final opaque or color-budget rule may still fail. Failed inputs are not repaired or silently omitted. Accepted top-level `native.png` and `rendered.png` are exported only when all input layers and the final candidate pass.

| Output | Meaning |
| --- | --- |
| `layers.json` | Aggregate status, input identities and results, final status, report and artifact paths |
| `layers/0000/profile.json` | Layer contract derived from the shared profile and this layer's dimensions |
| `layers/0000/qa/report.json`, `grid_overlay.png` | Actual input-layer audit; numeric directories follow manifest order |
| `final/report.json`, `grid_overlay.png` | Actual final candidate audit when all input layers pass |
| `native.png`, `rendered.png` | Accepted output pair, present only when all audits pass |
| `candidate/native.png`, `candidate/rendered.png` | Diagnostic output pair when final QA fails; these are not accepted artwork |

When any input layer fails, `layers.json` records `final.status: "not_composed"`, and no final candidate is generated. When input errors prevent completion, use the error details and exit code rather than inferring acceptance from files left in a failed run directory.

`layers.json` records input and output hashes, and `input_integrity` records repeated manifest and shared-profile snapshot checks. A detected change to either input metadata file prevents accepted export or demotes exported PNGs to diagnostic candidates. Reports identify whether a provenance path is based on the manifest directory or output directory through `source_path_base` and `profile_path_base`; resolve these bases explicitly when moving records.

Command exit codes are `0` for success/all PASS, `2` for a QA failure or review, and `1` for invalid manifest, input, or execution errors. Argument parsing can also use argparse's conventional exit code `2`.

Review the actual images separately from technical QA. Check each layer's silhouette and important detail, then the composite's scale relationships, lighting, contact points, occlusion, text, and overall readability. A layer hidden by another still needs its own technical and artistic review if it is part of the deliverable. Record art review as accepted, changes needed, or not reviewed with concrete observations.

Show the clean final PNG and its actual grid overlay by default, plus layer previews needed to explain the result. Keep overlays out of the manifest's artwork layers. Disclose sampled reference lines in dense grids; the checker still audits every cell. If any layer or the final composite fails, deliver the diagnostic paths and status instead of presenting the candidate as accepted artwork.
