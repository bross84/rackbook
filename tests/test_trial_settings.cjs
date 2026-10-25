// Settings UI only; no browser/network/Hevy writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..'),settings=fs.readFileSync(path.join(root,'index.html'),'utf8');
for(const match of settings.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);
const elements=new Map();
function el(){return {textContent:'',children:[],attrs:{},disabled:true,hidden:true,append(n){this.children.push(n)},replaceChildren(){this.children=[]},setAttribute(k,v){this.attrs[k]=v},addEventListener(k,fn){this[k]=fn},querySelector(){return this.box??=el()}};}
const get=id=>{if(!elements.has(id))elements.set(id,el());return elements.get(id)};
let fail=false,failLoad=false,calls=[];
const context=vm.createContext({document:{getElementById:get,createElement:el},fetch:async(url,options={})=>{
 calls.push([url,options]);if(fail||failLoad)throw Error('Offline');return {ok:true,json:async()=>url.endsWith('/dashboard')?{entries:[{status:'recorded'}],cohorts:[]}:({enabled:options.method==='PUT'?JSON.parse(options.body).enabled:true})};
}});
const script=settings.match(/<script id="trial-settings">([\s\S]*?)<\/script>/)[1].replace('  loadTrialSetting();','').replace('  loadTrialHistory();','');
vm.runInContext(script,context);
(async()=>{
 failLoad=true;await context.loadTrialSetting();assert.equal(get('trialEnabled').disabled,true);assert.match(get('trialSettingStatus').textContent,/Could not load/);
 failLoad=false;await context.loadTrialSetting();assert.equal(get('trialEnabled').attrs['aria-pressed'],'true');
 const toggle=context.toggleTrialSetting();assert.equal(get('trialEnabled').disabled,true);
 await context.toggleTrialSetting();assert.equal(calls.filter(([,o])=>o.method==='PUT').length,1,'No duplicate writes');
 await toggle;assert.equal(get('trialEnabled').attrs['aria-pressed'],'false');assert.equal(get('trialEnabled').disabled,false);
 fail=true;await context.toggleTrialSetting();assert.equal(get('trialEnabled').attrs['aria-pressed'],'false');assert.match(get('trialSettingStatus').textContent,/Could not save/);
 fail=false;await context.loadTrialHistory();assert.equal(get('trialHistory').hidden,false);assert.match(get('trialHistory').box.children.map(x=>x.textContent).join(' '),/No saved trial workouts.*1 snapshots/);
 assert.match(settings,/href="\/trial">View model trial dashboard/);
 for(const file of ['log.html','mesocycles.html','recent.html','progress.html','stress.html','rpe_charts.html','trial.html']){
  const text=fs.readFileSync(path.join(root,file),'utf8'),nav=text.match(/<nav class="app-nav"[\s\S]*?<\/nav>/)[0];
  assert.ok(!nav.includes('href="/trial"'),file+' keeps Model trial out of main navigation');
 }
 console.log('Trial Settings placement, loading, persistence, failure recovery and navigation passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
