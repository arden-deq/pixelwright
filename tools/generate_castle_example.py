#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Rebuild the independent native assets and field map used in the README.

Normal runs use the committed indexed artwork. --import-generated explicitly
projects the preserved image-tool outputs onto the declared native grids first;
it never edits those originals or reports their failures as passes.
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
KIT = ROOT / 'pixelwright/examples/demon-castle'
DOCS = ROOT / 'docs/examples/demon-castle'
SCRIPTS = ROOT / 'pixelwright/scripts'
ASSETS = {'castle': (192, 128, 'building'), 'knight': (32, 48, 'character'),
          'princess': (32, 48, 'character'), 'demon-king': (64, 64, 'boss'),
          'stone': (16, 16, 'tile'), 'moss': (16, 16, 'tile')}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(script, *args, expected=(0,)):
    result = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                            capture_output=True, text=True, cwd=ROOT)
    if result.returncode not in expected:
        raise RuntimeError(result.stdout + result.stderr)
    return result


def copy_report(source, target):
    def portable(value):
        if isinstance(value, str):
            return value.removeprefix(str(ROOT) + '/')
        if isinstance(value, list):
            return [portable(item) for item in value]
        if isinstance(value, dict):
            return {key: portable(item) for key, item in value.items()}
        return value
    write(target, portable(json.loads(source.read_text())))


def artwork(name, pixels, palette):
    lookup = {tuple(bytes.fromhex(value[1:])): token for token, value in palette['colors'].items()}
    rows = [[lookup[tuple(pixel)] for pixel in row] for row in pixels]
    spec = {'schema_version': 1, 'scale': 4, 'palette_file': 'palette.json', 'rows': rows}
    # One row per line keeps the editable native matrix compact.
    text = json.dumps({key: value for key, value in spec.items() if key != 'rows'}, indent=2)[:-2]
    text += ',\n  "rows": [\n' + ',\n'.join('    ' + json.dumps(row) for row in rows) + '\n  ]\n}\n'
    (KIT / f'{name}.json').write_text(text, encoding='utf-8')


def import_generated(work, palette):
    records = {}
    for name in ('castle', 'knight', 'princess', 'demon-king'):
        width, height, _ = ASSETS[name]
        original = DOCS / f'{name}-generated.png'
        source_hash = hashlib.sha256(original.read_bytes()).hexdigest()
        audit = work / f'{name}-original'
        run('pixelwright.py', 'inspect', original, '--profile', DOCS / f'{name}-source-profile.json',
            '--out-dir', audit, expected=(0, 2))
        original_report = json.loads((audit / 'report.json').read_text())
        copy_report(audit / 'report.json', DOCS / f'{name}-source-report.json')
        with Image.open(original) as image:
            physical = image.size
        projection_input = original
        padding = [0, 0, 0, 0]
        # The image tool can trim a transparent canvas (the boss is 1254²).
        # Preserve that source and explicitly pad a derived input; never silently
        # resize it or call the original's geometry a pass.
        scale = max((physical[0] + width - 1) // width, (physical[1] + height - 1) // height)
        target = (width * scale, height * scale)
        if physical != target:
            if physical[0] * height != physical[1] * width:
                raise ValueError(f'{name}: incompatible source aspect ratio {physical}')
            dx, dy = (target[0] - physical[0]) // 2, (target[1] - physical[1]) // 2
            padding = [dx, dy, target[0] - physical[0] - dx, target[1] - physical[1] - dy]
            with Image.open(original) as image:
                padded = Image.new('RGBA', target)
                padded.paste(image.convert('RGBA'), (dx, dy))
                projection_input = work / f'{name}-padded-input.png'
                padded.save(projection_input)
        projection = work / f'{name}-projection'
        run('pixel_qa.py', 'fix', projection_input, '--logical-size', f'{width}x{height}',
            '--render-size', f'{target[0]}x{target[1]}', '--hard-alpha', '--out-dir', projection,
            expected=(0, 2))
        profile = {'schema_version': 1, 'name': f'{name} derived grid/palette contract',
                   'logical_size': f'{width}x{height}', 'scale': scale, 'max_colors': 64,
                   'alpha': 'binary', 'transparent_rgb': 'exact',
                   'allowed_palette': list(palette['colors'].values())}
        profile_file = work / f'{name}-derived-profile.json'
        write(profile_file, profile)
        remapped = work / f'{name}-palette'
        run('pixel_palette.py', 'remap', projection / 'fixed_upscaled.png', '--palette', KIT / 'palette.json',
            '--profile', profile_file, '--out-dir', remapped)
        with Image.open(remapped / 'native.png') as image:
            pixels = np.asarray(image.convert('RGBA'))
        artwork(name, pixels, palette)
        assert hashlib.sha256(original.read_bytes()).hexdigest() == source_hash
        records[name] = {'original_sha256': source_hash, 'original_size': list(physical),
                         'declared_native_size': [width, height], 'projection_scale': scale,
                         'derived_input_padding_ltrb': padding,
                         'original_status': original_report['status'],
                         'method': 'Pixelwright representative-cell projection, hard alpha, shared-palette remap; derived artwork, not raw-generation acceptance'}
    write(DOCS / 'generation.json', {'tool': 'built-in image_gen', 'assets_generated_separately': True,
                                   'originals_preserved': True, 'assets': records})


def tiles(palette):
    colors = {token: tuple(bytes.fromhex(value[1:])) for token, value in palette['colors'].items()}
    stone = np.empty((16, 16, 4), dtype=np.uint8)
    moss = stone.copy()
    for y in range(16):
        for x in range(16):
            # Hand-authored staggered slab joints and small contiguous clusters.
            joint = y in (0, 8) or (x + (8 if y >= 8 else 0)) % 16 == 0
            token = 'stone0' if joint else 'stone1'
            if y in (1, 9) and 2 <= x <= 12:
                token = 'stone2'
            if (x, y) in {(3, 5), (4, 5), (11, 12), (11, 13), (12, 14)}:
                token = 'stone0'
            stone[y, x] = colors[token]
            token = 'moss0'
            if (x, y) in {(2, 2), (3, 2), (3, 3), (11, 7), (12, 7), (12, 8), (6, 13), (7, 13)}:
                token = 'moss1'
            if (x, y) in {(3, 1), (12, 6), (7, 12)}:
                token = 'moss2'
            moss[y, x] = colors[token]
    artwork('stone', stone, palette)
    artwork('moss', moss, palette)


def export_readme_previews(work):
    """Keep GitHub previews small enough to avoid fractional desktop downscaling."""
    images = ROOT / 'docs/images'
    exports = {}
    for name, source, source_scale, size in (
        ('game-scene', DOCS / 'scene-native.png', 1, (384, 256)),
        ('game-assets', images / 'game-assets.png', 3, (384, 160)),
        ('game-screen-check', images / 'game-screen-check.png', 4, (384, 256)),
    ):
        with Image.open(source) as image:
            if image.size != (size[0] * source_scale, size[1] * source_scale):
                raise ValueError(f'Unexpected source dimensions: {source}')
            native = image.convert('RGBA').resize(size, Image.Resampling.NEAREST)
        outputs = {}
        for label, scale in (('native', 1), ('preview', 2), ('6x', 6)):
            if label == '6x' and name != 'game-scene':
                continue
            path = source if name == 'game-scene' and scale == 1 else images / f'{name}-{label}.png'
            if path != source:
                native.resize((size[0] * scale, size[1] * scale), Image.Resampling.NEAREST).save(path)
            outputs[label] = {'path': str(path.relative_to(ROOT)), 'scale': scale,
                              'size': [size[0] * scale, size[1] * scale],
                              'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            if name == 'game-scene' and scale > 1:
                profile = json.loads((DOCS / 'scene-profile.json').read_text())
                profile.update(name=f'Demon Castle README at {scale}x', scale=scale)
                profile_path = DOCS / f'readme-{label}-profile.json'
                write(profile_path, profile)
                out = work / f'readme-{label}'
                run('pixelwright.py', 'inspect', path, '--profile', profile_path, '--out-dir', out)
                copy_report(out / 'report.json', DOCS / f'readme-{label}-report.json')
                if scale == 2:
                    shutil.copyfile(out / 'grid_overlay.png', DOCS / 'readme-preview-grid_overlay.png')
        exports[name] = outputs
    write(DOCS / 'readme-exports.json', {'method': 'nearest-neighbor integer exports; native detail unchanged',
                                      'exports': exports})


def verify_runtime(work):
    """Audit real browser captures, including the deliberately broken variant."""
    for name, expected, codes in (
        ('clean', 0, set()),
        ('injected-errors', 2, {'CELL_NOT_UNIFORM', 'COLOR_OUTSIDE_PALETTE'}),
    ):
        out = work / name
        run('pixel_game.py', 'screen', DOCS / f'runtime-{name}.png',
            '--contract', KIT / 'game.json', '--out-dir', out, expected=(expected,))
        report = json.loads((out / 'report.json').read_text())
        if {issue['code'] for issue in report['issues']} != codes:
            raise ValueError(f'Unexpected runtime issues: {report["issues"]}')
        copy_report(out / 'report.json', DOCS / f'runtime-{name}-report.json')
        if name == 'injected-errors':
            shutil.copyfile(out / 'screen_overlay.png', ROOT / 'docs/images/game-screen-check.png')
    capture = DOCS / 'runtime-field.png'
    with Image.open(DOCS / 'scene-native.png') as native, Image.open(capture) as browser:
        expected = np.asarray(native.convert('RGBA').resize((1152, 768), Image.Resampling.NEAREST))
        actual = np.asarray(browser.convert('RGBA'))
    if not np.array_equal(actual, expected):
        raise ValueError('Browser composition differs from the independent native composition')
    shutil.copyfile(capture, ROOT / 'docs/images/game-scene.png')
    out = work / 'browser-grid'
    run('pixelwright.py', 'inspect', ROOT / 'docs/images/game-scene.png',
        '--profile', DOCS / 'scene-profile.json', '--out-dir', out)
    copy_report(out / 'report.json', DOCS / 'scene-report.json')
    for name in ('grid_overlay.png', 'violation_mask.png'):
        shutil.copyfile(out / name, DOCS / f'scene-{name}')
    record = {'status': 'pass', 'browser_matches_independent_composition': True,
              'native_size': [384, 256], 'capture_size': [1152, 768], 'scale': 3,
              'visible_colors': len(np.unique(actual.reshape(-1, 4), axis=0)),
              'native_sha256': hashlib.sha256((DOCS / 'scene-native.png').read_bytes()).hexdigest(),
              'capture_sha256': hashlib.sha256(capture.read_bytes()).hexdigest()}
    write(DOCS / 'composition-verification.json', record)
    export_readme_previews(work)
    print(json.dumps(record))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--import-generated', action='store_true')
    modes.add_argument('--verify-runtime', action='store_true', help='audit captures from check_castle_demo.mjs')
    modes.add_argument('--export-readme', action='store_true', help='export integer README previews and a 6x scene')
    args = parser.parse_args()
    (ROOT / '.work').mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='castle-', dir=ROOT / '.work'))
    if args.export_readme:
        export_readme_previews(work)
        print('README previews and 6x scene exported and audited')
        return
    if args.verify_runtime:
        verify_runtime(work)
        return
    palette = json.loads((KIT / 'palette.json').read_text())
    if args.import_generated:
        import_generated(work, palette)
        tiles(palette)
    build = KIT / 'build'
    build.mkdir(exist_ok=True)
    pivots, evidence = {}, {}
    for name, (width, height, category) in ASSETS.items():
        out = work / f'{name}-build'
        run('pixel_build.py', '--spec', KIT / f'{name}.json', '--out-dir', out)
        shutil.copyfile(out / 'native.png', build / f'{name}.png')
        with Image.open(build / f'{name}.png') as image:
            assert image.size == (width, height)
            bbox = image.getbbox()
            pivots[name] = [width // 2, bbox[3]]
        check = work / f'{name}-asset'
        run('pixel_game.py', 'asset', build / f'{name}.png', '--category', category,
            '--contract', KIT / 'game.json', '--out-dir', check, expected=(0, 2))
        report = json.loads((check / 'report.json').read_text())
        if report['status'] != 'pass':
            raise ValueError(f'{name} failed its game contract: {report["issues"]}')
        copy_report(check / 'report.json', DOCS / f'{name}-asset-report.json')
        evidence[name] = {'status': report['status'], 'size': [width, height],
                          'sha256': hashlib.sha256((build / f'{name}.png').read_bytes()).hexdigest(),
                          'issues': report['issues']}
    # Scene positions are foot anchors in native game pixels, not image corners.
    layout = {'schema_version': 1, 'base': [384, 256], 'tile_size': 16,
              'tiles': [['stone' if 4 <= x < 20 and y >= 5 else 'moss' for x in range(24)] for y in range(16)],
              'pivots': pivots, 'objects': [
                  {'asset': 'castle', 'x': 192, 'y': 144},
                  {'asset': 'princess', 'x': 142, 'y': 210},
                  {'asset': 'demon-king', 'x': 235, 'y': 192},
                  {'asset': 'knight', 'x': 181, 'y': 229}],
              'collision': [{'x': 103, 'y': 91, 'width': 178, 'height': 54}]}
    write(KIT / 'field.json', layout)
    scene = Image.new('RGBA', (384, 256))
    loaded = {name: Image.open(build / f'{name}.png').convert('RGBA') for name in ASSETS}
    # Every object stays at 1x on this comparison board; enlarge the whole board once.
    board = Image.new('RGBA', (384, 160), palette['colors']['ink1'])
    labels = ImageDraw.Draw(board)
    board.alpha_composite(loaded['castle'], (4, 22))
    for name, x, y in [('knight', 212, 66), ('princess', 258, 66), ('demon-king', 304, 50),
                       ('stone', 214, 134), ('moss', 260, 134)]:
        board.alpha_composite(loaded[name], (x, y))
    for text, x, y in [('CASTLE', 8, 4), ('KNIGHT', 208, 49), ('PRINCESS', 252, 49),
                        ('DEMON KING', 306, 33), ('STONE', 208, 118), ('MOSS', 254, 118)]:
        labels.text((x, y), text, fill=palette['colors']['ivory4'])
    board.resize((1152, 480), Image.Resampling.NEAREST).save(ROOT / 'docs/images/game-assets.png')
    for y, row in enumerate(layout['tiles']):
        for x, name in enumerate(row):
            scene.alpha_composite(loaded[name], (x * 16, y * 16))
    for obj in sorted(layout['objects'], key=lambda obj: obj['y']):
        px, py = pivots[obj['asset']]
        scene.alpha_composite(loaded[obj['asset']], (obj['x'] - px, obj['y'] - py))
    scene.save(DOCS / 'scene-native.png')
    scene.resize((1152, 768), Image.Resampling.NEAREST).save(ROOT / 'docs/images/game-scene.png')
    # A strict enlarged-image audit is separate from the 1x game contract.
    write(DOCS / 'scene-profile.json', {'schema_version': 1, 'name': 'Demon Castle field at 3x',
          'logical_size': '384x256', 'scale': 3, 'max_colors': 64, 'alpha': 'opaque',
          'transparent_rgb': 'exact', 'allowed_palette': list(palette['colors'].values())})
    run('pixelwright.py', 'inspect', ROOT / 'docs/images/game-scene.png', '--profile', DOCS / 'scene-profile.json',
        '--out-dir', work / 'scene-grid')
    for name in ('report.json', 'grid_overlay.png', 'violation_mask.png'):
        target = DOCS / ('scene-' + name)
        if name.endswith('.json'):
            copy_report(work / 'scene-grid' / name, target)
        else:
            shutil.copyfile(work / 'scene-grid' / name, target)
    enlarged = DOCS / 'knight-2x-rejected.png'
    loaded['knight'].resize((64, 96), Image.Resampling.NEAREST).save(enlarged)
    run('pixel_game.py', 'intake', enlarged, '--category', 'character', '--contract', KIT / 'game.json',
        '--out-dir', work / 'bad-intake', expected=(2,))
    intake = json.loads((work / 'bad-intake/report.json').read_text())
    assert {'COARSE_PIXELS', 'PIXEL_SIZE_DIFFERS', 'CATEGORY_SIZE'} <= {issue['code'] for issue in intake['issues']}
    shutil.copyfile(work / 'bad-intake/side_by_side.png', ROOT / 'docs/images/game-intake.png')
    copy_report(work / 'bad-intake/report.json', DOCS / 'intake-report.json')
    write(DOCS / 'asset-summary.json', evidence)
    export_readme_previews(work)
    print(json.dumps({'assets': evidence, 'scene_grid': 'pass', 'intake_negative': 'fail as expected'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
