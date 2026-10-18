const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'..','stress.html'),'utf8');
for(const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);
function el(tag,cls,text) { return {tag,cls,text,attrs:{},children:[],append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},setAttribute(k,v){this.attrs[k]=v;}}; }
function svgNode(tag,attrs,text) { const n=el(tag,null,text); n.attrs=attrs; return n; }
const box=el('section');
const context=vm.createContext({el,svgNode,$:()=>box,date:s=>s,api:async()=>({}),generation:1});
vm.runInContext(html.slice(html.indexOf('  const sorenessNames ='),html.indexOf('  async function selectMovement(')),context);
function text(node) { return [node.text??'',...node.children.map(text)].join(' '); }
function nodes(node) { return [node,...node.children.flatMap(nodes)]; }
const collection={ready:true,sessions:12,required_sessions:12,previous_paired:6,recent_paired:6,required_paired_per_window:5,window_sessions:6,recent_ratings:3,required_recent_ratings:3};
const point={start_time:'2026-10-18',e1rm_lb:285,ts_reps:1,ts_rpe:8,bodyweight_kg:90,working_sets:4,total_reps:16,soreness:0,pain:false};
const sample={status:'declining',message:'Consider one fewer back-off set.',collection,e1rm_change_pct:-5,bw_change_pct:0,relative_change_pct:-5,comparable_sessions:12,baseline_start:'2026-10-01',gap_reset:false,pattern:'squat',reasons:['Matched medians'],points:[point]};
context.renderFatigue(sample);
assert.match(text(box),/Provisional: declining TS trend/);
assert.match(text(box),/-5.0%/);
assert.equal(nodes(box).filter(n=>n.tag==='svg').length,4,'All four observed histories are visual');
assert.ok(nodes(box).filter(n=>n.tag==='circle').some(n=>n.children.some(c=>String(c.text).includes('None'))),'Zero soreness is a plotted observation');
context.renderFatigue({...sample,collection:{...collection,ready:false,sessions:6,previous_paired:0},status:'building_baseline',message:'Collecting your baseline.',e1rm_change_pct:null,bw_change_pct:null,relative_change_pct:null,reasons:[]});
assert.match(text(box),/6 \/ 12 comparable TS sessions/);
assert.match(text(box),/No minimum number of weeks/);
assert.doesNotMatch(text(box),/-5.0%|Consider one fewer|Provisional: declining/);
assert.equal(nodes(box).filter(n=>n.tag==='svg').length,4,'Charts remain visible during collection');
assert.equal(nodes(box).find(n=>n.tag==='progress').value,6);
context.renderFatigue({...sample,collection:{...collection,ready:false,sessions:1},status:'pain_flag',message:'Pain recorded.',e1rm_change_pct:null,gap_reset:true,pattern:null,points:[{start_time:'2026-10-18',soreness:null,pain:true}]});
assert.match(text(box),/Baseline reset/);
assert.match(text(box),/No soreness-pattern mapping/);
assert.match(text(box),/Unrated/);
assert.match(text(box),/Flagged/);
assert.ok(nodes(box).some(n=>n.tag==='text'&&n.text==='!'),'Pain marker does not need a soreness score');
const chart=context.observationChart([
  {start_time:'2026-01-01',e1rm_lb:300},
  {start_time:'2026-01-02',e1rm_lb:301},
  {start_time:'2026-01-03',e1rm_lb:null},
  {start_time:'2026-01-04',e1rm_lb:302},
  {start_time:'2026-01-25',e1rm_lb:290}
],'e1rm_lb','TS', '2026-01-25');
assert.equal(nodes(chart).filter(n=>n.tag==='line'&&n.attrs['stroke-width']===1.5).length,1,'No joined lines across unknowns or 21-day breaks');
assert.equal(nodes(chart).filter(n=>n.tag==='circle').length,4);
assert.equal(nodes(chart).filter(n=>n.tag==='circle'&&n.attrs.fill==='var(--muted)').length,3);
for(const n of nodes(chart))for(const value of Object.values(n.attrs))if(typeof value==='number')assert.ok(Number.isFinite(value));
const soreness=context.observationChart([{...point,soreness:0},{...point,start_time:'2026-10-19',soreness:2}], 'soreness','Soreness',null);
assert.equal(nodes(soreness).filter(n=>n.tag==='line'&&n.attrs['stroke-width']===1.5).length,0,'Ordinal soreness has no interpolated lines');
console.log('Collection gate, four charts, missing values, pain, gap resets and script syntax passed.');
