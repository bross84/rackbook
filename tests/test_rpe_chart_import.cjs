const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '..', 'rpe_charts.html'), 'utf8');
for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
function node(tag) {
  return {tag,children:[],attrs:{},style:{},events:{},textContent:'',
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},
    setAttribute(k,v){this.attrs[k]=v;},addEventListener(k,fn){this.events[k]=fn;}};
}
const ids = new Map(['importBridge','importStatus','status','view','lifts'].map(id=>[id,node('div')]));
const calls=[];
let fail=false;
const data={exercise_template_id:'group:squat',cells:[],estimated:[{rpe:10,reps:11,estimated:.7}],
  sets_used:15,ts_sets:0,gate:{passed:true,sets:15,workouts:3,k_span:5},fit:null,
  sources:[{title:'Low-bar squat',local_sets:5,imported_sets:7},{title:'Paused squat',local_sets:3,imported_sets:0}]};
const context=vm.createContext({document:{getElementById:id=>ids.get(id),createElement:node},
  localStorage:{setItem(){}},fetch:async(path,options)=>{
    calls.push({path,options});
    if(path==='/rpe-history/import-bs-bridge') return {ok:!fail,json:async()=>fail?{detail:'Read failed'}:
      {sets_imported:7,sessions_imported:2,local_sessions_preserved:1,sessions_already_imported:0}};
    if(path==='/rpe-observed')return {ok:true,json:async()=>[{key:'squat',title:'Squat',exercise_template_id:'low',sets:15}]};
    if(path==='/rpe-observed/group/squat')return {ok:true,json:async()=>data};
    throw Error('Unexpected request '+path);
  }});
const start=html.indexOf('  const $ ='),end=html.lastIndexOf('  init();');
vm.runInContext(html.slice(start,end),context);
vm.runInContext('current="squat"',context);
const all=n=>[n,...(n.children||[]).flatMap(c=>typeof c==='object'?all(c):[])];
const text=n=>[n.textContent,...(n.children||[]).map(c=>typeof c==='object'?text(c):c)].join(' ');
(async()=>{
  await ids.get('importBridge').events.click();
  assert.equal(calls[0].options.method,'POST');
  assert.match(ids.get('importStatus').textContent,/Imported 7 rated sets/);
  assert.match(ids.get('importStatus').textContent,/Kept 1 exact local sessions/);
  assert.equal(ids.get('importBridge').disabled,false);
  assert.ok(calls.some(c=>c.path==='/rpe-observed/group/squat'),'Refresh the grouped chart, not one template');
  assert.match(text(ids.get('view')),/Low-bar squat: 5 exact local sets \+ 7 imported sets/);
  assert.match(text(ids.get('view')),/Paused squat: 3 exact local sets \+ 0 imported sets/);
  assert.ok(all(ids.get('view')).some(n=>n.tag==='th'&&n.textContent==='11'),'Display estimated columns beyond ten reps');
  fail=true;
  const previous=ids.get('view').children;
  await ids.get('importBridge').events.click();
  assert.match(ids.get('importStatus').textContent,/Read failed.*retry/);
  assert.equal(ids.get('importBridge').disabled,false);
  assert.equal(ids.get('view').children,previous,'A failed import keeps the current chart');
  console.log('RPE import, exact sources, grouped refresh, estimates, retry and script syntax passed.');
})().catch(err=>{console.error(err);process.exitCode=1;});
