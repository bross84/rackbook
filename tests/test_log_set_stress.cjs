// Run with: node tests/test_log_set_stress.cjs (no browser or Hevy writes).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'log.html'), 'utf8');
const checked = {done:true, type:'normal', kg:'100', reps:'5', rpe:'8', arpe:'7'};
const warmup = {done:false, type:'warmup', kg:'50', reps:'5', rpe:'5'};
const planned = {done:false, type:'normal', kg:'90', reps:'8', rpe:'6', arpe:'9'};
const cells = new Map([checked, warmup, planned].map(s => [s, {}]));
const totals = [0, 1].map(() => ({dataset:{}, value:{setAttribute(k,v) {this[k]=v;}}, querySelector() {return this.value;}}));
const cards = new Map(totals.map((total,i) => [i, {querySelector() {return total;}}]));
const states = new Map([['bench', {result:{
  session:{total:.4}, preview:{total:1.2}, preview_status:'usual', status:'below_usual',
  window:{median:1,lower:.8,upper:1.2},
  preview_set_scores:[{total:.5,estimated_sets:0}, null, {total:.7,estimated_sets:0}],
}}]]);
const context = vm.createContext({
  draft:{startedAt:'2026-10-17T12:00:00Z',exercises:[
    {id:0,template_id:'bench',sets:[checked,warmup]},
    {id:1,template_id:'bench',sets:[planned]},
    {id:2,template_id:'squat',sets:[{done:true}]},
  ]},
  num: v => parseFloat(v), cardEls:cards, stressStates:states,
});
vm.runInContext(html.slice(html.indexOf('  function stressBody('), html.indexOf('  function paintStress(')),context);
vm.runInContext(html.slice(html.indexOf('  const setStressCells ='),html.indexOf('  function queueStress(')),context);
vm.runInContext('globalThis.testCells = setStressCells;',context);
for (const [set,cell] of cells) context.testCells.set(set,cell);
const body = context.stressBody('bench');
assert.equal(body.sets.length,1);
assert.equal(body.preview_sets.length,3);
assert.equal(body.sets[0].rpe,7,'Checked set uses actual RPE');
assert.equal(body.preview_sets[2].rpe,6,'Unchecked set uses target RPE');
context.paintSetStress('bench');
assert.equal(cells.get(checked).textContent,'0.50');
assert.equal(cells.get(warmup).textContent,'—');
assert.equal(cells.get(planned).textContent,'0.70');
assert.match(cells.get(planned).title,/Preview/);
for (const total of totals) {
  assert.equal(total.dataset.status,'usual');
  assert.equal(total.value.textContent,'1.20');
  assert.match(total.title,/Checked stress 0.40/);
  assert.match(total.value['aria-label'],/Within usual range/);
}
states.get('bench').pending=true;
context.paintSetStress('bench');
assert.equal(cells.get(checked).textContent,'…','Do not show an older score while recalculating');
assert.equal(totals[0].dataset.status,'no_sets');
states.get('bench').pending=false;
states.get('bench').error='offline';
context.paintSetStress('bench');
assert.equal(cells.get(checked).textContent,'—');
assert.equal(totals[0].value.textContent,'—');
console.log('Stress preview payloads, duplicate-movement row alignment, totals, pending/error states and accessible bands passed.');

// Pending refreshes retain the rendered summary instead of shrinking the card.
function element(tag, cls, text) {
  return {tag, cls, textContent:text, children:[], dataset:{}, attrs:{},
    append(...children){this.children.push(...children);},
    replaceChildren(){this.children=[];}, setAttribute(k,v){this.attrs[k]=v;},
    querySelector(selector){return this.children.find(child => '.'+child.cls === selector);}};
}
const metric = {total:1,sets:1,estimated_sets:0,skipped_sets:0,peripheral:0,central:0};
const summaryState = {pending:false,result:{session:{...metric},preview:{...metric,sets:2},
  rolling_7:metric,rolling_28:metric,status:'usual',window:{median:1,lower:.8,upper:1.2,sessions:6,days:56}}};
const summaryContext = vm.createContext({el:element,stressStates:new Map([['bench',summaryState]]),
  stressComparison:()=> 'Within usual range'});
vm.runInContext(html.slice(html.indexOf('  function fillStress('),html.indexOf('  function say(')),summaryContext);
const box=element('div','stress');
summaryContext.fillStress(box,'bench');
const rendered=box.children;
summaryState.pending=true;
summaryContext.fillStress(box,'bench');
assert.equal(box.children,rendered,'Pending refresh must retain the summary DOM and height');
assert.equal(box.attrs['aria-busy'],'true');
summaryState.pending=false;
summaryState.result.session.sets=2;
summaryContext.fillStress(box,'bench');
assert.equal(box.attrs['aria-busy'],'false');
assert.equal(box.children.length,rendered.length,'Checking the final set must not remove the preview line');
assert.ok(box.children.some(child=>child.textContent?.endsWith('2/2 sets checked')));
console.log('Stress summary remains in place during refresh and final-set completion.');
