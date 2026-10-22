---
name: pixelwright
description: Create and audit PNG pixel art with declared square cells and exact single-color RGBA blocks. Use for sprites, items, UI icons, palettes, pixel-grid repairs, layers, and consistent sprite animations of characters or imaginary objects. Generate from a selected 2D design and check independently observed parts, proportions, colors, features and timed motion without requiring a skeleton; declared rigs remain optional.
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

### Inspect an external sprite-gen sheet

For an existing sprite-gen atlas PNG and runtime `manifest.json`, read
[external-atlases.md](references/external-atlases.md). No new generation or rig
is needed. Read the manifest's explicit rectangles and inspect actual pixels:

```sh
python scripts/pixelwright.py sprite-gen --sheet sprite-sheet-alpha.png --manifest manifest.json --max-colors 32 --out-dir atlas-audit-v1
```

Use `--request sprite-request.json` to obtain `fit.palette_size` instead of
`--max-colors`. Margins come from manifest/request source-pixel declarations;
missing declarations remain REVIEW. Palette and margin violations FAIL.
Within-state visible width, height and area are compared with the medians;
default 10% dimension / 25% area outliers require REVIEW because pose and
occlusion can change them. This is a silhouette screen, not automatic body-part
recognition. Keep the input untouched and show `frames.png` or
`layout_overlay.png` with the per-check results from `report.json`. This mode
does not certify dot fidelity or motion; use the strict profile and observed
sequence workflows for those claims.

### Animate frames and check moving parts

For generated sprite animations, start with [sequences.md](references/sequences.md). Select a 2D design from the user's reference or prompt first. Name visible parts and features in the object's own terms, including imaginary objects. Freeze the frame size, scale, palette, pose descriptions, timing and consistency tolerances before generation. A 3D model, skeleton or human joint vocabulary is not required.

```sh
python scripts/pixel_sequence.py prepare --spec sequence.json --reference selected-design.png --out-dir creature-run
python scripts/pixel_sequence.py import --run creature-run --state hover --image generated-sheet.png --producer "host image generation"
python scripts/pixel_sequence.py observations --run creature-run --out observed.json
python scripts/pixel_sequence.py check --run creature-run --observations observed.json --out-dir creature-audit
```

Use the frozen state prompt and selected design with the host's image tool, then import its untouched PNG. An optional HTTP `generate` command accepts an explicit provider-supported model. Fill observations from the actual exported pixels: part masks, visible measurement endpoints and 2D landmarks. `check` without observations first exports coordinate aids and remains REVIEW. The template supplies no inferred anatomy or expected coordinates. Missing or occluded observations stay REVIEW; raw-image replacement invalidates their hashes.

Check part area, shape, colored patterns, measurements, relative proportions, attachment, required travel, timed adjacent/loop transitions and optional acceleration/contact. Use `relative_to` for articulation relative to an observed anchor, so whole-object motion cannot satisfy a moving-part requirement. Inspect masks and features beside the actual artwork. The bundled `examples/sequence-orbit/` uses independently authored fixture cells; its example observer must reject changed artwork.

Preserve raw images and clearly distinguish their grid from a projected derivative. `strict` rejects invalid raw cells; an explicitly frozen `project` mode samples the whole canvas once, never fits individual frames. Pixel PASS alone does not certify identity or natural animation. Record artistic review separately, with actual notes and reviewer identity; assistant review cannot claim user approval. Regenerate failed states using the original contract and fresh observations, preserving replacement history.

For an already authored atlas or an explicitly requested rig workflow, read [sprites.md](references/sprites.md). The optional paths below retain their own contracts. Freeze the frame size, scale, slot layout, palette and animations first; gutters and unused slots stay transparent, and the profile's logical size is the computed sheet size.

For generative animation guided by a 3D skeleton, establish the **2D character design first** from the user's reference or prompt. That selected design controls anatomy, costume, silhouette, equipment and pixel treatment. Identify its joints and proportions, then fit a bare 3D skeleton and camera to it. Supply the selected 2D design for appearance and projected bones/depth for motion. Do not treat a 3D armor render, mesh silhouette, material or shading as the character design unless the user explicitly requests that transfer. A valid 3D rig proves its own geometry, not the generated artwork's anatomy. Missing independent artwork observations keep pose acceptance at REVIEW; pixel-grid PASS never promotes it to PASS. The source-checkout recipe is `tools/knight_design_first.py`.

When a declared 2D rig is appropriate, list parts back to front, give each a motion (`fixed`, `rigid` with a pivot, `bone` between two joints, or `free`), and write each frame's color rows together with its part map and joint coordinates. Then build and check:

```sh
python scripts/pixel_sprite.py build --spec sprite.json --out-dir sheet-v1
python scripts/pixel_sprite.py check --spec sprite.json --sheet sheet-v1/rendered.png --profile profile.json --out-dir sheet-check-v1
```

The checker audits the whole sheet, draws the declared skeleton over every frame, and fails parts whose dots leave their bone, change shape or size, detach from their parent, or vanish where nothing is drawn in front. Repair the reported part or joint; never loosen tolerances, mark parts hidden, reorder depth or accept partial coverage to obtain a PASS without the user's agreement. Bundled examples are `examples/sprite-walk/` (humanoid walk) and `examples/sprite-lever/` (fixed base, hinged handle, rigid knob).

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

For a sprite sheet, also show each animation preview, name failed frames and distinguish pixel, appearance, motion and artistic status. In the sequence workflow, include `observation-overlay.png` and disclose observation uncertainty. When a rig exists, show its `.rig.gif` (art under the skeleton beside the part colors) or `rig_overlay.png`. Overlays and GIF previews are diagnostics, not deliverable artwork.

Provide native and enlarged PNGs when creating, the declared contract, technical status with the report path, and any unresolved visual findings. Record artistic review separately as accepted, changes needed, or not reviewed, with actual observations (silhouette, palette, stepped contours, important details). Hashes identify the audited bytes; subsequent edits or interpolated scaling require a new audit. A technically compliant image can still be poor art.
