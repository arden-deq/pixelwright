# Sprite sheets, animation and part rigs

Read this when an asset has several frames: a sprite sheet or atlas, an animation cycle, or a character or object whose parts move between frames.

## Freeze the sheet contract

Agree on the frame size in logical cells, the integer scale, the palette, the grid of frame slots, and the animations before drawing. Frames are equal rectangles numbered row-major from the top-left slot. The sheet's logical size follows from the layout:

```text
width  = 2 × margin + columns × frame_width  + (columns − 1) × spacing
height = 2 × margin + rows    × frame_height + (rows − 1)    × spacing
```

Margins, spacing between frames and unused slots must stay fully transparent (alpha 0); the strict profile still decides the exact RGBA values, so include `#00000000` in `allowed_palette` when the sheet has any gutter. Declare the sheet in an ordinary profile whose `logical_size` equals this computed size; the checker refuses a profile that describes a different sheet. An opaque profile is only possible with no margin, no spacing and every slot used.

## Sprite spec

One UTF-8 JSON file describes the layout, the animations and, optionally, the rig. The same file can carry each frame's color rows for the builder.

```json
{
  "schema_version": 1,
  "name": "Lever",
  "frame_size": "18x16",
  "layout": {"columns": 5, "rows": 1, "spacing": 1},
  "edge_margin": 1,
  "scale": 6,
  "palette": {".": "transparent", "o": "#1E1A2B", "m": "#C8CDD6"},
  "animations": {"switch_on": {"frames": [0, 1, 2, 3, 4], "loop": false, "frame_ms": 90}},
  "rig": {"joints": {"pivot": {"fixed": true}, "grip": {}}, "parts": {"...": {}}},
  "frames": [{"rows": ["..."], "parts": ["..."], "joints": {"pivot": [8, 10], "grip": [3, 5]}}]
}
```

| Field | Rule |
| --- | --- |
| `schema_version` | Required integer `1`; unknown fields fail validation |
| `frame_size` | Required `WIDTHxHEIGHT` of one frame in logical cells |
| `layout` | Required `columns` and `rows` (1..4096); optional `margin` and `spacing` in cells, default 0; at most 1,024 slots and 4,096 cells per sheet side |
| `frame_count` | Optional number of used slots, default `columns × rows`; later slots must stay empty |
| `edge_margin` | Optional cells that must stay transparent inside every frame edge, catching clipped or bleeding art |
| `scale` | Integer 2..4096; required by `build`, and must equal the profile scale when present |
| `palette` / `palette_file` | Same as [creation.md](creation.md); required only with frame `rows` |
| `animations` | Optional object of ids; each has `frames` (frame indices, repeats allowed), `loop` (default `true`) and either `frame_ms` (default 100) or `durations_ms` per entry |
| `frames` | One entry per used slot with `rows` (color tokens, for `build`), and with a rig: `parts`, `joints`, optional `hidden` and `z` |

`build` needs `scale`, a palette and `rows` in every frame. `check` needs only the layout; when the spec also has `rows`, frames that differ from them are reported because the part maps were probably written for the older pixels.

## Declare the rig

The checker never guesses anatomy. The author declares a virtual skeleton, and the checker draws it over every frame and compares each part's dots with the part's reference frame.

- **Joints** (`rig.joints`): named points. Each frame gives every joint as `[x, y]` in frame-local logical cells; whole numbers are cell centers and `.5` lies between cells. A joint with `"fixed": true` must keep its position in every frame.
- **Parts** (`rig.parts`): body segments or object pieces, **listed back to front**. Each has a unique one-character `token` other than `.` and a `motion`.
- **Part maps** (`frames[i].parts`): one string per row, one token per cell, `.` for no part. Every visible cell must belong to a part unless `rig.coverage` is `"partial"`; part tokens on transparent cells always fail.

| Motion | Use for | Rule |
| --- | --- | --- |
| `fixed` | A body that must not move: a lever base, a chest box, a background prop | Exactly the same cells and colors in every frame |
| `rigid` | A piece that only translates: a bobbing head, a lever knob, a drawer | Needs `pivot`; the dots are an exact copy of the reference moved by the pivot's whole-cell offset. Optional `axis: [dx, dy]` limits the direction, for example a drawer that only slides sideways |
| `bone` | A limb or hinged piece that rotates: upper arm, shin, lid, lever handle | Needs `bone: [start, end]`; reference dots are carried along the bone, keeping their distance across it and stretching along it |
| `free` | Cloth, hair, effects with no stable shape | Presence, size and colors only |

Optional part fields: `parent` (the part must touch its parent in every frame), `z` (drawing depth; defaults to the part's position in the list), `reference_frame` (the frame where the part is best visible; default `rig.reference_frame`, itself default 0), and tolerances. `rig.defaults` sets tolerances for all parts; a part field overrides it.

| Tolerance | Default | Meaning |
| --- | --- | --- |
| `min_shape_match` | 0.8 | Share of bone-part dots that land within one cell of where the moved reference puts them |
| `max_drift` | 1.0 | Maximum shift, in cells along or across the bone, of the comparable dots' center from the moved reference |
| `length_tolerance` | 1.0 | Maximum bone length change in cells |
| `area_tolerance` | 0.25 | Allowed relative change in a part's dot count, after allowing for covered dots and bone stretch |

`rig.max_joint_step` optionally limits how far any joint may move between consecutive frames of an animation, including the wrap from the last frame to the first in a loop.

### Overlap and hidden parts

A part's dot may be missing only where a part drawn in front of it (higher `z`) covers that cell. A forearm cannot vanish into a torso that is drawn behind it. Dots that appear where the reference was covered show more of the part and are not treated as errors. When drawing order changes in one frame, for example a turn, give that frame `"z": {"arm_back": 9}`.

List a part in a frame's `hidden` only when it has no visible cells there. Its expected dots must then be covered by parts drawn in front; a part hidden over empty space fails. The part map of that frame must not show the part.

## Build and check

Run from the skill directory, or resolve these script paths from it:

```sh
python scripts/pixel_sprite.py list --spec examples/sprite-walk/spec.json
python scripts/pixel_sprite.py build --spec examples/sprite-walk/spec.json --out-dir walk-build-v1
python scripts/pixel_sprite.py check --spec examples/sprite-walk/spec.json --sheet walk-build-v1/rendered.png --profile examples/sprite-walk/profile.json --out-dir walk-check-v1 --preview-scale 4
```

`list` validates the spec without reading a PNG. `build` writes `native.png`, `rendered.png` and `build.json`; it does not accept the art. `check` first runs the strict profile audit on the whole sheet. Frame, animation and rig checks run only when every sheet cell has one exact color; palette or alpha failures still allow them as diagnostics but keep the result failed.

| Output | Meaning |
| --- | --- |
| `sprite_report.json` | Overall status, input hashes, layout, per-frame bounds, animations, every joint and part per frame, and all issues with frame and part context |
| `sheet/report.json`, `sheet/grid_overlay.png` | Strict audit of the whole sheet |
| `layout_overlay.png` | Frame slots outlined; failing frames in red, review frames in amber, gutter dots filled red |
| `rig_overlay.png` | Each frame twice: art under the declared skeleton, then the part map. Thin gray links join each bone chain to its parent's nearest joint. Red outlines mark failing dots; white outlines mark where the moved reference expects a failing part |
| `animations/<id>.gif` | Playback preview on a flat background; the sheet remains the audited artwork |
| `animations/<id>-rig.gif` | With a rig: the same frames with the art under its skeleton beside every dot colored by part, plus a legend |

`--preview-scale` sets the whole-number enlargement of both GIFs (1..16); by default they are about 512 px tall. Exit codes: `0` when everything passes, `2` for any fail or review, `1` for invalid specs, inputs or execution errors. Use a new or empty output directory for every run; inputs are never modified.

## Issue codes

| Code | Severity | Meaning |
| --- | --- | --- |
| `GUTTER_NOT_EMPTY`, `UNUSED_SLOT_NOT_EMPTY` | fail | Visible dots outside the declared frames |
| `EDGE_MARGIN_VIOLATION` | fail | Content enters the declared edge margin |
| `EMPTY_FRAME` | review | A used frame has no visible dots |
| `SHEET_DIFFERS_FROM_SPEC_ROWS` | review | The PNG no longer matches the spec's color rows |
| `PART_MAP_ON_TRANSPARENT`, `UNASSIGNED_VISIBLE_CELLS` | fail | The part map does not describe the dots |
| `PART_MISSING` | fail | A part has no dots and is not listed as hidden |
| `FIXED_PART_CHANGED`, `RIGID_PART_CHANGED` | fail | Exact dots differ from the reference copy |
| `PART_JOINT_MISMATCH` | fail | A rigid part moved differently from its pivot, or the pivot moved by a fraction of a cell |
| `RIGID_AXIS_VIOLATION` | fail | A rigid part left its declared sliding axis |
| `PART_OFF_SKELETON` | fail | Too few bone-part dots land where the skeleton carries them |
| `PART_DRIFT` | fail | A bone part's dots slid along or across its bone |
| `BONE_LENGTH_CHANGED`, `BONE_DEGENERATE` | fail | The skeleton itself stretched or collapsed |
| `PART_AREA_CHANGED` | fail | A part grew or shrank beyond its tolerance |
| `PART_DETACHED` | fail | A part does not touch its parent, even through parts drawn in front of both |
| `JOINT_OFF_PART` | fail | A joint is not drawn on its part's dots or under a part in front |
| `OCCLUSION_WITHOUT_OCCLUDER` | fail | A hidden part's expected dots lie on empty space |
| `FIXED_JOINT_MOVED`, `JOINT_STEP_EXCEEDED` | fail | A fixed joint moved, or a joint jumped too far between frames |
| `PART_COLOR_ADDED` | review | A part shows colors absent from its reference |
| `PART_FRAGMENTED` | review | A part splits into more pieces than in its reference |
| `BASELINE_SHIFT`, `DUPLICATE_ADJACENT_FRAMES`, `UNUSED_FRAMES` | info | Possible jitter, accidental holds or forgotten frames |

## Author and review

When creating an animation, write each frame's color rows, part map and joints together; the map is easiest to keep correct while the dots are fresh. Choose a reference frame where each part is fully visible. Keep tightly linked pieces such as a hand and its weapon in one part, or give the weapon a pivot at the hand.

Fix a failure by redrawing the reported part or correcting a mistaken joint. Do not loosen a tolerance, mark a part hidden, reorder `z` or switch coverage to `partial` just to pass; those change the contract and need the user's agreement. `tools/generate_sprite_examples.py` in the development kit rasterizes the bundled examples from their skeletons, and `tools/generate_knight_animations.py` rigs an existing painting by cutting it into parts and turning them with a pixel-art resampler; hand-drawn frames use the same spec format.

The checks are deliberately tolerant to the one-cell steps of rotated pixel art, which sets their limits. A thin diagonal part can shift about 1.4 cells and still match within one cell, so `PART_DRIFT` compares where the dots sit; drift is measured only with at least six comparable dots. A limb drawn one cell thicker can stay within the default area tolerance; lower `area_tolerance` for parts whose thickness must stay exact. Free parts have no shape check. Technical PASS does not judge timing, weight, silhouette or appeal: watch the previews and record art review separately.
