// Read-only dashboard: no browser, network or Hevy writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'..','trial.html'),'utf8');
for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(m[1]);
const code=html.slice(html.indexOf('function category('),html.indexOf('function dateText('));
const context=vm.createContext({Date,JSON});vm.runInContext(code,context);
const rows=[{exercise_template_id:'s',status:'completed',model_version:'v1',mode:'strength',workout_start:'2026-10-24T10:00:00Z',prediction:'uncertain',observed:'unclassified',soreness:0,daily:{status:'available',ratings:{tiredness:0,perceived_recovery:null}}},
 {exercise_template_id:'s',status:'recorded',model_version:'v1',workout_start:'2026-10-24T10:00:00Z'},
 {exercise_template_id:'s',status:'completed',model_version:'v2',mode:'strength',workout_start:'2026-10-24T10:00:00Z'},
 {exercise_template_id:'s',status:'completed',model_version:'v1',mode:'hypertrophy',workout_start:'2026-10-24T10:00:00Z'}];
const selected=context.filteredEntries(rows,'s',JSON.stringify(['v1','strength']),56,Date.parse('2026-10-25'));
assert.equal(selected.length,1,'Pending, versions and modes stay separate');
const point=context.trialPoints(selected)[0];
assert.equal(point.expected,null);assert.equal(point.actual,null);assert.equal(point.soreness,0);assert.equal(point.tiredness,0);assert.equal(point.recovery,null);
assert.equal(context.category('near_usual'),1);assert.equal(context.category('below_usual'),0);
rows[0].daily.status='stale';assert.equal(context.trialPoints([rows[0]])[0].tiredness,null,'Stale daily ratings are not treated as same-day observations');
assert.equal(context.filteredEntries(rows,'s',JSON.stringify(['v1','strength']),7,Date.parse('2026-12-25')).length,0);
assert.equal(context.filteredEntries(rows,'s',JSON.stringify(['v1','strength']),0,Date.parse('2026-12-25')).length,1);
console.log('Trial dashboard filtering, missing values, scales and script syntax passed.');
