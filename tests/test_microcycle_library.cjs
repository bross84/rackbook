// Local rendering only: no browser, network or Hevy writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'..','mesocycles.html'),'utf8');
function el(tag,cls,text){return {tag,className:cls,textContent:text,children:[],append(...x){this.children.push(...x)},prepend(x){this.children.unshift(x)},replaceChildren(){this.children=[]}}}
const elements=new Map(['library','completedLibrary','completedPlans','completedPlansSummary'].map(id=>[id,el('div')]));
const context=vm.createContext({$:id=>elements.get(id),el,busy:false,plans:[],button:(label,click)=>({...el('button',null,label),click}),openPlan(){},duplicateMicrocycle(){},deleteMicrocycle(){},setMicrocycleActive(){},startUrl:()=>'/log'});
vm.runInContext(html.match(/function nextSession\([^\n]+/)[0]+ '\n'+html.slice(html.indexOf('function renderLibrary()'),html.indexOf('async function refreshPlans()')),context);
const plan=(id,sessions,completed=[])=>({id,name:id,active:false,weeks:[{sessions}],completed});
const day={id:'day',name:'Day 1',exercises:[{}]};
context.plans=[plan('current',[day]),plan('complete',[day],[{session_id:'day'}]),plan('empty',[]),plan('wrong-completion',[day],[{session_id:'old-day'}])];
context.renderLibrary();
const titles=box=>box.children.map(card=>card.children[0].textContent);
assert.deepEqual(titles(elements.get('library')),['current','empty','wrong-completion']);
assert.deepEqual(titles(elements.get('completedLibrary')),['complete']);
assert.equal(elements.get('completedPlans').hidden,false);
assert.equal(elements.get('completedPlansSummary').textContent,'Completed microcycles (1)');
assert.equal(elements.get('completedPlans').open,undefined,'Collapsed by default');
const actions=elements.get('completedLibrary').children[0].children.at(-1).children;
for(const label of ['Edit plan','Duplicate microcycle','Delete'])assert.ok(actions.some(a=>a.textContent===label));
elements.get('completedPlans').open=true;context.renderLibrary();
assert.equal(elements.get('completedPlans').open,true,'Keep expanded state across library refreshes');
context.plans=[plan('current',[day])];context.renderLibrary();
assert.equal(elements.get('completedPlans').hidden,true);assert.equal(elements.get('completedLibrary').children.length,0);
context.plans=[];context.renderLibrary();assert.match(elements.get('library').children[0].textContent,/No plans yet/);
console.log('Completed microcycle grouping, empty plans, actions and collapse state passed.');
