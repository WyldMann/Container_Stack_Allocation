"use strict";

const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const path = require("node:path");
const {test} = require("node:test");
const vm = require("node:vm");

const context = {};
vm.runInNewContext(readFileSync(path.join(__dirname, "../stacking_ui/static/yard-map.js"), "utf8"), context);
const layout = context.layoutYardBlocks;
const block = (code, x, y, slots = 6, rows = 4) => ({code, x, y, slots, rows});
const coordinates = result => Object.fromEntries(Array.from(result.rectangles, item =>
  [item.block.code, {left: item.left, top: item.top, width: item.width, height: item.height}]));

function checkLayout(blocks) {
  const result = layout(blocks);
  assert.equal(result.rectangles.length, blocks.length);
  assert.equal(new Set(result.rectangles.map(item => item.block)).size, blocks.length);
  assert.ok(Number.isFinite(result.width) && Number.isFinite(result.height));
  for (const [index, a] of result.rectangles.entries()) {
    assert.ok(a.left >= 16 && a.top >= 16);
    assert.ok(a.left + a.width <= result.width - 16);
    assert.ok(a.top + a.height <= result.height - 16);
    for (const b of result.rectangles.slice(index + 1)) {
      assert.ok(a.left + a.width + 22 <= b.left || b.left + b.width + 22 <= a.left ||
        a.top + a.height + 22 <= b.top || b.top + b.height + 22 <= a.top,
      "Missing gap between " + a.block.code + " and " + b.block.code);
    }
  }
  return result;
}

test("empty and single-block maps have finite padded bounds", () => {
  const empty = layout([]);
  assert.equal(empty.rectangles.length, 0);
  assert.equal(empty.width, 32);
  assert.equal(empty.height, 32);
  checkLayout([block("A", -100, 800)]);
});

test("large coordinate distances do not enlarge a two-block schematic", () => {
  for (const axis of ["x", "y"]) {
    const nearby = [block("A", 0, 0), {...block("B", 0, 0), [axis]: 100}];
    const distant = [nearby[0], {...nearby[1], [axis]: 1e9}];
    assert.deepEqual(coordinates(checkLayout(nearby)), coordinates(checkLayout(distant)));
  }
});

test("small offsets still produce aligned rows and columns", () => {
  const result = checkLayout([
    block("1A", 387, 277, 26, 6), block("2A", 1204, 283, 26, 6),
    block("1B", 384, 409, 26, 6), block("2B", 1199, 417, 26, 6),
    block("1C", 382, 553, 26, 6), block("2C", 1208, 553, 26, 6),
  ]);
  const p = coordinates(result);
  for (const row of ["A", "B", "C"]) {
    assert.equal(p["1" + row].left, p["1A"].left);
    assert.equal(p["2" + row].left, p["2A"].left);
    assert.equal(p["1" + row].top, p["2" + row].top);
  }
  assert.ok(p["1A"].top < p["1B"].top && p["1B"].top < p["1C"].top);
});

test("a wider lower block stays aligned without pushing apart the upper row", () => {
  const p = coordinates(checkLayout([
    block("3A", 723, 67, 44, 6), block("2A", 2194, 68, 12, 6),
    block("1A", 2611, 74, 10, 6), block("1B", 2205, 270, 20, 6),
  ]));
  assert.equal(p["2A"].left, p["1B"].left);
  assert.equal(p["2A"].top, p["1A"].top);
  assert.equal(p["1A"].left, p["2A"].left + p["2A"].width + 22);
  assert.ok(p["1B"].top >= p["2A"].top + p["2A"].height + 22);
});

test("shared coordinates form a compact cluster with stable block order", () => {
  const blocks = Array.from({length: 16}, (_, i) => block("B" + i, 0, 0, 4 + i % 3, 3 + i % 5));
  const result = checkLayout(blocks);
  const verticalHeight = result.rectangles.reduce((height, item) => height + item.height + 22, 0);
  assert.ok(result.height < verticalHeight / 2);
  assert.ok(new Set(result.rectangles.map(item => item.left)).size > 1);
  assert.deepEqual(coordinates(result), coordinates(checkLayout([...blocks].reverse())));
});

test("layout preserves source coordinates and does not depend on occupancy", () => {
  const blocks = [block("A", -50, -100), block("B", 90, 50), block("C", 300, -95)];
  const original = JSON.stringify(blocks);
  const initial = checkLayout(Object.freeze(blocks.map(item => Object.freeze(item))));
  assert.equal(JSON.stringify(blocks), original);
  const occupied = checkLayout(blocks.map(item => ({...item, occupied_tiers: 100, container_count: 100})));
  assert.deepEqual(coordinates(initial), coordinates(occupied));
  assert.deepEqual(coordinates(initial), coordinates(checkLayout([...blocks].reverse())));
  const translated = checkLayout(blocks.map(item => ({...item, x: item.x * 100 + 9000, y: item.y * 100 - 7000})));
  assert.deepEqual(coordinates(initial), coordinates(translated));
});

test("irregular mixed-size yards retain every block without collisions", () => {
  let seed = 8273;
  const random = limit => {seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed % limit;};
  for (let scenario = 0; scenario < 12; scenario++) {
    const blocks = Array.from({length: 35}, (_, index) => block("B" + index,
      random(8) * 1000 + random(8), random(7) * 1000 + random(8), 1 + random(44), 1 + random(35)));
    checkLayout(blocks);
  }
});
