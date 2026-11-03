// SPDX-License-Identifier: Apache-2.0
// Import only native 1x assets. Enlarge the complete world once, with integer pixels.
const canvas = document.querySelector('canvas');
const ctx = canvas.getContext('2d', { alpha: false });
const [layout, contract] = await Promise.all([
  fetch('field.json').then(r => { if (!r.ok) throw Error('Missing field.json'); return r.json(); }),
  fetch('game.json').then(r => { if (!r.ok) throw Error('Missing game.json'); return r.json(); }),
]);
const assets = {};
await Promise.all(Object.keys(layout.pivots).map(async name => {
  const image = new Image();
  image.src = `build/${name}.png`;
  await image.decode();
  assets[name] = image;
}));
const world = document.createElement('canvas');
[world.width, world.height] = layout.base;
const pen = world.getContext('2d', { alpha: false });
pen.imageSmoothingEnabled = false;
const keys = new Set();
const objects = structuredClone(layout.objects);
const player = objects.find(o => o.asset === 'knight');
const initial = { x: player.x, y: player.y };
const fault = new URLSearchParams(location.search).get('fault') === '1';
let manualTime = false;
let remainder = 0;
let viewport;

function blocked(x, y) {
  if (x < 72 || x > 312 || y < 142 || y > 245) return true;
  if (layout.collision.some(r => x + 5 > r.x && x - 5 < r.x + r.width &&
      y + 2 > r.y && y - 5 < r.y + r.height)) return true;
  return objects.some(o => o !== player && o.asset !== 'castle' &&
    Math.abs(x - o.x) < 13 && Math.abs(y - o.y) < 8);
}

function update(dt) {
  remainder += dt * 60;
  const steps = Math.floor(remainder + 1e-9);
  remainder = Math.max(0, remainder - steps);
  for (let frame = 0; frame < steps; frame++) {
    // A native-pixel step per frame avoids subpixel coordinates and interpolation.
    const dx = Number(keys.has('ArrowRight')) - Number(keys.has('ArrowLeft'));
    const dy = Number(keys.has('ArrowDown')) - Number(keys.has('ArrowUp'));
    if (!blocked(player.x + dx, player.y)) player.x += dx;
    if (!blocked(player.x, player.y + dy)) player.y += dy;
  }
}

function draw() {
  pen.fillStyle = contract.letterbox;
  pen.fillRect(0, 0, world.width, world.height);
  for (let y = 0; y < layout.tiles.length; y++) {
    for (let x = 0; x < layout.tiles[y].length; x++) {
      pen.drawImage(assets[layout.tiles[y][x]], x * layout.tile_size, y * layout.tile_size);
    }
  }
  // Sort by foot position, so sprites can walk behind or in front of each other.
  for (const object of [...objects].sort((a, b) => a.y - b.y)) {
    const [px, py] = layout.pivots[object.asset];
    pen.drawImage(assets[object.asset], object.x - px, object.y - py);
  }
  const dpr = window.devicePixelRatio || 1;
  const width = Math.round(innerWidth * dpr), height = Math.round(innerHeight * dpr);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width; canvas.height = height;
  }
  const scale = Math.floor(Math.min(width / world.width, height / world.height));
  const x = Math.floor((width - world.width * scale) / 2);
  const y = Math.floor((height - world.height * scale) / 2);
  viewport = { scale, x, y, window: [width, height] };
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = contract.letterbox;
  ctx.fillRect(0, 0, width, height);
  if (scale < 1) return; // Never shrink the art with a fractional scale.
  ctx.drawImage(world, x, y, world.width * scale, world.height * scale);
  if (fault) {
    // Deliberately bad runtime draws for the README's negative audit example.
    ctx.drawImage(assets.knight, x + 290 * scale + 2, y + 173 * scale,
      assets.knight.width * scale, assets.knight.height * scale);
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.fillRect(x + 266 * scale, y + 215 * scale, 12 * scale, 8 * scale);
  }
}

addEventListener('keydown', event => {
  if (event.key.startsWith('Arrow')) { keys.add(event.key); event.preventDefault(); }
  if (event.key === 'Escape' && document.fullscreenElement) document.exitFullscreen().catch(console.error);
  if (event.key.toLowerCase() === 'r') { Object.assign(player, initial); remainder = 0; draw(); }
  if (event.key.toLowerCase() === 'f') {
    (document.fullscreenElement ? document.exitFullscreen() : canvas.requestFullscreen()).catch(console.error);
  }
});
addEventListener('keyup', event => keys.delete(event.key));
addEventListener('blur', () => keys.clear());
addEventListener('resize', draw);
window.advanceTime = ms => { manualTime = true; update(ms / 1000); draw(); };
window.render_game_to_text = () => JSON.stringify({
  mode: 'field', coordinates: 'native game pixels; top-left origin; x right, y down; objects use foot anchors',
  base: layout.base, viewport, imageSmoothingEnabled: ctx.imageSmoothingEnabled,
  player: { x: player.x, y: player.y }, objects, assets: Object.keys(assets),
  draw_order: [...objects].sort((a, b) => a.y - b.y).map(o => o.asset),
  collision: layout.collision, fault,
});
let previous = performance.now();
function frame(now) {
  if (!manualTime) update(Math.min((now - previous) / 1000, 0.05));
  previous = now; draw(); requestAnimationFrame(frame);
}
draw(); canvas.focus(); requestAnimationFrame(frame);
