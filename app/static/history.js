/* Local SVG charts: no CDN, tracking, extra API requests, or saved server settings. */
const FafHistory = (() => {
 const metrics = [
  {key:'mass', label:'Masse gesamt', unit:'Masse'},
  {key:'reclaim', label:'Reclaim gesamt', unit:'Masse'},
  {key:'score', label:'Punktestand', unit:'Punkte'},
  {key:'energy', label:'Energie gesamt', unit:'Energie'},
  {key:'experimentals', label:'Experimentals gebaut', unit:'Einheiten'},
  {key:'mass_spent', label:'Masse ausgegeben', unit:'Masse'},
  {key:'mass_wasted', label:'Masseüberschuss', unit:'Masse'},
  {key:'kills_mass', label:'Zerstörte Masse', unit:'Masse'}
 ];
 const palette=['#a5efc8','#ffb68a','#b8a5ff','#73c9ff','#ff8eb4','#f1dd77','#4cddcd','#ff9279','#85a5ff','#cfdf94','#e9a5df','#b9c6d5'];
 const enabledMetrics=new Set(['mass','reclaim','score']);
 const hiddenPlayers=new Set();
 const colors=new Map();
 let configuredColors=new Map();
 let games=[],players=[],range='50',initialized=false;
 const dimensions={w:1040,h:300,left:88,right:24,top:24,bottom:53};
 const color=id=>{
  if(configuredColors.has(id))return configuredColors.get(id);
  if(!colors.has(id)){const i=colors.size;colors.set(id,palette[i]||`hsl(${Math.round(i*137.5)%360} 65% 70%)`);}
  return colors.get(id);
 };
 const value=(game,id,key)=>{
  const v=game.players.find(p=>p.id===id)?.[key];
  return typeof v==='number'&&Number.isFinite(v)&&v>=0?v:null;
 };
 function init(){
  if(initialized)return;
  initialized=true;
  document.querySelector('#history-metrics').innerHTML=metrics.map(m=>`<label><input type="checkbox" data-history-metric="${m.key}" ${enabledMetrics.has(m.key)?'checked':''}>${m.label}</label>`).join('');
  document.querySelector('#history-metrics').addEventListener('change',e=>{
   const key=e.target.dataset.historyMetric;
   if(!key)return;
   if(e.target.checked)enabledMetrics.add(key);else enabledMetrics.delete(key);
   render();
  });
  document.querySelector('#history-players').addEventListener('change',e=>{
   const id=e.target.dataset.historyPlayer;
   if(!id)return;
   if(e.target.checked)hiddenPlayers.delete(id);else hiddenPlayers.add(id);
   render();
  });
  document.querySelector('#history-all').onclick=()=>{hiddenPlayers.clear();renderPlayers();render();};
  document.querySelector('#history-none').onclick=()=>{players.forEach(p=>hiddenPlayers.add(p.id));renderPlayers();render();};
  document.querySelector('#history-range').onchange=e=>{range=e.target.value;render();};
 }
 function renderPlayers(){
  document.querySelector('#history-players').innerHTML=players.map(p=>`<label style="--series-color:${color(p.id)}"><input type="checkbox" data-history-player="${esc(p.id)}" ${hiddenPlayers.has(p.id)?'':'checked'}><span class="history-swatch"></span>${esc(p.name)}</label>`).join('')||empty('Noch keine Freunde in der Auswahl.');
 }
 function update(data,roster){
  init();
  games=data.games;
  configuredColors=new Map(roster.filter(p=>/^#[0-9a-f]{6}$/i.test(p.color||'')).map(p=>[p.id,p.color]));
  const allowed=new Set(roster.map(p=>p.id));
  players=data.players.filter(p=>allowed.has(p.id)).slice().sort((a,b)=>a.name.localeCompare(b.name,'de'));
  renderPlayers();render();
 }
 function render(){
  const dated=games.filter(g=>typeof g.played_at==='number'&&Number.isFinite(g.played_at)&&g.played_at>0)
    .slice().sort((a,b)=>a.played_at-b.played_at||a.id.localeCompare(b.id));
  const start=range==='all'?0:Math.max(0,dated.length-Number(range));
  const shown=dated.slice(start);
  const selected=players.filter(p=>!hiddenPlayers.has(p.id));
  document.querySelector('#history-summary').textContent=`${shown.length} von ${dated.length} datierten Partien · ${selected.length} Freunde eingeblendet. ${games.length-dated.length} Partien ohne Datum werden im Verlauf ausgelassen. Gesamtwerte je Partie, nicht über mehrere Spiele aufsummiert.`;
  const container=document.querySelector('#history-charts');
  container.replaceChildren();
  if(!shown.length){container.innerHTML=empty('Noch keine datierten Partien in dieser Auswahl.');return;}
  if(!selected.length){container.innerHTML=empty('Alle Freunde ausgeblendet. Wählt mindestens einen Spieler für den Verlauf.');return;}
  if(!enabledMetrics.size){container.innerHTML=empty('Alle Kennzahlen ausgeblendet. Wählt Masse, Reclaim oder eine andere Kennzahl.');return;}
  for(const metric of metrics.filter(m=>enabledMetrics.has(m.key)))draw(container,metric,shown,selected,start);
 }
 function draw(container,metric,shown,selected,start){
  const {w,h,left,right,top,bottom}=dimensions;
  const plotW=w-left-right,plotH=h-top-bottom;
  const x=i=>shown.length===1?left+plotW/2:left+i*plotW/(shown.length-1);
  const series=selected.map(player=>({player,values:shown.map(g=>value(g,player.id,metric.key))}));
  let max=0,samples=0;
  for(const s of series)for(const v of s.values)if(v!==null){max=Math.max(max,v);samples++;}
  const roughStep=(max||1)/4;
  const magnitude=10**Math.floor(Math.log10(roughStep));
  const step=[1,2,2.5,5,10].map(n=>n*magnitude).find(n=>n>=roughStep);
  const scaleMax=Math.ceil((max||1)/step)*step;
  const y=v=>top+plotH-(v/scaleMax)*plotH;
  const card=document.createElement('article');card.className='panel history-chart';card.dataset.metric=metric.key;
  card.innerHTML=`<div class="section-title"><h3>${metric.label}</h3><span class="muted">Y: ${metric.unit} · ${samples} Messwerte</span></div>`;
  container.append(card);
  if(!samples){card.insertAdjacentHTML('beforeend',empty('Für diese Kennzahl fehlen in der Auswahl noch Daten.'));return;}
  let svg=`<svg viewBox="0 0 ${w} ${h}" role="img" tabindex="0" aria-label="${metric.label} pro Partie. Mit Pfeiltasten Partien auswählen, mit Enter öffnen."><title>${metric.label} je Partie</title>`;
  for(let i=0;i<=Math.round(scaleMax/step);i++){
   const v=step*i,py=y(v);
   svg+=`<line class="history-grid" x1="${left}" y1="${py}" x2="${w-right}" y2="${py}"/><text class="history-axis" text-anchor="end" x="${left-12}" y="${py+4}">${esc(num(v))}</text>`;
  }
  const ticks=[...new Set(Array.from({length:Math.min(6,shown.length)},(_,i)=>Math.round(i*(shown.length-1)/Math.max(1,Math.min(6,shown.length)-1))))];
  for(const i of ticks)svg+=`<text class="history-axis" text-anchor="middle" x="${x(i)}" y="${h-bottom+23}">${start+i+1}</text>`;
  svg+=`<text class="history-axis" text-anchor="middle" x="${left+plotW/2}" y="${h-6}">Partie (chronologisch)</text>`;
  for(const {player,values} of series){
   let path='',bridges='',points='',previous=null;
   for(let i=0;i<values.length;i++){
    if(values[i]===null)continue;
    const position=`${x(i).toFixed(2)},${y(values[i]).toFixed(2)}`;
    const adjacent=previous!==null&&previous===i-1;
    path+=`${adjacent?'L':'M'}${position} `;
    if(previous!==null&&!adjacent)
     bridges+=`M${x(previous).toFixed(2)},${y(values[previous]).toFixed(2)} L${position} `;
    points+=`<circle data-series="${esc(player.id)}" cx="${x(i)}" cy="${y(values[i])}" r="${shown.length>100?1.8:3}" fill="${color(player.id)}" stroke="var(--panel,#131b24)" stroke-width="1"/>`;
    previous=i;
   }
   svg+=`<path class="history-gap" data-series="${esc(player.id)}" d="${bridges}" fill="none" stroke="${color(player.id)}" stroke-width="1.5" stroke-dasharray="4 6" opacity=".5"><title>Verbindung über Partien ohne Messwert – keine Zwischenwerte</title></path>`;
   svg+=`<path data-series="${esc(player.id)}" d="${path}" fill="none" stroke="${color(player.id)}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"><title>${esc(player.name)}</title></path>${points}`;
  }
  svg+=`<line class="history-cursor" x1="${x(shown.length-1)}" x2="${x(shown.length-1)}" y1="${top}" y2="${h-bottom}"/><rect class="history-hit" x="${left}" y="${top}" width="${plotW}" height="${plotH}" fill="transparent"/></svg>`;
  card.insertAdjacentHTML('beforeend',`<div class="history-plot">${svg}</div><div class="history-detail" aria-live="polite"></div>`);
  const chart=card.querySelector('svg'),cursor=card.querySelector('.history-cursor'),detail=card.querySelector('.history-detail');
  let current=-1;
  function inspect(index){
   const i=Math.max(0,Math.min(shown.length-1,index));if(i===current)return;
   current=i;cursor.setAttribute('x1',x(i));cursor.setAttribute('x2',x(i));
   const game=shown[i];
   detail.innerHTML=`<div class="history-game"><button class="match-link" data-game="${esc(game.id)}">Partie ${start+i+1} · #${esc(game.id)} ↗</button><span class="muted">${date(game.played_at)} · ${duration(game.duration)}</span></div><div class="history-values">${series.map(s=>`<span style="--series-color:${color(s.player.id)}"><i class="history-swatch"></i>${esc(s.player.name)}: <strong>${s.values[i]===null?'Keine Daten':esc(formatNumber(s.values[i]))}</strong></span>`).join('')}</div>`;
  }
  chart.addEventListener('pointermove',e=>{
   const point=chart.createSVGPoint();point.x=e.clientX;point.y=e.clientY;
   const matrix=chart.getScreenCTM();if(!matrix)return;
   const local=point.matrixTransform(matrix.inverse());
   inspect(shown.length===1?0:Math.round((local.x-left)/plotW*(shown.length-1)));
  });
  chart.addEventListener('pointerdown',e=>{
   const point=chart.createSVGPoint();point.x=e.clientX;point.y=e.clientY;
   const matrix=chart.getScreenCTM();if(!matrix)return;
   const local=point.matrixTransform(matrix.inverse());
   inspect(shown.length===1?0:Math.round((local.x-left)/plotW*(shown.length-1)));
  });
  chart.addEventListener('keydown',e=>{
   if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();inspect(current+(e.key==='ArrowLeft'?-1:1));}
   if(e.key==='Home'||e.key==='End'){e.preventDefault();inspect(e.key==='Home'?0:shown.length-1);}
   if(e.key==='Enter'){e.preventDefault();showGame(shown[current].id);}
  });
  inspect(shown.length-1);
 }
 return {update};
})();
