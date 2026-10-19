// Run with: node tests/test_log_rpe_entry.cjs (no packages or Hevy connection).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '..', 'log.html'), 'utf8');
for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) {
  new vm.Script(match[1]);
}

function element(tag, cls, text) {
  return {
    tag, className: cls, textContent: text, value: '', attrs: {}, events: {}, children: [],
    classList: { toggle() {} },
    append(...children) { this.children.push(...children); },
    setAttribute(k, v) { this.attrs[k] = v; },
    removeAttribute(k) { delete this.attrs[k]; },
    setCustomValidity(message) { this.error = message; },
    checkValidity() { return !this.error; },
    reportValidity() { return this.checkValidity(); },
    focus() { this.focused = true; },
    blur() { this.blurred = true; this.events.blur(); },
    addEventListener(name, callback) { this.events[name] = callback; },
  };
}

let picked, pickedCurrent;
const context = vm.createContext({
  unit: 'kg', sorenessPatterns: null,
  el: element,
  RPES: [4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 9.5, 10],
  pickRpe(current, callback) { pickedCurrent = current; picked = callback; },
});
const start = html.indexOf('  function rpeControl(');
const end = html.indexOf('  // A bottom sheet', start);
vm.runInContext(html.slice(start, end), context);
const changes = [];
const control = context.rpeControl('7', v => changes.push(v));
const [input, picker] = control.children;
function type(value) { input.value = value; input.events.input(); }
function key(key) { input.events.keydown({ key, preventDefault() {} }); }

assert.equal(input.value, '7');
type('8'); type('8.'); type('8.5');
assert.equal(input.value, '8.5');
assert.equal(changes.at(-1), '8.5');
key('Enter'); assert.equal(input.blurred, true);
type('9,5'); input.events.blur();
assert.equal(input.value, '9.5');
assert.equal(changes.at(-1), '9.5');

for (const value of ['11', '3.5', '7.2', '7abc', '1e1', '-', '.']) {
  const previous = changes.length;
  type(value);
  assert.equal(control.reportValidity(), false, value);
  assert.equal(input.attrs['aria-invalid'], 'true');
  assert.equal(changes.length, previous, 'Invalid RPE must not update the set');
}
key('Escape');
assert.equal(input.value, '9.5');
assert.equal(control.reportValidity(), true);
type(''); assert.equal(changes.at(-1), '');
type('4'); assert.equal(changes.at(-1), '4');
type('10'); assert.equal(changes.at(-1), '10');

type('11'); picker.events.click();
assert.equal(pickedCurrent, '10');
picked('6.5');
assert.equal(input.value, '6.5');
assert.equal(changes.at(-1), '6.5');
assert.equal(control.reportValidity(), true);
assert.equal(picker.focused, true);
picker.events.click(); picked('');
assert.equal(input.value, '');
assert.equal(changes.at(-1), '');

// The save path must reject an invalid visible edit rather than save its older value.
const row = { done: true, type: 'normal', kg: '100', reps: '3', rpe: '8', arpe: '7.5' };
context.draft = { title: 'Test', startedAt: '2026-10-17T12:00:00Z', exercises: [
  { title: 'Bench', template_id: 'bench', notes: '', sets: [row] },
] };
context.document = { querySelector() { return input.attrs['aria-invalid'] ? input : null; } };
const buildStart = html.indexOf('  function buildEntry()');
const buildEnd = html.indexOf('  $("finish").addEventListener', buildStart);
vm.runInContext(html.slice(buildStart, buildEnd), context);
type('7.2');
assert.throws(() => context.buildEntry(), /Correct the highlighted RPE/);
type('7.5');
const entry = context.buildEntry();
assert.equal(entry.exercises[0].sets[0].rpe, 7.5);
assert.equal(entry.exercises[0].sets[0].weight_kg, 100);
console.log('RPE typing, validation, keyboard, picker and script syntax checks passed.');
