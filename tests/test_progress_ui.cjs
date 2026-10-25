const assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path'), vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'..','progress.html'),'utf8');
const scripts=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
for(const source of scripts)new vm.Script(source);
for(const [,source] of html.matchAll(/<script src="([^"]+)"/g)) {
  assert.ok(source.startsWith('/static/vendor/'));
  assert.ok(fs.statSync(path.join(__dirname,'..',source)).size>10000);
}
function node(tag='div') {return {tag,textContent:'',children:[],dataset:{},attrs:{},events:{},style:{},hidden:false,offsetWidth:250,offsetHeight:140,value:'',
  append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items;this.textContent=''},
  setAttribute(k,v){this.attrs[k]=v},addEventListener(k,fn){this.events[k]=fn},focus(){this.events.focus?.()},
  querySelectorAll(selector){return walk(this).slice(1).filter(n=>selector==='[data-days]'?n.dataset.days!=null:n.tag===selector)}};}
const walk=n=>[n,...n.children.flatMap(walk)], text=n=>walk(n).map(n=>n.textContent||'').join(' ');
const boxes=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],node()]));
const instances=[];
class ChartStub {
  static registry={plugins:{get:()=>({})}};
  constructor(canvas,config) {this.canvas=canvas;this.options=config.options;this.data=config.data;this.config=config;
    this.chartArea={left:0,right:100,top:0,bottom:100};this.width=800;this.height=260;
    this.scales={x:{min:this.options.scales.x.min,max:this.options.scales.x.max,getValueForPixel:x=>this.options.scales.x.min+(this.options.scales.x.max-this.options.scales.x.min)*x/100}};instances.push(this);}
  update(){this.scales.x.min=this.options.scales.x.min;this.scales.x.max=this.options.scales.x.max;}
  draw(){this.drawn=true;} destroy(){this.destroyed=true;}
}
let requests=[];
const c=vm.createContext({document:{createElement:tag=>node(tag),getElementById:id=>boxes[id]||Object.values(boxes).flatMap(walk).find(n=>n.id===id),documentElement:{}},localStorage:{getItem:()=>null},Chart:ChartStub,
  getComputedStyle:()=>({getPropertyValue:()=> '#667788'}),fetch:()=>new Promise(resolve=>requests.push(resolve))});
vm.runInContext(scripts.at(-1).split('  // Boot.')[0],c);c.initControls();
const DAY=86400000, point=(date,bw=180)=>({date,e1rm_lb:300,bodyweight_lb:bw,dots:bw==null?null:100,
  bodyweight_source_date:bw==null?null:date,bodyweight_age_days:bw==null?null:0,bodyweight_weigh_in_count:bw==null?null:3});
const series=[{...point('2025-08-12',188.5),bodyweight_source_date:'2025-08-01',bodyweight_age_days:11},point('2026-08-01'),point('2026-09-01',null),point('2026-09-30'),point('2026-10-16',169.8)];
const sample={title:'Squat',series};c.render(sample);
assert.equal(instances.length,2);assert.match(text(boxes.stats),/-9.9%/);assert.match(text(boxes.comparison),/188.5 lb → 169.8 lb/);
assert.match(text(boxes.comparison),/2025/);assert.match(text(boxes.comparison),/11 days old/);assert.equal(boxes.sessionCount.textContent,'4 sessions');
for(const chart of instances) {
  assert.equal(chart.options.maintainAspectRatio,false);assert.equal(chart.options.scales.x.type,'linear','Keep elapsed time, not category spacing');
  for(const set of chart.data.datasets)assert.equal(set.spanGaps,false);
  assert.equal(chart.options.plugins.zoom.zoom.pinch.enabled,true);assert.equal(chart.options.plugins.zoom.pan.mode,'x');
}
assert.equal(instances[1].data.datasets[0].data[2].y,null,'Missing scores remain to break lines');
const controls=Object.fromEntries(boxes.zoomControls.children.map(n=>[n.dataset.action,n]));
controls['Zoom in'].events.click();assert.ok(instances[0].options.scales.x.max-instances[0].options.scales.x.min<84*DAY);
assert.equal(instances[0].options.scales.x.min,instances[1].options.scales.x.min,'Charts share zoom');
const beforePan=instances[0].options.scales.x.min;controls.Earlier.events.click();assert.ok(instances[0].options.scales.x.min<beforePan);
assert.match(text(boxes.stats),/-9.9%/,'Zoom preserves overall comparison');controls['Reset zoom'].events.click();assert.equal(boxes.sessionCount.textContent,'5 sessions');
assert.equal(controls.Earlier.disabled,true);assert.equal(controls.Later.disabled,true);assert.equal(controls['Reset zoom'].disabled,true);
// Hover/tap must inspect missing observations rather than silently snap to a different scored date.
const chart=instances[1], position=(Date.parse('2026-09-01')-chart.options.scales.x.min)/(chart.options.scales.x.max-chart.options.scales.x.min)*100;
chart.options.onHover({x:position,y:40},[],chart);assert.match(text(boxes.selectedValues),/Unavailable/);assert.match(text(boxes.scoreTooltip),/Unavailable/);
assert.equal(boxes.sessionSelect.value,'2');assert.equal(boxes.scoreTooltip.hidden,false);
chart.options.onClick({x:position,y:40},[],chart);assert.equal(boxes.sessionSelect.value,'2');
boxes.scoreCanvas.events.keydown({key:'ArrowLeft',preventDefault(){}});assert.equal(boxes.sessionSelect.value,'1');
boxes.scoreCanvas.events.keydown({key:'End',preventDefault(){}});assert.equal(boxes.sessionSelect.value,'4');
boxes.sessionSelect.value='0';boxes.sessionSelect.events.change();assert.match(boxes.selectedSource.textContent,/Aug 1, 2025/);assert.equal(boxes.previousSession.disabled,true);
// A plugin gesture synchronizes both charts without destroying them.
chart.scales.x.min=Date.parse('2026-08-01');chart.scales.x.max=Date.parse('2026-09-30');c.gestureWindow({chart});
assert.equal(instances[0].options.scales.x.max,Date.parse('2026-09-30'));assert.equal(instances.length,2);
const submit=()=>boxes.customRange.events.submit({preventDefault(){}});
boxes.dateFrom.value='2026-10-01';boxes.dateTo.value='2026-09-01';submit();assert.match(boxes.dateError.textContent,/From on or before To/);
boxes.dateFrom.value='2026-07-01';boxes.dateTo.value='2026-07-20';submit();assert.equal(boxes.strengthEmpty.hidden,false);assert.equal(boxes.inspector.hidden,true);assert.match(boxes.strengthCanvas.attrs["aria-label"],/No sessions/);
boxes.dateFrom.value='2026-09-01';boxes.dateTo.value='2026-09-01';submit();assert.equal(boxes.sessionCount.textContent,'1 session');
assert.equal(boxes.strengthEmpty.hidden,true);assert.equal(boxes.scoreEmpty.hidden,false);assert.match(text(boxes.selectedValues),/Unavailable/);assert.equal(controls['Zoom in'].disabled,true);
controls['Reset zoom'].events.click();for(let i=0;i<20;i++)c.zoom(.5);assert.ok(instances[0].options.scales.x.max-instances[0].options.scales.x.min<=DAY+1);
for(let i=0;i<500;i++)c.pan(-1);assert.equal(instances[0].options.scales.x.min,c.domain()[0]);
for(let i=0;i<500;i++)c.pan(1);assert.equal(instances[0].options.scales.x.max,c.domain()[1]);
for(const width of [280,900]) {const ticks=c.dateTicks(Date.parse('2025-12-01'),Date.parse('2026-01-15'),width);assert.equal(new Set(ticks.map(t=>t.value)).size,ticks.length);assert.ok(ticks.length<=(width<500?3:7));}
const previous=instances.slice();c.render({title:'Bench',series:[series[0]]});assert.ok(previous.every(chart=>chart.destroyed));
assert.equal(boxes.sessionCount.textContent,'1 session');assert.equal(controls['Zoom in'].disabled,true);assert.doesNotMatch(text(boxes.periodLabel),/NaN/);
c.render({title:'Press',series:[]});assert.equal(boxes.progress.hidden,true);assert.match(boxes.empty.textContent,/No sets/);
// An older request finishing JSON parsing after a new lift must be ignored.
(async()=>{const old=c.load();assert.equal(boxes.progressLoading.hidden,false,'Loading indicator is visible during requests');let finishOld;requests.shift()({ok:true,json:()=>new Promise(resolve=>{finishOld=resolve})});await new Promise(setImmediate);
  const fresh=c.load();requests.shift()({ok:true,json:async()=>({title:'Newer lift',series:[series[4]]})});await fresh;finishOld(sample);await old;
  assert.match(text(boxes.comparison),/169.8 lb → 169.8 lb/);assert.equal(boxes.sessionCount.textContent,'1 session');
  assert.equal(boxes.progressLoading.hidden,true,'Loading indicator clears after the latest response');
  const failed=c.load();assert.equal(boxes.progressLoading.hidden,false);requests.shift()({ok:false,status:500,json:async()=>({detail:'Server unavailable'})});await failed;
  assert.equal(boxes.progressLoading.hidden,true,'Loading indicator clears after errors');assert.match(text(boxes.status),/Server unavailable/);
  console.log('Chart.js Progress ranges, gestures, real time spacing, gaps, provenance, hover/tap/keyboard, lifecycle and stale-load checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
