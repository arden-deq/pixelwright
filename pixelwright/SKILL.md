---
name: pixelwright
description: Create and audit static PNG pixel art with declared square cells and exact single-color RGBA blocks. Use for sprites, items, UI icons, palette extraction and remapping, pixel-grid repairs, and optional layer composition for complex artwork.
---

# Pixelwright

Create reproducible pixel art and verify its technical contract. The guarantee covers the decoded PNG grid, cell size, and per-cell color. Artistic quality and rendering by downstream apps require separate review.

## Establish the contract

Use the user's existing logical dimensions, integer scale, palette and alpha policy. Logical size is the number of intended dots, not the enlarged PNG size. If missing, ask for a consequential choice or propose a stated default appropriate to the asset (for example, a 16×16 item at 8×). Freeze it before generating; never change the grid to make an existing image pass. A neighboring same-color cluster may span many cells and need not itself be square.

The strict rule is `rendered = logical × S`, with the same positive integer `S` on both axes and origin `(0,0)`. Every physical sample in each `S×S` cell must have exactly the same RGBA8 value. Profile acceptance requires `S≥2`. At 1×, within-cell consistency is tautological; do not treat it as evidence of enlarged block fidelity.

Default to exact RGBA, including hidden RGB under alpha zero. Use the explicit `visible` policy only when invisible RGB should be canonicalized; disclose that weaker byte-level scope. Binary alpha is a useful game-asset default; uniform translucent cells are allowed by an `any` contract. Do not remove intentional translucency or dither without considering the user's design.

## Choose the workflow

Resolve script paths relative to this skill directory and run with Python 3.12+ and the dependencies in `requirements.txt`. Read [platforms.md](references/platforms.md) if the host's execution or installation support is uncertain. If code execution or the original PNG is unavailable, produce a plan or prompt and label the result **unverified**; do not claim a PASS from visual inspection.

### Create with a guaranteed grid

For icons and sprites that can be authored as indexed cells, read [creation.md](references/creation.md). Create a palette and logical token matrix, then render it deterministically:

```sh
python scripts/pixel_build.py --spec artwork.json --out-dir build-v1
python scripts/pixelwright.py inspect build-v1/rendered.png --profile profile.json --out-dir audit-v1
```

Design on the logical grid, iterate the matrix, and use nearest-neighbor integer enlargement. Display the actual exported image and inspect its native-size readability and intended detail. A built-in example is `examples/lantern.json`; `examples/item-profile.json` defines its project contract.

When several assets share named colors or shading ramps, read [palettes.md](references/palettes.md). The builder can reference a reusable palette library with `palette_file` instead of an inline palette.

If a generative image tool is available and better fits the requested artwork, use it according to the host's tool rules. Treat its result as an unverified design candidate. Audit the original exported PNG and preserve it. A prompt saying “pixel art” cannot enforce this contract. A candidate needing projection becomes a new derived asset; generation-tool edits and deterministic repairs follow their respective host permissions.

### Extract or apply a palette

Read [palettes.md](references/palettes.md) when extracting observed colors, building a named ramp, or converting an asset to a declared palette. Extraction records colors without certifying the source's grid. Remapping changes colors on an already valid grid, preserves alpha, and audits the result against the original project profile and the selected target palette. Keep the source and compare changed cells at native size; a technical PASS does not show that the new colors preserve readability or material detail.

### Compose complex artwork in layers when useful

Use layers when independent changes to a background, item, UI, or text would simplify a complex request. Keep tightly interacting parts, such as a character's hand and held weapon, together unless their contact can be checked reliably. A simple icon does not need layers. Read [layers.md](references/layers.md) for the manifest, management commands, and composition contract.

Decide the layout, common grid and RGBA palette, lighting, and drawing order before creating layers. Author each layer to the shared scale and palette; positions use integer logical cells. The compositor audits every listed layer, including hidden layers, composes opaque cells on the logical canvas, enlarges once, and audits the final saved PNG. It exports accepted `native.png` and `rendered.png` only when every layer and the composite pass. Technical acceptance does not replace visual review of individual layers, contact points, occlusion, and final readability. Keep QA overlays separate from artwork.

### Inspect or repair existing art

Read [quality-contract.md](references/quality-contract.md) for profile fields, artifacts, and exit codes. Prefer a reusable profile for final acceptance:

```sh
python scripts/pixelwright.py inspect input.png --profile profile.json --out-dir audit-v1
python scripts/pixelwright.py batch item-a.png item-b.png --profile profile.json --out-dir batch-v1
```

The lower-level checker is useful for ad hoc diagnosis and explicit lossy projection:

```sh
python scripts/pixel_qa.py inspect input.png --logical-size 32x48 --render-size 256x384 --out-dir audit-v1
python scripts/pixel_qa.py fix input.png --logical-size 32x48 --render-size 256x384 --out-dir repair-v1
```

Inspect `report.json`, `grid_overlay.png`, and the logical-resolution preview. Exact violations fail even if a diagnostic score rounds to 100. Geometry failures are not resized or sampled as if valid. Partial alpha and palette rules follow the stated contract; isolated dots are candidates for review, not automatic defects.

Use projection when the user's request authorizes repair and its losses are acceptable. Compare `comparison.png`, `fix_review.json`, and the post-repair report. Re-audit the saved corrected PNG with the original project profile. Never overwrite the source, weaken constraints, auto-approve art from a technical PASS, or loop indefinitely: after two repair attempts, report the remaining defect and propose a targeted redraw.

## Deliver

By default, show both the clean exported PNG and the checker's actual `grid_overlay.png` inline so the user can inspect the intended cells themselves. Label each preview with logical dimensions, physical cell size and technical status; for multiple assets, pair each clean view with its corresponding grid view. If the host cannot display images, provide direct links to both files. Respect a request for clean artwork only.

Explain the overlay briefly: cyan lines mark every declared cell boundary, red-filled cells mark exact color violations, and orange lines indicate approximate boundaries when geometry fails. The overlay is a separate diagnostic preview; keep the deliverable artwork unchanged. Use the checker-generated overlay, not a generative redraw. Never sample the axes differently: square cells must also appear square in the preview. For dense grids, include a nearest-neighbor crop enlarged equally on both axes so individual cells remain inspectable; visual inspection complements the full sample-level audit.

Provide native and enlarged PNGs when creating, the declared contract, technical status with the report path, and any unresolved visual findings. Record artistic review separately as accepted, changes needed, or not reviewed, with actual observations (silhouette, palette, stepped contours, important details). Hashes identify the audited bytes; subsequent edits or interpolated scaling require a new audit. A technically compliant image can still be poor art.
