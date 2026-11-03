#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build the SD field from preserved candidates and editable indexed cells.

Raw candidates are audited without modification. --import-generated explicitly
creates derived artwork: alpha-bounds framing, representative-cell projection,
binary alpha, then the shared palette. Normal builds use only committed cells.
"""
import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'pixelwright/examples/demon-castle-sd'
DOCS = ROOT / 'docs/examples/demon-castle-sd'
IMAGES = ROOT / 'docs/images'
ASSETS = {'castle': (192, 128, 'building'),
          'knight': (48, 96, 'character'), 'princess': (48, 96, 'character'),
          'demon-king': (48, 96, 'boss'), 'shadow': (40, 8, 'shadow')}
ASSETS.update({f'{kind}{i}': (16, 16, 'tile') for kind in ('stone', 'moss') for i in range(4)})


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(script, *args, expected=(0,)):
    result = subprocess.run([sys.executable, str(ROOT / 'pixelwright/scripts' / script), *map(str, args)],
                            capture_output=True, text=True, cwd=ROOT)
    if result.returncode not in expected:
        raise RuntimeError(result.stdout + result.stderr)


def portable_report(source, target):
    def clean(value):
        if isinstance(value, str):
            return value.removeprefix(str(ROOT) + '/')
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value
    result = clean(json.loads(source.read_text()))
    mask = result.get('violation_mask', {}).get('file')
    if mask and (source.parent / mask).is_file():
        filename = target.stem.removesuffix('-report') + '-violation_mask.png'
        shutil.copyfile(source.parent / mask, target.parent / filename)
        result['violation_mask']['file'] = filename
    write(target, result)


def profile(size, scale, palette, name, alpha='binary'):
    return {'schema_version': 1, 'name': name, 'logical_size': f'{size[0]}x{size[1]}',
            'scale': scale, 'max_colors': 64, 'alpha': alpha, 'transparent_rgb': 'exact',
            'allowed_palette': list(palette['colors'].values())}


def indexed(name, image, palette):
    array = np.asarray(image.convert('RGBA'))
    lookup = {tuple(bytes.fromhex(color[1:])): key for key, color in palette['colors'].items()}
    rows = [[lookup[tuple(pixel)] for pixel in row] for row in array]
    spec = {'schema_version': 1, 'scale': 4, 'palette_file': 'palette.json', 'rows': rows}
    # Keep one native row per line, so the matrix stays practical to edit.
    header = json.dumps({key: value for key, value in spec.items() if key != 'rows'}, indent=2)[:-2]
    text = header + ',\n  "rows": [\n' + ',\n'.join('    ' + json.dumps(row) for row in rows) + '\n  ]\n}\n'
    (KIT / f'{name}.json').write_text(text, encoding='utf-8')


def import_generated(work, palette):
    records = {}
    for name in ('knight', 'princess', 'demon-king', 'castle'):
        width, height, _ = ASSETS[name]
        original = DOCS / f'{name}-generated.png'
        original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
        source_scale = 8 if name == 'castle' else 16
        source_profile = DOCS / f'{name}-source-profile.json'
        write(source_profile, profile((width, height), source_scale, palette, f'{name}: unmodified image-tool candidate'))
        original_audit = work / f'{name}-original'
        run('pixelwright.py', 'inspect', original, '--profile', source_profile, '--out-dir', original_audit, expected=(0, 2))
        portable_report(original_audit / 'report.json', DOCS / f'{name}-source-report.json')
        shutil.copyfile(original_audit / 'grid_overlay.png', DOCS / f'{name}-source-grid_overlay.png')
        with Image.open(original) as image:
            raw = image.convert('RGBA')
        # Framing discards only the alpha<128 fringe and empty surrounding space.
        # Raw bytes remain intact; the alpha threshold is part of the derived path.
        solid = Image.fromarray(np.where(np.asarray(raw)[:, :, 3] >= 128, 255, 0).astype('uint8'))
        bbox = solid.getbbox()
        if bbox is None:
            raise ValueError(f'{name}: empty candidate at alpha threshold 128')
        cropped = raw.crop(bbox)
        # Horns and the broad cape need the boss's full width, so they must not
        # shrink its face relative to the two human sprites. Canvas stays 48x96.
        inner = ((width - 2 if name == 'demon-king' else width - 8), height - 12) if name != 'castle' else (width - 8, height - 6)
        scale = max(2, math.ceil(max(cropped.width / inner[0], cropped.height / inner[1])))
        framed = Image.new('RGBA', (width * scale, height * scale))
        x = (framed.width - cropped.width) // 2
        baseline = height - (2 if name == 'castle' else 4)
        y = baseline * scale - cropped.height
        framed.paste(cropped, (x, y))
        framed_path = work / f'{name}-framed.png'
        framed.save(framed_path)
        projected = work / f'{name}-projected'
        run('pixel_qa.py', 'fix', framed_path, '--logical-size', f'{width}x{height}',
            '--render-size', f'{framed.width}x{framed.height}', '--hard-alpha', '--out-dir', projected, expected=(0, 2))
        for source, suffix in (('fix_review.json', 'projection-review.json'),
                               ('post_report.json', 'projection-report.json')):
            portable_report(projected / source, DOCS / f'{name}-{suffix}')
        shutil.copyfile(projected / 'comparison.png', DOCS / f'{name}-projection-comparison.png')
        projection_profile = work / f'{name}-projection-profile.json'
        write(projection_profile, profile((width, height), scale, palette, f'{name}: derived shared-palette asset'))
        remapped = work / f'{name}-remapped'
        run('pixel_palette.py', 'remap', projected / 'fixed_upscaled.png', '--palette', KIT / 'palette.json',
            '--profile', projection_profile, '--out-dir', remapped)
        with Image.open(remapped / 'native.png') as native:
            indexed(name, native, palette)
        assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash
        records[name] = {'original_sha256': original_hash, 'original_size': list(raw.size),
                         'original_status': json.loads((original_audit / 'report.json').read_text())['status'],
                         'derived_crop_ltrb': list(bbox), 'derived_paste_xy': [x, y],
                         'derived_canvas': list(framed.size), 'projection_scale': scale,
                         'logical_size': [width, height], 'alpha_threshold': 128,
                         'method': 'Explicit framing, representative-cell projection, binary alpha, shared-palette remap; raw candidate is not certified.'}
    write(DOCS / 'generation.json', {'tool': 'built-in image_gen', 'separate_generations': True,
                                   'originals_preserved': True, 'assets': records})


def create_terrain(palette):
    colors = palette['colors']
    for variant in range(4):
        stone = Image.new('RGBA', (16, 16), colors['stone1'])
        pen = ImageDraw.Draw(stone)
        # Two staggered slabs, quiet mortar and large material clusters.
        for y, shift in ((0, variant % 2 * 4), (8, 8 + variant % 2 * 4)):
            pen.line((0, y, 15, y), fill=colors['stone0'])
            px = shift % 16
            pen.line((px, y, px, y + 7), fill=colors['stone0'])
            pen.line((px + 2, y + 1, min(15, px + 9), y + 1), fill=colors['stone3'])
            pen.line((0, y + 7, 15, y + 7), fill=colors['ink3'])
            pen.rectangle((2 + variant, y + 3, 6 + variant, y + 5), fill=colors['stone2'])
        crack = [(10, 3), (10, 4), (11, 5)] if variant % 2 == 0 else [(4, 11), (5, 12), (5, 13)]
        for p in crack:
            pen.point(p, fill=colors['stone0'])
        if variant >= 2:
            pen.line((12, 13, 14, 12), fill=colors['moss1'])
            pen.point((13, 11), fill=colors['moss2'])
        indexed(f'stone{variant}', stone, palette)
        moss = Image.new('RGBA', (16, 16), colors['moss0'])
        pen = ImageDraw.Draw(moss)
        for j in range((2, 3, 1, 0)[variant]):
            x = (j * 7 + variant * 3) % 13 + 1
            y = (j * 5 + variant * 7) % 12 + 2
            pen.line((x - 1, y + 1, x + 2, y + 1), fill=colors['moss1'])
            pen.line((x, y, x, y - 1), fill=colors['moss1'])
            pen.point((x + 1, y), fill=colors['moss2'] if j == 0 else colors['moss1'])
        indexed(f'moss{variant}', moss, palette)
    shadow = Image.new('RGBA', (40, 8))
    pen = ImageDraw.Draw(shadow)
    pen.ellipse((0, 0, 39, 7), fill=colors['stone0'])
    pen.ellipse((5, 1, 34, 6), fill=colors['ink2'])
    indexed('shadow', shadow, palette)


def inspect(path, size, scale, palette, name, work, alpha='binary'):
    profile_path = DOCS / f'{name}-profile.json'
    write(profile_path, profile(size, scale, palette, name, alpha))
    target = work / name
    run('pixelwright.py', 'inspect', path, '--profile', profile_path, '--out-dir', target)
    portable_report(target / 'report.json', DOCS / f'{name}-report.json')
    shutil.copyfile(target / 'grid_overlay.png', DOCS / f'{name}-grid_overlay.png')


def verify_intake(work):
    enlarged = DOCS / 'knight-2x-rejected.png'
    with Image.open(KIT / 'build/knight.png') as knight:
        knight.resize((96, 192), Image.Resampling.NEAREST).save(enlarged)
    output = work / 'bad-intake'
    run('pixel_game.py', 'intake', enlarged, '--category', 'character', '--contract', KIT / 'game.json',
        '--out-dir', output, expected=(2,))
    result = json.loads((output / 'report.json').read_text())
    expected = {'COARSE_PIXELS', 'PIXEL_SIZE_DIFFERS', 'CATEGORY_SIZE'}
    if not expected <= {issue['code'] for issue in result['issues']}:
        raise ValueError('The enlarged knight must fail the native-asset intake')
    portable_report(output / 'report.json', DOCS / 'intake-report.json')
    shutil.copyfile(output / 'side_by_side.png', IMAGES / 'game-sd-intake.png')


def build(work, palette):
    evidence, loaded, pivots = {}, {}, {}
    (KIT / 'build').mkdir(exist_ok=True)
    for name, (width, height, category) in ASSETS.items():
        output = work / f'{name}-build'
        run('pixel_build.py', '--spec', KIT / f'{name}.json', '--out-dir', output)
        native = KIT / f'build/{name}.png'
        shutil.copyfile(output / 'native.png', native)
        shutil.copyfile(output / 'rendered.png', DOCS / f'{name}-4x.png')
        loaded[name] = Image.open(native).convert('RGBA')
        pivots[name] = [width // 2, 126 if name == 'castle' else 4 if name == 'shadow' else 92 if height == 96 else 16]
        inspect(DOCS / f'{name}-4x.png', (width, height), 4, palette, name, work)
        output = work / f'{name}-game'
        run('pixel_game.py', 'asset', native, '--category', category, '--contract', KIT / 'game.json', '--out-dir', output)
        portable_report(output / 'report.json', DOCS / f'{name}-game-report.json')
        evidence[name] = {'status': 'pass', 'size': [width, height],
                          'sha256': hashlib.sha256(native.read_bytes()).hexdigest()}
    rng = np.random.default_rng(347)
    rows = [[f'{"stone" if 4 <= x < 20 and y >= 6 else "moss"}{int(rng.integers(4))}'
             for x in range(24)] for y in range(18)]
    layout = {'schema_version': 1, 'base': [384, 288], 'tile_size': 16, 'tiles': rows,
              'pivots': pivots, 'objects': [{'asset': 'castle', 'x': 192, 'y': 140},
                                         {'asset': 'princess', 'x': 112, 'y': 232},
                                         {'asset': 'demon-king', 'x': 266, 'y': 216},
                                         {'asset': 'knight', 'x': 188, 'y': 270}],
              'walk_bounds': {'left': 72, 'right': 312, 'top': 136, 'bottom': 278},
              'collision': [{'x': 105, 'y': 101, 'width': 174, 'height': 40}]}
    write(KIT / 'field.json', layout)
    scene = Image.new('RGBA', tuple(layout['base']))
    for y, row in enumerate(rows):
        for x, name in enumerate(row):
            scene.alpha_composite(loaded[name], (x * 16, y * 16))
    for obj in sorted(layout['objects'], key=lambda o: o['y']):
        if obj['asset'] != 'castle':
            scene.alpha_composite(loaded['shadow'], (obj['x'] - 20, obj['y'] - 4))
        px, py = pivots[obj['asset']]
        scene.alpha_composite(loaded[obj['asset']], (obj['x'] - px, obj['y'] - py))
    scene.save(DOCS / 'scene-native.png')
    for scale, suffix in ((2, 'preview'), (3, '3x'), (6, '6x')):
        path = IMAGES / f'game-sd-scene-{suffix}.png'
        scene.resize((384 * scale, 288 * scale), Image.Resampling.NEAREST).save(path)
        inspect(path, (384, 288), scale, palette, f'scene-{suffix}', work, alpha='opaque')
    board = Image.new('RGBA', (384, 160), palette['colors']['ink1'])
    pen = ImageDraw.Draw(board)
    pen.fontmode = '1'
    for name, x in (('knight', 8), ('princess', 62), ('demon-king', 116)):
        board.alpha_composite(loaded[name], (x, 42))
        pen.text((x, 20), name.split('-')[0].upper(), fill=palette['colors']['ivory4'])
    board.alpha_composite(loaded['castle'], (184, 22))
    pen.text((184, 4), 'CASTLE', fill=palette['colors']['ivory4'])
    board.save(IMAGES / 'game-sd-assets-native.png')
    board.resize((768, 320), Image.Resampling.NEAREST).save(IMAGES / 'game-sd-assets-preview.png')
    strip = Image.new('RGBA', (160, 104), palette['colors']['stone0'])
    for name, x in (('knight', 4), ('princess', 56), ('demon-king', 108)):
        strip.alpha_composite(loaded[name], (x, 4))
    strip.save(DOCS / 'characters-native.png')
    strip.resize((320, 208), Image.Resampling.NEAREST).save(DOCS / 'characters-2x.png')
    inspect(DOCS / 'characters-2x.png', (160, 104), 2, palette, 'characters-2x', work, alpha='opaque')
    strip.resize((640, 416), Image.Resampling.NEAREST).save(DOCS / 'characters-4x.png')
    inspect(DOCS / 'characters-4x.png', (160, 104), 4, palette, 'characters', work, alpha='opaque')
    write(DOCS / 'asset-summary.json', evidence)
    verify_intake(work)
    print(json.dumps({'assets': len(ASSETS), 'status': 'pass', 'scene': [384, 288]}))


def verify_runtime(work, palette):
    with Image.open(DOCS / 'scene-native.png') as native, Image.open(DOCS / 'runtime-field.png') as browser:
        expected = np.asarray(native.convert('RGBA').resize((1152, 864), Image.Resampling.NEAREST))
        actual = np.asarray(browser.convert('RGBA'))
        if not np.array_equal(actual, expected):
            raise ValueError('Browser field differs from the independent composition')
    for name, expected_code in (('clean', 0), ('injected-errors', 2)):
        output = work / f'runtime-{name}'
        run('pixel_game.py', 'screen', DOCS / f'runtime-{name}.png', '--contract', KIT / 'game.json',
            '--out-dir', output, expected=(expected_code,))
        portable_report(output / 'report.json', DOCS / f'runtime-{name}-report.json')
        shutil.copyfile(output / 'screen_overlay.png', DOCS / f'runtime-{name}-overlay.png')
    shutil.copyfile(DOCS / 'runtime-field.png', IMAGES / 'game-sd-scene-3x.png')
    write(DOCS / 'composition-verification.json', {'status': 'pass', 'browser_matches_independent_composition': True,
          'native_size': [384, 288], 'capture_size': [1152, 864], 'scale': 3,
          'capture_sha256': hashlib.sha256((DOCS / 'runtime-field.png').read_bytes()).hexdigest()})
    verify_intake(work)
    print('Browser composition exact; clean PASS; injected negative FAIL as expected')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--import-generated', action='store_true')
    modes.add_argument('--verify-runtime', action='store_true')
    args = parser.parse_args()
    (ROOT / '.work').mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='sd-castle-', dir=ROOT / '.work'))
    palette = json.loads((KIT / 'palette.json').read_text())
    if args.verify_runtime:
        verify_runtime(work, palette)
        return
    if args.import_generated:
        import_generated(work, palette)
        create_terrain(palette)
    build(work, palette)


if __name__ == '__main__':
    main()
