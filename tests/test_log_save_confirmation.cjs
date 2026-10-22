const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '..', 'log.html'), 'utf8');
for (const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(m[1]);
const elements = new Map();
let focused, posts = 0, cleared = 0, shown, errorMessage, resolvePost, rejectPost;
function element() {
  return {style:{}, events:{}, open:false, setAttribute(){}, textContent:'', disabled:false,
    addEventListener(name, fn){this.events[name]=fn;}, replaceChildren(...items){this.children=items;},
    focus(){focused=this;}, showModal(){this.open=true;},
    close(){this.open=false; this.events.close?.();}, querySelector(){return get('doneMessage');}};
}
const get = id => {if(!elements.has(id)) elements.set(id,element()); return elements.get(id);};
const draft = {title:'Test <workout>', startedAt:'2026-10-21T10:00:00Z', exercises:[{
  title:'Squat', template_id:'sq', sets:[
    {done:true,type:'normal',kg:'100',reps:'1',rpe:'8',ts:true},
    {done:false,type:'normal',kg:'80',reps:'5',rpe:'5'},
    {done:false,type:'failure',kg:'80',reps:'5',rpe:'5'},
    {done:false,type:'warmup',kg:'20',reps:'5',rpe:''}]}]};
const context = vm.createContext({document:{createElement:element,body:{append(e){elements.set('dialog',e);}},querySelector(){return null;}},
  $:get,draft,unit:'kg',sorenessPatterns:null,saving:false,
  api(){posts++;return new Promise((resolve,reject)=>{resolvePost=resolve;rejectPost=reject;});},
  clearDraft(){cleared++;},show(x){shown=x;},say(x){errorMessage=x;},window:{scrollTo(){}}});
vm.runInContext(html.slice(html.indexOf('  function buildEntry()'), html.indexOf('  // ── Rest timer')),context);
async function run(){
  const before=JSON.stringify(draft);
  get('finish').events.click();
  assert.equal(posts,0);
  assert.equal(get('saveWorkoutName').textContent,'Test <workout>');
  assert.match(get('saveSetCount').textContent,/^1 completed/);
  assert.match(get('saveExcludedCount').textContent,/^2 unticked/);
  assert.equal(get('saveExcludedSets').children.length,2);
  assert.equal(focused,get('keepTraining'));
  get('finish').events.click();
  assert.equal(posts,0);
  get('keepTraining').events.click();
  assert.equal(get('dialog').open,false);
  assert.equal(JSON.stringify(draft),before);
  await get('confirmSave').events.click();
  assert.equal(posts,0,'Closed dialog cannot submit');
  get('finish').events.click();
  get('dialog').close(); // Native Escape closes the dialog through the same close event.
  assert.equal(JSON.stringify(draft),before);
  get('finish').events.click();
  let pending=get('confirmSave').events.click();
  get('finish').events.click();
  await get('confirmSave').events.click();
  assert.equal(posts,1);
  assert.equal(get('finish').disabled,true);
  rejectPost(new Error('Network failed'));
  await pending;
  assert.equal(cleared,0);
  assert.equal(JSON.stringify(draft),before);
  assert.match(errorMessage,/workout is still here/);
  assert.equal(get('finish').disabled,false);
  get('finish').events.click();
  pending=get('confirmSave').events.click();
  resolvePost({}); await pending;
  assert.equal(posts,2);assert.equal(cleared,1);assert.equal(shown,'done');
  console.log('Save confirmation checks passed');
}
run().catch(err=>{console.error(err);process.exitCode=1;});
