#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Author original indexed cells at the PREDECLARED game resolution.

No input raster is read, resized, projected, quantized or palette-remapped.
The old generated designs supply costume ideas only. Every coordinate below is
one final game pixel; saved token matrices are the editable production source.
"""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'pixelwright/examples/demon-castle-sd'
DOCS = ROOT / 'docs/examples/demon-castle-sd'
PALETTE = json.loads((KIT / 'palette.json').read_text())
COLORS = PALETTE['colors']
CONTRACT = json.loads((DOCS / 'design-contract.json').read_text())
FACES = {}


class Cells:
    def __init__(self, width, height):
        self.image = Image.new('RGBA', (width, height))
        self.pen = ImageDraw.Draw(self.image)

    def r(self, box, fill, outline=None):
        self.pen.rectangle(box, fill=COLORS[fill], outline=COLORS[outline] if outline else None)

    def p(self, points, fill, outline=None):
        self.pen.polygon(points, fill=COLORS[fill], outline=COLORS[outline] if outline else None)

    def l(self, points, color):
        self.pen.line(points, fill=COLORS[color], width=1)

    def dot(self, x, y, color):
        self.pen.point((x, y), fill=COLORS[color])

    def ellipse(self, box, fill, outline=None):
        self.pen.ellipse(box, fill=COLORS[fill], outline=COLORS[outline] if outline else None)

    def patch(self, x, y, rows, tokens):
        assert len({len(row) for row in rows}) == 1
        for dy, row in enumerate(rows):
            for dx, token in enumerate(row):
                if token != '.':
                    self.dot(x + dx, y + dy, tokens[token])

    def save(self, name):
        lookup = {tuple(bytes.fromhex(value[1:])): key for key, value in COLORS.items()}
        rgba = self.image.tobytes()
        pixels = [tuple(rgba[i:i + 4]) for i in range(0, len(rgba), 4)]
        width, height = self.image.size
        rows = [[lookup[pixels[y * width + x]] for x in range(width)] for y in range(height)]
        header = json.dumps({'schema_version': 1, 'scale': 4, 'palette_file': 'palette.json'}, indent=2)[:-2]
        text = header + ',\n  "rows": [\n' + ',\n'.join('    ' + json.dumps(row) for row in rows) + '\n  ]\n}\n'
        (KIT / f'{name}.json').write_text(text)
        return {'size': [width, height], 'cells_sha256': hashlib.sha256(text.encode()).hexdigest()}


def skin(c, demon=False):
    base, light, shade = ('ivory3', 'ivory4', 'ivory2') if demon else ('skin3', 'skin4', 'skin2')
    c.p([(8, 16), (23, 16), (25, 19), (25, 27), (23, 31), (20, 33),
         (11, 33), (8, 31), (6, 27), (6, 20)], base, 'ink1')
    c.p([(8, 18), (22, 18), (23, 21), (23, 28), (21, 31), (11, 31),
         (8, 28), (7, 24)], light)
    c.l([(24, 21), (24, 27), (22, 30)], shade)


def expression(c, name):
    eye = ['.kk.', 'kwwk', 'kwdk', 'kbbk', 'kbbk', '.kk.']
    tokens = {'k': 'ink0', 'w': 'ivory4', 'd': 'ink0',
              'b': 'ember2' if name == 'demon-king' else 'blue2'}
    for x in (9, 19):
        c.patch(x, 20, eye, tokens)
    if name == 'princess':
        c.l([(9, 18), (12, 18)], 'gold0')
        c.l([(19, 18), (22, 18)], 'gold0')
        c.dot(8, 21, 'ink0')
        c.dot(23, 21, 'ink0')
        mouth = ['m...m', 'm...m', '.mmm.']
        c.dot(8, 27, 'skin2')
        c.dot(23, 27, 'skin2')
    elif name == 'knight':
        c.l([(9, 18), (12, 19)], 'gold0')
        c.l([(19, 19), (22, 18)], 'gold0')
        mouth = ['....m', 'mmmmm', '.....']
    else:
        c.l([(9, 17), (12, 19)], 'ink0')
        c.l([(19, 19), (22, 17)], 'ink0')
        mouth = ['....m', '..mm.', 'mm...']
    mouth_token = 'crimson0' if name == 'demon-king' else 'skin0'
    c.patch(14, 28, mouth, {'m': mouth_token})
    FACES[name] = {'face_xywh': [6, 16, 20, 18], 'eyes': [
        {'xy': [x, 20], 'rows': eye, 'tokens': tokens} for x in (9, 19)],
        'mouth': {'xy': [14, 28], 'rows': mouth, 'tokens': {'m': mouth_token}},
        'expression': CONTRACT['face_design']['expressions'][name]}


def knight():
    c = Cells(32, 64)
    c.p([(8, 34), (25, 34), (29, 54), (25, 58), (17, 54), (6, 57)], 'crimson1', 'ink0')
    c.p([(9, 36), (14, 35), (10, 53), (7, 55)], 'crimson3')
    c.l([(24, 37), (27, 53), (24, 55)], 'crimson2')
    for x in (10, 19):
        c.r((x, 49, x + 4, 58), 'steel1', 'ink0')
        c.r((x + 1, 50, x + 3, 56), 'steel3')
        c.p([(x, 56), (x + 4, 56), (x + 5, 59), (x + 5, 61), (x - 1, 61), (x - 1, 59)], 'steel2', 'ink0')
        c.l([(x, 58), (x + 3, 58)], 'steel5')
    c.p([(10, 33), (22, 33), (25, 38), (23, 48), (20, 51), (11, 51), (7, 45), (8, 38)], 'steel2', 'ink0')
    c.p([(11, 35), (20, 35), (22, 39), (20, 44), (11, 43), (9, 39)], 'steel4')
    c.l([(11, 35), (19, 35)], 'steel5')
    c.l([(10, 38), (12, 37), (16, 37)], 'steel5')
    c.l([(11, 42), (15, 43), (19, 42)], 'steel2')
    c.p([(20, 36), (23, 39), (21, 44), (18, 44)], 'steel1')
    c.p([(12, 44), (20, 44), (20, 54), (17, 56), (12, 53)], 'crimson2', 'ink1')
    c.l([(13, 45), (13, 52)], 'crimson3')
    c.r((10, 45, 22, 47), 'gold0')
    c.r((11, 45, 21, 46), 'gold3')
    c.r((15, 45, 17, 47), 'gold5')
    c.p([(7, 35), (11, 35), (12, 39), (8, 42), (4, 40), (4, 38)], 'steel3', 'ink0')
    c.l([(6, 36), (9, 36)], 'steel5')
    c.r((5, 40, 9, 45), 'steel2', 'ink0')
    c.r((6, 41, 8, 43), 'steel5')
    c.r((3, 43, 5, 47), 'gold1', 'ink0')
    c.r((1, 45, 9, 46), 'gold4', 'ink0')
    c.p([(3, 47), (6, 47), (6, 57), (4, 60), (2, 57), (2, 49)], 'steel3', 'ink0')
    c.l([(3, 49), (3, 56), (4, 58)], 'steel5')
    c.p([(22, 35), (26, 35), (28, 39), (25, 43), (21, 40)], 'steel2', 'ink0')
    c.l([(23, 36), (25, 36)], 'steel5')
    c.r((21, 40, 25, 44), 'steel3', 'ink0')
    c.p([(23, 40), (29, 40), (31, 43), (30, 51), (27, 55), (23, 52), (22, 43)], 'gold3', 'ink0')
    c.p([(24, 42), (28, 42), (29, 44), (28, 50), (27, 52), (24, 50)], 'crimson2', 'gold5')
    c.l([(26, 43), (26, 49)], 'gold3')
    c.l([(25, 45), (28, 45)], 'gold3')
    c.r((14, 32, 18, 35), 'skin3', 'ink0')
    c.l([(11, 34), (15, 37), (20, 34)], 'crimson3')
    c.p([(8, 3), (21, 3), (26, 7), (29, 17), (27, 26), (24, 30),
         (7, 30), (3, 26), (2, 18), (4, 10)], 'steel2', 'ink0')
    c.p([(8, 5), (20, 5), (24, 9), (26, 16), (5, 17), (6, 10)], 'steel4')
    c.l([(8, 6), (17, 6), (20, 8)], 'steel5')
    c.p([(20, 6), (24, 9), (27, 17), (24, 19), (20, 16)], 'steel1')
    c.l([(7, 11), (6, 15)], 'steel1')
    c.l([(11, 9), (10, 14)], 'steel2')
    c.l([(15, 9), (15, 14)], 'steel2')
    c.p([(18, 4), (19, 1), (23, 0), (27, 2), (30, 5), (29, 9), (24, 8), (21, 6)], 'crimson2', 'ink0')
    c.l([(20, 2), (24, 2), (27, 4)], 'crimson3')
    skin(c)
    c.p([(7, 16), (12, 14), (18, 15), (24, 17), (24, 19), (20, 18),
         (17, 17), (14, 19), (12, 17), (8, 19)], 'gold0')
    c.l([(4, 18), (4, 25), (7, 29)], 'steel5')
    c.l([(27, 18), (27, 25), (24, 29)], 'steel1')
    expression(c, 'knight')
    return c


def princess():
    c = Cells(32, 64)
    c.p([(7, 12), (24, 12), (29, 25), (30, 38), (26, 43), (21, 37),
         (10, 37), (5, 43), (1, 38), (2, 24)], 'gold2', 'ink0')
    c.p([(5, 24), (9, 23), (9, 37), (5, 40), (3, 37)], 'gold4')
    c.p([(24, 23), (28, 27), (28, 37), (25, 40), (23, 36)], 'gold3')
    for x in (10, 19):
        c.r((x, 57, x + 4, 61), 'crimson2', 'ink0')
        c.l([(x + 1, 59), (x + 3, 59)], 'crimson4')
    c.p([(11, 34), (21, 34), (24, 40), (23, 44), (29, 57), (26, 59),
         (6, 59), (2, 57), (9, 43), (8, 39)], 'ivory3', 'ink0')
    c.p([(10, 43), (15, 42), (12, 57), (5, 57)], 'ivory4')
    c.p([(21, 43), (27, 56), (24, 58), (20, 48)], 'ivory1')
    c.p([(13, 37), (19, 37), (20, 45), (22, 58), (11, 58), (13, 45)], 'crimson2', 'gold3')
    c.l([(14, 39), (14, 44)], 'crimson3')
    c.l([(13, 48), (12, 56)], 'crimson3')
    c.l([(4, 57), (8, 58), (25, 58), (27, 57)], 'gold4')
    c.l([(5, 59), (25, 59)], 'gold2')
    c.p([(9, 35), (12, 35), (12, 39), (9, 42), (5, 40), (5, 37)], 'crimson2', 'ink0')
    c.p([(21, 35), (25, 36), (27, 39), (23, 42), (20, 39)], 'crimson2', 'ink0')
    c.r((5, 40, 8, 45), 'ivory4', 'ink1')
    c.r((24, 40, 27, 45), 'ivory3', 'ink1')
    c.r((6, 44, 9, 47), 'skin4', 'skin0')
    c.r((23, 44, 26, 47), 'skin3', 'skin0')
    c.r((14, 32, 18, 36), 'skin3', 'ink1')
    c.l([(12, 35), (16, 38), (20, 35)], 'gold4')
    c.dot(16, 37, 'ivory4')
    c.p([(9, 5), (22, 5), (27, 10), (29, 17), (27, 26), (24, 32),
         (7, 32), (3, 27), (2, 17), (5, 10)], 'gold3', 'ink0')
    skin(c)
    c.p([(7, 9), (20, 8), (25, 11), (27, 17), (24, 20), (20, 18),
         (17, 15), (16, 18), (11, 16), (6, 20), (4, 17)], 'gold4')
    c.l([(7, 11), (12, 9), (18, 9)], 'gold5')
    c.p([(19, 9), (24, 12), (26, 17), (23, 18), (20, 16)], 'gold3')
    c.l([(5, 22), (5, 29), (7, 32)], 'gold5')
    c.p([(8, 7), (7, 1), (11, 4), (15, 0), (19, 4), (24, 1),
         (23, 8), (10, 8)], 'gold3', 'ink0')
    c.l([(9, 3), (10, 6), (21, 6), (22, 3)], 'gold5')
    c.r((14, 2, 17, 6), 'crimson1', 'gold5')
    c.r((15, 3, 16, 5), 'crimson3')
    expression(c, 'princess')
    return c


def demon():
    c = Cells(32, 64)
    c.p([(6, 33), (26, 33), (31, 56), (27, 60), (20, 56), (15, 58),
         (6, 60), (1, 56)], 'crimson1', 'ink0')
    c.p([(5, 38), (9, 37), (6, 55), (3, 56)], 'crimson3')
    c.l([(26, 37), (29, 55), (27, 57)], 'crimson2')
    for x in (8, 19):
        c.r((x, 51, x + 5, 60), 'violet1', 'ink0')
        c.p([(x, 57), (x + 5, 57), (x + 6, 60), (x + 6, 61), (x - 1, 61)], 'violet2', 'ink0')
        c.l([(x, 58), (x + 4, 58)], 'gold4')
    c.p([(10, 34), (22, 34), (26, 41), (23, 51), (20, 55), (10, 54),
         (6, 47), (7, 39)], 'violet2', 'ink0')
    c.p([(11, 36), (20, 36), (23, 41), (20, 46), (11, 46), (8, 41)], 'violet3', 'gold3')
    c.p([(20, 37), (24, 41), (21, 46), (18, 44)], 'violet1')
    c.l([(11, 37), (14, 39), (17, 38), (21, 37)], 'gold5')
    c.r((14, 39, 17, 42), 'gold3', 'ink0')
    c.r((15, 40, 16, 41), 'crimson3')
    c.r((9, 47, 23, 49), 'gold3', 'ink0')
    c.r((14, 47, 18, 50), 'gold5', 'gold1')
    c.p([(11, 50), (20, 50), (23, 55), (18, 56), (16, 53), (12, 56), (9, 54)], 'violet2', 'gold2')
    for x in (4, 23):
        c.p([(x, 35), (x + 4, 33), (x + 6, 38), (x + 4, 42), (x - 1, 40)], 'violet3', 'ink0')
        c.l([(x, 36), (x + 3, 35), (x + 5, 38)], 'gold5')
        c.r((x, 41, x + 4, 47), 'violet2', 'ink0')
        c.r((x, 47, x + 4, 50), 'violet1', 'ink0')
        c.l([(x + 1, 47), (x + 3, 47)], 'gold4')
    c.p([(8, 9), (23, 9), (28, 16), (28, 27), (25, 33), (7, 33),
         (3, 26), (3, 17)], 'violet2', 'ink0')
    c.p([(5, 20), (0, 17), (1, 23), (6, 27)], 'ivory2', 'ink0')
    c.p([(26, 20), (31, 17), (30, 23), (25, 27)], 'ivory2', 'ink0')
    skin(c, demon=True)
    c.p([(5, 16), (8, 10), (12, 6), (15, 8), (17, 3), (21, 9),
         (25, 8), (28, 16), (24, 20), (20, 15), (16, 18), (12, 15), (7, 20)], 'violet1', 'ink0')
    c.p([(9, 12), (12, 8), (15, 11), (18, 6), (20, 11), (24, 11),
         (25, 15), (20, 13), (16, 15), (12, 12)], 'violet3')
    c.p([(7, 15), (3, 13), (0, 9), (0, 4), (3, 1), (5, 1),
         (3, 5), (4, 9), (8, 11)], 'gold3', 'ink0')
    c.l([(2, 4), (1, 7), (2, 10), (5, 12)], 'gold5')
    c.p([(24, 15), (28, 13), (31, 9), (31, 4), (28, 1), (26, 1),
         (28, 5), (27, 9), (23, 11)], 'gold2', 'ink0')
    c.l([(29, 4), (30, 7), (29, 10), (26, 12)], 'gold4')
    c.p([(12, 14), (15, 12), (19, 14), (17, 17), (14, 17)], 'gold3', 'ink0')
    c.r((15, 14, 16, 15), 'crimson3')
    expression(c, 'demon-king')
    return c


def castle():
    c = Cells(192, 128)
    # Distant keep, broad roof facets, then the front masonry and towers.
    c.r((49, 36, 143, 109), 'stone2', 'ink0')
    c.p([(49, 38), (65, 16), (126, 16), (143, 38), (139, 43), (52, 43)], 'violet2', 'ink0')
    c.p([(52, 37), (67, 18), (96, 18), (91, 38)], 'violet3')
    c.p([(97, 18), (124, 18), (139, 37), (98, 37)], 'violet1')
    for y in (24, 30, 36):
        left = 65 - (y - 16) // 2
        right = 126 + (y - 16) // 2
        c.l([(left, y), (right, y)], 'violet0')
        c.l([(left + 1, y + 1), (93, y + 1)], 'violet3')
    c.l([(65, 15), (126, 15)], 'gold3')
    for x in range(65, 127, 8):
        c.r((x, 12, x + 1, 15), 'gold4')
    # Masonry is designed in final game pixels, with calm, repeatable clusters.
    for y in range(45, 108, 8):
        c.l([(51, y), (141, y)], 'stone0')
        for x in range(54 + (y // 8 % 2) * 8, 141, 16):
            c.l([(x, y), (x, min(108, y + 7))], 'stone1')
            c.l([(x + 2, y + 1), (min(141, x + 12), y + 1)], 'stone3')
    for x in (64, 120):
        c.r((x, 46, x + 7, 62), 'ink0')
        c.p([(x + 1, 61), (x + 1, 51), (x + 3, 47), (x + 6, 51), (x + 6, 61)], 'crimson1')
        c.l([(x + 3, 50), (x + 3, 60)], 'ember2')
        c.l([(x, 63), (x + 8, 63)], 'stone4')
    c.p([(60, 78), (69, 54), (95, 39), (121, 54), (131, 78), (126, 82), (65, 82)], 'violet1', 'ink0')
    c.p([(64, 76), (72, 56), (95, 43), (95, 77)], 'violet3')
    c.p([(96, 43), (119, 56), (127, 76), (97, 77)], 'violet2')
    c.l([(70, 55), (95, 40), (122, 55)], 'gold3')
    c.l([(66, 79), (126, 79)], 'stone4')
    c.p([(90, 59), (95, 53), (100, 59), (108, 57), (103, 65), (96, 70),
         (88, 65), (83, 57)], 'gold3', 'ink0')
    c.p([(91, 60), (95, 57), (99, 60), (102, 60), (99, 64), (95, 67), (91, 64), (88, 60)], 'crimson2')
    c.dot(95, 59, 'gold5')
    # The twin cylindrical towers share the same material and native outline.
    for center in (30, 162):
        c.ellipse((center - 19, 106, center + 19, 121), 'stone1', 'ink0')
        c.r((center - 17, 55, center + 17, 113), 'stone2', 'ink0')
        c.r((center - 15, 58, center - 10, 112), 'stone3')
        c.r((center + 10, 58, center + 16, 112), 'stone0')
        for y in (67, 79, 91, 103):
            c.l([(center - 16, y), (center + 16, y)], 'stone1')
            c.l([(center - 14, y + 1), (center - 7, y + 1)], 'stone4')
        c.ellipse((center - 20, 108, center + 20, 119), 'stone3', 'ink0')
        c.l([(center - 17, 116), (center - 8, 118), (center + 9, 118), (center + 17, 115)], 'stone1')
        c.r((center - 4, 64, center + 4, 77), 'ink0')
        c.p([(center - 3, 76), (center - 3, 68), (center, 65), (center + 3, 68), (center + 3, 76)], 'crimson1')
        c.l([(center, 68), (center, 75)], 'ember3')
        c.r((center - 7, 82, center + 7, 101), 'gold2', 'ink0')
        c.p([(center - 5, 83), (center + 5, 83), (center + 5, 101), (center, 107), (center - 5, 101)], 'crimson1', 'gold3')
        c.l([(center - 3, 85), (center - 3, 100)], 'crimson3')
        c.l([(center - 3, 89), (center, 92), (center + 3, 89)], 'gold5')
        c.l([(center, 92), (center, 99)], 'gold5')
        c.ellipse((center - 21, 50, center + 21, 62), 'stone2', 'ink0')
        c.r((center - 20, 52, center + 20, 57), 'stone3', 'ink0')
        for dx in (-18, -8, 2, 12):
            c.r((center + dx, 48, center + dx + 5, 54), 'stone4', 'ink0')
            c.l([(center + dx + 1, 49), (center + dx + 4, 49)], 'ivory3')
        c.p([(center, 6), (center + 17, 46), (center + 15, 51), (center - 15, 51), (center - 17, 46)], 'violet2', 'ink0')
        c.p([(center - 1, 10), (center - 14, 46), (center - 2, 47)], 'violet3')
        c.p([(center + 1, 10), (center + 15, 46), (center + 2, 47)], 'violet1')
        for y in (25, 36, 46):
            half = (y - 6) * 17 // 40
            c.l([(center - half, y), (center + half, y)], 'violet0')
            c.l([(center - half + 1, y + 1), (center - 2, y + 1)], 'violet3')
        c.l([(center - 15, 49), (center + 15, 49)], 'gold2')
        c.r((center - 1, 1, center + 1, 7), 'gold3', 'ink0')
        c.dot(center, 2, 'gold5')
    # Front arch, substantial steps and visible paired door panels.
    c.p([(69, 118), (69, 95), (73, 85), (83, 77), (108, 77), (119, 85), (123, 95), (123, 118)], 'stone3', 'ink0')
    c.p([(74, 116), (74, 95), (78, 87), (85, 81), (106, 81), (114, 87), (118, 95), (118, 116)], 'stone0', 'stone5')
    c.p([(78, 115), (78, 96), (81, 89), (87, 84), (104, 84), (111, 89), (114, 96), (114, 115)], 'crimson1', 'ink0')
    c.l([(96, 85), (96, 115)], 'gold1')
    for x in (82, 99):
        c.r((x, 96, x + 10, 112), 'crimson2', 'gold2')
        c.r((x + 2, 98, x + 8, 110), 'crimson1')
    c.r((91, 101, 93, 104), 'gold4', 'gold1')
    c.r((99, 101, 101, 104), 'gold4', 'gold1')
    for y in (89, 98, 107):
        c.l([(70, y), (75, y)], 'stone5')
        c.l([(118, y), (122, y)], 'stone1')
    for x in (62, 130):
        c.r((x - 3, 107, x + 3, 118), 'stone2', 'ink0')
        c.l([(x - 2, 110), (x - 2, 115)], 'stone4')
        c.r((x - 4, 103, x + 4, 107), 'gold1', 'ink0')
        c.p([(x - 3, 102), (x - 4, 98), (x - 1, 95), (x, 91), (x + 2, 96), (x + 4, 98), (x + 3, 102)], 'ember2', 'ink0')
        c.p([(x - 1, 101), (x - 2, 98), (x, 96), (x + 2, 100)], 'gold5')
    for y, left, right in ((117, 71, 121), (120, 65, 127), (123, 59, 133)):
        c.r((left, y, right, y + 2), 'stone2', 'ink0')
        c.l([(left + 1, y), (right - 1, y)], 'stone5')
    return c


def terrain():
    result = {}
    for variant in range(4):
        c = Cells(32, 32)
        c.r((0, 0, 31, 31), 'stone1')
        for y, offset in ((0, variant % 2 * 8), (16, (variant % 2 + 1) * 8)):
            c.l([(0, y), (31, y)], 'stone0')
            c.l([(0, y + 15), (31, y + 15)], 'stone0')
            for x in range(offset % 16, 32, 16):
                c.l([(x, y), (x, y + 15)], 'stone0')
                c.l([(x + 2, y + 1), (min(31, x + 13), y + 1)], 'stone2')
            c.r((4 + variant, y + 5, 12 + variant, y + 10), 'stone1')
        if variant == 1:
            c.l([(21, 20), (21, 22), (22, 23), (23, 23)], 'stone0')
        if variant == 2:
            c.l([(3, 28), (6, 28), (7, 27)], 'moss1')
        if variant == 3:
            c.l([(27, 3), (29, 3)], 'stone2')
        result[f'stone{variant}'] = c
        c = Cells(32, 32)
        c.r((0, 0, 31, 31), 'moss0')
        for j in range((3, 2, 2, 1)[variant]):
            x = (variant * 5 + j * 13) % 24 + 3
            y = (variant * 11 + j * 9) % 23 + 5
            c.l([(x - 2, y), (x, y + 1), (x + 3, y)], 'moss1')
            c.l([(x, y), (x - 1, y - 3)], 'moss1')
            c.l([(x + 1, y), (x + 3, y - 2)], 'moss1')
            if j == 0:
                c.dot(x - 1, y - 2, 'moss2')
        result[f'moss{variant}'] = c
    c = Cells(28, 6)
    c.ellipse((0, 0, 27, 5), 'stone0')
    c.ellipse((4, 1, 23, 4), 'ink2')
    # Two small sole contacts, drawn in native cells rather than doubled blocks.
    c.r((6, 2, 10, 3), 'ink1')
    c.r((18, 3, 22, 4), 'ink1')
    result['shadow'] = c
    return result


def main():
    assert CONTRACT['character_logical_size'] == [32, 64]
    assert CONTRACT['tile_logical_size'] == [32, 32]
    authored = {'knight': knight(), 'princess': princess(), 'demon-king': demon(), 'castle': castle(), **terrain()}
    records = {name: cells.save(name) for name, cells in authored.items()}
    face_path = DOCS / 'face-design.json'
    face_path.write_text(json.dumps({'schema_version': 1, 'coordinate_space': 'final native32x64 character cells',
                                    'characters': FACES}, ensure_ascii=False, indent=2) + '\n')
    provenance = {'workflow': 'native_cell_authoring', 'contract_sha256': hashlib.sha256((DOCS / 'design-contract.json').read_bytes()).hexdigest(),
                  'contract_fixed_before_authoring_commit': '8e39a33', 'authoring_script': 'tools/author_sd_castle_cells.py',
                  'authoring_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'palette_sha256': hashlib.sha256((KIT / 'palette.json').read_bytes()).hexdigest(),
                  'raster_inputs': [], 'downsampling_operations': 0, 'palette_remapping_operations': 0,
                  'historical_concept_role': 'Costume and palette reference only; original generated PNGs are preserved but are not production inputs.',
                  'face_design_sha256': hashlib.sha256(face_path.read_bytes()).hexdigest(), 'assets': records}
    (DOCS / 'native-authoring.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': 'authored', 'assets': len(records), 'native_character_size': [32, 64]}))


if __name__ == '__main__':
    main()
