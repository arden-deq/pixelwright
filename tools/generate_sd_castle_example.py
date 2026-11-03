#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build and audit the frozen native-cell SD kit.

Source matrices are authored at final game resolution. No generated raster input,
projection, resampling downwards or automatic palette mapping is supported.
"""
import argparse
import hashlib
import json
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
CONTRACT = json.loads((DOCS / 'design-contract.json').read_text())
ASSETS = {'castle': (*CONTRACT['castle_logical_size'], 'building'),
          **{name: (*CONTRACT['character_logical_size'], 'boss' if name == 'demon-king' else 'character')
             for name in ('knight', 'princess', 'demon-king')},
          'shadow': (*CONTRACT['shadow_logical_size'], 'shadow')}
ASSETS.update({f'{kind}{i}': (*CONTRACT['tile_logical_size'], 'tile')
               for kind in ('stone', 'moss') for i in range(4)})


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
        knight.resize((64, 128), Image.Resampling.NEAREST).save(enlarged)
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
        assert loaded[name].size == (width, height), f'{name}: source differs from the frozen native size'
        pivots[name] = [width // 2, 126 if name == 'castle' else 3 if name == 'shadow' else 62 if category in ('character', 'boss') else 32]
        inspect(DOCS / f'{name}-4x.png', (width, height), 4, palette, name, work)
        output = work / f'{name}-game'
        run('pixel_game.py', 'asset', native, '--category', category, '--contract', KIT / 'game.json', '--out-dir', output)
        portable_report(output / 'report.json', DOCS / f'{name}-game-report.json')
        evidence[name] = {'status': 'pass', 'size': [width, height],
                          'sha256': hashlib.sha256(native.read_bytes()).hexdigest()}
    rng = np.random.default_rng(347)
    columns, row_count = CONTRACT['map_tiles']
    tile = CONTRACT['tile_logical_size'][0]
    rows = [[f'{"stone" if 2 <= x < 10 and y >= 3 else "moss"}{int(rng.integers(4))}'
             for x in range(columns)] for y in range(row_count)]
    plan = CONTRACT['layout']
    layout = {'schema_version': 1, 'base': CONTRACT['scene_logical_size'], 'tile_size': tile, 'tiles': rows,
              'pivots': pivots, 'objects': [{'asset': name, 'x': plan[name][0], 'y': plan[name][1]}
                                         for name in ('castle', 'princess', 'demon-king', 'knight')],
              'walk_bounds': plan['walk_bounds'], 'collision': [plan['castle_collision']]}
    write(KIT / 'field.json', layout)
    scene = Image.new('RGBA', tuple(layout['base']))
    for y, row in enumerate(rows):
        for x, name in enumerate(row):
            scene.alpha_composite(loaded[name], (x * tile, y * tile))
    for obj in sorted(layout['objects'], key=lambda o: o['y']):
        if obj['asset'] != 'castle':
            scene.alpha_composite(loaded['shadow'], (obj['x'] - 14, obj['y'] - 3))
        px, py = pivots[obj['asset']]
        scene.alpha_composite(loaded[obj['asset']], (obj['x'] - px, obj['y'] - py))
    scene.save(DOCS / 'scene-native.png')
    for scale, suffix in ((2, 'preview'), (3, '3x'), (6, '6x')):
        path = IMAGES / f'game-sd-scene-{suffix}.png'
        scene.resize((384 * scale, 288 * scale), Image.Resampling.NEAREST).save(path)
        inspect(path, (384, 288), scale, palette, f'scene-{suffix}', work, alpha='opaque')
    board = Image.new('RGBA', (384, 208), palette['colors']['stone0'])
    pen = ImageDraw.Draw(board)
    pen.fontmode = '1'
    for name, x, label in (('knight', 4, 'K'), ('princess', 40, 'P'), ('demon-king', 76, 'D')):
        board.alpha_composite(loaded[name], (x, 52))
        pen.text((x + 12, 40), label, fill=palette['colors']['ivory4'])
    for label, y in (('K: KNIGHT', 4), ('P: PRINCESS', 16), ('D: DEMON KING', 28)):
        pen.text((4, y), label, fill=palette['colors']['ivory4'])
    board.alpha_composite(loaded['castle'], (180, 14))
    pen.text((180, 2), 'CASTLE 192x128', fill=palette['colors']['ivory4'])
    pen.text((4, 152), 'NATIVE 32x32 TERRAIN', fill=palette['colors']['ivory4'])
    for i, name in enumerate([f'{kind}{v}' for kind in ('stone', 'moss') for v in range(4)]):
        board.alpha_composite(loaded[name], (4 + i * 34, 168))
    board.alpha_composite(loaded['shadow'], (330, 180))
    board.save(IMAGES / 'game-sd-assets-native.png')
    board.resize((768, 416), Image.Resampling.NEAREST).save(IMAGES / 'game-sd-assets-preview.png')
    strip = Image.new('RGBA', (112, 72), palette['colors']['stone0'])
    for name, x in (('knight', 4), ('princess', 40), ('demon-king', 76)):
        strip.alpha_composite(loaded[name], (x, 4))
    strip.save(DOCS / 'characters-native.png')
    for scale in CONTRACT['character_preview_scales']:
        path = DOCS / f'characters-{scale}x.png'
        strip.resize((112 * scale, 72 * scale), Image.Resampling.NEAREST).save(path)
        inspect(path, (112, 72), scale, palette, 'characters' if scale == 6 else f'characters-{scale}x', work, alpha='opaque')
    faces = Image.new('RGBA', (80, 26), palette['colors']['stone0'])
    for name, x in (('knight', 4), ('princess', 30), ('demon-king', 56)):
        faces.alpha_composite(loaded[name].crop((6, 16, 26, 34)), (x, 4))
    faces.save(DOCS / 'faces-native.png')
    faces.resize((240, 78), Image.Resampling.NEAREST).save(DOCS / 'faces-3x.png')
    inspect(DOCS / 'faces-3x.png', (80, 26), 3, palette, 'faces-3x', work, alpha='opaque')
    faces.resize((480, 156), Image.Resampling.NEAREST).save(DOCS / 'faces-6x.png')
    inspect(DOCS / 'faces-6x.png', (80, 26), 6, palette, 'faces', work, alpha='opaque')
    verify_faces(loaded, scene)
    write(DOCS / 'asset-summary.json', evidence)
    verify_intake(work)
    print(json.dumps({'assets': len(ASSETS), 'status': 'pass', 'scene': [384, 288]}))


def verify_faces(loaded, scene, browser=None):
    design = json.loads((DOCS / 'face-design.json').read_text())
    colors = json.loads((KIT / 'palette.json').read_text())['colors']
    records = {}
    for name, face in design['characters'].items():
        native = np.asarray(loaded[name])
        for feature in (*face['eyes'], face['mouth']):
            x, y = feature['xy']
            for dy, row in enumerate(feature['rows']):
                for dx, token in enumerate(row):
                    if token != '.':
                        expected = tuple(bytes.fromhex(colors[feature['tokens'][token]][1:]))
                        assert tuple(native[y + dy, x + dx]) == expected, f'{name}: expression cells changed'
        x, y = CONTRACT['layout'][name]
        origin = (x - 16, y - 62)
        crop = native[16:34, 6:26]
        composed = np.asarray(scene)[origin[1] + 16:origin[1] + 34, origin[0] + 6:origin[0] + 26]
        opaque = crop[:, :, 3] == 255
        assert np.array_equal(crop[opaque], composed[opaque]), f'{name}: face obscured in scene'
        item = {'native_face_size': [20, 18], 'expression_cells_match_design': True,
                'opaque_native_face_cells_preserved': True,
                'face_rgba_sha256': hashlib.sha256(crop.tobytes()).hexdigest(),
                'composed_face_rgba_sha256': hashlib.sha256(composed.tobytes()).hexdigest()}
        if browser is not None:
            sx, sy = (origin[0] + 6) * 3, (origin[1] + 16) * 3
            captured = np.asarray(browser)[sy:sy + 54, sx:sx + 60]
            assert np.array_equal(captured, composed.repeat(3, axis=0).repeat(3, axis=1)), f'{name}: runtime face changed'
            item['runtime_face_matches_composition_3x'] = True
        records[name] = item
    write(DOCS / 'face-preservation.json', {'status': 'pass',
          'scope': 'Exact preservation of authored expression cells; not an automated aesthetic judgment',
          'downsampling_operations': 0, 'palette_remapping_operations': 0, 'characters': records})


def verify_runtime(work, palette):
    with Image.open(DOCS / 'scene-native.png') as native, Image.open(DOCS / 'runtime-field.png') as browser:
        expected = np.asarray(native.convert('RGBA').resize((1152, 864), Image.Resampling.NEAREST))
        actual = np.asarray(browser.convert('RGBA'))
        if not np.array_equal(actual, expected):
            raise ValueError('Browser field differs from the independent composition')
    loaded = {name: Image.open(KIT / f'build/{name}.png').convert('RGBA')
              for name in ('knight', 'princess', 'demon-king')}
    verify_faces(loaded, Image.open(DOCS / 'scene-native.png').convert('RGBA'),
                 Image.open(DOCS / 'runtime-field.png').convert('RGBA'))
    for name, expected_code in (('clean', 0), ('injected-errors', 2)):
        output = work / f'runtime-{name}'
        run('pixel_game.py', 'screen', DOCS / f'runtime-{name}.png', '--contract', KIT / 'game.json',
            '--out-dir', output, expected=(expected_code,))
        portable_report(output / 'report.json', DOCS / f'runtime-{name}-report.json')
        shutil.copyfile(output / 'screen_overlay.png', DOCS / f'runtime-{name}-overlay.png')
    write(DOCS / 'composition-verification.json', {'status': 'pass', 'browser_matches_independent_composition': True,
          'native_size': [384, 288], 'capture_size': [1152, 864], 'scale': 3,
          'capture_sha256': hashlib.sha256((DOCS / 'runtime-field.png').read_bytes()).hexdigest()})
    verify_intake(work)
    print('Browser composition exact; clean PASS; injected negative FAIL as expected')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-runtime', action='store_true')
    args = parser.parse_args()
    (ROOT / '.work').mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='sd-castle-', dir=ROOT / '.work'))
    palette = json.loads((KIT / 'palette.json').read_text())
    if args.verify_runtime:
        verify_runtime(work, palette)
        return
    provenance = json.loads((DOCS / 'native-authoring.json').read_text())
    assert provenance['contract_sha256'] == hashlib.sha256((DOCS / 'design-contract.json').read_bytes()).hexdigest()
    assert provenance['palette_sha256'] == hashlib.sha256((KIT / 'palette.json').read_bytes()).hexdigest()
    for name, asset in provenance['assets'].items():
        assert asset['cells_sha256'] == hashlib.sha256((KIT / f'{name}.json').read_bytes()).hexdigest(), name
    write(DOCS / 'generation.json', {**provenance, 'historical_concepts': 'generated-concepts.json'})
    build(work, palette)


if __name__ == '__main__':
    main()
