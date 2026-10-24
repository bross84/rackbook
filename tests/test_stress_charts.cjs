// No browser, network or Hevy writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function node(tag){return {tag,children:[],dataset:{},style:{},attributes:{},listeners:{},isConnected:true,clientWidth:500,offsetWidth:200,offsetHeight:80,
 append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=nodes;},setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,fn){this.listeners[k]=fn;}};}
const instances=[],frames=[];let cleanup;
class ChartStub {
 constructor(canvas,config){Object.assign(this,config);this.canvas=canvas;this.scales={x:{min:config.options.scales.x.min,max:config.options.scales.x.max,getValueForPixel:x=>x,getPixelForValue:x=>x}};this.chartArea={left:0,right:Date.parse('2027-01-01'),top:0,bottom:260};instances.push(this);}
 update(){}draw(){}destroy(){this.destroyed=true;}
}
const context=vm.createContext({document:{createElement:node,documentElement:{}},Chart:ChartStub,getComputedStyle:()=>({getPropertyValue:k=>k}),requestAnimationFrame:fn=>frames.push(fn),MutationObserver:class{constructor(fn){cleanup=fn;}observe(){}}});
vm.runInContext(fs.readFileSync('static/stress-charts.js','utf8')+'\nthis.charts=RackbookCharts;',context);
const rows=[{start_time:'2026-01-01',score:{sets:2,total:5,peripheral:3,central:2},window:{lower:2,upper:4}},
 {start_time:'2026-02-01',score:{sets:0,total:0},window:{}},
 {start_time:'2026-03-01',score:{sets:1,total:1,peripheral:1,central:0},window:{lower:2,upper:12}}];
const box=context.charts.create(rows,{title:'Stress',stress:true,series:[['total','Total','#4a79f5'],['central','Central','#d99132']]});
frames.shift()();const chart=instances[0];
assert.equal(chart.options.maintainAspectRatio,false);assert.equal(chart.options.scales.x.type,'linear');
assert.equal(chart.data.datasets[0].spanGaps,false);assert.equal(chart.data.datasets[0].data[1].y,null,'Unscored sessions must leave a gap');
assert.equal(chart.data.datasets.at(-1).data[2].y,12,'The entire usual window must participate in auto-scaling');
assert.equal(chart.data.datasets[0].pointBackgroundColor[0],'--error');assert.equal(chart.data.datasets[0].pointBackgroundColor[2],'--card');
assert.equal(chart.options.plugins.zoom.zoom.pinch.enabled,true);assert.equal(chart.options.plugins.zoom.pan.modifierKey,'shift');
const walk=n=>[n,...n.children.flatMap(x=>typeof x==='object'?walk(x):[])];
const nodes=walk(box),canvas=nodes.find(n=>n.tag==='canvas'),selection=nodes.find(n=>n.className==='chart-selection');
chart.options.onClick({x:Date.parse('2026-02-01'),y:50},[],chart);
assert.match(selection.textContent,/Unavailable/,'Tapping a missing observation must explain it');
canvas.listeners.keydown({key:'End',preventDefault(){}});assert.match(selection.textContent,/Total: 1/);
nodes.find(n=>n.attributes['aria-label']==='Zoom in').listeners.click();
assert.ok(chart.options.scales.x.max-chart.options.scales.x.min<Date.parse('2026-03-02')-Date.parse('2026-01-01'));
nodes.find(n=>n.attributes['aria-label']==='Reset zoom').listeners.click();
assert.equal(chart.options.scales.x.min,Date.parse('2026-01-01')-43200000);
for(const width of [280,900])assert.ok(context.charts.dateTicks(Date.parse('2025-12-01'),Date.parse('2026-02-01'),width).length<=(width<500?3:7));
box.isConnected=false;cleanup();assert.equal(chart.destroyed,true);
const observations=context.charts.create([{start_time:'2026-01-01',soreness:null,pain:true},{start_time:'2026-03-01',soreness:2,pain:false}],{title:'Soreness',categorical:true,series:[['soreness','Soreness','#4a79f5']]});
frames.shift()();const soreness=instances[1];assert.equal(soreness.data.datasets[0].showLine,false);assert.equal(soreness.options.scales.y.max,3);
soreness.options.onClick({x:Date.parse('2026-01-01'),y:50},[],soreness);
assert.match(walk(observations).find(n=>n.className==='chart-selection').textContent,/Pain\/injury: Flagged/);
const detached=context.charts.create(rows,{title:'Stress',stress:true,series:[['total','Total','#4a79f5']]});detached.isConnected=false;frames.shift()();assert.equal(instances.length,2,'Detached charts must never initialize');
const pairedRows=[{start_time:'2026-01-01',sets:4,bw:90},{start_time:'2026-02-01',sets:null,bw:91},{start_time:'2026-03-01',sets:5,bw:92}];
const pairedA=context.charts.create(pairedRows,{title:'Sets',series:[['sets','Sets','#4a79f5']]});
const pairedB=context.charts.create(pairedRows,{title:'BW',series:[['bw','BW','#d99132']]});
frames.shift()();frames.shift()();
walk(pairedA).find(n=>n.attributes['aria-label']==='Zoom in').listeners.click();
assert.equal(instances[2].options.scales.x.min,instances[3].options.scales.x.min,'Observation charts share their zoom window');
instances[2].options.onClick({x:Date.parse('2026-02-01'),y:50},[],instances[2]);
assert.match(walk(pairedB).find(n=>n.className==='chart-selection').textContent,/BW: 91/,'Observation charts share the selected session');
const trialRows=[{start_time:'2026-01-01',expected:0,actual:1},{start_time:'2026-02-01',expected:null,actual:null}];
const trialBox=context.charts.create(trialRows,{title:'Trial',categorical:true,valueLabels:['Below usual','Near usual'],series:[['expected','Expected','blue'],['actual','Actual','green']]});
frames.shift()();const trialChart=instances.at(-1);
assert.equal(trialChart.options.scales.y.max,1.15);assert.equal(trialChart.options.scales.y.ticks.callback(0),'Below usual');
assert.equal(trialChart.options.scales.y.ticks.callback(1),'Near usual');
assert.equal(trialChart.data.datasets[0].pointStyle,'triangle');assert.equal(trialChart.data.datasets[1].pointStyle,'circle');
assert.equal(trialChart.data.datasets[0].data[1].y,null);assert.equal(trialChart.data.datasets[0].showLine,false);
trialChart.options.onClick({x:Date.parse('2026-02-01'),y:50},[],trialChart);
assert.match(walk(trialBox).find(n=>n.className==='chart-selection').textContent,/Expected: Unavailable.*Actual: Unavailable/);
console.log('Stress/trial charts: time spacing, categories, gaps, markers, inspection, keyboard, zoom and cleanup passed.');
