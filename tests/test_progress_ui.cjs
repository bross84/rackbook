const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const html = fs.readFileSync('progress.html','utf8');
for (const m of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(m[1]);
function node(tag,cls,text) { return {tag,className:cls,textContent:text,children:[],attrs:{},events:{},style:{},append(...x){this.children.push(...x)},prepend(x){this.children.unshift(x)},replaceChildren(...x){this.children=x},setAttribute(k,v){this.attrs[k]=v},addEventListener(k,v){this.events[k]=v},getBoundingClientRect(){return {width}},querySelector(q){return walk(this).find(n=>String(n.attrs['data-session'])===q.match(/"(\d+)"/)[1])},focus(){this.events.focus()}}; }
const walk = n => [n,...n.children.flatMap(walk)];
let width=390;
const boxes=Object.fromEntries(['charts','stats','foot'].map(k=>[k,node('div')]));
const c=vm.createContext({document:{createElement:tag=>node(tag),createElementNS:(_,tag)=>node(tag)},$:id=>boxes[id],Date,Math,NS:'svg'});
vm.runInContext(html.slice(html.indexOf('  function el('),html.indexOf('  let lastData;')),c);
const point=(date,bw=188.5)=>({date,e1rm_lb:300,bodyweight_lb:bw,dots:bw==null?null:100,bodyweight_source_date:bw==null?null:'2025-08-01',bodyweight_age_days:bw==null?null:11,bodyweight_weigh_in_count:bw==null?null:1});
const series=[point('2025-08-12'),point('2026-01-01',null),{...point('2026-10-16',169.8),bodyweight_source_date:'2026-10-16',bodyweight_age_days:0}];
c.render({title:'Squat',series});
const text=n=>walk(n).map(n=>n.textContent||'').join(' ');
assert.match(text(boxes.stats),/-9.9%/); assert.match(text(boxes.stats),/2025/);assert.match(text(boxes.stats),/2026/);assert.match(text(boxes.stats),/188.5/);assert.match(text(boxes.stats),/169.8/);assert.match(text(boxes.stats),/11 days old/);
let charts=walk(boxes.charts).filter(n=>n.tag==='svg');
const scorePath=walk(charts[0]).find(n=>n.tag==='path');assert.equal((scorePath.attrs.d.match(/M/g)||[]).length,2);assert.doesNotMatch(scorePath.attrs.d,/L/);
const targets=walk(charts[0]).filter(n=>n.tag==='rect');const panel=walk(boxes.charts).find(n=>n.className==='chart-detail');
for(const event of ['pointerenter','click','focus']){targets[1].events[event]();assert.match(panel.textContent,/Unavailable/);}
targets[0].events.keydown({key:'ArrowRight',preventDefault(){}});assert.match(panel.textContent,/Unavailable/);
targets[0].events.keydown({key:'Enter',preventDefault(){}});assert.match(panel.textContent,/188.5/);
const ticks=walk(charts[0]).filter(n=>n.tag==='text'&&n.attrs.y===234).length;
width=1100;c.render({title:'Squat',series});charts=walk(boxes.charts).filter(n=>n.tag==='svg');assert.ok(walk(charts[0]).filter(n=>n.tag==='text'&&n.attrs.y===234).length>ticks);
c.render({title:'Squat',series:[series[0]]});assert.doesNotMatch(text(boxes.charts),/NaN/);
c.render({title:'Squat',series:[]});assert.equal(boxes.stats.hidden,true);assert.match(text(boxes.charts),/No sets/);
console.log('Progress comparisons, gaps, responsive ticks, zero/one/multiple sessions and hover/tap/keyboard passed.');
