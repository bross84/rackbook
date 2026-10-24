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
let calls=[], saves=0, failSettings=false;
const context = vm.createContext({el,$,Date,JSON,Number,Boolean,encodeURIComponent,
  cardEls:new Map(),saveDraft(){saves++},api:async(url,options)=>{calls.push([url,options]);
    if(url==='/fatigue-trial/settings') { if(failSettings) throw new Error('Offline'); return {enabled:JSON.parse(options.body).enabled}; }
    return {id:'snapshot',prospective:true}},
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
const button=box.children.find(x=>x.tag==='button');
assert.equal(button.textContent,'Record before first set');
(async()=>{
  await button.events.click();
  const payload=JSON.parse(calls[0][1].body);
  assert.equal(payload.soreness,0); assert.equal(payload.pain,true);
  assert.equal(payload.mode,'strength'); assert.equal(payload.exercise_order,0);
  assert.equal(ex.trialId,'snapshot'); assert.equal(saves,1);
  assert.equal(box.children[0].children[0].textContent,'Trial recorded · Result hidden');
  assert.ok(!JSON.stringify(box).includes('Expected performance'));
  const late={...ex,trialId:null,trialStarted:true}; const lateBox=el('section');
  context.renderTrial(late,lateBox); assert.equal(lateBox.children.find(x=>x.tag==='button').textContent,'Record late entry');
  context.showTrialResults([{id:'snapshot',exercise_template_id:'squat',prediction:'uncertain',observed:'unclassified',prospective:true,
    across_sessions:{status:'insufficient evidence',message:'Still collecting a baseline.'},reasons:['Missing RPE'],evidence:{}}]);
  assert.ok(JSON.stringify($('trialResults')).includes('unclassified'));
  vm.runInContext('trialEnabled=false; renderTrialSetting()',context);
  assert.equal($('trialEnabled').textContent,'Enable model trial');
  assert.equal($('trialSettingState').textContent,'Off · Optional');
  const enabling=$('trialEnabled').events.click();
  assert.equal($('trialEnabled').disabled,true,'prevent duplicate requests while saving');
  await enabling;
  assert.equal($('trialEnabled').attrs['aria-pressed'],'true');
  assert.equal($('trialEnabled').textContent,'Turn off trial');
  failSettings=true;
  await $('trialEnabled').events.click();
  assert.equal($('trialEnabled').attrs['aria-pressed'],'true','failed save retains the saved setting');
  assert.equal($('trialEnabled').disabled,false);
  assert.ok($('trialSettingStatus').textContent.includes('Offline'));
  console.log('Optional trial controls, hidden state, provenance payload, late entry and result rendering passed');
})().catch(err=>{console.error(err);process.exitCode=1});
