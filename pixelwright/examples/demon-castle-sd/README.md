# SD demon castle field

A static RPG Maker-style field composed from independent native PNGs. All three characters use 48×96 canvases with two-head SD anatomy. Tiles are 16×16, the castle is 192×128 and the base screen is 384×288. The shared 64-color palette, binary alpha and integer rendering apply to every asset.

Serve the repository root with `python -m http.server 8000` and open `/pixelwright/examples/demon-castle-sd/`. Arrow keys translate the static knight, R resets, F enters/exits fullscreen and Escape exits fullscreen. There are no walking animation frames. `?fault=1` deliberately injects a misaligned duplicate and a blended effect for a negative check.

Rebuild from editable token matrices with `python tools/generate_sd_castle_example.py`. Generation originals, separate source/derived audits, strict 4× output audits, actual browser captures and the artistic review are in [the example record](../../../docs/examples/demon-castle-sd/README.md).
