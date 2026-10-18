const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '..', 'log.html'), 'utf8');
function element(tag, cls, text) {
  return {tag, text, style:{}, children:[], attrs:{}, append(...items) {this.children.push(...items);},
    replaceChildren() {this.children=[];}, setAttribute(k,v) {this.attrs[k]=v;},
    addEventListener(event, fn) {this[event]=fn;}};
}
const box = element('div');
let saves=0;
const context = vm.createContext({draft:{}, $:()=>box, el:element, saveDraft:()=>saves++});
vm.runInContext(html.slice(html.indexOf('  function renderSoreness()'), html.indexOf('  function renderWorkout()')), context);
context.renderSoreness();
const groups = () => box.children.slice(2);
const buttons = i => groups()[i].children[1].children;
const pain = i => groups()[i].children[2].children[0];
assert.equal(groups().length,3);
assert.deepEqual(buttons(0).map(b=>b.text), ['None','Mild','Moderate','Severe']);
assert.ok(groups().every((_, i)=>buttons(i).every(b=>b.attrs['aria-pressed']==='false')));
buttons(0)[0].click();
assert.equal(context.draft.soreness.squat.level,0);
assert.equal(buttons(0)[0].attrs['aria-pressed'],'true');
buttons(1)[2].click();
assert.equal(context.draft.soreness.bench_press.level,2);
pain(1).checked=true; pain(1).change();
assert.equal(context.draft.soreness.bench_press.pain,true);
assert.equal(context.draft.soreness.bench_press.level,2);
context.renderSoreness();
assert.equal(pain(1).checked,true);
assert.equal(buttons(0)[0].attrs['aria-pressed'],'true');
buttons(0)[0].click();
assert.equal(context.draft.soreness.squat.level,null);
pain(2).checked=true; pain(2).change();
assert.equal(context.draft.soreness.deadlift.level,null);
assert.equal(context.draft.soreness.deadlift.pain,true);
assert.equal(saves,5);
console.log('Soreness controls passed');
