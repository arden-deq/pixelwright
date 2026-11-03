# Engine settings for pixel art

Read this when writing game code or import settings for pixel-art assets. The goals are the same in every engine; setting names differ by version, so confirm each one in the engine version in use and check the result with `pixel_game.py screen`.

## Goals

1. Import the 1× PNG. Never import an enlarged review image.
2. Sample textures with nearest-neighbor filtering. Turn off mipmaps and lossy or block compression for sprites, tiles, fonts and UI.
3. Render the game at its base resolution, then enlarge the whole frame by the largest whole number that fits. Fill the remaining window with the letterbox color.
4. Place the camera and every sprite on whole game pixels. Round positions when drawing; keep sub-pixel values only in game logic.
5. Do not rotate or scale individual sprites at runtime. Use pre-drawn rotation frames, 90° turns and flips.
6. Use a bitmap font at its native size without anti-aliasing.
7. Draw particles and effects as sprites on the same grid with palette colors; avoid translucent and additive blending unless the contract allows it.

## Unity (2D)

- Sprite import: Texture Type `Sprite (2D and UI)`, Filter Mode `Point (no filter)`, Compression `None`, Generate Mip Maps off, Pixels Per Unit equal to the tile size. Apply the same to sprite atlases.
- Camera: the Pixel Perfect Camera component with Reference Resolution set to the base resolution and Assets Pixels Per Unit matching the sprites; enable upscaling through a render texture and cropping so the frame scales by whole numbers with bars.
- Snap positions to `1 / pixelsPerUnit`, or enable the camera's pixel snapping.

## Godot 4

- Project Settings: Rendering › Textures › Canvas Textures › Default Texture Filter `Nearest`.
- Display › Window: viewport size equal to the base resolution, Stretch Mode `viewport`, Aspect `keep`, Scale Mode `integer`. The clear color or a background node sets the bar color.
- Rendering › 2D: enable Snap 2D Transforms to Pixel and Snap 2D Vertices to Pixel.
- Texture import: mipmaps off, compression `Lossless`.

## Phaser 3

- Game config `pixelArt: true` (nearest filtering, no antialiasing) and `roundPixels: true`; game width and height equal to the base resolution.
- Choose a whole-number zoom for the window and center the canvas on a page background in the letterbox color, rather than a fit mode that scales by fractions.

## PixiJS

- Default texture scale mode `nearest` and `roundPixels: true` on the renderer.
- Render the stage into a base-resolution render texture, then draw it enlarged by a whole number.

## Web canvas

- Canvas width and height equal to the base resolution; CSS size equal to that times a whole number; CSS `image-rendering: pixelated`.
- `context.imageSmoothingEnabled = false`, and draw at `Math.round` positions.
- Page background in the letterbox color.

## LÖVE

- `love.graphics.setDefaultFilter("nearest", "nearest")` before loading images.
- Draw the game into a base-resolution canvas, then draw that canvas with a whole-number scale and centered offset; round positions with `math.floor`.

## GameMaker

- Turn off interpolating colors between pixels in the game options, and keep texture pages uncompressed.
- Size the application surface or camera view to the base resolution and scale it by a whole number with bars.
