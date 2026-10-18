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
for(const name of ['session','completed','newPlan','addDay','removeDay','duplicateMicrocycle','recoverLegacyEditor'])vm.runInContext(builder.match(new RegExp('function '+name+'\\([^\\n]+'))[0],context);
context.newPlan();assert.equal(context.plan.weeks.length,1);assert.equal(context.plan.weeks[0].sessions.length,0);
context.addDay();context.addDay();assert.equal(context.plan.weeks[0].sessions.length,2);
context.si=0;context.removeDay();assert.equal(context.plan.weeks[0].sessions[0].name,'Day 2');
context.addDay();assert.equal(context.plan.weeks[0].sessions[1].name,'Day 1');
context.removeDay();context.removeDay();assert.equal(context.plan.weeks[0].sessions.length,0);
context.removeDay();assert.equal(context.plan.weeks[0].sessions.length,0);
const single=structuredClone(doc);single.weeks=[single.weeks[0]];single.completed=[{session_id:'a'}];single.active=true;single.revision=3;
context.duplicateMicrocycle(single);assert.equal(context.plan.id,undefined);assert.equal(context.plan.completed.length,0);assert.equal(context.plan.revision,0);
assert.notEqual(context.plan.weeks[0].sessions[0].id,'a');assert.equal(single.weeks[0].sessions[0].id,'a');
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
 console.log('Mesocycle sequencing, independent copies, log draft/loading, fixed/auto weights, TS, checked-only save linkage and script syntax passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
