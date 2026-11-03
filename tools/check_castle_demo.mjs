// SPDX-License-Identifier: Apache-2.0
// Optional browser integration check. npm install --prefix .work/browser-runtime --no-save playwright
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
let chromium;
try { ({ chromium } = await import('playwright')); }
catch { ({ chromium } = await import('../.work/browser-runtime/node_modules/playwright/index.mjs')); }
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'output/playwright/castle-verified');
const docs = path.join(root, 'docs/examples/demon-castle');
await fs.mkdir(output, { recursive: true });
const url = process.argv[2] || 'http://127.0.0.1:18873/pixelwright/examples/demon-castle/';
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1664, height: 1088 }, deviceScaleFactor: 1 });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
const state = () => page.evaluate(() => JSON.parse(window.render_game_to_text()));
const step = ms => page.evaluate(ms => window.advanceTime(ms), ms);
async function key(key, frames) {
  await page.keyboard.down(key); await step(frames * 1000 / 60); await page.keyboard.up(key);
}
async function capture(name) {
  const image = await page.locator('canvas').screenshot();
  await fs.writeFile(path.join(output, name), image);
  await fs.writeFile(path.join(docs, name), image);
}
try {
  await page.goto(url);
  await page.waitForFunction(() => typeof window.render_game_to_text === 'function');
  await step(0);
  const initial = await state();
  assert.equal(initial.assets.length, 6);
  assert.deepEqual(initial.base, [384, 256]);
  assert.deepEqual(initial.viewport, { scale: 4, x: 64, y: 32, window: [1664, 1088] });
  assert.equal(initial.imageSmoothingEnabled, false);
  await capture('runtime-clean.png');
  await key('ArrowRight', 20);
  const moved = await state();
  assert.equal(moved.player.x, initial.player.x + 20);
  assert.equal(moved.player.y, initial.player.y);
  await page.keyboard.press('r');
  assert.deepEqual((await state()).player, initial.player);
  await key('ArrowUp', 160);
  const wall = await state();
  assert.equal(wall.player.y, 150);
  await page.keyboard.press('r');
  await key('ArrowRight', 54); await key('ArrowUp', 90);
  const npc = await state();
  assert.equal(npc.player.x, 235); assert.equal(npc.player.y, 200);
  await page.keyboard.press('r');
  await key('ArrowRight', 400);
  assert.equal((await state()).player.x, 312);
  await page.keyboard.press('r');
  await key('ArrowLeft', 53); await key('ArrowUp', 24);
  const behind = await state();
  assert.ok(behind.draw_order.indexOf('knight') < behind.draw_order.indexOf('princess'));
  await capture('runtime-depth.png');
  await page.keyboard.press('r');
  await page.keyboard.press('f');
  await page.waitForFunction(() => !!document.fullscreenElement);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => !document.fullscreenElement);
  await page.setViewportSize({ width: 1152, height: 768 });
  await step(0);
  assert.equal((await state()).viewport.scale, 3);
  await capture('runtime-field.png');
  await fs.copyFile(path.join(docs, 'runtime-field.png'), path.join(root, 'docs/images/game-scene.png'));
  await page.setViewportSize({ width: 240, height: 160 });
  await step(0); assert.equal((await state()).viewport.scale, 0);
  await page.setViewportSize({ width: 1664, height: 1088 });
  await page.goto(url + '?fault=1');
  await page.waitForFunction(() => typeof window.render_game_to_text === 'function');
  await step(0); await capture('runtime-injected-errors.png');
  const fault = await state(); assert.equal(fault.fault, true);
  assert.deepEqual(errors, []);
  const record = { status: 'pass', base: initial.base, assets_loaded: initial.assets.sort(),
    initial_player: initial.player, moved_player: moved.player, movement_delta: [20, 0],
    wall_stop: wall.player, npc_stop: npc.player, boundary_x: 312,
    depth_order: behind.draw_order, reset: 'pass', fullscreen: 'pass',
    integer_scales: [4, 3], fractional_downscaling: 'refused',
    console_errors: errors, fault_capture: 'runtime-injected-errors.png' };
  await fs.writeFile(path.join(docs, 'runtime-verification.json'), JSON.stringify(record, null, 2) + '\n');
  console.log(JSON.stringify(record));
} finally { await browser.close(); }
