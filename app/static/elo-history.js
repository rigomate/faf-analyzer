/* Ratings come from the server's chronological replay, keyed by stable FAF ID. */
const FafEloHistory=(()=>{
 const palette=['#a5efc8','#ffb68a','#b8a5ff','#73c9ff','#ff8eb4','#f1dd77','#4cddcd','#ff9279','#85a5ff','#cfdf94','#e9a5df','#b9c6d5'];
 const hidden=new Set(),fallback=new Map();
 let model={},players=[],range='all',initialized=false;
 const el=id=>document.getElementById(id);
 const color=p=>/^#[0-9a-f]{6}$/i.test(p.color||'')?p.color:fallback.get(p.id);
 const shortDate=t=>new Date(t*1000).toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit',year:'2-digit'});
 function update(elo,roster){
  if(!initialized){
   initialized=true;
   el('elo-history-players').addEventListener('change',e=>{
    const id=e.target.dataset.eloPlayer;if(!id)return;
    if(e.target.checked)hidden.delete(id);else hidden.add(id);render();
   });
   el('elo-history-all').onclick=()=>{hidden.clear();choices();render();};
   el('elo-history-none').onclick=()=>{players.forEach(p=>hidden.add(p.id));choices();render();};
   el('elo-history-range').onchange=e=>{range=e.target.value;render();};
  }
  model=elo||{};players=roster.slice().sort((a,b)=>a.name.localeCompare(b.name,'de'));
  for(const p of players)if(!fallback.has(p.id)){
   const i=fallback.size;fallback.set(p.id,palette[i]||`hsl(${Math.round(i*137.5)%360} 65% 70%)`);
  }
  choices();render();
 }
 function choices(){
  el('elo-history-players').innerHTML=players.map(p=>`<label style="--series-color:${color(p)}"><input type="checkbox" data-elo-player="${esc(p.id)}" ${hidden.has(p.id)?'':'checked'}><i class="history-swatch"></i>${esc(p.name)}</label>`).join('');
 }
 function render(){
  const container=el('elo-history-chart'),history=model.history||[],selected=players.filter(p=>!hidden.has(p.id));
  if(!history.length){container.innerHTML=empty('Noch keine gewerteten Partien für den Elo-Verlauf.');return;}
  if(!selected.length){container.innerHTML=empty('Wählt mindestens einen Freund für den Elo-Verlauf.');return;}
  const cutoff=range==='all'?history[0].played_at:Date.now()/1000-Number(range)*86400;
  const shown=history.filter(p=>p.played_at>=cutoff);
  if(!shown.length){container.innerHTML=empty('Keine gewerteten Partien in diesem Zeitraum.');return;}
  // Carry the preceding rating into the window; never restart a filtered series.
  const previous=history.filter(p=>p.played_at<cutoff).at(-1);
  const initial={played_at:Math.min(cutoff,shown[0].played_at),ratings:previous?.ratings||Object.fromEntries(players.map(p=>[p.id,model.base??1000]))};
  const points=[initial,...shown],w=1040,h=340,left=75,right=35,top=25,bottom=55;
  let min=model.base??1000,max=min;
  for(const point of points)for(const p of selected){
   const value=point.ratings[p.id]??model.base??1000;min=Math.min(min,value);max=Math.max(max,value);
  }
  const low=Math.floor((min-20)/50)*50,high=Math.ceil((max+20)/50)*50;
  const first=points[0].played_at,last=points.at(-1).played_at;
  const x=t=>first===last?left+(w-left-right)/2:left+(t-first)/(last-first)*(w-left-right);
  const y=v=>top+(high-v)/(high-low)*(h-top-bottom);
  let svg=`<svg viewBox="0 0 ${w} ${h}" tabindex="0" role="img" aria-label="Elo im Zeitverlauf. Pfeiltasten wählen Partien."><title>Elo nach jeder Partie</title>`;
  for(let i=0;i<=4;i++){
   const v=low+(high-low)*i/4;
   svg+=`<line class="history-grid" x1="${left}" x2="${w-right}" y1="${y(v)}" y2="${y(v)}"/><text class="history-axis" x="${left-10}" y="${y(v)+4}" text-anchor="end">${num(v)}</text>`;
   const t=first+(last-first)*i/4;
   if(first!==last||i===2)svg+=`<text class="history-axis" x="${x(t)}" y="${h-28}" text-anchor="middle">${shortDate(t)}</text>`;
  }
  svg+=`<text class="history-axis" x="${left}" y="15">Elo</text><text class="history-axis" x="${w/2}" y="${h-5}" text-anchor="middle">Spieltermin</text>`;
  for(const p of selected){
   let path=`M${x(first)},${y(initial.ratings[p.id])}`;
   for(const point of shown)path+=` H${x(point.played_at)} V${y(point.ratings[p.id])}`;
   svg+=`<path d="${path}" fill="none" stroke="${color(p)}" stroke-width="2"><title>${esc(p.name)}</title></path>`;
  }
  svg+=`<line class="history-cursor" y1="${top}" y2="${h-bottom}"/><rect class="history-hit" x="${left}" y="${top}" width="${w-left-right}" height="${h-top-bottom}" fill="transparent"/></svg>`;
  container.innerHTML=`<article class="panel history-chart"><div class="history-plot">${svg}</div><div class="history-detail" aria-live="polite"></div></article>`;
  const chart=container.querySelector('svg'),cursor=container.querySelector('.history-cursor'),detail=container.querySelector('.history-detail');let current=-1;
  function inspect(index){
   current=Math.max(0,Math.min(shown.length-1,index));const point=shown[current];
   cursor.setAttribute('x1',x(point.played_at));cursor.setAttribute('x2',x(point.played_at));
   detail.innerHTML=`<div class="history-game"><strong>Nach Partie #${esc(point.id)}</strong><span class="muted">${date(point.played_at)} · ${shown.length} gewertete Partien im Zeitraum</span></div><div class="history-values">${selected.map(p=>`<span style="--series-color:${color(p)}"><i class="history-swatch"></i>${esc(p.name)}: <strong>${num(point.ratings[p.id])}</strong></span>`).join('')}</div>`;
  }
  function pointer(e){
   const matrix=chart.getScreenCTM();if(!matrix)return;
   const point=chart.createSVGPoint();point.x=e.clientX;point.y=e.clientY;
   const px=point.matrixTransform(matrix.inverse()).x;
   let nearest=0;for(let i=1;i<shown.length;i++)if(Math.abs(x(shown[i].played_at)-px)<=Math.abs(x(shown[nearest].played_at)-px))nearest=i;
   inspect(nearest);
  }
  chart.addEventListener('pointermove',pointer);chart.addEventListener('pointerdown',pointer);
  chart.addEventListener('keydown',e=>{
   if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();
   inspect(e.key==='Home'?0:e.key==='End'?shown.length-1:current+(e.key==='ArrowLeft'?-1:1));
  });
  inspect(shown.length-1);
 }
 return {update};
})();
