#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate the knight frames listed in a pose kit's prompts.json.

Entries with references use the OpenAI Images API edits endpoint, preserving
input order. Prompt-only entries use the generations endpoint. The result is
saved at the entry's output path inside the kit. An input that is another
entry's output (the anchor frame) is generated first. Existing frames are kept
unless --force is given, so a failed frame can be deleted and regenerated alone.
generated/manifest.json records the model, settings and SHA-256 of every input,
prompt and output. Needs OPENAI_API_KEY; OPENAI_BASE_URL overrides the endpoint.
Exit codes: 0 success, 1 error.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
POSES = ROOT / "docs" / "examples" / "knight-animation" / "poses"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def multipart(fields, files):
    boundary = uuid.uuid4().hex
    body = bytearray()
    for name, value in fields:
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    for name, filename, data in files:
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                 "Content-Type: image/png\r\n\r\n").encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def request_image(entry, kit: Path, args, key: str):
    inputs = [(name, (kit / name).read_bytes()) for name in entry["images"]]
    fields = {"model": args.model, "prompt": entry["prompt"], "size": entry.get("size", args.size),
              "quality": args.quality, "background": entry.get("background", "transparent"),
              "output_format": "png", "n": 1}
    if inputs:
        if args.input_fidelity != "none":
            fields["input_fidelity"] = args.input_fidelity
        files = [("image[]", f"{index}-{Path(name).name}", data) for index, (name, data) in enumerate(inputs)]
        body, content_type = multipart(fields.items(), files)
        endpoint = "/images/edits"
    else:
        # input_fidelity belongs to image edits, never prompt-only generation.
        body, content_type = json.dumps(fields).encode(), "application/json"
        endpoint = "/images/generations"
    request = urllib.request.Request(args.base_url.rstrip("/") + endpoint, data=body, method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": content_type})
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read(4096).decode("utf-8", "replace")
        raise RuntimeError(f"Images API returned HTTP {error.code}: {detail}") from None
    image = base64.b64decode(payload["data"][0]["b64_json"])
    with Image.open(io.BytesIO(image)) as candidate:
        candidate.verify()
    return image, {name: sha256(data) for name, data in inputs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--poses", type=Path, default=POSES, help="Pose kit directory with prompts.json")
    parser.add_argument("--animation", action="append", help="Limit to these animations (default: all)")
    parser.add_argument("--model", default="gpt-image-1")
    parser.add_argument("--quality", default="high", choices=["low", "medium", "high", "auto"])
    parser.add_argument("--input-fidelity", default="high", choices=["high", "low", "none"],
                        help="'none' leaves the field out for models without it")
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--force", action="store_true", help="Regenerate frames that already exist")
    parser.add_argument("--dry-run", action="store_true", help="List what would be generated and stop")
    args = parser.parse_args()
    kit = args.poses
    prompts = json.loads((kit / "prompts.json").read_text(encoding="utf-8"))
    canvas = json.loads((kit / "poses.json").read_text(encoding="utf-8"))["canvas"]
    args.size = f"{canvas[0]}x{canvas[1]}"
    producer = {entry["output"]: key for key, entry in prompts.items()}
    wanted = [key for key in prompts if not args.animation or key.split("/")[0] in args.animation]
    order, seen = [], set()

    def visit(key):
        if key in seen:
            return
        seen.add(key)
        for name in prompts[key]["images"]:
            if name in producer and (args.force or not (kit / name).is_file()):
                visit(producer[name])
        order.append(key)

    for key in wanted:
        visit(key)
    todo = [key for key in order if args.force or not (kit / prompts[key]["output"]).is_file()]
    if args.dry_run:
        for key in todo:
            print(json.dumps({"frame": key, "images": prompts[key]["images"], "output": prompts[key]["output"]}))
        return 0
    key_value = os.environ.get("OPENAI_API_KEY")
    if todo and not key_value:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1
    manifest_path = kit / "generated" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    for key in todo:
        entry = prompts[key]
        try:
            image, inputs = request_image(entry, kit, args, key_value)
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            print(f"{key}: {error}", file=sys.stderr)
            return 1
        out = kit / entry["output"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(image)
        with Image.open(out) as candidate:
            size = candidate.size
        manifest[key] = {"model": args.model, "size": entry.get("size", args.size), "quality": args.quality,
                         "background": entry.get("background", "transparent"),
                         "input_fidelity": args.input_fidelity if inputs and args.input_fidelity != "none" else None,
                         "endpoint": "/images/edits" if inputs else "/images/generations", "inputs": inputs,
                         "prompt_sha256": sha256(entry["prompt"].encode()), "output": entry["output"],
                         "output_sha256": sha256(image), "output_size": list(size)}
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8", newline="\n")
        print(json.dumps({"frame": key, "output": entry["output"], "size": list(size)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
