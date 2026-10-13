# Pixelwright README header

The header was designed with the built-in image generation tool, then revised with its image editor to remove the magnified window and connecting lines. The subtitle was finalized directly in the editable logical matrix with a single cream color. The revised artwork was exported and audited with Pixelwright. The English and Korean READMEs use the same final PNG.

| Property | Final export |
| --- | --- |
| Logical artwork | 512×256 |
| Rendered PNG | 2048×1024, 2:1 |
| Physical cell | 4×4 px, origin (0, 0) |
| Palette | 32 opaque RGBA colors |
| Exact uniform cells | 131,072 / 131,072 |
| Nonuniform cells, partial-alpha samples, outside-palette samples | 0 |
| Strict technical verdict | PASS |

[Final banner](../../images/pixelwright-header.png) · [Actual report](report.json) · [Checker grid overlay](grid_overlay.png) · [Direct pixel verification](verification.json)

## Source and preparation

The preserved [generative source](generated-source.png) is 1774×887, despite the prompt's requested dimensions. It **fails** the chosen 2048×1024 / 4 px contract: [source report](source-report.json). The source inspector did not resample it or claim measurable grid compliance.

A new canvas at the chosen dimensions was prepared with aspect-preserving nearest-neighbor scaling. Pixelwright projected it onto the 512×256 logical grid. The revised artwork retains the existing 32-color palette, originally assembled from 29 dominant colors and three reserved teal colors for the potion accent. Palette assignment and cell projection are lossy; the original PNG is retained unchanged.

The resulting [indexed artwork](artwork.json) was rendered with `pixel_build.py`. The final saved banner was then inspected with the strict [profile](profile.json). Direct PNG comparisons confirm that every native sample repeats exactly into one 4×4 cell, the color and alpha constraints hold, and the report identifies the actual final bytes. These checks establish structural compliance; they do not independently establish artistic quality.

Visual review confirmed the title `PIXELWRIGHT`, the subtitle `CREATE. GRID. VERIFY.`, and the knight, potion, and shield icon remain readable and fully framed. The linked grid overlay is the checker's actual diagnostic output.

The small subtitle uses exactly one foreground RGBA color, **`#F9E6B8FF`**, against a flat **`#11141AFF`** background. Its glyphs were authored directly on the native grid to remove mottled color and shading. Every decoded PNG sample outside the subtitle rectangle remains identical to the previous published header; the established 32-color palette and strict profile are unchanged. [Subtitle color and region verification](subtitle-style.json) records the glyph masks, coordinates, exact foreground color count, and parent image identity.

The overlay uses cyan reference lines every **8 px horizontally** (every second vertical cell boundary) and **4 px vertically**. Dense-grid line sampling only affects the preview: all 131,072 individual 4×4 cells were audited. Grid lines add diagnostic colors to the preview; the clean banner retains its 32-color palette.

[Initial design prompt](generation-prompt.txt) · [Removal edit prompt](edit-prompt.txt) · [Projection review](projection-review.json)

## Reproduce the final export

From the repository root, with Pixelwright dependencies installed:

```sh
python pixelwright/scripts/pixel_build.py --spec docs/examples/header/artwork.json --out-dir runs/header-build-v1
python pixelwright/scripts/pixelwright.py inspect runs/header-build-v1/rendered.png --profile docs/examples/header/profile.json --out-dir runs/header-audit-v1
```

Choose new output directories for another run. The indexed matrix reproduces the final PNG; regenerating the design prompt is not deterministic.
