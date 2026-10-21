#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bind this independently authored fixture's known cells to its exact run.

This is a tutorial/test observer, not an image recognizer. It refuses changed
artwork or specifications; never use these masks for a generated replacement.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import pixel_sequence as sequence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    example = Path(__file__).resolve().parent
    try:
        run, _, manifest = sequence.load_run(args.run)
        for actual, expected in ((run / "source-spec.json", example / "spec.json"),
                                 (run / "reference-source.png", example / "reference.png"),
                                 (run / "raw/orbit.png", example / "sheet.png")):
            if sequence.project.sha256(actual) != sequence.project.sha256(expected):
                raise ValueError("This observer only accepts the unchanged authored example")
        data = sequence.read_json(example / "observed-pixels.json")
        result = sequence.observation_template(run)
        result["method"] = "Known independently authored RGBA fixture cells, verified against exact source files; no guide coordinates"
        result["reference"] = data["reference"]
        result["states"]["orbit"]["frames"] = data["frames"]
        result["states"]["orbit"]["review"] = {
            "status": "accepted", "reviewer": "Authored fixture specification; not human approval",
            "observations": ["Fixed blue capsule and marked gold fin preserve their authored cells through the floating orbit."]}
        sequence.sprite._write_new(args.out, sequence.json_bytes(result))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f"Fixture observation error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
