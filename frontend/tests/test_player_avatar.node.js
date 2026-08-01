'use strict';

/**
 * Independent QA acceptance test for frontend/js/components/player_avatar.js
 * ---------------------------------------------------------------------------
 * Pure-function lock-down. Run with:
 *   node frontend/tests/test_player_avatar.node.js
 *
 * Covers the acceptance matrix mandated by the task:
 *   A1) ok path        -> <img src="/headshots/{id}"> + onerror fallback
 *   A2) degrade ①      -> headshot_status != 'ok' -> initials div (1-2 letters)
 *   A3) degrade ②      -> missing/undefined headshot fields -> initials, NEVER blank
 *   A4) single name     -> "Kobe" -> 1-2 letter initials
 *   A5) deterministic   -> same player_id -> same background color (hash stable)
 */

const assert = require('node:assert');
const avatar = require('../js/components/player_avatar.js');

const { renderPlayerAvatar, avatarInitialsHTML, colorForId, computeInitials } = avatar;

let passed = 0;
let failed = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    passed++;
    console.log('  \u2713 ' + name);
  } catch (e) {
    failed++;
    failures.push({ name, message: e.message });
    console.log('  \u2717 ' + name + '  -> ' + e.message);
  }
}

/** Extract the inner text of the single root <div> returned by avatarInitialsHTML. */
function divInner(html) {
  const m = html.match(/^<div[^>]*>([\s\S]*?)<\/div>$/);
  if (!m) throw new Error('expected a single root <div>, got: ' + html);
  return m[1];
}

console.log('player_avatar.js — independent node unit tests\n');

// ── A1) ok path ─────────────────────────────────────────────────────────────
test('A1 ok path: renders <img src="/headshots/{id}"> with onerror fallback', () => {
  const bio = { player_id: 'ervinju01', name: 'Julius Erving', headshot_status: 'ok', headshot_path: '/x.jpg' };
  const html = renderPlayerAvatar(bio, { size: 'sm' });
  assert.ok(typeof html === 'string' && html.length > 0, 'returns non-empty string');
  assert.ok(html.includes('/headshots/ervinju01'), 'src must be /headshots/ervinju01');
  assert.ok(html.includes('onerror='), 'must include onerror fallback to initials');
  assert.ok(html.includes('class="player-avatar-img"'), 'must use player-avatar-img class');
  assert.ok(!html.includes('player-avatar-initials'), 'must NOT render initials div when image ok');
});

// ── A2) degrade ①: status !== 'ok' ─────────────────────────────────────────
test('A2 degrade when headshot_status != ok -> initials div, "Julius Erving"->"JE"', () => {
  const bio = { player_id: 'ervinju01', name: 'Julius Erving', headshot_status: 'missing', headshot_path: '/x.jpg' };
  const html = renderPlayerAvatar(bio, { size: 'sm' });
  assert.ok(html.includes('player-avatar-initials'), 'should render initials fallback');
  const ini = divInner(html).trim();
  assert.ok(/^[A-Z]{1,2}$/.test(ini), 'initials must be 1-2 uppercase letters, got: ' + JSON.stringify(ini));
  assert.strictEqual(ini, 'JE', 'Julius Erving -> JE');
});

// ── A3) degrade ②a: headshot_path undefined (status ok) ─────────────────────
test('A3a degrade when headshot_path is undefined -> initials, never blank', () => {
  const bio = { player_id: 'lebronjames', name: 'LeBron James', headshot_status: 'ok', headshot_path: undefined };
  const html = renderPlayerAvatar(bio, { size: 'sm' });
  assert.ok(html.includes('player-avatar-initials'), 'should render initials when path missing');
  assert.ok(!html.includes('/headshots/'), 'should NOT render image when path missing');
  const ini = divInner(html).trim();
  assert.ok(ini.length >= 1 && ini.length <= 2, 'initials must be non-blank 1-2 chars, got: ' + JSON.stringify(ini));
});

// ── A3) degrade ②b: bio entirely lacks headshot fields ──────────────────────
test('A3b degrade when bio has NO headshot fields -> initials, never blank', () => {
  const bio = { player_id: 'kobebryant', name: 'Kobe Bryant' };
  const html = renderPlayerAvatar(bio, { size: 'sm' });
  assert.ok(html.includes('player-avatar-initials'), 'should still render initials');
  assert.ok(!html.includes('/headshots/'), 'no image when no headshot fields');
  const ini = divInner(html).trim();
  assert.ok(ini.length >= 1 && ini.length <= 2, 'initials must be non-blank, got: ' + JSON.stringify(ini));
});

// ── A3) degrade ②c: null / empty bio (no throw, never blank) ───────────────
test('A3c degrade when bio is null -> safe initials div, no throw', () => {
  const html = renderPlayerAvatar(null, { size: 'sm' });
  assert.ok(html.includes('player-avatar-initials'), 'null bio still yields initials div');
  assert.ok(divInner(html).trim().length >= 1, 'never blank even for null bio');
});

// ── A4) single name ──────────────────────────────────────────────────────────
test('A4 single-word name "Kobe" -> 1-2 letter initials', () => {
  const bio = { player_id: 'kobebryant', name: 'Kobe' };
  const html = renderPlayerAvatar(bio, { size: 'sm' });
  const ini = divInner(html).trim();
  assert.ok(/^[A-Z]{1,2}$/.test(ini), 'single name initials 1-2 letters, got: ' + JSON.stringify(ini));
  assert.strictEqual(computeInitials('Kobe'), 'KO', 'computeInitials("Kobe") -> KO');
});

// ── A5) deterministic color ───────────────────────────────────────────────────
test('A5 deterministic color: same player_id -> same background (hash stable)', () => {
  const c1 = colorForId('ervinju01');
  const c2 = colorForId('ervinju01');
  assert.ok(/^#[0-9a-fA-F]{6}$/.test(c1), 'color is a hex string, got: ' + c1);
  assert.strictEqual(c1, c2, 'same id -> same color');
  const bio = { player_id: 'ervinju01', name: 'Julius Erving', headshot_status: 'missing' };
  const h1 = renderPlayerAvatar(bio, { size: 'lg' });
  const h2 = renderPlayerAvatar(bio, { size: 'lg' });
  const bg1 = h1.match(/background:([^"]+)/)[1];
  const bg2 = h2.match(/background:([^"]+)/)[1];
  assert.strictEqual(bg1, bg2, 'rendered background color stable across calls');
});

// ── Extra: name resolution + size class + square option ──────────────────────
test('EXTRA name field preferred + size class + square option', () => {
  const h1 = renderPlayerAvatar({ player_id: 'p1', name: 'Michael Jordan', headshot_status: 'missing' }, { size: 'md' });
  assert.ok(h1.includes('player-avatar-initials md'), 'size md class applied');
  assert.ok(divInner(h1).includes('MJ'), 'uses name field -> MJ');

  const h2 = renderPlayerAvatar({ player_id: 'p2', name: 'LeBron James', headshot_status: 'missing' }, { size: 'md', rounded: false });
  assert.ok(h2.includes('player-avatar-initials md square'), 'square class when rounded:false');

  const h3 = avatarInitialsHTML({ player_id: 'ervinju01', name: 'Julius Erving' }, { size: 'lg' });
  assert.ok(h3.includes('player-avatar-initials lg'), 'avatarInitialsHTML honors size lg');
});

console.log('');
console.log(`RESULT  PASS: ${passed}  FAIL: ${failed}`);
if (failed > 0) {
  console.log('Failures:');
  for (const f of failures) console.log('  - ' + f.name + ': ' + f.message);
  process.exit(1);
}
console.log('ALL TESTS PASSED');
