# Pixelwright

![Pixelwright banner with a knight, potion, and shield icon](docs/images/pixelwright-header.png)

Header: 2048×1024 · 4×4 px cells · 32 colors · 131,072 cells PASS · [Audit report](docs/examples/header/report.json) · [Grid preview](docs/examples/header/grid_overlay.png) · [Build records](docs/examples/header/)

[English](README.md) · [한국어](README.ko.md) · Version 0.3.0 · [Apache License 2.0](LICENSE)

**Create static PNG pixel art on a declared grid, then verify every cell.**

Pixelwright is a shared AI skill for GPT-powered hosts and Claude. It helps create and audit characters, items, and UI icons with a consistent dot size, complete square grid cells, and exactly one RGBA color per cell. The same `SKILL.md` and Python tools serve both ecosystems; the host must provide file access and Python execution.

Author a palette and a logical pixel matrix, render at an integer scale, and audit the exported PNG. For existing artwork, declare its intended grid before inspection. By default, deliver both the clean artwork and its actual grid QA preview so users can check the cells themselves.

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
python tools/package_skill.py --verify dist/pixelwright-v0.3.0.zip
python tools/verify_release.py --archive dist/pixelwright-v0.3.0.zip --out-dir runs/release-check-v1
```

Packaging creates an installation ZIP with one top-level `pixelwright/` folder and a development-kit ZIP with tests and documentation. The package verifier checks the ZIP layout and SHA-256 manifest; the release verifier extracts and exercises the installation package. Build artifacts are generated locally in `dist/`.

Run `verify_release.py` only on trusted packages built from reviewed Pixelwright source: it executes their Python scripts. A matching manifest proves internal integrity, not the identity of the publisher.

## Scope, license, and security

Version 0.3.0 supports **static PNG characters, items, and UI icons**. Technical PASS covers the inspected file's grid, exact per-cell color, and declared profile constraints. It does not judge artistic quality or guarantee how a downstream app scales the image. Review silhouette, readability, palette, and material detail separately. Animation and atlas validation are outside this release.

Pixelwright is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Read [SECURITY.md](SECURITY.md) for supported versions and vulnerability reporting. The repository includes [CI](.github/workflows/ci.yml), [CodeQL](.github/workflows/codeql.yml), and [dependency update configuration](.github/dependabot.yml). These checks support maintenance; they are not a claim of a completed independent security audit.

Start with [`pixelwright/SKILL.md`](pixelwright/SKILL.md) for the AI workflow, [the compatibility guide](docs/COMPATIBILITY_ko.md) for platform conditions, and [the design notes](docs/DESIGN_ko.md) for implementation rationale.
