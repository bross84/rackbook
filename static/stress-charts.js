/* Stress charts use the same Chart.js presentation and gestures as Progress. */
const RackbookCharts = (() => {
  const DAY=86400000, live=new Set(), names=['None','Mild','Moderate','Severe'];
  const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
  const fullDate=t=>new Date(t).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'});
  const valueText=(v,categorical,labels=names)=>Number.isFinite(v)?(categorical?(labels[v]??'Unavailable'):Number(v.toFixed(1)).toString()):'Unavailable';
  function dateTicks(start,end,width) {
    const first=Math.ceil(start/DAY)*DAY,last=Math.floor(end/DAY)*DAY;
    const count=Math.min(width<500?3:7,Math.round((last-first)/DAY)+1);
    return count<=1?[{value:first}]:Array.from({length:count},(_,i)=>({value:Math.round((first+(last-first)*i/(count-1))/DAY)*DAY}));
  }
  function colors() {
    const s=getComputedStyle(document.documentElement),get=k=>s.getPropertyValue(k).trim();
    return {muted:get('--muted'),card:get('--card'),grid:get('--line'),error:get('--error')};
  }
  function create(input, config) {
    const box=node('div','stress-chart'),rows=input.filter(r=>Number.isFinite(Date.parse(r.start_time))).slice().sort((a,b)=>Date.parse(a.start_time)-Date.parse(b.start_time));
    const val=(r,key)=>config.stress?(r.score?.sets?r.score[key]:null):r[key];
    if(!rows.some(r=>config.series.some(([k])=>Number.isFinite(val(r,k))) || (config.categorical&&r.pain))) {
      box.append(node('p','note','No observations in this range.'));return box;
    }
    const times=rows.map(r=>Date.parse(r.start_time)),first=times[0]-DAY/2,last=times.at(-1)+DAY/2;
    let start=first,end=last,selected=rows.length-1,instance;
    const controls=node('div','range-row'),ranges=node('div','segmented'),actions=node('div','zoom-actions');
    const plot=node('div','plot-wrap'),canvas=node('canvas'),tip=node('div','chart-tooltip'),selection=node('div','chart-selection');
    tip.hidden=true;canvas.tabIndex=0;canvas.setAttribute('role','img');canvas.setAttribute('aria-label',config.title+' over time');
    selection.setAttribute('aria-live','polite');
    const period=node('div','period'),from=node('input'),to=node('input');
    for(const [control,label] of [[from,'From date'],[to,'To date']]) {control.type='date';control.min=new Date(times[0]).toISOString().slice(0,10);control.max=new Date(times.at(-1)).toISOString().slice(0,10);control.setAttribute('aria-label',config.title+' '+label);}
    function button(parent,label,action,title=label) {const b=node('button',null,label);b.type='button';b.title=title;b.setAttribute('aria-label',title);b.addEventListener('click',action);parent.append(b);return b;}
    function setWindow(a,b,propagate=true) {
      const width=Math.min(last-first,Math.max(DAY,b-a));start=Math.max(first,Math.min(last-width,a));end=start+width;
      tip.hidden=true;
      if(instance){instance.options.scales.x.min=start;instance.options.scales.x.max=end;instance.update('none');}
      period.textContent=fullDate(start)+' – '+fullDate(end);
      for(const b of ranges.children)b.setAttribute('aria-pressed',String(b.dataset.days==='0'&&start===first&&end===last));
      const visible=times.map((t,i)=>t>=start&&t<=end?i:-1).filter(i=>i>=0);
      select(visible.includes(selected)?selected:(visible.at(-1)??-1),undefined,false);
      if(propagate)for(const other of live)if(other!==state&&other.group===input)other.setWindow(start,end,false);
    }
    for(const [label,days] of [['4 Weeks',28],['8 Weeks',56],['12 Weeks',84],['1 Year',365],['All',0]]) {
      const b=button(ranges,label,()=>{setWindow(days?last-days*DAY:first,last);b.setAttribute('aria-pressed','true');});b.dataset.days=String(days);
    }
    controls.append(ranges,actions);
    function zoom(factor){const mid=(start+end)/2,w=(end-start)*factor;setWindow(mid-w/2,mid+w/2);}
    for(const [label,title,action] of [['←','Earlier',()=>setWindow(start-(end-start)/2,end-(end-start)/2)],['+','Zoom in',()=>zoom(.5)],['−','Zoom out',()=>zoom(2)],['→','Later',()=>setWindow(start+(end-start)/2,end+(end-start)/2)],['Reset','Reset zoom',()=>setWindow(first,last)]])button(actions,label,action,title);
    const custom=node('div','range-row');custom.append(from,to);button(custom,'Apply dates',()=>{
      const a=Date.parse(from.value),b=Date.parse(to.value);
      if(!Number.isFinite(a)||!Number.isFinite(b)||a>b||a<Math.floor(times[0]/DAY)*DAY||b>times.at(-1)){selection.textContent='Choose dates within this history, From on or before To.';return;}
      setWindow(a-DAY/2,b+DAY/2);
    });
    from.value=from.min;to.value=to.max;
    const detailLines=i=>{
      const r=rows[i],lines=config.series.map(([k,label])=>[label,valueText(val(r,k),config.categorical,config.valueLabels)]);
      if(config.stress)lines.push(['Usual window',Number.isFinite(r.window?.lower)&&Number.isFinite(r.window?.upper)?valueText(r.window.lower)+'–'+valueText(r.window.upper):'Unavailable']);
      if(config.categorical&&!config.valueLabels)lines.push(['Pain/injury',r.pain?'Flagged':'Not flagged']);
      if(config.baselineStart&&times[i]<Date.parse(config.baselineStart))lines.push(['Baseline','Before current baseline']);
      return lines;
    };
    function select(i,position,propagate=true) {
      selected=i;
      if(i<0){selection.textContent='No sessions in this date range.';return;}
      const description=fullDate(times[i])+ ' · '+detailLines(i).map(([k,v])=>k+': '+v).join(' · ');
      selection.textContent=description;canvas.setAttribute('aria-label',config.title+'. '+description);
      if(position){tip.replaceChildren(node('strong',null,fullDate(times[i])));for(const [k,v] of detailLines(i)){const line=node('div','tooltip-row');line.append(node('span',null,k),node('b',null,v));tip.append(line);}tip.hidden=false;tip.style.left=Math.max(6,Math.min(plot.clientWidth-tip.offsetWidth-6,position.x+12))+'px';tip.style.top=Math.max(6,position.y-tip.offsetHeight-12)+'px';}
      if(instance)instance.draw();
      if(propagate)for(const other of live)if(other!==state&&other.group===input)other.select(i,undefined,false);
    }
    function inspect(event,_items,chart) {
      const area=chart.chartArea;if(!event||event.x<area.left||event.x>area.right||event.y<area.top||event.y>area.bottom){tip.hidden=true;return;}
      const t=chart.scales.x.getValueForPixel(event.x);let best=-1;
      times.forEach((time,i)=>{if(time>=start&&time<=end&&(best<0||Math.abs(time-t)<Math.abs(times[best]-t)))best=i;});
      if(best>=0)select(best,event);
    }
    canvas.addEventListener('keydown',e=>{
      if(!['ArrowLeft','ArrowRight','Home','End','+','=','-','Escape'].includes(e.key))return;e.preventDefault();tip.hidden=true;
      if(e.key==='+'||e.key==='=')return zoom(.5);if(e.key==='-')return zoom(2);if(e.key==='Escape')return setWindow(first,last);
      const visible=times.map((t,i)=>t>=start&&t<=end?i:-1).filter(i=>i>=0),at=visible.indexOf(selected);
      select(e.key==='Home'?visible[0]??-1:e.key==='End'?visible.at(-1)??-1:visible[Math.max(0,Math.min(visible.length-1,at+(e.key==='ArrowRight'?1:-1)))]??-1);
    });
    canvas.addEventListener('focus',()=>select(selected));canvas.addEventListener('mouseleave',()=>{tip.hidden=true;});
    plot.append(canvas,tip);box.append(controls,custom,period,plot,selection,node('p','chart-note','Drag to zoom · Shift-drag to pan · Ctrl + wheel or pinch to zoom. Use arrow keys to inspect sessions; + / − to zoom.'+(config.stress?' Shading shows the usual window known before each workout; red points are above usual and hollow points below.':'')));
    const decoration={id:'stressDecoration',beforeDatasetsDraw(chart){
      if(!config.stress)return;
      const {ctx,scales:{x,y}}=chart;ctx.save();ctx.beginPath();ctx.rect(chart.chartArea.left,chart.chartArea.top,chart.chartArea.right-chart.chartArea.left,chart.chartArea.bottom-chart.chartArea.top);ctx.clip();
      let band=[];const draw=()=>{if(!band.length)return;ctx.beginPath();const coords=band.map(i=>[x.getPixelForValue(times[i]),y.getPixelForValue(rows[i].window.upper),y.getPixelForValue(rows[i].window.lower)]);if(coords.length===1){const [xx,top,bottom]=coords[0];ctx.rect(xx-6,top,12,bottom-top);}else{ctx.moveTo(coords[0][0],coords[0][1]);for(const [xx,top]of coords.slice(1))ctx.lineTo(xx,top);for(const [xx,,bottom]of coords.slice().reverse())ctx.lineTo(xx,bottom);ctx.closePath();}ctx.fillStyle='rgba(74,121,245,.14)';ctx.fill();band=[];};
      rows.forEach((r,i)=>{if(r.score?.sets&&Number.isFinite(r.window?.lower)&&Number.isFinite(r.window?.upper))band.push(i);else draw();});draw();ctx.restore();
    },afterDatasetsDraw(chart){
      const {ctx,scales:{x,y},chartArea:a}=chart;ctx.save();
      if(selected>=0){const xx=x.getPixelForValue(times[selected]);if(xx>=a.left&&xx<=a.right){ctx.beginPath();ctx.setLineDash([3,4]);ctx.strokeStyle=colors().muted;ctx.moveTo(xx,a.top);ctx.lineTo(xx,a.bottom);ctx.stroke();ctx.setLineDash([]);}}
      if(config.categorical){ctx.fillStyle=colors().error;ctx.textAlign='center';rows.forEach((r,i)=>{const xx=x.getPixelForValue(times[i]);if(r.pain&&xx>=a.left&&xx<=a.right)ctx.fillText('!',xx,a.top+12);});}ctx.restore();
    }};
    const state={box,group:input,setWindow,select,destroy(){instance?.destroy();live.delete(state);}};live.add(state);
    requestAnimationFrame(()=>{
      if(!box.isConnected){state.destroy();return;}
      if(typeof Chart!=='function'){box.replaceChildren(node('p','error','Chart files could not load. Refresh to try again.'));live.delete(state);return;}
      const c=colors(),datasets=config.series.map(([key,label,color],seriesIndex)=>({label,data:rows.map((r,i)=>({x:times[i],y:Number.isFinite(val(r,key))?val(r,key):null})),borderColor:color,backgroundColor:color,borderWidth:2,pointStyle:config.valueLabels?(seriesIndex===0?'triangle':'circle'):'circle',pointRadius:config.valueLabels?(seriesIndex===0?7:3):rows.length>80?1.5:2.5,pointHoverRadius:8,pointHitRadius:12,pointBorderWidth:1,pointBorderColor:config.stress?rows.map(r=>key==='total'&&r.score?.total>r.window?.upper?c.error:color):c.card,
        pointBackgroundColor:config.stress?rows.map(r=>key==='total'&&r.score?.total>r.window?.upper?c.error:key==='total'&&r.score?.total<r.window?.lower?c.card:color):rows.map((r,i)=>config.baselineStart&&times[i]<Date.parse(config.baselineStart)?c.muted:color),
        tension:.15,spanGaps:false,showLine:!config.categorical,fill:false,
        segment:config.stress?{}:{borderColor:ctx=>times[ctx.p1DataIndex]-times[ctx.p0DataIndex]>=21*DAY?'transparent':undefined}
      }));
      // Include baseline bounds in auto-scaling without drawing an extra line.
      if(config.stress)for(const key of ['lower','upper'])datasets.push({label:'Usual window '+key,data:rows.map((r,i)=>({x:times[i],y:r.score?.sets&&Number.isFinite(r.window?.[key])?r.window[key]:null})),borderWidth:0,pointRadius:0,pointHoverRadius:0,showLine:false});
      const gesture=({chart})=>setWindow(chart.scales.x.min,chart.scales.x.max);
      instance=new Chart(canvas,{type:'line',data:{datasets},plugins:[decoration],options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'nearest',axis:'x',intersect:false},onHover:inspect,onClick:inspect,
        plugins:{legend:{display:config.stress,position:'bottom',align:'start',labels:{filter:item=>!item.text.startsWith('Usual window '),color:c.muted,boxWidth:12,boxHeight:2,padding:14,font:{size:11}}},tooltip:{enabled:false},zoom:{limits:{x:{min:first,max:last,minRange:DAY}},pan:{enabled:true,mode:'x',modifierKey:'shift',onPan:gesture},zoom:{mode:'x',wheel:{enabled:true,modifierKey:'ctrl',speed:.12},pinch:{enabled:true},drag:{enabled:true,backgroundColor:'rgba(74,121,245,.12)',borderColor:'#4a79f5',borderWidth:1,threshold:12},onZoom:gesture}}},
        scales:{x:{type:'linear',min:start,max:end,border:{display:false},grid:{color:c.grid,lineWidth:.5},afterBuildTicks:scale=>{scale.ticks=dateTicks(scale.min,scale.max,scale.width);},ticks:{color:c.muted,font:{size:10},maxRotation:0,autoSkip:true,callback:fullDate}},
          y:{border:{display:false},grid:{color:c.grid,lineWidth:.5},...(config.categorical?{min:config.valueLabels?-.15:0,max:config.valueLabels?config.valueLabels.length-1+.15:3}:{}),...(config.valueLabels?{afterBuildTicks:scale=>{scale.ticks=config.valueLabels.map((_,i)=>({value:i}));}}:{}),...(config.bounds||{}),ticks:{color:c.muted,font:{size:10},maxTicksLimit:5,...(config.categorical?{stepSize:1}:config.series[0][0]==='working_sets'?{precision:0}:{}),callback:v=>valueText(v,config.categorical,config.valueLabels)}}}}});
      setWindow(first,last,false);
    });
    return box;
  }
  new MutationObserver(()=>{for(const state of live)if(!state.box.isConnected)state.destroy();}).observe(document.documentElement,{childList:true,subtree:true});
  return {create,dateTicks};
})();
