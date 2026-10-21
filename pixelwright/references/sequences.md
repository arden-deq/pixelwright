# Consistent 2D sequences without a skeleton

Use `scripts/pixel_sequence.py` for characters, machines, imaginary creatures or
other objects whose moving parts do not have a useful anatomical skeleton.
Python 3.12+, Pillow and NumPy are sufficient. Blender is not required.

The selected 2D design defines appearance. Name its visible parts and features
in the object's own terms, describe each pose, and freeze common dimensions,
colors, timing and tolerances **before** generating state sheets. Observations
come from the actual artwork, independently of those pose descriptions.

## Run the bundled tutorial

From the installed skill directory, use fresh output paths:

```sh
python scripts/pixel_sequence.py prepare --spec examples/sequence-orbit/spec.json --reference examples/sequence-orbit/reference.png --out-dir orbit-run
python scripts/pixel_sequence.py import --run orbit-run --state orbit --image examples/sequence-orbit/sheet.png --producer authored-tutorial-fixture
python examples/sequence-orbit/observe_fixture.py --run orbit-run --out orbit-observed.json
python scripts/pixel_sequence.py check --run orbit-run --observations orbit-observed.json --out-dir orbit-audit
```

This small blue capsule with a floating gold fin is independently authored test
art, not an image-generation result. Its observer accepts only the unchanged
bundled spec, reference and sheet. It must refuse regenerated artwork.

## Generate from your selected design

Create a spec using the tutorial as a starting point, then `prepare` with your
selected PNG. The run freezes `contract.json`, the untouched reference,
`reference-native.png`, original spec, palette and state prompts. Their SHA-256
values are checked before import, generation and audit. Changing the design or
tolerances requires a **new run**.

If a host image tool is available, give it `reference-native.png` plus the exact
`prompts/STATE.txt`, save its PNG and record its producer:

```sh
python scripts/pixel_sequence.py import --run creature-run --state hover --image generated-sheet.png --producer "host image tool; selected design only"
```

The optional HTTP adapter sends the same selected design and prompt to an
Images-compatible `/images/edits` endpoint. It requires an explicit model and
`OPENAI_API_KEY` from the environment:

```sh
python scripts/pixel_sequence.py generate --run creature-run --state hover --model YOUR_SUPPORTED_IMAGE_MODEL --size auto --quality high
```

`--base-url` (or `OPENAI_BASE_URL`) selects an HTTPS provider. `--background`
is optional and omitted by default; set it only if the chosen model supports
that parameter. The prompt still requests a transparent PNG. Provider/model
capabilities and supported canvas sizes must be checked independently. An
opaque backdrop or incorrect layout is a failed candidate, not something the
tool removes or fits automatically. The adapter does not discover models.
HTTP behavior has mocked request/response tests; the included real-generation
example used a host image tool, not this adapter's paid endpoint.

`--replace` archives the exact previous PNG and its generation record under
`history/`. It does not reuse old observations. Network errors preserve the
current raw image and manifest. Keys and provider error bodies are not written
to reports. Endpoint redirects are refused with credentials.

## Contract fields

The complete executable example is `examples/sequence-orbit/spec.json`.
Part, landmark, measurement, ratio and state identifiers use 1–64 ASCII letters,
digits, underscores or hyphens, starting with a letter/digit. Their descriptions
can use the user's own language; identifiers do not imply an anatomical type.

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `name`, `description` | Selected object's identity and intended appearance |
| `frame_size` | Shared logical cell canvas, e.g. `64x64` |
| `scale` | Integer export enlargement, 2–32; same on both axes |
| `max_colors` | Shared visible RGBA color budget, 2–256 |
| `derivation` | `mode: strict` or `project`, optional `alpha_threshold` (default 128) |
| `limits` | `edge_margin`, visible `area_ratio: [min,max]`, `color_distance`, `max_bad_color_fraction` |
| `parts` | Arbitrary identifiers, descriptions and frozen appearance/measurement tolerances |
| `landmarks` | Named visible 2D features; description string or `{description, part}` binding the feature to a part |
| `ratios` | Optional named ratios of two `[part, measurement]` lengths and their relative tolerance |
| `states` | Named state sheets, poses, playback and motion rules |

Each part can define `area_tolerance` (default .2), `min_shape_match` (.65),
`min_color_overlap` (.8), `min_design_match` (.65), and `measurements`, a mapping
from meaningful length names to relative tolerances. Declare measurements that
remain comparable in this view; foreshortened or hidden lengths need review.

Each state requires `intent`, 2–128 textual `poses`, `columns`, `loop`,
`durations_ms` per frame, and `motion` explicitly covering **every** landmark:

```json
"motion": {
  "hub": {"min_travel": 0, "max_speed": 30},
  "vane_tip": {
    "relative_to": "hub", "min_travel": 4,
    "max_speed": 70, "max_acceleration": 1200
  }
}
```

Travel is maximum pairwise displacement in logical cells. Speeds use cells per
second and acceleration cells per second squared, with declared frame times.
`relative_to` subtracts another **observed** feature before these checks, so
moving a whole frozen object cannot masquerade as articulation. This is a 2D
displacement comparison, not a generated skeleton or automatic joint inference.
Without it, motion is measured in frame coordinates. Looping states check the
last-to-first transition; one-shot states omit it.

Optional state rules:

- `attachments: [{a, b, max_distance}]`: proximity of actual connection features.
- `distances: [{a, b, minimum, maximum}]`: preserved span or allowed extension.
- `root_offsets: [[x,y], ...]`: cumulative per-frame displacement added to screen
  observations for contact checks; defaults to zero, with x right and y down.
- `contacts: [{landmark, frames, max_drift, ground_y?, max_ground_error?}]`:
  pairwise drift of contact points in the restored movement coordinates. Supply
  both ground fields together to check a declared ground height.

For in-place walking, supply the cumulative travel that restores the intended
movement before checking planted-foot drift. Contract values express intended
motion; they are not inferred from a failing generated result. Do not relax
them after generation to obtain a PASS.

## Strict source versus projected derivative

`strict` requires one common integer raw cell scale, uniform RGBA within each
cell, binary alpha and exact transparent RGBA. A native 1x PNG may be authored
cells, but cannot demonstrate enlarged within-cell fidelity; metadata discloses
this. The final enlarged PNG is audited separately at `scale >= 2`.

`project` preserves the raw PNG, requires the exact declared whole-sheet aspect
ratio, and performs one fixed nearest-neighbor whole-canvas sampling to the
declared logical size. It then thresholds alpha and maps to the selected
reference's frozen palette. A noninteger input scale is allowed as a derivative
source, never certified as a valid raw grid. There is no per-frame cropping,
zoom, recentering, stretching or fitting. Pre-remap color distances are also
checked on the sampled logical pixels, so quantization cannot hide a gross
source-color change. Unused slots must stay transparent.

## Observe the actual artwork

```sh
python scripts/pixel_sequence.py observations --run creature-run --out creature-observed.json
python scripts/pixel_sequence.py check --run creature-run --out-dir creature-unobserved
```

The template contains null observations and `not_reviewed`, not expected poses.
The first check produces native frames and `*.coordinates.png` aids. Fill the
template by inspecting those actual cells, using manual annotation or an
independent observer. Record the method and its uncertainty. Never copy a pose
guide, assume parts stayed constant, or bind old masks to a new image hash.

Each reference/frame observation has `parts` and `landmarks`:

```json
{
  "parts": {
    "vane": {
      "visibility": "visible",
      "mask": [[10, 15, 18], [11, 15, 18], [12, 15, 18]],
      "measurements": {"span": [[15, 10], [17, 10]]}
    }
  },
  "landmarks": {"vane_tip": [17, 11]}
}
```

Mask runs are `[y, x_start, x_end_exclusive]` in native cells. Observed masks
must not overlap or cover transparent cells. When all parts are visible and
observed, they must cover every visible cell. Measurement endpoints must be
distinct visible cells of their part. A part-bound feature must lie on that
part. Coordinates use `(0,0)` at the top left, integer cell centers.

Use `null` for unobserved data, or `{visibility: "occluded", reason: "..."}`
for a part that cannot be measured. Missing/occluded data yields REVIEW; it is
not interpolated or silently accepted. Contract, reference and raw PNG hashes
bind the observations to their exact inputs; stale observations are rejected.

For each state, also record `review: {status, reviewer, observations}`. Status
is `accepted`, `changes_needed` or `not_reviewed`; a reviewed entry needs an
identified reviewer and substantive notes. Tool/assistant review must identify
itself and cannot claim user approval. Numeric PASS with no art review remains
REVIEW. Reports always disclose that human approval has not been established.

## Audit results and limits

```sh
python scripts/pixel_sequence.py check --run creature-run --observations creature-observed.json --out-dir creature-audit --preview-scale 4
```

The checker compares observed parts against the selected reference: visible
area, color histogram overlap, shape IoU and colored-cell IoU under translation
and 5-degree rotation search, endpoint lengths and cross-part ratios. It never
size-fits parts to make them match. It then checks required travel, timed
transitions, optional acceleration, attachments, feature spans and contacts.

`report.json` separates overall status, technical status, pixel status, art
review, per-frame metrics and actionable findings. `redraw-requests.json`
includes the frozen prompt and failed findings; regenerate the affected state
with the same reference/contract and observe it again. Each state also exports
`native.png`, `rendered.png`, the strict pixel audit and actual grid overlay,
GIF with timing readback, part/feature overlay and coordinate previews.
Exit codes: `0` PASS/success, `2` FAIL or REVIEW, `1` invalid input/error.

These checks do not identify parts automatically or prove semantic identity,
correct anatomy, weight or naturalness. 2D visible area can change through
occlusion; flexible surfaces, lighting and foreshortening affect comparisons.
Record those limits and review contour quality, clusters, timing and intended
action separately. This workflow makes failures and missing evidence visible;
it does not guarantee a generative model will produce a usable sheet.
