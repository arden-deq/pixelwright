#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build reproducible, high-resolution QA figures from exact exported PNGs."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs" / "examples"
IMAGES = ROOT / "docs" / "images"
SCRIPTS = ROOT / "pixelwright" / "scripts"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def execute(script, args, expected=0):
    result = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                            capture_output=True, text=True)
    if result.returncode != expected:
        raise RuntimeError(f"{script}: {result.returncode}: {result.stderr}")


def portable_report(path, image_path, profile_path):
    report = json.loads(path.read_text(encoding="utf-8"))
    report["provenance"]["source_path"] = image_path.relative_to(ROOT).as_posix()
    report["provenance"]["profile_path"] = profile_path.relative_to(ROOT).as_posix()
    return report


def font(size, korean=False, bold=False):
    paths = (["C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
              "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"] if korean else
             ["C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    if korean:
        raise RuntimeError("Install a Korean font before generating the Korean QA figure")
    return ImageFont.load_default(size=size)


def make_figure(hero, clean_audit, broken_audit, cell, before, after, korean=False):
    canvas = Image.new("RGB", (4736, 2520), "#101927")
    draw = ImageDraw.Draw(canvas)
    def text(x, y, english, ko, size=48, color="#A6BED0", bold=False):
        draw.text((x, y), ko if korean else english, font=font(size, korean, bold), fill=color)
    text(96, 44, "PIXELWRIGHT / EXACT GRID QA", "PIXELWRIGHT / 정확한 격자 QA", 100, "#E9F0DB", True)
    text(96, 186, "32 x 48 logical dots  |  40x integer enlargement  |  1280 x 1920 PNG",
         "논리 도트 32 x 48  |  정수 배율 40배  |  PNG 1280 x 1920", 52)
    text(96, 316, "01  ACTUAL CLEAN EXPORT", "01  실제 원본 PNG", 46, "#72C7C9", True)
    text(1472, 316, "02  CHECKER-GENERATED GRID", "02  검사기가 표시한 격자", 46, "#72C7C9", True)
    text(2880, 316, "03  WHAT MAKES ONE CELL FAIL?", "03  어떤 셀이 불합격일까요?", 46, "#72C7C9", True)
    with Image.open(hero / "clean.png") as loaded:
        clean = loaded.convert("RGBA")
    plate = Image.new("RGBA", clean.size, "#E5E9DD")
    plate.alpha_composite(clean)
    canvas.paste(plate.convert("RGB"), (96, 410))
    with Image.open(clean_audit / "grid_overlay.png") as loaded:
        canvas.paste(loaded.convert("RGB"), (1472, 410))
    text(96, 2370, "PASS  1,536 / 1,536 solid RGBA cells", "PASS  1,536 / 1,536 셀 RGBA 단색", 46, "#A7C57C", True)
    text(1472, 2370, "Each cyan square = 40 x 40 source pixels", "청록색 한 칸 = 원본 픽셀 40 x 40", 46, "#A7C57C", True)
    text(2880, 410, "One logical dot contains 1,600 physical samples.", "논리 도트 하나에는 물리 샘플 1,600개가 있습니다.", 41)
    for index, (name, image_name) in enumerate((("PASS", "clean.png"), ("FAIL", "broken.png"))):
        x = 2920 + index * 800
        draw.text((x, 490), name, font=font(56, korean, True), fill="#A7C57C" if index == 0 else "#FF6271")
        with Image.open(hero / image_name) as loaded:
            crop = loaded.convert("RGBA").crop((cell[0]*40, cell[1]*40, (cell[0]+1)*40, (cell[1]+1)*40))
        zoom = crop.resize((560, 560), Image.Resampling.NEAREST)
        canvas.paste(zoom.convert("RGB"), (x, 580))
        draw.rectangle((x-2, 578, x+561, 1141), outline="#A7C57C" if index == 0 else "#FF6271", width=4)
        if index:
            sx, sy = x + 20*14, 580 + 20*14
            draw.rectangle((sx-8, sy-8, sx+21, sy+21), outline="#FF6271", width=6)
            draw.line((sx+14, sy, x+548, 542), fill="#FF6271", width=4)
        text(x, 1170, f"RGBA {before if index == 0 else after}", f"RGBA {before if index == 0 else after}", 30)
    text(2880, 1260, "ONE sample differs by ONE channel value.", "샘플 하나의 채널 값이 1만 달라도 불합격입니다.", 46, "#E9F0DB", True)
    text(2880, 1340, "Rounded grid score: 100.0   /   Strict verdict: FAIL",
         "반올림 격자 점수: 100.0   /   엄격한 판정: FAIL", 42, "#FF6271", True)
    text(2880, 1424, "03a  EXACT ERROR LOCATION", "03a  실제 오류 셀 위치", 40, "#72C7C9", True)
    with Image.open(broken_audit / "grid_overlay.png") as loaded:
        patch = loaded.crop(((cell[0]-1)*40, (cell[1]-1)*40, (cell[0]+2)*40, (cell[1]+2)*40))
        canvas.paste(patch.resize((840, 840), Image.Resampling.NEAREST).convert("RGB"), (2920, 1520))
    text(3860, 1530, "1 bad cell", "오류 셀 1개", 56, "#FF6271", True)
    text(3860, 1630, f"Logical ({cell[0]}, {cell[1]})", f"논리 좌표 ({cell[0]}, {cell[1]})", 39)
    text(3860, 1740, "Cyan: cell boundary", "청록색: 셀 경계", 39)
    text(3860, 1810, "Red: mixed RGBA cell", "빨간색: RGBA 불일치", 39)
    text(3860, 1940, "The original stays intact.", "원본은 그대로 보존합니다.", 39)
    text(3860, 2010, "The preview is diagnostic.", "격자 이미지는 검사용입니다.", 39)
    text(3860, 2140, "Inspect every saved sample.", "저장된 모든 샘플을 검사합니다.", 38, "#A7C57C")
    text(96, 2460, "High rendered resolution preserves the logical dot grid. Technical compliance and visual quality are reviewed separately.",
         "고해상도로 확대해도 논리 도트 격자는 유지됩니다. 구조 규격과 미술적 품질은 따로 검수합니다.", 36)
    IMAGES.mkdir(parents=True, exist_ok=True)
    canvas.save(IMAGES / ("pixelwright-grid-qa.ko.png" if korean else "pixelwright-grid-qa.png"))


def main():
    PUBLIC.mkdir(parents=True, exist_ok=True)
    work_parent = ROOT / ".work"
    work_parent.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="docs-assets-", dir=work_parent))
    # Bootstrap curated sources from the local demo; future clones use the checked-in JSON.
    for key in ("character", "item", "ui"):
        target = PUBLIC / "assets" / key
        target.mkdir(parents=True, exist_ok=True)
        for name in ("artwork.json", "profile.json"):
            if not (target / name).exists():
                shutil.copyfile(ROOT / "demos" / "2026-10-14" / key / name, target / name)
        build = work / key / "build"
        audit = work / key / "audit"
        execute("pixel_build.py", ["--spec", target / "artwork.json", "--out-dir", build])
        for name in ("native.png", "rendered.png"):
            shutil.copyfile(build / name, target / name)
        execute("pixelwright.py", ["inspect", target / "rendered.png", "--profile", target / "profile.json", "--out-dir", audit])
        write_json(target / "report.json", portable_report(audit / "report.json", target / "rendered.png", target / "profile.json"))
        for name in ("grid_overlay.png", "grid_lines.png", "violation_mask.png"):
            shutil.copyfile(audit / name, target / name)

    hero = PUBLIC / "grid-qa"
    hero.mkdir(exist_ok=True)
    art = json.loads((PUBLIC / "assets/character/artwork.json").read_text(encoding="utf-8"))
    art["scale"] = 40
    profile = json.loads((PUBLIC / "assets/character/profile.json").read_text(encoding="utf-8"))
    profile.update({"name": "High-resolution exact-grid example", "scale": 40})
    write_json(hero / "artwork.json", art)
    write_json(hero / "profile.json", profile)
    execute("pixel_build.py", ["--spec", hero / "artwork.json", "--out-dir", work / "hero-build"])
    shutil.copyfile(work / "hero-build/rendered.png", hero / "clean.png")
    cell = (16, 25)
    with Image.open(hero / "clean.png") as loaded:
        broken = loaded.convert("RGBA")
    sample = (cell[0]*40+20, cell[1]*40+20)
    before = broken.getpixel(sample)
    assert before[3] == 255
    after = ((before[0]+1) % 256, *before[1:])
    broken.putpixel(sample, after)
    broken.save(hero / "broken.png")
    audits = {}
    for name, expected in (("clean", 0), ("broken", 2)):
        audit = work / f"{name}-audit"
        execute("pixelwright.py", ["inspect", hero / f"{name}.png", "--profile", hero / "profile.json", "--out-dir", audit], expected)
        public_audit = hero / f"{name}-audit"
        public_audit.mkdir(exist_ok=True)
        report = portable_report(audit / "report.json", hero / f"{name}.png", hero / "profile.json")
        write_json(public_audit / "report.json", report)
        for filename in ("grid_overlay.png", "grid_lines.png", "violation_mask.png"):
            shutil.copyfile(audit / filename, public_audit / filename)
        audits[name] = audit
    clean_report = json.loads((hero / "clean-audit/report.json").read_text(encoding="utf-8"))
    broken_report = json.loads((hero / "broken-audit/report.json").read_text(encoding="utf-8"))
    assert clean_report["status"] == "pass"
    assert broken_report["status"] == "fail"
    assert broken_report["metrics"]["nonuniform_rgba_cells"] == 1
    assert broken_report["metrics"]["grid_score"] == 100.0
    write_json(hero / "explanation.json", {"logical_size": "32x48", "rendered_size": "1280x1920", "scale": 40,
              "changed_logical_cell": cell, "changed_source_sample": sample, "before_rgba": before, "after_rgba": after,
              "clean_status": "pass", "broken_status": "fail", "rounded_grid_score": 100.0,
              "changed_source_samples": 1, "nonuniform_cells": 1})
    make_figure(hero, audits["clean"], audits["broken"], cell, before, after)
    make_figure(hero, audits["clean"], audits["broken"], cell, before, after, korean=True)
    gallery = Image.new("RGB", (1800, 1000), "#101927")
    draw = ImageDraw.Draw(gallery)
    draw.text((56, 30), "PIXELWRIGHT / ACTUAL PNG EXPORTS", font=font(52, bold=True), fill="#E9F0DB")
    draw.text((56, 108), "One shared palette. Exact 8x8 dots. Clean artwork + visible cell grid.", font=font(30), fill="#A6BED0")
    for index, key in enumerate(("character", "item", "ui")):
        x = 56 + 588*index
        draw.text((x, 196), key.upper(), font=font(36, bold=True), fill="#72C7C9")
        for offset, name in ((0, "rendered.png"), (280, "grid_overlay.png")):
            with Image.open(PUBLIC / "assets" / key / name) as loaded:
                image = loaded.convert("RGBA")
            plate = Image.new("RGBA", (256, 384), "#E5E9DD")
            plate.alpha_composite(image, ((256-image.width)//2, (384-image.height)//2))
            gallery.paste(plate.convert("RGB"), (x+offset, 284))
        report = json.loads((PUBLIC / "assets" / key / "report.json").read_text(encoding="utf-8"))
        m = report["metrics"]
        draw.text((x, 740), f"PASS  {m['uniform_rgba_cells']:,}/{m['total_logical_cells']:,} cells", font=font(35, bold=True), fill="#A7C57C")
        draw.text((x, 810), f"{m['visible_rgb_colors_source']} colors / 0 nonuniform cells", font=font(29), fill="#A6BED0")
    draw.text((56, 936), "Diagnostic overlays stay separate. Delivered PNGs retain their transparent background.", font=font(28), fill="#A6BED0")
    gallery.save(IMAGES / "pixelwright-gallery.png")
    print(json.dumps({"figures": [p.name for p in IMAGES.glob("*.png")], "clean_status": "pass", "broken_status": "fail", "bad_cells": 1}))


if __name__ == "__main__":
    main()
