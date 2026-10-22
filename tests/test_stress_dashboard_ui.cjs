const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'..','stress.html'),'utf8');
for(const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);
function el(tag,cls,text) {return {tag,cls,text,children:[],attrs:{},append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},setAttribute(k,v){this.attrs[k]=v;},addEventListener(){}};}
function svgNode(tag,attrs,text) {const n=el(tag,null,text);n.attrs=attrs;return n;}
function nodes(node) {return [node,...node.children.flatMap(nodes)];}
function text(node) {return nodes(node).map(n=>n.text??'').join(' ');}
const boxes={fatigue:el('section'),detail:el('section'),range:{value:'180'},detailsLink:{},dashboardLink:{}};
const historyCalls=[];
const context=vm.createContext({RackbookCharts:{create:()=>el('canvas')},el,svgNode,$:id=>boxes[id],URLSearchParams,detailsMode:false,
  history:{replaceState:(...args)=>historyCalls.push(args)},location:{hash:''},
  date:s=>s,movements:[{id:'a/b & c',title:'Squat'}],selected:'a/b & c',fmt:v=>v==null?'—':v.toFixed(2),chart:()=>el('svg')});
vm.runInContext(html.slice(html.indexOf('  function stressViewUrl('),html.indexOf('  const results =')),context);
vm.runInContext(html.slice(html.indexOf('  const sorenessNames ='),html.indexOf('  async function loadFatigue(')),context);
context.updateViewLinks('a/b & c');
const detailURL=new URL(boxes.detailsLink.href,'https://example.test');
assert.equal(detailURL.pathname,'/stress/details');
assert.equal(detailURL.searchParams.get('movement'),'a/b & c');
assert.equal(detailURL.searchParams.get('days'),'180');
assert.equal(new URL(boxes.dashboardLink.href,'https://example.test').pathname,'/stress');
assert.equal(historyCalls.at(-1)[2],boxes.dashboardLink.href);
const collection={ready:false,sessions:5,required_sessions:12};
const point={start_time:'2026-10-18',e1rm_lb:300,bodyweight_kg:90,working_sets:4,soreness:0,pain:false};
const sample={collection,status:'building_baseline',message:'Long explanations do not belong on the dashboard',points:[point],baseline_start:'2026-10-18'};
context.renderFatigueDashboard(sample);
assert.match(text(boxes.fatigue),/Collecting baseline/);
assert.match(text(boxes.fatigue),/5 \/ 12/);
assert.equal(nodes(boxes.fatigue).filter(n=>n.tag==='canvas').length,4);
assert.equal(nodes(boxes.fatigue).filter(n=>n.tag==='table'||n.tag==='details').length,0);
assert.doesNotMatch(text(boxes.fatigue),/Long explanations|When interpretations begin|Review related|Unknown|Provisional/);
assert.equal(nodes(boxes.fatigue).find(n=>n.tag==='progress').value,5);
context.renderFatigueDashboard({...sample,collection:{...collection,ready:true,sessions:12},status:'stable',action:'hold'});
assert.match(text(boxes.fatigue),/Current sets held/);
assert.equal(nodes(boxes.fatigue).filter(n=>n.tag==='progress').length,0);
context.renderFatigueDashboard({...sample,status:'pain_flag',message:'Pain reported'});
assert.match(text(boxes.fatigue),/Pain reported/,'Recorded pain remains visible before the baseline gate');
context.renderStressDashboard({current:{rolling_7:{total:4},rolling_28:{total:16}},sessions:[]});
assert.equal(nodes(boxes.detail).filter(n=>n.tag==='svg').length,1);
assert.equal(nodes(boxes.detail).filter(n=>n.tag==='table'||n.tag==='details').length,0);

const initSource=html.slice(html.indexOf('  async function init()'),html.indexOf('  $("relationshipEditor").addEventListener'));
async function checkInitial(requested,detailsMode) {
  const selected=[], overview=[];
  const elements={movement:{replaceChildren(){},append(){}},overview:el('section'),status:el('div'),relationshipEditor:{}};
  const scope=vm.createContext({api:async()=>[{id:'squat',title:'Squat',primary_key:'squat'},{id:'leg',title:'Leg press',primary_key:null}],
    $:id=>elements[id],el,detailsMode,pageParams:new URLSearchParams({movement:requested}),location:{hash:detailsMode?'#relationshipEditor':''},
    movements:[],cards:new Map(),paintCard:()=>{},selectMovement:id=>selected.push(id),loadOverview:()=>overview.push(true),names:{squat:'Squat',bench:'Bench',deadlift:'Deadlift'}});
  vm.runInContext(initSource,scope); await scope.init();
  return {selected,overview,elements};
}
(async()=>{
  const detail=await checkInitial('leg',true);
  assert.deepEqual(detail.selected,['leg']);
  assert.equal(detail.overview.length,0,'Details does not reload all shortcut histories');
  assert.equal(detail.elements.relationshipEditor.open,true);
  const fallback=await checkInitial('missing',false);
  assert.deepEqual(fallback.selected,['squat']);
  assert.equal(fallback.overview.length,1);
  console.log('Visual dashboard, details links, selection/range preservation, pain and direct navigation passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
