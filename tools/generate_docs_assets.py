#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit the actual knight exports and render their parameter comparison."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/examples/knight"
IMAGES = ROOT / "docs/images"
SCRIPTS = ROOT / "pixelwright/scripts"
VARIANTS = (("4px", 4, (256, 384), 98304), ("8px", 8, (128, 192), 24576))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def font(size, korean=False, bold=False):
    choices = (["C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"] if korean else
               ["C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for path in choices:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    if korean:
        raise RuntimeError("A Korean font is needed to render the Korean figure")
    return ImageFont.load_default(size=size)


def audit_variant(tag, scale, logical, cells, work):
    folder = EXAMPLES / tag
    for name in ("artwork.json", "profile.json"):
        path = folder / name
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    profile = json.loads((folder / "profile.json").read_text(encoding="utf-8"))
    assert profile["logical_size"] == f"{logical[0]}x{logical[1]}" and profile["scale"] == scale
    assert profile["max_colors"] == 31 and profile["alpha"] == "binary"
    command = [sys.executable, str(SCRIPTS / "pixelwright.py"), "inspect", str(folder / "rendered.png"),
               "--profile", str(folder / "profile.json"), "--out-dir", str(work / tag)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{tag} failed its declared contract: {result.stderr} {result.stdout}")
    report = json.loads((work / tag / "report.json").read_text(encoding="utf-8"))
    assert report["metrics"]["uniform_rgba_cells"] == cells
    report["provenance"]["source_path"] = (folder / "rendered.png").relative_to(ROOT).as_posix()
    report["provenance"]["profile_path"] = (folder / "profile.json").relative_to(ROOT).as_posix()
    write_json(folder / "report.json", report)
    shutil.copyfile(work / tag / "violation_mask.png", folder / "violation_mask.png")
    with Image.open(folder / "native.png") as loaded:
        native = np.array(loaded.convert("RGBA"))
    with Image.open(folder / "rendered.png") as loaded:
        rendered = loaded.convert("RGBA")
    actual = np.array(rendered)
    assert (native.shape[1], native.shape[0]) == logical
    assert rendered.size == (1024, 1536)
    assert np.array_equal(actual, np.repeat(np.repeat(native, scale, axis=0), scale, axis=1))
    palette = np.unique(native.reshape(-1, 4), axis=0)
    assert len(palette) == 32 and set(palette[:, 3].tolist()) == {0, 255}
    assert np.all(palette[palette[:, 3] == 0, :3] == 0)
    # A full boundary layer is required here; the stock dense-grid preview samples lines.
    lines = Image.new("RGBA", rendered.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(lines)
    for x in range(0, rendered.width, scale):
        draw.line((x, 0, x, rendered.height-1), fill=(0, 215, 245, 88), width=1)
    for y in range(0, rendered.height, scale):
        draw.line((0, y, rendered.width-1, y), fill=(0, 215, 245, 88), width=1)
    lines.save(folder / "grid_lines.png")
    background = Image.new("RGBA", rendered.size, "#E4E8E1")
    background.alpha_composite(rendered)
    overlay = Image.alpha_composite(background, lines).convert("RGB")
    overlay.save(folder / "grid_overlay.png")
    verification = {
        "status": "pass", "method": "Direct PNG decoding, NumPy native-repeat equality, palette and hash checks, separate from the checker verdict.",
        "source_path": report["provenance"]["source_path"], "native_path": (folder / "native.png").relative_to(ROOT).as_posix(),
        "profile_path": report["provenance"]["profile_path"], "logical_size": list(logical), "rendered_size": [1024, 1536],
        "cell_size": [scale, scale], "uniform_cells": cells, "nonuniform_cells": 0,
        "total_rgba_colors": 32, "visible_rgb_colors": 31, "transparent_entries": 1,
        "exact_native_repeat": True, "alpha_values": [0, 255], "partial_alpha_samples": 0,
        "source_sha256": digest((folder / "rendered.png").read_bytes()),
        "native_sha256": digest((folder / "native.png").read_bytes()),
        "profile_sha256": digest((folder / "profile.json").read_bytes()),
        "decoded_rgba_sha256": digest(actual.tobytes()),
        "grid_preview": {"source_spacing": [scale, scale], "sampled": False,
                         "colors_are_diagnostic": True},
    }
    for field in ("source_sha256", "profile_sha256", "decoded_rgba_sha256"):
        assert verification[field] == report["provenance"][field]
    write_json(folder / "verification.json", verification)
    return {"tag": tag, "scale": scale, "logical": logical, "cells": cells,
            "image": rendered, "overlay": overlay, "palette": palette.tolist(), "verification": verification}


def make_figure(variants, korean=False):
    figure = Image.new("RGB", (2240, 2810), "#101927")
    draw = ImageDraw.Draw(figure)
    def text(x, y, en, ko, size=34, color="#A6BED0", bold=False):
        draw.text((x, y), ko if korean else en, font=font(size, korean, bold), fill=color)
    text(64, 36, "PIXELWRIGHT / CONDITIONS CHANGE, QA HOLDS", "PIXELWRIGHT / 조건을 바꿔도 지킨 QA 규칙", 66, "#E9F0DB", True)
    text(64, 132, "Same knight. Same 32-color palette. Same 1024 x 1536 output. Two tested grids.",
         "같은 기사, 같은 32색 팔레트, 같은 1024 x 1536 출력. 실제로 검사한 두 격자.", 34)
    for index, variant in enumerate(variants):
        x = 64 + index*1088
        scale, logical, count = variant["scale"], variant["logical"], variant["cells"]
        text(x, 202, f"{scale} x {scale} px DOTS", f"도트 {scale} x {scale} px", 44, "#72C7C9", True)
        text(x, 264, f"Native {logical[0]}x{logical[1]}  ->  PNG 1024x1536", f"작화 {logical[0]}x{logical[1]}  ->  PNG 1024x1536", 32)
        plate = Image.new("RGBA", variant["image"].size, "#E4E8E1")
        plate.alpha_composite(variant["image"])
        figure.paste(plate.convert("RGB"), (x, 322))
        text(x, 1878, f"PASS / {count:,} of {count:,} solid RGBA cells", f"PASS / {count:,}개 셀 모두 RGBA 단색", 38, "#A7C57C", True)
        text(x, 1940, "0 nonuniform cells / 0 partial-alpha samples", "불균일 셀 0 / 반투명 샘플 0", 32)
        # Identical physical crop and display zoom in both columns make dot-size comparison honest.
        crop = variant["overlay"].crop((384, 320, 512, 448)).resize((512, 512), Image.Resampling.NEAREST)
        figure.paste(crop, (x, 2020))
        text(x+550, 2030, "GRID CLOSE-UP", "격자 확대", 38, "#72C7C9", True)
        text(x+550, 2104, f"Source cell: {scale} x {scale} px", f"원본 셀: {scale} x {scale} px", 30)
        text(x+550, 2168, "Display zoom: 4x", "표시 확대: 4배", 30)
        text(x+550, 2250, "Every boundary is shown.", "모든 셀 경계를 표시했습니다.", 28)
        text(x+550, 2310, "Cyan = cell boundary", "청록색 = 셀 경계", 28)
        text(x+550, 2394, "Palette: 31 colors + transparent", "팔레트: 31색 + 투명색", 26, "#A7C57C")
    text(64, 2570, "ONE SHARED 32-ENTRY PALETTE", "두 조건에 사용한 동일한 32색 팔레트", 36, "#E9F0DB", True)
    for index, color in enumerate(variants[0]["palette"]):
        x, y = 64+index*66, 2630
        if color[3] == 0:
            for dy in range(0, 56, 14):
                for dx in range(0, 56, 14):
                    draw.rectangle((x+dx, y+dy, x+dx+13, y+dy+13), fill="#D4D8D1" if (dx+dy)//14%2 else "#9EA8AD")
            draw.text((x+18, y+8), "T", font=font(30), fill="#101927")
        else:
            draw.rectangle((x, y, x+55, y+55), fill=tuple(color[:3]))
    text(64, 2720, "Recorded technical compliance under both tested contracts. Coarser dots simplify fine detail.",
         "검증한 두 조건에서 같은 구조 규칙을 충족했습니다. 도트가 커지면 세부 묘사는 간결해집니다.", 30)
    IMAGES.mkdir(parents=True, exist_ok=True)
    figure.save(IMAGES / ("knight-conditions.ko.png" if korean else "knight-conditions.png"))


def main():
    (ROOT / ".work").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="knight-readme-", dir=ROOT / ".work"))
    variants = [audit_variant(*settings, work) for settings in VARIANTS]
    assert variants[0]["palette"] == variants[1]["palette"]
    make_figure(variants)
    make_figure(variants, korean=True)
    evidence = {"scope": "Two observed technical contracts for the same knight", "output_size": [1024, 1536],
                "total_rgba_colors": 32, "same_palette": True, "uniform_cells_total": 122880,
                "nonuniform_cells_total": 0, "variants": [v["verification"] for v in variants],
                "workflow": "Generated design -> explicit grid/palette projection -> indexed logical source -> deterministic export -> strict audit",
                "visual_review": "User-confirmed examples retain full plate armor, shield and flanged mace. Coarser dots simplify fine details."}
    write_json(EXAMPLES / "evidence.json", evidence)
    print(json.dumps({"status": "pass", "variants": 2, "uniform_cells": 122880, "same_palette": True}))


if __name__ == "__main__":
    main()
