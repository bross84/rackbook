// Mock DOM and API only; never writes to Hevy.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'..','log.html'),'utf8');
const source=html.slice(html.indexOf('  async function loadPlannedStart()'),html.indexOf('  async function loadPlannedWorkout('));
function node(tag,cls,text){return {tag,className:cls,textContent:text,children:[],events:{},append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},setAttribute(){},addEventListener(name,fn){this.events[name]=fn;}};}
function find(root,tag){return root.children.flatMap(x=>[...(x.tag===tag?[x]:[]),...find(x,tag)]);}
const plans=[{id:'first',name:'Week 1',active:false,completed:[{session_id:'done'}],weeks:[{sessions:[{id:'done',name:'Day 1',exercises:[{}]},{id:'next',name:'Day 2',exercises:[{}]}]}]},
 {id:'second',name:'Week 2',active:true,completed:[],weeks:[{sessions:[{id:'other',name:'Next week',exercises:[{}]}]}]},
 {id:'blank',name:'Empty week',active:false,completed:[],weeks:[{sessions:[]}]}];
const box=node('section'),calls=[],loads=[],errors=[];
let data=plans,fail=false;
let allowMark=false;
const context=vm.createContext({$:()=>box,el:node,confirm:()=>allowMark,api:async(url,options)=>{calls.push({url,options});if(options&&fail)throw Error('Activation failed');if(url.endsWith('/complete')){const p=data.find(p=>p.id==='first');p.completed.push({session_id:'done'});return structuredClone(p);}return structuredClone(data);},loadPlannedWorkout:async(...args)=>loads.push(args),say:text=>errors.push(text)});
vm.runInContext(source,context);
(async()=>{
 await context.loadPlannedStart();const select=find(box,'select')[0];assert.equal(select.value,'second');
 select.value='first';select.events.change();const day=find(box,'select')[1];assert.equal(day.value,'next');
 assert.equal(day.children[0].disabled,true,'Completed days must be unavailable');
 assert.equal(calls.length,1,'Changing selection must not activate a plan');
 await find(box,'button')[0].events.click();assert.equal(calls.at(-1).url,'/api/mesocycles/first/activate');
 assert.equal(loads[0].join(','),'first,next');assert.equal(select.disabled,false);
 select.value='blank';select.events.change();assert.equal(find(box,'button').length,0);assert.match(find(box,'p')[0].textContent,/No days/);
 select.value='second';select.events.change();fail=true;await find(box,'button')[0].events.click();
 assert.equal(loads.length,1);assert.equal(errors.at(-1),'Activation failed');assert.equal(select.disabled,false);
 data=structuredClone(plans);data.forEach(p=>p.active=false);await context.loadPlannedStart();assert.equal(find(box,'select')[0].value,'first');
 data[0].completed=[];data[0].weeks[0].sessions[0].name='BS-Bridge1.4.1';data[0].weeks[0].sessions[1].name='BS-Bridge1.4.2';
 fail=false;await context.loadPlannedStart();const days=find(box,'select')[1];assert.equal(days.value,'done');
 const before=calls.length;days.value='next';days.events.change();assert.equal(calls.length,before,'Choosing a day must not write progress');
 await find(box,'button')[0].events.click();assert.equal(loads.at(-1).join(','),'first,next');
 assert.equal(data[0].completed.length,0,'Starting on day 2 must leave day 1 uncompleted');
 data[0].weeks[0].sessions[0].exercises=[];await context.loadPlannedStart();assert.equal(find(box,'button').length,1,'Movement-free days still allow recording prior completion');
 const mark=find(box,'button')[0],beforeMark=calls.length;await mark.events.click();assert.equal(calls.length,beforeMark,'Cancelling must not mark completion');
 allowMark=true;await mark.events.click();assert.equal(calls.at(-1).url,'/api/mesocycles/first/sessions/done/complete');
 assert.equal(find(box,'select')[1].value,'next','Recording day 1 completion must advance the default to day 2');
 assert.equal(find(box,'select')[1].children[0].disabled,true);
 const later=find(box,'select')[1];later.value='next';later.events.change();assert.equal(find(box,'button').length,2,'A movement-free earlier day must not prevent selecting a later workout');
 data=[];await context.loadPlannedStart();assert.equal(find(box,'select').length,0);assert.equal(find(box,'a')[0].href,'/microcycles');
 console.log('Log microcycle selection, active default, next pending day, activation, failures and empty states passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
