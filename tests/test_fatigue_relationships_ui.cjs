const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '..', 'stress.html'), 'utf8');
function el(tag, cls, text) {
  return {tag, cls, textContent:text ?? '', attrs:{}, children:[], events:{},
    append(...items) {this.children.push(...items);}, replaceChildren(...items) {this.children=items;},
    setAttribute(key,value) {this.attrs[key]=value;}, addEventListener(event, fn) {this.events[event]=fn;}};
}
const box=el('div'), editor=el('details'); editor.scrollIntoView=()=>{};
const calls=[], reloads=[];
let fail=false;
const context=vm.createContext({el, $:id=>id==='relationshipEditor'?editor:box, selected:'squat', generation:2,
  loadFatigue:(...args)=>reloads.push(args), api:async(path, options)=>{
    calls.push({path,options});
    if(fail)throw Error('offline');
    if(options)return {patterns:JSON.parse(options.body).patterns};
    return [{exercise_template_id:'leg',title:'Leg press',reviewed:false,patterns:[],suggested_patterns:['squat']}];
  }});
vm.runInContext(html.slice(html.indexOf('  const patternLabels ='), html.indexOf('  const sorenessNames =')), context);
function nodes(node) {return [node,...node.children.flatMap(nodes)];}
function input(row, value) {return nodes(row).find(n=>n.tag==='input'&&n.value===value);}
function button(row) {return nodes(row).find(n=>n.tag==='button');}
function text(row) {return nodes(row).map(n=>n.textContent).join(' ');}
(async()=>{
  const item={exercise_template_id:'leg/one',title:'Leg press',reviewed:false,patterns:[],suggested_patterns:['squat']};
  const row=context.relationshipRow(item);
  assert.equal(input(row,'squat').checked,true,'Suggestion is preselected');
  assert.equal(calls.length,0,'Rendering a suggestion cannot save it');
  assert.match(text(row),/Unreviewed/);
  input(row,'deadlift').checked=true;
  await button(row).events.click();
  assert.equal(calls[0].path,'/fatigue/relationships/leg%2Fone');
  assert.deepEqual(JSON.parse(calls[0].options.body).patterns,['squat','deadlift']);
  assert.match(text(row),/Confirmed: Squat, Deadlift/);
  assert.deepEqual(reloads,[['squat',2]]);
  for(const n of nodes(row).filter(n=>n.tag==='input'))n.checked=false;
  await button(row).events.click();
  assert.deepEqual(JSON.parse(calls[1].options.body).patterns,[]);
  assert.match(text(row),/Confirmed: Not related/);
  fail=true; input(row,'squat').checked=true;
  await button(row).events.click();
  assert.equal(input(row,'squat').checked,true,'Failed save retains choices');
  assert.equal(button(row).disabled,false);
  assert.match(text(row),/Could not save/);
  assert.equal(reloads.length,2,'A failed save must not refresh analysis');
  const reviewed=context.relationshipRow({...item,reviewed:true,patterns:[]});
  assert.equal(input(reviewed,'squat').checked,false,'Explicit empty mapping takes precedence over a suggestion');
  await context.loadRelationships();
  assert.match(text(box),/Could not load relationships/);
  fail=false; await context.loadRelationships();
  assert.match(text(box),/Leg press/);
  const summary=context.renderFatigueContext({latest_exercise_days:8,reference_exercise_days:3,current_exercise_days:0,
    latest_pattern_days:null,reference_pattern_days:3,latest_related_sets_7:null,reference_related_sets_7:0,
    block_reasons:['Longer break'],pending_mappings:[{title:'Leg press'}]});
  assert.match(text(summary),/8.0 days/);
  assert.match(text(summary),/Unknown/);
  assert.match(text(summary),/Usual: 0/);
  assert.match(text(summary),/Longer break/);
  await button(summary).events.click();
  assert.equal(editor.open,true);
  const pending=[], rendered=[];
  const raceBox=el('div');
  const race=vm.createContext({$:()=>raceBox,el,generation:1,api:()=>new Promise(resolve=>pending.push(resolve)),renderFatigue:value=>rendered.push(value)});
  vm.runInContext('let fatigueGeneration=0;'+html.slice(html.indexOf('  async function loadFatigue('),html.indexOf('  async function selectMovement(')),race);
  const old=race.loadFatigue('squat',1), fresh=race.loadFatigue('squat',1);
  pending[1]('new analysis'); await fresh;
  pending[0]('stale analysis'); await old;
  assert.deepEqual(rendered,['new analysis'],'A pre-save response cannot overwrite refreshed context');
  console.log('Relationship suggestions, explicit confirmation, empty mappings, errors and context rendering passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
