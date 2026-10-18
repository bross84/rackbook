const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '..', 'log.html'), 'utf8');
for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
function element(tag, cls, text) {
  return {tag, text, style:{}, children:[], attrs:{}, append(...items) {this.children.push(...items);},
    replaceChildren(...items) {this.children=items;}, setAttribute(k,v) {this.attrs[k]=v;},
    addEventListener(event, fn) {this[event]=fn;}};
}
const squat={id:'sq',title:'Squat'}, bench={id:'bp',title:'Bench'}, press={id:'ohp',title:'Press'}, dead={id:'dl',title:'Deadlift'};
const boxes = new Map([squat,bench,press,dead].map(ex=>[ex.id,element('div')]));
let saves=0;
const context = vm.createContext({draft:{exercises:[squat,bench,press,dead]}, el:element, saveDraft:()=>saves++,
  cardEls:new Map([...boxes].map(([id,box])=>[id,{querySelector:()=>box}]))});
vm.runInContext(html.slice(html.indexOf('  let sorenessPatterns ='), html.indexOf('  function renderWorkout()')), context);
vm.runInContext('sorenessPatterns = {Squat:"squat",Bench:"bench_press",Press:"bench_press",Deadlift:"deadlift"}',context);
for(const ex of [squat,bench,press,dead]) context.renderSoreness(ex,boxes.get(ex.id));
const group=id=>boxes.get(id).children[1];
const buttons=id=>group(id).children[1].children;
const pain=id=>group(id).children[2].children[0];
assert.deepEqual(buttons('sq').map(b=>b.text), ['None','Mild','Moderate','Severe']);
assert.ok(buttons('sq').every(b=>b.attrs['aria-pressed']==='false'));
buttons('sq')[0].click();
assert.equal(context.draft.soreness.squat.level,0);
assert.equal(buttons('sq')[0].attrs['aria-pressed'],'true');
buttons('bp')[2].click();
assert.equal(buttons('ohp')[2].attrs['aria-pressed'],'true','Bench and press share one observation');
pain('bp').checked=true; pain('bp').change();
assert.equal(context.draft.soreness.bench_press.pain,true);
assert.equal(context.draft.soreness.bench_press.level,2);
buttons('sq')[0].click();
assert.equal(context.draft.soreness.squat.level,null);
pain('dl').checked=true; pain('dl').change();
assert.equal(context.draft.soreness.deadlift.level,null);
assert.equal(context.draft.soreness.deadlift.pain,true);
const unmapped=element('div'); context.renderSoreness({title:'Unknown variant'},unmapped);
assert.equal(unmapped.children.length,0,'Do not guess soreness mappings');
assert.equal(saves,5);
console.log('Soreness controls passed');
