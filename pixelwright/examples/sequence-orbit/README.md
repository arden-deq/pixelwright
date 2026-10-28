# A floating capsule, without a skeleton

This is a deterministic tutorial/test fixture authored directly as RGBA cells,
not generated production artwork. A blue capsule stays still while a marked
gold fin follows a small closed orbit. The fin is an invented magnetic part;
there is no human anatomy, 3D model, mesh, bone or joint hierarchy.

From the installed `pixelwright/` directory:

```sh
python scripts/pixel_sequence.py prepare --spec examples/sequence-orbit/spec.json --reference examples/sequence-orbit/reference.png --out-dir orbit-run
python scripts/pixel_sequence.py import --run orbit-run --state orbit --image examples/sequence-orbit/sheet.png --producer authored-fixture
python examples/sequence-orbit/observe_fixture.py --run orbit-run --out orbit-observed.json
python scripts/pixel_sequence.py check --run orbit-run --observations orbit-observed.json --out-dir orbit-audit
```

Expected: technical PASS, overall PASS for the authored fixture, six 100ms
frames, 24x24 logical frames, 3 columns, 4x enlarged cells and three shared
colors. This is fixture acceptance, not a user's approval of generated art.

`observed-pixels.json` stores independently authored visible regions and
endpoints. `observe_fixture.py` first verifies the exact packaged spec,
reference and raw sheet before binding those known observations to the run's
hashes. Changed artwork is refused. Do not reuse this observer for your object;
use `pixel_sequence.py observations` and inspect the actual exported cells.

Running `check` without observations must yield REVIEW despite pixel PASS.
Replacing all six poses with the first must fail required motion. The installed
release verifier exercises both cases and confirms regeneration history and
stale-observation rejection. See [the sequence reference](../../references/sequences.md).
