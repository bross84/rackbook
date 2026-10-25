// Unit choices, canonical kg and rounding; no browser/network/Hevy writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'..','log.html'),'utf8'),factor=2.20462262185;
for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(m[1]);
const c=vm.createContext({unit:'kg',LB_PER_KG:factor,trim:n=>String(Number(n.toFixed(2))),refs:{curl:{basis:'e1rm',ls:true,tm_pct:.95,weight_unit:'lb'}},primaryInputs:new Map(),refCells:new Map(),document:{activeElement:null}});
vm.runInContext(html.slice(html.indexOf('  const lbOfKg ='),html.indexOf("  // One set's e1RM"))+'\nthis.unitFor=unitFor;this.stepOf=stepOf;this.primaryText=primaryText;this.refText=refText;',c);
const curl={template_id:'curl',title:'Incline curl',ref:{...c.defaultRef(),weightUnit:'lb'},sets:[{kg:String(25/factor),done:true},{kg:'12.5',manual:true},{kg:'',done:false}]};
const squat={template_id:'squat',title:'Squat',ref:c.defaultRef(),sets:[{kg:'100',done:true}]};
assert.equal(c.primaryText(curl.sets[0],curl),'25');assert.equal(c.unitFor(squat.ref),'kg');
assert.equal(c.refFromServer('curl').weightUnit,'lb');assert.equal(c.refFromServer('unknown').weightUnit,null);
assert.ok(Math.abs(c.plannedKg(80,curl.ref)*factor-80)<1e-8);assert.equal(c.plannedKg(80,squat.ref),37.5);
assert.equal(c.stepOf(curl.ref),5);assert.equal(c.stepOf(squat.ref),2.5);
let saves=0,persisted,menu;
Object.assign(c,{draft:{exercises:[curl,squat]},closeNumberPad(){},saveDraft(){saves++},saveRef:ex=>persisted=ex.ref.weightUnit,renderWorkout(){},autoWeight:ex=>c.plannedKg(80,ex.ref),el:(tag,cls,text)=>({textContent:text,attrs:{},setAttribute(k,v){this.attrs[k]=v},addEventListener(k,fn){this[k]=fn}}),openSheet:(title,desc,items,columns,callback)=>menu={items,callback}});
vm.runInContext(html.slice(html.indexOf('  function applyAuto('),html.indexOf('  function refreshCard(')),c);
vm.runInContext(html.slice(html.indexOf('  function setExerciseUnit('),html.indexOf('  function exerciseComplete(')),c);
const original=curl.sets.slice(0,2).map(s=>s.kg);
c.setExerciseUnit(curl,'kg');assert.deepEqual(curl.sets.slice(0,2).map(s=>s.kg),original,'Done/manual weights never change');
assert.equal(curl.sets[2].kg,'37.5');assert.equal(squat.sets[0].kg,'100');assert.equal(persisted,'kg');
c.setExerciseUnit(curl,'lb');assert.ok(Math.abs(Number(curl.sets[2].kg)*factor-80)<.00001);
c.unit='lb';assert.equal(c.unitFor(squat.ref),'lb');assert.equal(c.unitFor({weightUnit:'kg'}),'kg');
const control=c.exerciseUnitControl(curl);assert.equal(control.attrs['aria-label'],'Weight unit for Incline curl');control.click();
assert.equal(menu.items.map(x=>x.v).join(','),'page,kg,lb');menu.callback('page');assert.equal(curl.ref.weightUnit,null);assert.equal(persisted,null);
assert.ok(saves>=3);
// The upload carries each pinned choice separately from the page default.
Object.assign(c,{sorenessPatterns:null,document:{querySelector:()=>null},draft:{title:'Mixed',startedAt:'2026-10-25T10:00:00Z',exercises:[{...curl,ref:{weightUnit:'lb'},sets:[{type:'normal',kg:String(25/factor),reps:'10',rpe:'7',done:true}]},{...squat,ref:{weightUnit:'kg'},sets:[{type:'normal',kg:'100',reps:'5',rpe:'8',done:true}]}]}});
vm.runInContext(html.slice(html.indexOf('  function buildEntry()'),html.indexOf('  const saveDialog =')),c);
const entry=c.buildEntry();assert.equal(entry.weight_unit,'lb');assert.equal(entry.exercises[0].weight_unit,'lb');assert.equal(entry.exercises[1].weight_unit,'kg');assert.equal(entry.exercises[1].sets[0].weight_kg,100);
console.log('Per-exercise units, conversion, rounding, unchanged logged weights, menu and mixed upload passed.');
