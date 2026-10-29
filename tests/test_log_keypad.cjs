// Run with: node tests/test_log_keypad.cjs. Exercises the actual keypad controller without Hevy.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'log.html'), 'utf8');
for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
const keys = [...html.matchAll(/<button[^>]*data-pad-key="([^"]+)"/g)].map(m => m[1]);
assert.deepEqual(keys, ['1', '2', '3', 'backspace', '4', '5', '6', 'clear', '7', '8', '9', 'next', '.', '0', 'done']);
const buttons = Object.fromEntries(keys.map(key => [key, { dataset: { padKey: key }, disabled: false }]));
const handlers = {}, documentHandlers = {}, windowHandlers = {}, timers = [];
const classes = new Set();
let coarse = true, height;
const pad = {
  hidden: true, offsetHeight: 220,
  addEventListener(name, fn) { handlers[name] = fn; },
  querySelector(selector) { return buttons[selector.match(/="([^"]+)"/)[1]]; },
  contains(target) { return Object.values(buttons).includes(target); },
};
const labels = { numberpad: pad, padField: {}, padContext: {} };
const inputs = [];
const doc = {
  activeElement: null,
  body: { classList: { add(c) { classes.add(c); }, remove(c) { classes.delete(c); } }, style: { setProperty(k, v) { height = v; } } },
  querySelectorAll() { return inputs; },
  addEventListener(name, fn) { documentHandlers[name] = fn; },
};
const context = vm.createContext({
  $: id => labels[id], document: doc,
  window: { matchMedia: () => ({ matches: coarse }), addEventListener(name, fn) { windowHandlers[name] = fn; } },
  Event: class { constructor(type) { this.type = type; } },
  requestAnimationFrame: fn => fn(), setTimeout: fn => timers.push(fn), liftIntoView() {},
});
vm.runInContext(html.slice(html.indexOf('  function numberPadEdit('), html.indexOf('  // Other text fields')), context);
function field(value, decimal, name) {
  const events = {};
  const input = {
    value, dataset: {}, selectionStart: 0, selectionEnd: 0, isConnected: true, edits: [],
    addEventListener(name, fn) { events[name] = fn; },
    getAttribute() { return name; },
    focus() { doc.activeElement = this; events.focus(); },
    blur() { doc.activeElement = null; },
    select() { this.selectionStart = 0; this.selectionEnd = this.value.length; },
    setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; },
    dispatchEvent(e) { assert.equal(e.type, 'input'); this.edits.push(this.value); },
    events,
  };
  context.prepareKeypadInput(input, decimal, 'Bench · Set 1'); inputs.push(input);
  return input;
}
function tap(key) { handlers.click({ target: { closest: () => buttons[key] } }); }
function touch(input) { input.events.pointerdown({ pointerType: 'touch' }); input.focus(); }
function edit(value, start, end, key, decimal = true) { return context.numberPadEdit(value, start, end, key, decimal); }
assert.equal(edit('123.5', 3, 3, 'backspace').value, '12.5');
assert.equal(edit('123.5', 1, 3, 'backspace').value, '1.5');
assert.equal(edit('123', 0, 3, '4', false).value, '4');
assert.equal(edit('', 0, 0, 'backspace').value, '');
assert.equal(edit('12.5', 2, 2, '.'), null);
assert.equal(edit('12,5', 2, 2, '.'), null);
assert.equal(edit('5', 1, 1, '.', false), null);

const weight = field('105', true, 'Weight in kilograms');
const reps = field('5', false, 'Reps');
const lastWeight = field('100', true, 'Weight in kilograms');
assert.equal(weight.inputMode, 'none');
touch(weight);
assert.equal(pad.hidden, false); assert.equal(height, '220px');
assert.equal(labels.padField.textContent, 'Weight in kilograms');
assert.equal(buttons['.'].disabled, false);
tap('1'); tap('2'); tap('.'); tap('5');
assert.equal(weight.value, '12.5'); assert.equal(weight.edits.at(-1), '12.5');
tap('backspace'); assert.equal(weight.value, '12.');
tap('next');
assert.equal(doc.activeElement, reps); assert.equal(buttons['.'].disabled, true);
assert.equal(labels.padField.textContent, 'Reps');
tap('8'); tap('.'); assert.equal(reps.value, '8');
tap('backspace'); assert.equal(reps.value, '');
tap('6'); tap('next');
assert.equal(doc.activeElement, lastWeight); assert.equal(buttons.next.disabled, true);
tap('clear'); assert.equal(lastWeight.value, '');
tap('done'); assert.equal(pad.hidden, true); assert.equal(classes.has('keypad-open'), false);

// Mouse input still uses the ordinary desktop keyboard, even on a hybrid device.
weight.events.pointerdown({ pointerType: 'mouse' }); weight.focus();
assert.equal(weight.inputMode, 'decimal'); assert.equal(pad.hidden, true);
touch(weight);
let prevented = false;
handlers.pointerdown({ target: { closest: () => buttons.backspace }, preventDefault() { prevented = true; } });
assert.equal(prevented, true, 'Tapping keys must retain the field caret/selection');
const outside = { target: { closest: () => null } };
documentHandlers.pointerdown(outside);
assert.equal(pad.hidden, false, 'Touching a set control must not shift rows before its click');
doc.activeElement = null;
documentHandlers.focusout();
while (timers.length) timers.shift()();
assert.equal(pad.hidden, false, 'Button focus must not dismiss the pad during the tap');
documentHandlers.click(outside);
assert.equal(pad.hidden, true, 'Dismiss only after the tapped control handles its click');
touch(weight); weight.events.keydown({ key: 'Escape', preventDefault() {} });
assert.equal(pad.hidden, true);
touch(weight); weight.isConnected = false; tap('1'); assert.equal(pad.hidden, true);
coarse = false;
assert.equal(field('', false, 'Reps').inputMode, 'numeric');
console.log('Keypad editing, fixed key order, touch/mouse activation, Next, dismissal and script syntax checks passed.');
