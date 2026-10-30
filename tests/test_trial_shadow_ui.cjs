const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'..','trial.html'),'utf8');
function node(tag,text){return {tag,textContent:text??'',children:[],value:'',attrs:{},append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},setAttribute(k,v){this.attrs[k]=v}};}
const elements=new Map();
const get=id=>{if(!elements.has(id))elements.set(id,node('div'));return elements.get(id);};
get('movement').value='squat';get('cohort').value=JSON.stringify(['shared-trial-v0','strength']);get('range').value='0';
const context=vm.createContext({document:{getElementById:get,createElement:tag=>node(tag)},
 RackbookCharts:{create:()=>node('chart')},Date,console});
const code=html.slice(html.indexOf("'use strict';"),html.indexOf("$('movement').addEventListener"));
vm.runInContext(code,context);
const text=n=>[n.textContent,...n.children.map(text)].join(' ');
const original={id:'old',exercise_template_id:'squat',title:'Squat',status:'completed',model_version:'shared-trial-v0',mode:'strength',
 workout_start:'2026-10-30T15:00:00Z',recorded_at:'2026-10-30T14:55:00Z',prediction:'uncertain',observed:'unclassified',reasons:[],notes:[],prospective:true};
const smoother={model_version:'hf-recovery-shadow-v1',source_model_version:'recovery-confirmation-v1',
 recommendation_label:'Continue Training as Normal',recommendation_detail:'Insufficient data to recommend a change.',assessed_at:'2026-10-30T14:55:00Z'};
context.fixture={entries:[original,{...original,id:'new',shadow:smoother}],cohorts:[]};
vm.runInContext('dashboard=fixture;renderDashboard()',context);
assert.ok(text(get('sessions')).includes('Expected: Uncertain'));
assert.ok(text(get('sessions')).includes('Actual: Unclassified'));
assert.ok(text(get('sessions')).includes('Original trial result preserved'));
assert.ok(text(get('sessions')).includes(smoother.recommendation_label));
assert.ok(text(get('shadow-summary')).includes('1 saved observations'));
context.fixture={entries:[{...original,status:'recorded',shadow:{...smoother,recommendation_label:'Large Decrease'}}],cohorts:[]};
vm.runInContext('dashboard=fixture;renderDashboard()',context);
assert.ok(!text(get('sessions')).includes('Large Decrease'));
assert.ok(!text(get('shadow-summary')).includes('Large Decrease'));
assert.ok(text(get('pending')).includes('Result hidden'));
console.log('Shadow trial UI passed: separate action labels, preserved legacy results, historical absence, hidden unsaved outputs.');
