# Demon Castle field demo

A small RPG Maker-style field assembled from six independent native PNGs. The castle, knight, princess and demon king were generated separately and exported to fixed native grids and one palette. Stone and moss are indexed 16×16 tiles. All six exports pass `game.json`.

| Asset | Native canvas | Category |
| --- | --- | --- |
| `build/stone.png`, `build/moss.png` | 16×16 | tile |
| `build/castle.png` | 192×128 | building |
| `build/knight.png`, `build/princess.png` | 32×48 | character |
| `build/demon-king.png` | 64×64 | boss |

Run a local server from the repository root:

```sh
python -m http.server 8000
```

Open <http://localhost:8000/pixelwright/examples/demon-castle/>. For an installed skill, serve the parent of the `pixelwright/` directory and use the same URL.

- Arrow keys: move the knight.
- **R**: reset position.
- **F**: toggle fullscreen; **Escape**: exit fullscreen.

`field.json` defines a 24×16 tile map, separate object foot anchors and castle collision. `field.js` loads the six PNGs, draws them at 1× onto a 384×256 canvas, sorts objects by foot height, then enlarges the entire canvas once with nearest-neighbor integer scaling. Remaining window space uses the contract's letterbox color. Windows smaller than the native screen show only that color rather than shrinking the art. Static sprites move as objects; walking frames, combat and dialogue are outside this example.

Add `?fault=1` to deliberately draw an off-grid knight and a translucent rectangle. These are negative inputs for `pixel_game.py screen`.

The matching JSON files contain editable palette-token matrices. From the source repository, rebuild their PNGs and checks with:

```sh
python tools/generate_castle_example.py
```

The source repository's [generation and validation record](https://github.com/arden-deq/pixelwright/tree/main/docs/examples/demon-castle) includes original image-tool outputs, exact prompts, raw FAIL reports, derived PASS reports and real browser captures. The installed skill ZIP includes this self-contained demo and native assets.
