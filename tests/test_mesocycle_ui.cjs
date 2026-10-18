// Run with node tests/test_mesocycle_ui.cjs; no browser/network/Hevy writes.
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
const root=path.join(__dirname,'..'), builder=fs.readFileSync(path.join(root,'mesocycles.html'),'utf8'), log=fs.readFileSync(path.join(root,'log.html'),'utf8');
for(const html of [builder,log])for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(m[1]);
let counter=0;
const doc={id:'plan-1',name:'Strength block',completed:[],weeks:[{name:'Week 1',sessions:[
 {id:'a',name:'Day A',exercises:[{exercise_template_id:'squat',title:'Squat',notes:'Controlled reps',sets:[
  {reps:1,rpe:8,weight_kg:null,type:'normal',ts:true},{reps:5,rpe:6,weight_kg:100,type:'normal',ts:false}]}]},
 {id:'b',name:'Day B',exercises:[]}]},{name:'Week 2',sessions:[{id:'c',name:'Day C',exercises:[]}]}]};
const context=vm.createContext({structuredClone,id:()=>String(++counter)});
for(const name of ['cloneSession','nextSession'])vm.runInContext(builder.match(new RegExp('function '+name+'\\([^\\n]+'))[0],context);
context.dirty=false;context.remember=()=>{};context.renderEditor=()=>{};
context.confirm=()=>true;context.message=()=>{};
for(const name of ['session','completed','namingNumber','applyNaming','newPlan','addDay','removeDay','duplicateMicrocycle','recoverLegacyEditor'])vm.runInContext(builder.match(new RegExp('function '+name+'\\([^\\n]+'))[0],context);
context.newPlan();assert.equal(context.plan.weeks.length,1);assert.equal(context.plan.weeks[0].sessions.length,0);
context.addDay();context.addDay();assert.equal(context.plan.weeks[0].sessions.length,2);
context.si=0;context.removeDay();assert.equal(context.plan.weeks[0].sessions[0].name,'Day 2');
context.addDay();assert.equal(context.plan.weeks[0].sessions[1].name,'Day 1');
context.removeDay();context.removeDay();assert.equal(context.plan.weeks[0].sessions.length,0);
context.removeDay();assert.equal(context.plan.weeks[0].sessions.length,0);
const single=structuredClone(doc);single.weeks=[single.weeks[0]];single.completed=[{session_id:'a'}];single.active=true;single.revision=3;
context.duplicateMicrocycle(single);assert.equal(context.plan.id,undefined);assert.equal(context.plan.completed.length,0);assert.equal(context.plan.revision,0);
assert.notEqual(context.plan.weeks[0].sessions[0].id,'a');assert.equal(single.weeks[0].sessions[0].id,'a');
const named=structuredClone(single);Object.assign(named,{program_name:'BS-Bridge',cycle:1,week:1,completed:[]});context.applyNaming(named);
assert.equal(named.weeks[0].sessions[0].name,'BS-Bridge1.1.1');assert.equal(named.weeks[0].sessions[1].name,'BS-Bridge1.1.2');
const incomplete=structuredClone(named);incomplete.cycle=null;incomplete.week=null;context.applyNaming(incomplete);
assert.equal(incomplete.name,'BS-Bridge?.?');assert.equal(incomplete.weeks[0].sessions[0].name,'BS-Bridge?.?.1');
assert.equal(incomplete.cycle,null,'Preview must preserve the blank field');
incomplete.cycle=2;context.applyNaming(incomplete);assert.equal(incomplete.name,'BS-Bridge2.?');
incomplete.week=3;context.applyNaming(incomplete);assert.equal(incomplete.weeks[0].sessions[0].name,'BS-Bridge2.3.1');
for(const value of [0,-1,1.5,10000,NaN,''])assert.equal(context.namingNumber(value),'?');
assert.equal(context.namingNumber(undefined),1,'Older drafts still default to cycle/week 1');
const controls=new Map(), restored=structuredClone(named);restored.cycle=null;restored.week=null;
const restoreContext=vm.createContext({plan:restored,dirty:true,applyNaming:context.applyNaming,renderWeeks(){},renderSession(){},$:key=>{if(!controls.has(key))controls.set(key,{});return controls.get(key);}});
vm.runInContext(builder.match(/function renderEditor\([^\n]+/)[0],restoreContext);restoreContext.renderEditor();
assert.equal(controls.get('cycleNumber').value,'');assert.equal(controls.get('weekNumber').value,'');
assert.equal(controls.get('planName').value,'BS-Bridge?.?','Restored drafts must replace old null text and retain blank inputs');
context.duplicateMicrocycle(named);assert.equal(context.plan.week,2);assert.equal(context.plan.cycle,1);
assert.equal(context.plan.name,'BS-Bridge1.2');assert.equal(context.plan.weeks[0].sessions[0].name,'BS-Bridge1.2.1');
assert.equal(named.week,1);assert.equal(named.weeks[0].sessions[0].name,'BS-Bridge1.1.1');
context.plan.cycle=2;context.plan.week=1;context.applyNaming(context.plan);assert.equal(context.plan.weeks[0].sessions[0].name,'BS-Bridge2.1.1');
context.si=0;context.removeDay();context.applyNaming(context.plan);assert.equal(context.plan.weeks[0].sessions[0].name,'BS-Bridge2.1.1');
context.addDay();context.applyNaming(context.plan);assert.equal(context.plan.weeks[0].sessions[1].name,'BS-Bridge2.1.2');
context.plan.completed=[{session_id:context.plan.weeks[0].sessions[1].id}];context.si=0;context.removeDay();assert.equal(context.plan.weeks[0].sessions.length,2,'Removing an earlier day must not renumber a completed workout');
const legacy=structuredClone(doc);legacy.weeks[1].sessions[0].exercises=structuredClone(legacy.weeks[0].sessions[0].exercises);
const recovery=context.recoverLegacyEditor({plan:legacy,wi:0});assert.equal(recovery.length,2);assert.equal(recovery[1].weeks.length,1);
assert.equal(recovery[1].weeks[0].sessions[0].exercises.length,1);assert.equal(recovery[1].completed.length,0);
const copy=context.cloneSession(doc.weeks[0].sessions[0]);
assert.notEqual(copy.id,'a');assert.equal(copy.name,'Day A');
copy.exercises[0].sets[0].rpe=9;assert.equal(doc.weeks[0].sessions[0].exercises[0].sets[0].rpe,8);
assert.equal(context.nextSession(doc).s.id,'a');
doc.completed=[{session_id:'a'}];assert.equal(context.nextSession(doc).s.id,'b');
doc.completed.push({session_id:'b'});assert.equal(context.nextSession(doc).s.id,'c');
doc.completed.push({session_id:'c'});assert.equal(context.nextSession(doc),null);
doc.completed=[];
let snapshots=0, loaded=[];
const logContext=vm.createContext({
 draft:null, api:async()=>structuredClone(doc), uid:()=>String(++counter),
 refFromServer:()=>({basis:'tm',ls:true}),saveDraft:()=>snapshots++,say(){},renderWorkout(){},
 loadState:ex=>loaded.push(ex.template_id),confirm:()=>false,
 document:{querySelector:()=>null},
});
vm.runInContext(log.slice(log.indexOf('  async function loadPlannedWorkout('),log.indexOf('  async function loadPlannedQuery(')),logContext);
vm.runInContext(log.slice(log.indexOf('  function buildEntry()'),log.indexOf('  $("finish").addEventListener')),logContext);
(async()=>{
 await logContext.loadPlannedWorkout('plan-1','a');
 const draft=logContext.draft;
 assert.equal(draft.planned_session.session_id,'a');assert.equal(draft.planLabel,'Strength block · Day A');
 assert.equal(draft.exercises[0].ref.basis,'tm');
 const sets=draft.exercises[0].sets;
 assert.equal(sets[0].manual,false);assert.equal(sets[0].kg,'');assert.equal(sets[0].ts,true);
 assert.equal(sets[1].manual,true);assert.equal(sets[1].kg,'100');
 assert.equal(sets.every(s=>!s.done),true);assert.equal(loaded[0],'squat');
 await logContext.loadPlannedWorkout('plan-1','a');assert.equal(snapshots,1,'Reload must preserve an existing matching draft');
 await assert.rejects(logContext.loadPlannedWorkout('plan-1','b'),/needs movements/);
 sets[0].done=true;sets[0].kg='120';
 const payload=logContext.buildEntry();
 assert.equal(payload.planned_session.session_id,'a');assert.equal(payload.exercises[0].sets.length,1);
 assert.equal(payload.exercises[0].sets[0].ts,true);
 doc.completed=[{session_id:'a'}];logContext.draft=null;
 await assert.rejects(logContext.loadPlannedWorkout('plan-1','a'),/already completed/);
 doc.completed=[];doc.name='BS-Bridge1.2';doc.weeks[0].sessions[0].name='BS-Bridge1.2.1';
 await logContext.loadPlannedWorkout('plan-1','a');assert.equal(logContext.draft.title,'BS-Bridge1.2.1');
 logContext.draft.exercises[0].sets[0].done=true;logContext.draft.exercises[0].sets[0].kg='120';
 assert.equal(logContext.buildEntry().title,'BS-Bridge1.2.1','Generated name must reach the Hevy save payload');
 console.log('Mesocycle sequencing, independent copies, log draft/loading, fixed/auto weights, TS, checked-only save linkage and script syntax passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
