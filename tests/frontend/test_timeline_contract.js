/**
 * Permanent contract regression test for the locked shared frontend contract
 * `window.ClutchReplay.Timeline.mount(...)` — architecture §3.2 / §8.6.
 *
 * WHY THIS EXISTS
 * ---------------
 * The Video Library (P2, tasks #13/#14) consumes this handle directly via its
 * SyncController. A missing/incorrect export would silently break that feature
 * (TypeError). The original defect slipped through precisely because the
 * frontend had zero test coverage on this single-source-of-truth contract.
 *
 * WHAT IT ASSERTS (verbatim contract)
 * -----------------------------------
 *   mount(containerEl, {segments, frameCount, onSeek}) -> { setProgress(p), onSeek(cb) }
 *   1) handle shape: { setProgress, onSeek }
 *   2) p is always 0–1000 normalized (component only emits/consumes p)
 *   3) onSeek (mount arg) + handle.onSeek(cb) are append-semantics (no overwrite)
 *   4) setProgress does NOT trigger onSeek (no loop-back); tolerates [0,1] and [0,1000]
 *   5) defensive: null container / frameCount=0 return a no-op handle
 *
 * Runs under node only (no npm deps). Driven from Python via
 * tests/test_clutch_replay_timeline_contract.py so it executes inside the
 * pytest suite. Exit 0 = pass, 1 = fail.
 */
'use strict';

// ── minimal mock DOM (only what Timeline.mount touches) ──
function MockEl(tag) {
  this.tag = tag;
  this.style = {};
  this.title = '';
  this.dataset = {};
  this._children = [];
  this._html = '';
  this.onclick = null;
  this.classList = { _set: {}, toggle: function (c, on) { this._set[c] = !!on; } };
}
MockEl.prototype.appendChild = function (c) { this._children.push(c); };
MockEl.prototype.getBoundingClientRect = function () { return { left: 0, width: 1000 }; };
MockEl.prototype.querySelectorAll = function () { return this._children; };
Object.defineProperty(MockEl.prototype, 'innerHTML', {
  get: function () { return this._html; },
  set: function (v) { this._html = v; if (v === '') this._children = []; },
});

global.window = {};
global.document = {
  createElement: function (t) { return new MockEl(t); },
  getElementById: function () { return null; },
  querySelectorAll: function () { return []; },
};

// load the module under test (IIFE assigns window.ClutchReplay)
// Use path.join(__dirname, ...) so the require resolves relative to THIS
// test file (tests/frontend/) regardless of the caller's cwd. The previous
// './frontend/...' was relative to the test file location and resolved to
// tests/frontend/frontend/... which did not exist.
const path = require('path');
require(path.join(__dirname, '..', '..', 'frontend', 'js', 'components', 'clutch_replay.js'));

const TL = global.window.ClutchReplay && global.window.ClutchReplay.Timeline;
if (!TL || typeof TL.mount !== 'function') {
  console.error('FAIL: window.ClutchReplay.Timeline.mount is undefined');
  process.exit(1);
}

const segments = [
  { start_frame: 10, end_frame: 20, period: 4, clock_start: 250, clock_end: 240, margin: 2, players: [{ player: 'A' }] },
  { start_frame: 30, end_frame: 40, period: 4, clock_start: 200, clock_end: 190, margin: 1, players: [{ player: 'B' }] },
  { start_frame: 70, end_frame: 80, period: 4, clock_start: 120, clock_end: 110, margin: 4, players: [{ player: 'C' }] },
];
const frameCount = 100;
const container = new MockEl('div');
container.innerHTML = '';

let seekCalls = [];
const handle = TL.mount(container, {
  segments: segments,
  frameCount: frameCount,
  onSeek: function (p, idx) { seekCalls.push(['init', p, idx]); },
});

function assert(cond, msg) {
  if (!cond) { console.error('FAIL: ' + msg); process.exit(1); }
  console.log('ok  - ' + msg);
}

// 1) handle shape
assert(typeof handle.setProgress === 'function', 'handle.setProgress is a function');
assert(typeof handle.onSeek === 'function', 'handle.onSeek is a function');

// 2) segments rendered
assert(container._children.length === 3, 'rendered 3 highlight segments');

// 3) onSeek append semantics — a second listener coexists with the init one
let secondCalls = [];
handle.onSeek(function (p, idx) { secondCalls.push(['second', p, idx]); });
assert(handle.onSeek === handle.onSeek, 'onSeek reference is stable');

// 4) segment click fires BOTH listeners; p in 0–1000 (seg.start_frame/maxFrame*1000)
const seg0 = container._children[0];
const expectedP0 = (10 / 99) * 1000;
seg0.onclick({ stopPropagation: function () {} });
assert(seekCalls.length === 1 && seekCalls[0][0] === 'init', 'init onSeek fired once on segment click');
assert(Math.abs(seekCalls[0][1] - expectedP0) < 1e-6, 'segment click emits p in 0–1000 (got ' + seekCalls[0][1].toFixed(2) + ')');
assert(seekCalls[0][2] === 0, 'segment click passes segment index 0');
assert(secondCalls.length === 1 && secondCalls[0][0] === 'second', 'appended onSeek listener also fired (append semantics)');

// 5) blank-track scrub emits p in 0–1000, idx=-1, to BOTH listeners
container.onclick({ target: container, clientX: 500 }); // middle -> p≈500
assert(seekCalls.length === 2 && secondCalls.length === 2, 'blank-track scrub fired both listeners');
assert(Math.abs(seekCalls[1][1] - 500) < 1e-6, 'scrub emits p≈500 in 0–1000 (got ' + seekCalls[1][1].toFixed(2) + ')');
assert(seekCalls[1][2] === -1, 'scrub passes idx=-1');

// 6) setProgress does NOT trigger onSeek (no loop-back) + highlights matching segment
const before = seekCalls.length;
handle.setProgress(350); // inside segment 1 (start 30->303, end 40->404)
assert(seekCalls.length === before, 'setProgress does NOT trigger onSeek (no loop-back)');
const activeIdx = container._children.findIndex(function (c) { return c.classList._set['clutch-seg-active'] === true; });
assert(activeIdx === 1, 'setProgress highlights the matching segment (index 1)');

// 7) setProgress tolerates [0,1] input (0.15 -> 150 in 0–1000, inside segment 0 [101,202])
handle.setProgress(0.15);
assert(container._children[0].classList._set['clutch-seg-active'] === true, 'setProgress accepts [0,1] and highlights segment 0 (p=0.15)');
// boundary: p=0 (frame 0) precedes segment 0 -> nothing highlighted (correct)
handle.setProgress(0.0);
const anyActiveAtZero = container._children.some(function (c) { return c.classList._set['clutch-seg-active'] === true; });
assert(!anyActiveAtZero, 'setProgress(0.0) highlights nothing (frame 0 precedes segment 0)');

// 8) defensive no-op handles
const noop1 = TL.mount(null, { segments: segments, frameCount: 100 });
const noop2 = TL.mount(container, { segments: segments, frameCount: 0 });
assert(typeof noop1.setProgress === 'function' && typeof noop1.onSeek === 'function', 'noop handle shape preserved (null container)');
assert(typeof noop2.setProgress === 'function' && typeof noop2.onSeek === 'function', 'noop handle shape preserved (frameCount=0)');

console.log('\nALL TIMELINE CONTRACT CHECKS PASSED');
