const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '..', 'log.html'), 'utf8');
function el(tag, cls, text) {
  return {tag, cls, textContent:text, children:[], attrs:{}, style:{}, events:{},
    classList:{toggle(){}}, append(...items){this.children.push(...items);},
    setAttribute(k,v){this.attrs[k]=v;}, addEventListener(k,fn){this.events[k]=fn;}};
}
const noop=()=>{};
let saved=0, rests=0, redraws=0;
const context=vm.createContext({el, unit:'kg', trim:String, stepOf:()=>2.5, makeReorderable:noop,
  restLabel:String, restFor:()=>60, renderRefBar:()=>el('div'), renderSoreness:noop,
  queueStress:noop,fillStress:noop,kindOf:s=>s.type,KIND:{warmup:'W'},
  prepareKeypadInput:noop,primaryText:s=>s.kg,refText:()=>'',primaryInputs:new Map(),refCells:new Map(),
  rpeControl:()=>({reportValidity:()=>true}),setE1rm:()=>null,setE1Cells:new Map(),setStressCells:new Map(),
  makeSwipeable:noop,renderLoader:()=>el('div'),applyAuto:noop,saveDraft:()=>saved++,
  showRpe:noop,restStart:()=>rests++,closeNumberPad:noop,renderWorkout:()=>redraws++,setTimeout:noop});
vm.runInContext(html.slice(html.indexOf('  function exerciseComplete('), html.indexOf('  function tickClock()')),context);
const nodes=n=>[n,...(n.children||[]).flatMap(x=>typeof x==='object'?nodes(x):[])];
const ticks=card=>nodes(card).filter(n=>n.cls==='tick');
const toggle=card=>nodes(card).find(n=>n.attrs['aria-expanded']!==undefined);
const section=(card,cls)=>nodes(card).find(n=>n.cls===cls);
const set=done=>({type:'normal',kg:'100',reps:'5',rpe:'7',done});
const ex={title:'Squat',ref:{state:null},sets:[set(false),set(false)]};
let card=context.renderExercise(ex);
ticks(card)[1].events.click();
assert.equal(Boolean(ex.collapsed),false,'Checking last row first must not collapse unfinished work');
ticks(card)[0].events.click();
assert.equal(ex.collapsed,true);
assert.equal(section(card,'exleft').hidden,true);
assert.equal(section(card,'exright').hidden,true);
assert.equal(toggle(card).textContent,'Reopen');
assert.equal(toggle(card).attrs['aria-expanded'],'false');
assert.equal(rests,2,'Completion still starts the rest timer');
card=context.renderExercise(ex);
assert.equal(section(card,'exright').hidden,true,'Collapsed state survives redraw');
toggle(card).events.click();
assert.equal(ex.collapsed,false);
assert.equal(section(card,'exright').hidden,false);
card=context.renderExercise(ex);
assert.equal(section(card,'exright').hidden,false,'Reopened completed cards stay open');
ticks(card)[0].events.click();
assert.equal(ex.sets[0].done,false);
assert.equal(Boolean(ex.collapsed),false);
ticks(card)[0].events.click();
assert.equal(ex.collapsed,true,'Completing the exercise again collapses it');
toggle(card).events.click();
const add=nodes(card).find(n=>n.textContent==='+ Add set'); add.events.click();
assert.equal(ex.collapsed,false);
assert.equal(ex.sets.length,3);
assert.equal(ex.sets[2].done,false);
assert.equal(redraws,1);
assert.equal(context.exerciseComplete({sets:[]}),false);
assert.equal(context.exerciseComplete({sets:[{type:'warmup',done:true}]}),false);
assert.equal(context.exerciseComplete({sets:[set(true),{type:'warmup',done:false}]}),true);
console.log('Exercise completion, automatic collapse, reopening, redraw persistence and add-set checks passed.');
