# Pixelwright

![Pixelwright banner with a knight, potion, and shield icon](docs/images/pixelwright-header.png)

Header: 2048×1024 · 4×4 px cells · 32 colors · 131,072 cells PASS · [Audit report](docs/examples/header/report.json) · [Grid preview](docs/examples/header/grid_overlay.png) · [Build records](docs/examples/header/)

[English](README.md) · [한국어](README.ko.md) · Version 0.6.2 · [Apache License 2.0](LICENSE)

**Create static PNG pixel art on a declared grid, then verify every cell.**

Pixelwright is a shared AI skill for GPT-powered hosts and Claude. It helps create and audit characters, items, and UI icons with a consistent dot size, complete square grid cells, and exactly one RGBA color per cell. The same `SKILL.md` and Python tools serve both ecosystems; the host must provide file access and Python execution.

Author a palette and a logical pixel matrix, render at an integer scale, and audit the exported PNG. Reuse named palette libraries and shading ramps across assets, or remap colors on an already valid grid. For animation, place frames on one sprite sheet and declare a skeleton so every body or object part can be checked as it moves. For existing artwork, declare its intended grid before inspection. By default, deliver both the clean artwork and its actual grid QA preview so users can check the cells themselves.

## One knight, two grid contracts

![The same full plate knight with shield and mace at 4×4 and 8×8 dots: clean artwork, magnified grid cells, the shared 32-color palette, and actual QA results](docs/images/knight-conditions.png)

These are the actual outputs reviewed during Pixelwright development: a full-body knight wearing full plate armor, carrying a shield and flanged mace. Both PNGs are **1024×1536**, use the same **32-color RGBA palette** (31 visible colors plus transparency), and pass the same strict quality criteria. Changing the dot size changes the logical canvas and the amount of detail; it preserves complete square cells and exact single-color fills.

| Version | Native artwork → output PNG | One dot | Uniform cells | Colors, including transparency | Audit |
| --- | --- | --- | ---: | ---: | --- |
| Fine dots | [256×384](docs/examples/knight/4px/native.png) → [1024×1536](docs/examples/knight/4px/rendered.png) | 4×4 px | 98,304 / 98,304 | 32 | [PASS report](docs/examples/knight/4px/report.json) |
| Larger dots | [128×192](docs/examples/knight/8px/native.png) → [1024×1536](docs/examples/knight/8px/rendered.png) | 8×8 px | 24,576 / 24,576 | 32 | [PASS report](docs/examples/knight/8px/report.json) |

Both inspections found **zero nonuniform cells, zero partially transparent pixels, and zero colors outside the declared palette**. Every cell contains one exact RGBA value, including transparent cells. Independent pixel comparisons also confirm that each output is an exact nearest-neighbor enlargement of its native artwork: [4 px verification](docs/examples/knight/4px/verification.json) · [8 px verification](docs/examples/knight/8px/verification.json).

The figure pairs clean artwork with enlarged grid crops so you can inspect individual dots. Its labels distinguish the dot size in the actual PNG from the display magnification. Grid lines and checkerboard backgrounds belong to the separate diagnostic preview; the clean PNGs retain their transparent backgrounds and 32-color palette. Open the full [4 px grid preview](docs/examples/knight/4px/grid_overlay.png) or [8 px grid preview](docs/examples/knight/8px/grid_overlay.png) to inspect the whole image.

The generative source was kept as unverified; Pixelwright's grid projection, palette-constrained logical matrices, and integer-scale rendering produced the inspected outputs. These two tested contracts provide evidence that technical quality stays consistent when dot size and logical resolution change. Artistic quality remains a separate visual review.

The [knight example files](docs/examples/knight/) include editable `artwork.json` matrices, native and rendered PNGs, the declared profiles, actual inspection reports, and independent verification records. After installing the dependencies below, reproduce either version with the bundled tools:

```sh
python pixelwright/scripts/pixel_build.py --spec docs/examples/knight/4px/artwork.json --out-dir runs/knight-4px-build-v1
python pixelwright/scripts/pixelwright.py inspect runs/knight-4px-build-v1/rendered.png --profile docs/examples/knight/4px/profile.json --out-dir runs/knight-4px-audit-v1
python pixelwright/scripts/pixel_build.py --spec docs/examples/knight/8px/artwork.json --out-dir runs/knight-8px-build-v1
python pixelwright/scripts/pixelwright.py inspect runs/knight-8px-build-v1/rendered.png --profile docs/examples/knight/8px/profile.json --out-dir runs/knight-8px-audit-v1
```

## Quick start

Requires **Python 3.12+**, Pillow, and NumPy. Run these commands from the repository root:

```sh
git clone https://github.com/jungducknam/pixelwright.git
cd pixelwright
python -m venv .venv
```

Activate the environment:

```sh
# macOS / Linux
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

Build the included lantern and inspect the saved PNG:

```sh
python -m pip install -r pixelwright/requirements.txt
python pixelwright/scripts/pixel_build.py --spec pixelwright/examples/lantern.json --out-dir runs/lantern-build-v1
python pixelwright/scripts/pixelwright.py inspect runs/lantern-build-v1/rendered.png --profile pixelwright/examples/item-profile.json --out-dir runs/lantern-audit-v1
```

The example builds a 16×16 logical canvas at 8×, producing a 128×128 PNG. Open `rendered.png`, `report.json`, and `grid_overlay.png` together. Each output directory must be empty or nonexistent; choose a new run name when repeating a command.

## Reuse, extract, and remap palettes

Version 0.5.0 adds a reusable JSON palette library with named colors and ramps. An artwork can use `palette_file` instead of an inline palette; the same library can serve several logical matrices. The [palette demo](pixelwright/examples/palette-demo/) includes a library-backed artwork and a 16×16, 8× profile.

After the lantern quick start above, run from the repository root:

```sh
python pixelwright/scripts/pixel_palette.py extract runs/lantern-build-v1/rendered.png --max-colors 16 --name lantern-observed --out-dir runs/palette-extract-v1
python pixelwright/scripts/pixel_palette.py ramp --start '#283040' --end '#C8D8E8' --steps 5 --name metal5 --palette pixelwright/examples/palette-demo/palette.json --out-dir runs/palette-ramp-v1
python pixelwright/scripts/pixel_palette.py remap runs/lantern-build-v1/rendered.png --palette pixelwright/examples/palette-demo/palette.json --profile pixelwright/examples/palette-demo/profile.json --out-dir runs/palette-remap-v1
python pixelwright/scripts/pixel_build.py --spec pixelwright/examples/palette-demo/artwork.json --out-dir runs/palette-demo-build-v1
python pixelwright/scripts/pixelwright.py inspect runs/palette-demo-build-v1/rendered.png --profile pixelwright/examples/palette-demo/profile.json --out-dir runs/palette-demo-audit-v1
```

Extraction selects frequent observed RGBA colors and reports truncation; it does not certify the source grid. Ramp creation interpolates same-alpha endpoints into distinct shades. Remapping preserves the declared grid and alpha, chooses nearest same-alpha target colors, and rejects invalid geometry or nonuniform cells. It audits the converted PNG against the original profile and selected palette before exporting accepted `native.png` and `rendered.png`.

Review `palette_report.json`, the source and final QA, `comparison.png`, and the logical `changed_cells.png` mask. Color conversion can merge important details even when technical QA passes. Each command writes into a fresh directory and keeps original files intact. See [palette guidance](pixelwright/references/palettes.md) for the schema, optional ramp targets, alpha requirements, and source hashes.

## Castle guard scene

![Armored knight at a castle gate, with a wall-mounted lantern, burgundy shield, and distant towers](docs/examples/castle-guard/rendered.png)

**1280×896 PNG · 320×224 logical cells · 4×4 px cells · 32 colors · all 71,680 cells PASS.** [QA report](docs/examples/castle-guard/report.json) · [Complete square grid](docs/examples/castle-guard/grid_overlay.png) · [Enlarged cells](docs/examples/castle-guard/grid-detail.png).

The gate, lantern, distant castle, and knight share one palette and lighting treatment. The [editable scene](docs/examples/castle-guard/) renders a single indexed logical matrix using a reusable palette library. It includes the native PNG, declared profile, preserved generation source, and independent verification. Grid projection, palette remapping, and a logical wordmark edit produced the audited output; artistic review is recorded separately.

## Complex requests: optional layers

For complex requests, the skill can separate elements that benefit from independent edits: backgrounds, items, UI, and text. Parts with important contact or pose relationships, such as a character's hands and held equipment, are usually kept together. Simple icons can still use one artwork.

Define the layout, common scale and RGBA palette, lighting, and drawing order first. `pixel_layers.py` manages a JSON layer manifest, audits every input PNG, composes at logical resolution, enlarges once, and audits the saved final PNG. Every layer uses the same palette; giving each layer a separate color budget would not constrain the whole scene.

The [four-layer composition tutorial](pixelwright/examples/layered-scene/) uses a background, the knight with its shield and mace, an item, and a title. Its 320×224 logical canvas is rendered to 1280×896 with 4×4 px cells and one shared 32-entry RGBA palette. See the actual [layer results](docs/examples/layered-scene/layers.json), [final report](docs/examples/layered-scene/final-report.json), and [final grid preview](docs/examples/layered-scene/grid_overlay.png).

**All four layers PASS, and all 71,680 final cells PASS:** zero nonuniform cells, partially transparent pixels, or samples outside the shared palette. The opaque final PNG uses 31 visible RGB colors. This composition example reuses the previously validated knight with a simple native-authored background, item, and text.

```sh
# Validate and list the layout, then compose and audit all layers and the result.
python pixelwright/scripts/pixel_layers.py list --manifest pixelwright/examples/layered-scene/scene.json
python pixelwright/scripts/pixel_layers.py compose --manifest pixelwright/examples/layered-scene/scene.json --out-dir runs/layers-scene-v1

# Move the title and write a new manifest beside the original.
python pixelwright/scripts/pixel_layers.py edit --manifest pixelwright/examples/layered-scene/scene.json --layer title --position 16,28 --out pixelwright/examples/layered-scene/scene-title-v2.json
python pixelwright/scripts/pixel_layers.py compose --manifest pixelwright/examples/layered-scene/scene-title-v2.json --out-dir runs/layers-scene-v2
```

`edit` can also set `--visible true|false` and a zero-based `--index` in bottom-to-top drawing order. It writes a new manifest and preserves source PNGs. Positions are integer logical cells; full layers must fit inside the canvas. Hidden layers are audited too. Paths are relative to the manifest directory and cannot escape it.

Each composition writes `layers.json`, per-layer reports and grid previews under `layers/0000/qa/`, and the final audit under `final/`. Accepted `native.png` and `rendered.png` appear at the output root only when **all layers and the final PNG PASS**. Failed final candidates remain under `candidate/` for diagnosis; a failing input layer prevents composition. Exit codes are `0` for all PASS, `2` for QA FAIL/REVIEW, and `1` for manifest, input, or execution errors.

This mode requires binary layer transparency, an explicit shared palette and visible RGB budget, and exact transparent RGBA. It uses opaque-cell replacement, with no semitransparent blending, resizing, rotation, or clipping. A final opaque canvas is supported with transparent foreground layers. Technical QA is followed by visual review of the layers and final image, including contacts, occlusion, lighting, and readability. QA overlays remain separate from artwork. See the [layer workflow and manifest reference](pixelwright/references/layers.md).

## 2D design first, 3D bones for motion

The optional [animation workflow](docs/SPRITE_3D_ko.md) starts with a 2D pixel character designed from a prompt or user reference. Its proportions define a bare 3D skeleton. Image generation then redraws that same 2D design in the projected poses; the skeleton supplies camera, joints and depth, while the 2D design supplies appearance. The Blender scene contains zero armor or equipment meshes. These development tools require a source checkout.

![Selected 2D design, made before the skeleton](docs/examples/knight-design-first/design.png)

| Walk | Attack | Block |
| --- | --- | --- |
| ![Walk draft](docs/examples/knight-design-first/audit/walk.gif) | ![Attack draft](docs/examples/knight-design-first/audit/attack.gif) | ![Block draft](docs/examples/knight-design-first/audit/block.gif) |

This real generation draft uses **128×128 logical frames and 24 shared colors**. Exact pixel storage and 3D geometry PASS; independent artwork observations find pose and equipment-size failures, so the sample is **not production accepted**. [The example](docs/examples/knight-design-first/) preserves raw inputs, GIFs, the actual grid overlay, annotations and failed checks. Frames are never individually fitted or recentered. A valid skeleton cannot certify the generated artwork. The older [mesh-transfer experiment](docs/examples/knight-3d/) is retained as history.

The [integration validation record](docs/VALIDATION_design_first_ko.md) covers Pillow 13, selected-design protection, archived regeneration history, independent measurement inputs and the rechecked real example.

The [requirements and progress record](docs/SPRITE_REQUIREMENTS_AND_STATUS_ko.md) tracks the requested workflow, implemented checks and remaining work. The current walk still needs convincing foot contact, weight transfer and continuity across frames and the loop boundary.

## 2D sprite sheets and rig auditing

The README knight, animated with this skill. Frame 0 of each animation is the header knight itself; every frame keeps its 32 colors, and all three sheets pass the strict audit and the rig check. See [how the knight was rigged](docs/examples/knight-animation/).

| Mace swing | Shield block | Walk |
| --- | --- | --- |
| ![The knight raises the mace overhead and smashes it down](docs/examples/knight-animation/swing/animations/swing.gif) | ![The knight raises the shield across the body](docs/examples/knight-animation/block/animations/block.gif) | ![The knight marches in place, swinging the mace](docs/examples/knight-animation/walk/animations/walk.gif) |

The same animations with the declared skeleton over the art (left) and every dot colored by its part (right):

![Mace swing with skeleton and part colors](docs/examples/knight-animation/swing/animations/swing.rig.gif)

![Shield block with skeleton and part colors](docs/examples/knight-animation/block/animations/block.rig.gif)

![Walk with skeleton and part colors](docs/examples/knight-animation/walk/animations/walk.rig.gif)

Version 0.6.0 adds `pixel_sprite.py` for multi-frame assets. A sprite spec declares the frame size, the grid of slots with margins and spacing, and named animations; the profile's logical size is the computed sheet size. The checker first runs the strict audit on the whole sheet, then requires transparent gutters and unused slots, enforces an optional edge margin inside every frame, and records each frame's bounds.

For motion, declare a **rig**: named joints with coordinates in every frame, and a part map that assigns each visible dot to a part, with parts listed back to front. Pixelwright does not guess anatomy. It draws the declared skeleton over every frame and compares each part with the frame where that part is best visible:

| Motion | Typical parts | What must stay consistent |
| --- | --- | --- |
| `fixed` | lever base, chest body | identical dots in every frame |
| `rigid` | head, knob, drawer | an exact copy moved by its pivot joint, optionally along one axis |
| `bone` | limbs, torso, lever handle | reference dots carried along the bone: where they land, how far they drift, their count and the bone length |
| `free` | cape, hair, effects | presence, size and colors |

Every part must also touch its parent, joints must sit on their parts, fixed joints must stay put, and joint steps between frames can be capped. A dot may disappear only where a part drawn in front covers it, so a forearm cannot vanish into a torso drawn behind it.

![Walk frames above their part maps, each with the declared skeleton](docs/examples/sprites/walk/rig_overlay.png)

The [walk cycle](docs/examples/sprites/) has 8 frames, 8 parts and 9 joints; all 64 part-frame comparisons pass. Checking [the same sheet pixels with a skeleton whose front arm swings forward in frame 4](docs/examples/sprites/walk-arm-lag/) shows the failure this feature targets: the arm's dots stay behind, so `PART_OFF_SKELETON`, `PART_DRIFT` and `JOINT_OFF_PART` fail. The [lever example](docs/examples/sprites/) covers objects with a fixed base, a handle hinged on a fixed pivot, and a rigid knob.

```sh
python pixelwright/scripts/pixel_sprite.py build --spec pixelwright/examples/sprite-walk/spec.json --out-dir runs/walk-build-v1
python pixelwright/scripts/pixel_sprite.py check --spec pixelwright/examples/sprite-walk/spec.json --sheet runs/walk-build-v1/rendered.png --profile pixelwright/examples/sprite-walk/profile.json --out-dir runs/walk-check-v1
```

Each check writes `sprite_report.json`, the sheet audit under `sheet/`, `layout_overlay.png`, `rig_overlay.png`, and per animation a GIF preview plus a `.rig.gif` with the skeleton and part colors (`--preview-scale` sets their size). Exit codes are `0` for all PASS, `2` for FAIL/REVIEW, and `1` for invalid specs or errors. In an injected-error test, 9 of 11 realistic mistakes were detected; a limb drawn one cell thicker and a two-cell slide of a mostly covered thin handle stayed within the default tolerances. See the [sprite reference](pixelwright/references/sprites.md) and the [v0.6.0 validation record](docs/VALIDATION_v060_ko.md).

## Use as an AI skill

Place the **entire `pixelwright/` folder** in a skill directory, including its scripts, references, and examples.

| Host | Personal installation | Project installation | Explicit invocation |
| --- | --- | --- | --- |
| Codex | `~/.agents/skills/pixelwright/` | `<repo>/.agents/skills/pixelwright/` | `$pixelwright` |
| Claude Code | `~/.claude/skills/pixelwright/` | `<repo>/.claude/skills/pixelwright/` | `/pixelwright` |

Local installation paths and invocation follow the official [OpenAI skill documentation](https://learn.chatgpt.com/docs/build-skills) and [Claude Code skill documentation](https://code.claude.com/docs/en/skills). `~` means your home directory, including on Windows.

For a Claude environment with custom skill upload, build the install ZIP below and upload it through the host's skill interface. Enable code execution and file creation, and check that the Python dependencies are available. Other ChatGPT or API-based hosts need their own supported skill loader and execution environment. Pixelwright includes no provider-specific generation API adapters. See the [platform compatibility guide](docs/COMPATIBILITY_ko.md) and [Claude custom skill documentation](https://support.claude.com/en/articles/12512180-use-skills-in-claude).

Example request, after invoking the skill:

> Create a 24×24 potion item at 8× scale, with at most 10 visible colors and binary transparency. Use Pixelwright to inspect the exported PNG. Show both the clean image and grid overlay, and include the actual PASS/FAIL report.

Without access to the PNG and a successful checker run, the result is **unverified**. Loading the skill or asking a model to make “pixel art” alone cannot establish compliance. Claude account installation and upload have not been tested in this repository's validation run.

## Declare the quality contract

Use a reusable JSON profile to give multiple assets the same technical rules:

```json
{
  "schema_version": 1,
  "name": "24px game items",
  "logical_size": "24x24",
  "scale": 8,
  "max_colors": 10,
  "alpha": "binary",
  "transparent_rgb": "exact"
}
```

Save this as `profile.json`. It requires a 192×192 PNG with an origin at `(0, 0)` and 8×8 cells. The same positive integer scale applies on both axes; strict profiles require scale ≥ 2. Freeze the contract before creation or inspection. The checker does not infer another grid or resize an image to make it pass.

`transparent_rgb: "exact"` also compares hidden RGB values under alpha zero. Choose `"visible"` explicitly only when those hidden differences should be normalized. Optional `allowed_palette` constrains full RGBA values. Uniform translucent cells can be allowed with `alpha: "any"`. Adjacent same-color dots may form a large irregular shape; the square rule applies to individual grid cells.

See the [quality contract](pixelwright/references/quality-contract.md) for all fields, accepted PNG formats, output artifacts, and exit codes. See [creation guidance](pixelwright/references/creation.md) for the logical matrix format.

## Inspect, batch, and repair

Inspect one image or audit several under the same profile:

```sh
python pixelwright/scripts/pixelwright.py inspect input.png --profile profile.json --out-dir runs/audit-v1
python pixelwright/scripts/pixelwright.py batch item-a.png item-b.png --profile profile.json --out-dir runs/batch-v1
```

Profile commands exit with `0` for all PASS, `2` for FAIL/REVIEW, and `1` for input or execution errors. Use this interface for CI acceptance. Inspect the JSON status and exact violation counts alongside the visual preview.

Explicit repair projects observed colors onto the declared grid and creates a new, potentially lossy candidate:

```sh
python pixelwright/scripts/pixel_qa.py fix input.png --logical-size 24x24 --render-size 192x192 --out-dir runs/repair-v1
python pixelwright/scripts/pixelwright.py inspect runs/repair-v1/fixed_upscaled.png --profile profile.json --out-dir runs/repair-audit-v1
```

Review `comparison.png`, `fix_review.json`, and both reports before adopting a repair. Geometry must already match the declared grid. Repair keeps the source file and can remove detail; re-audit the corrected file against the original profile.

## Validation and packaging

```sh
python -m unittest discover -s pixelwright/tests -v
python tools/package_skill.py --out-dir dist
python tools/package_skill.py --verify dist/pixelwright-v0.6.2.zip
python tools/verify_release.py --archive dist/pixelwright-v0.6.2.zip --out-dir runs/release-check-v1
```

Packaging creates an installation ZIP with one top-level `pixelwright/` folder and a development-kit ZIP with tests and documentation. The package verifier checks the ZIP layout and SHA-256 manifest; the release verifier extracts and exercises the installation package. Build artifacts are generated locally in `dist/`.

Run `verify_release.py` only on trusted packages built from reviewed Pixelwright source: it executes their Python scripts. A matching manifest proves internal integrity, not the identity of the publisher.

The [v0.6.2 validation record](docs/VALIDATION_v062_ko.md) covers GIF holds longer than 655.35 seconds, preserved frame boundaries and saved timing metadata. The [v0.6.1 record](docs/VALIDATION_v061_ko.md) covers sprite rollback ownership, attachment and occlusion regressions, explicit GIF timing, finite 3D rig contracts, and anchor registration. The [v0.6.0 record](docs/VALIDATION_v060_ko.md) covers the original sprite sheets, animations, part rigs and installed examples. Earlier records cover [square-grid previews](docs/VALIDATION_v051_ko.md), [palettes](docs/VALIDATION_v050_ko.md) and [layer composition](docs/VALIDATION_v040_ko.md).

## Scope, license, and security

Version 0.6.2 supports **static PNG characters, items, UI icons, reusable palettes, optional layered scenes, and sprite sheets with declared animation rigs**. Technical PASS covers the inspected file's grid, exact per-cell color, and declared profile constraints. Palette remapping also checks the selected target colors; extraction and ramp generation do not certify artwork. Layer composition requires per-layer and final acceptance. It does not judge artistic quality or guarantee how a downstream app scales the image. Review silhouette, readability, palette, and material detail separately. Rig checks verify that declared parts keep their dots consistent with the declared skeleton; they do not infer anatomy or judge timing, weight, or appeal. Animated PNG input remains unsupported.

Pixelwright is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Read [SECURITY.md](SECURITY.md) for supported versions and vulnerability reporting. The repository includes [CI](.github/workflows/ci.yml), [CodeQL](.github/workflows/codeql.yml), and [dependency update configuration](.github/dependabot.yml). These checks support maintenance; they are not a claim of a completed independent security audit.

Start with [`pixelwright/SKILL.md`](pixelwright/SKILL.md) for the AI workflow, [the compatibility guide](docs/COMPATIBILITY_ko.md) for platform conditions, and [the design notes](docs/DESIGN_ko.md) for implementation rationale.
