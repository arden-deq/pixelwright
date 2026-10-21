# Skeleton-first knight animation kit

The skeleton comes first; each frame is then drawn by an image model on that skeleton. [`tools/knight_pose_guides.py`](../../../../tools/knight_pose_guides.py) writes this kit. The joints are measured from the README knight so the new sprite keeps its 128×192-cell size and proportions, but no pixels of that image are used: the knight is drawn new.

| Mace swing (downward smash) | Shield block | Walk |
| --- | --- | --- |
| ![Swing skeleton](swing-skeleton.gif) | ![Block skeleton](block-skeleton.gif) | ![Walk skeleton](walk-skeleton.gif) |
| 9 frames | 6 frames | 8 frames |

Every leg is solved with two-bone IK and never stretches: when the body rises past a straight leg, the foot lifts instead. Each bone keeps its length within 0.02 cells in every frame.

## Contents

| File | Purpose |
| --- | --- |
| `<animation>/pose_NN.png` | OpenPose-style guide for frame NN on the 1024×1536 generation canvas; the dark red outline marks the shield and the gray line with a circle marks the mace |
| `prompts.json` | Per frame, in generation order: the input images, the prompt and the output path |
| `poses.json` | Joint coordinates per frame in logical cells (frame 192×288; the 128×192-cell figure stands at 48,56), frame durations and the anchor frame |

## Generation order

1. **Anchor:** `swing/00` (ready stance) is drawn from its guide and a text design alone: a knight in full plate with a closed great helm, brass trim, leather straps, a dark red kite shield and a flanged mace, as detailed pixel art with at most 32 colors.
2. **Every other frame** gets the generated anchor first and its own guide second, and is asked to redraw the same knight in that pose. All frames share one image context, so armor, colors and pixel size stay the same while each pose is drawn fresh rather than rotated.

## Generate

[`tools/knight_generate_frames.py`](../../../../tools/knight_generate_frames.py) sends each entry to the OpenAI Images API edits endpoint, the API behind Codex's imagegen, at 1024×1536 with a transparent background, and saves it at the listed `output` path, for example `generated/swing/frame_06.png`. It generates the anchor first when a requested frame needs it, keeps frames that already exist (delete one to redraw it alone), and records model, settings and SHA-256 of every input, prompt and output in `generated/manifest.json`. It reads `OPENAI_API_KEY`.

```sh
python tools/knight_generate_frames.py --animation swing --dry-run   # list the requests
python tools/knight_generate_frames.py --animation swing             # anchor first, then frames 01-08
```

`--model`, `--quality` and `--input-fidelity` select the image model and its settings. In Codex, the same entries can be run with imagegen by hand: give it the listed images in order and the prompt, and save the result at the listed path without cropping or rescaling.

## Project and check

A generated frame is an unverified candidate. [`tools/knight_from_generated.py`](../../../../tools/knight_from_generated.py) turns the frames into a sheet and runs `pixel_sprite.py check`:

```sh
python tools/knight_from_generated.py --animation swing --out-dir runs/knight-generated-v1
```

Exit codes are `0` only when every selected animation passes, `2` if any animation fails or needs review, and `1` for invalid inputs or execution errors. Reports and candidate sheets remain available for diagnosis after a failed check. Parent links are resolved independently of drawing order, so the mace, arms and legs are checked for attachment to their declared parents.

- The palette comes from the anchor alone: its cells are reduced to 31 colors plus transparent, the size of the README knight's palette, and every frame is held to it.
- Each frame is projected onto the 192×288 grid: a cell takes its most common palette color, or turns transparent when background (transparency or flat #FF00FF) covers most of it. Isolated specks under 4 cells are dropped.
- Every dot is given to a part, back to front: mace, upper arm, forearm, each leg's shin, foot and thigh, torso, shield upper arm, head and shield. A part owns the dots inside a capsule around its bone, front parts first; the shield owns the kite around the shield hand. Each part is compared against the anchor frame unless the anchor shows less than half of it.
- A frame whose dots do not follow its skeleton fails and is regenerated; tolerances stay as declared. The mace alone allows 1.5 cells of drift, because projecting a freshly drawn 3-cell shaft onto the grid moves its dots up to 1.21 cells even when it lies exactly on its bone.

The pipeline was checked with stand-in frames: plain shapes drawn exactly on each skeleton at canvas size pass all three animations with no failures, and the same swing with the mace drawn 40 cells off its bone in one frame fails that frame with `PART_OFF_SKELETON`, `PART_DRIFT` and `JOINT_OFF_PART`. `GeneratedKnightPipelineTests` in [`test_sprites.py`](../../../../pixelwright/tests/test_sprites.py) repeats both cases. No generated frames are committed yet.

Regenerate this kit after changing a pose:

```sh
python tools/knight_pose_guides.py
```
