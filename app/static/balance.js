/* Exhaustive local balancing. No online selection is sent to the server. */
function balancedTeams(players) {
 if(players.length<2||players.length>20)return [];
 const sorted=players.slice().sort((a,b)=>a.id.localeCompare(b.id));
 const size=Math.floor(sorted.length/2), total=sorted.reduce((s,p)=>s+10**((p.rating-1000)/400),0);
 const best=[];
 function search(start,chosen,power){
  if(chosen.length===size){
   if(sorted.length%2===0&&chosen[0]!==0)return; // Mirrored teams are the same suggestion.
   const ids=new Set(chosen);
   const chance=power/total, gap=Math.abs(chance-.5);
   const candidate={a:chosen.map(i=>sorted[i]),b:sorted.filter((_,i)=>!ids.has(i)),chance,gap};
   best.push(candidate);best.sort((a,b)=>a.gap-b.gap);if(best.length>3)best.pop();
   return;
  }
  for(let i=start;i<=sorted.length-(size-chosen.length);i++)search(i+1,[...chosen,i],power+10**((sorted[i].rating-1000)/400));
 }
 search(0,[],0);return best;
}
const FafBalance=(()=>{
 let players=[], selected=new Set(), initialized=false, fingerprint='';
 function init(){
  if(initialized)return;initialized=true;
  document.querySelector('#balance-players').addEventListener('change',e=>{
   const id=e.target.dataset.balancePlayer;if(!id)return;
   if(e.target.checked)selected.add(id);else selected.delete(id);
   invalidate();
  });
  document.querySelector('#balance-all').onclick=()=>{selected=new Set(players.map(p=>p.id));renderChoices();invalidate();};
  document.querySelector('#balance-none').onclick=()=>{selected.clear();renderChoices();invalidate();};
  document.querySelector('#balance-calculate').onclick=calculate;
 }
 function invalidate(){
  document.querySelector('#balance-count').textContent=`${selected.size} Freunde ausgewählt${selected.size>=2?' · '+Math.floor(selected.size/2)+' gegen '+Math.ceil(selected.size/2):''}`;
  document.querySelector('#balance-calculate').disabled=selected.size<2||selected.size>20;
  document.querySelector('#balance-results').innerHTML=empty(selected.size>20?'Maximal 20 Freunde gleichzeitig auswählen.':selected.size<2?'Mindestens zwei Freunde auswählen.':'Bereit? Teams ausbalancieren!');
 }
 function dot(p){return /^#[0-9a-f]{6}$/i.test(p.color||'')?`<i class="history-swatch" style="--series-color:${p.color}"></i>`:'';}
 function renderChoices(){
  document.querySelector('#balance-players').innerHTML=players.map(p=>`<label>${dot(p)}<input type="checkbox" data-balance-player="${esc(p.id)}" ${selected.has(p.id)?'checked':''}>${esc(p.name)} · ${Math.round(p.rating)}${p.provisional?' *':''}</label>`).join('');
 }
 function update(elo,roster){
  init();if(!elo)return;
  const next=JSON.stringify([elo,roster]);if(next===fingerprint)return;fingerprint=next;
  const ratings=new Map(elo.players.map(p=>[p.id,p]));
  players=roster.map(p=>({...p,...(ratings.get(p.id)||{rating:1000,games:0,provisional:true})})).sort((a,b)=>a.name.localeCompare(b.name,'de'));
  selected=new Set([...selected].filter(id=>players.some(p=>p.id===id)));
  document.querySelector('#elo-summary').textContent=`${elo.games} gewertete Partien · ${elo.undated_games} ohne Datum und ${elo.unsupported_games} mit unbrauchbaren Teams ausgelassen. Alle starten bei ${elo.base}, K-Faktor ${elo.k}.`;
  const ranked=players.slice().sort((a,b)=>b.rating-a.rating||a.name.localeCompare(b.name,'de'));
  document.querySelector('#elo-table').innerHTML=ranked.length?`<table><thead><tr><th>Spieler</th><th>Elo</th><th>Gewertete Partien</th><th>Datenlage</th></tr></thead><tbody>${ranked.map(p=>`<tr><td>${dot(p)} ${esc(p.name)}</td><td><strong>${Math.round(p.rating)}</strong></td><td>${p.games}</td><td>${p.games===0?'Noch keine Wertung · Startwert':p.provisional?'Vorläufig':'Mindestens 10 Partien'}</td></tr>`).join('')}</tbody></table>`:empty('Keine Freunde konfiguriert.');
  renderChoices();invalidate();
 }
 function calculate(){
  const online=players.filter(p=>selected.has(p.id));
  const options=balancedTeams(online);
  if(!options.length){invalidate();return;}
  const formatChance=v=>Intl.NumberFormat('de-DE',{maximumFractionDigits:1}).format(v*100)+' %';
  function team(members,label,chance){
   return `<article class="panel"><h3>${label} · ${members.length} Spieler</h3><p class="pct">${formatChance(chance)}</p><small class="muted">Modellschätzung für einen Sieg</small>${members.map(p=>`<div class="row">${dot(p)}<strong class="grow">${esc(p.name)}</strong><span>${Math.round(p.rating)}${p.provisional?' *':''}</span></div>`).join('')}</article>`;
  }
  document.querySelector('#balance-results').innerHTML=(online.some(p=>p.provisional)?'<p class="notice">* Vorläufige Wertungen dabei: Wenige oder keine Partien machen die Schätzung unsicher.</p>':'')+options.map((o,i)=>`<section class="balance-option"><h3>${i===0?'Beste Aufteilung':'Alternative '+i} · ${formatChance(o.chance)} / ${formatChance(1-o.chance)}</h3>${i===0&&o.gap>.1?'<p class="notice">Auch die beste Aufteilung liegt außerhalb von 40:60. Die Teams sind nach diesem Modell deutlich ungleich.</p>':''}<div class="columns">${team(o.a,'Team A',o.chance)}${team(o.b,'Team B',1-o.chance)}</div></section>`).join('');
 }
 return {update};
})();
if(typeof module!=='undefined')module.exports={balancedTeams};
