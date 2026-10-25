const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname,'..','log.html'),'utf8');
for (const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(m[1]);
function el(tag,cls,text) {
  return {tag,cls,textContent:text,children:[],attrs:{},style:{},events:{},append(...x){this.children.push(...x)},
    replaceChildren(...x){this.children=x},setAttribute(k,v){this.attrs[k]=v},addEventListener(k,v){this.events[k]=v}};
}
const elements = new Map();
const $ = id => { if(!elements.has(id)) elements.set(id,el('div')); return elements.get(id); };
let calls=[], saves=0, failSettings=false, failSnapshot=false, scheduled;
const context = vm.createContext({el,$,Date,JSON,Number,Boolean,encodeURIComponent,
  setTimeout(fn){scheduled=fn;return 1},clearTimeout(){scheduled=null},renderWorkout(){},
  cardEls:new Map(),saveDraft(){saves++},api:async(url,options)=>{calls.push([url,options]);
    if(url==='/fatigue-trial/settings') { if(failSettings) throw new Error('Offline'); return {enabled:true,preview:false}; }
    if(failSnapshot)throw Error('Offline');return {id:'snapshot',prospective:true}},
  draft:{startedAt:'2026-10-22T15:00:00Z',exercises:[],soreness:{squat:{level:0,pain:true}}},
  sorenessPatterns:{Squat:'squat'}});
vm.runInContext(html.slice(html.indexOf('  let trialEnabled ='),html.indexOf('  let sorenessPatterns =')),context);
const ex={id:'e',title:'Squat',template_id:'squat',sets:[{type:'normal',ts:true,reps:'1',rpe:'8',kg:'100',done:false}]};
context.draft.exercises=[ex];
const box=el('section'); context.renderTrial(ex,box);
assert.equal(box.children.length,0,'disabled by default');
vm.runInContext('trialEnabled=true',context);
context.renderTrial(ex,box);
assert.ok(!box.className.split(' ').includes('stress'),'stress refresh must not overwrite the trial');
assert.equal(box.children.some(x=>x.tag==='button'),false,'No per-movement record button');
assert.equal(typeof scheduled,'function');
(async()=>{
  await context.recordTrialAutomatically(ex);
  const payload=JSON.parse(calls[0][1].body);
  assert.equal(payload.soreness,0); assert.equal(payload.pain,true);
  assert.equal(payload.mode,'strength'); assert.equal(payload.exercise_order,0);
  assert.equal(ex.trialId,'snapshot'); assert.equal(saves,1);
  box.replaceChildren();context.renderTrial(ex,box);
  assert.equal(box.children[0].children[0].textContent,'Trial recorded · Result hidden');
  assert.ok(!JSON.stringify(box).includes('Expected performance'));
  const late={...ex,trialId:null,trialStarted:true}; const lateBox=el('section');
  context.renderTrial(late,lateBox); assert.ok(JSON.stringify(lateBox).includes('not recorded before the first set'));
  context.draft.exercises=[late];const count=calls.length;
  await context.recordTrialAutomatically(late);assert.equal(calls.length,count,'Never record at completion as a pre-set prediction');
  const fresh={...late,trialStarted:false};context.draft.exercises=[fresh];
  context.draft.soreness.squat.level=null;
  await context.recordTrialAutomatically(fresh);assert.equal(calls.length,count,'Unknown soreness is not zero');
  context.draft.soreness.squat.level=0;fresh.sets=[{...ex.sets[0],kg:''}];
  await context.recordTrialAutomatically(fresh);assert.equal(calls.length,count,'Wait for planned weight');
  fresh.sets[0].kg='100';failSnapshot=true;await context.recordTrialAutomatically(fresh);
  assert.equal(fresh.trialId,null);assert.equal(fresh.trialRecordError,'Offline');
  failSnapshot=false;await Promise.all([context.recordTrialAutomatically(fresh),context.recordTrialAutomatically(fresh)]);
  assert.equal(calls.length,count+2,'One failed attempt and one deduplicated retry');
  assert.equal(fresh.trialId,'snapshot');assert.equal(fresh.trialRecordError,undefined);
  await context.recordTrialAutomatically(fresh);assert.equal(calls.length,count+2,'Frozen snapshot is not replaced');
  context.showTrialResults([{id:'snapshot',exercise_template_id:'squat',prediction:'uncertain',observed:'unclassified',prospective:true,
    across_sessions:{status:'insufficient evidence',message:'Still collecting a baseline.'},reasons:['Missing RPE'],evidence:{}}]);
  assert.ok(JSON.stringify($('trialResults')).includes('unclassified'));
  assert.ok(!html.includes('id="trialOptin"'),'Trial controls live in Settings');
  assert.ok(!html.includes('id="trialEnabled"'),'Log still reads the saved setting but cannot toggle it');
  await context.loadTrialPreference();
  assert.equal($('previewNotice').hidden,true);
  assert.equal(calls.at(-1)[0],'/fatigue-trial/settings','Automatic recording still loads the server preference');
  console.log('Automatic trial recording, eligibility, retries, deduplication, hidden state and results passed');
})().catch(err=>{console.error(err);process.exitCode=1});
