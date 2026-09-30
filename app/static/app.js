const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const formatNumber = v => Intl.NumberFormat('de-DE', {maximumFractionDigits:1}).format(v);
const num = v => v == null ? '—' : Math.abs(v)>=1e6 ? `${formatNumber(v/1e6)} Mio.` : Math.abs(v)>=10000 ? `${formatNumber(v/1000)} Tsd.` : formatNumber(v);
const pct = v => v == null ? '—' : `${Math.round(v*100)} %`;
const date = v => v ? new Date(v*1000).toLocaleDateString('de-DE',{day:'numeric',month:'short',year:'numeric'}) : 'Datum unbekannt';
const duration = v => `${Math.floor(v/60)} Min. ${Math.floor(v%60)} Sek.`;
const empty = text => `<div class="empty">${esc(text)}</div>`;

const outcomeText = value => ({win:'Sieg', victory:'Sieg', loss:'Niederlage', defeat:'Niederlage', draw:'Unentschieden', unknown:'Ergebnis unbekannt', resolved:'Entschieden'}[value] || 'Ergebnis unbekannt');

let rosterData;
let data, status, sortKey='wins', sortDirection=-1, requestId=0;
async function get(url) {
 const r=await fetch(url);
 if(!r.ok){
  if(r.status===429||r.status===503)throw new Error('Gerade viel Betrieb am Stammtisch. Bitte kurz warten und erneut laden.');
  throw new Error(`Anfrage fehlgeschlagen (${r.status})`);
 }
 return r.json();
}
async function refresh() {
  const id=++requestId; $('#refresh').disabled=true;
  try {
    const params=new URLSearchParams({minimum:$('#minimum').value});
    if($('#player').value) params.set('player',$('#player').value);
    if($('#period').value!=='all'){
      const today=new Date();today.setUTCHours(0,0,0,0);
      params.set('since',today.getTime()/1000-Number($('#period').value)*86400);
    }
    const result=await Promise.all([get('/api/dashboard?'+params),get('/api/status'),get('/api/roster')]);
    if(id!==requestId)return;
    [data,status,rosterData]=result;$('#error').hidden=true;
    const selectedPlayer=$('#player').value;
    const options=rosterData.players.slice().sort((a,b)=>a.name.localeCompare(b.name));
    $('#player').innerHTML='<option value="">Der ganzen Truppe</option>'+options.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
    if(selectedPlayer && !options.some(p=>p.id===selectedPlayer)){await refresh();return;}
    $('#player').value=selectedPlayer;
    $('.download').href='/api/dashboard?'+params;
    render();
  }catch(e){$('#error').textContent='Das Archiv konnte nicht geladen werden. '+e.message;$('#error').hidden=false;$('#sync').textContent='Keine Verbindung zum Archiv';}
  finally{if(id===requestId)$('#refresh').disabled=false;}
}
function render(){
 $('#sync').textContent=(status.error||status.counts.error>0)?'Replay-Import: Bitte Hinweise prüfen':status.running?'● Replays werden eingesammelt…':`● Automatischer Scan alle ${status.interval} Sek. · ${status.last_scan ? 'geprüft um '+new Date(status.last_scan*1000).toLocaleTimeString('de-DE') : 'startet gleich'}`;
 const t=data.totals;
 $('#summary').innerHTML=[[t.games,'Partien in dieser Ansicht','ARCHIV'],[t.players,'Freunde mit Partien','DIE TRUPPE'],[t.decided,'Entschiedene Partien','BILANZ'],[`${t.stats_games}/${t.games}`,'Partien mit Statistikdaten','DATENLAGE']].map(([v,l,s])=>`<div><small>${s}</small><strong>${v}</strong><span>${l}</span></div>`).join('');
 $('#leaders').innerHTML=[['reclaim','DER SCHROTTBARON','⌁','Masse aus Reclaim'],['experimentals','BAUMEISTER DER DICKEN DINGER','◇','Experimentals gebaut'],['mass','DIE ECO-MASCHINE','↗','Masse eingenommen']].map(([key,label,icon,unit])=>{const p=data.players.filter(p=>p.metrics[key].samples).sort((a,b)=>b.metrics[key].average-a.metrics[key].average)[0];return `<article class="leader"><span class="eyebrow">${label}</span><span class="icon">${icon}</span><h3>${p?esc(p.name):'Noch keine Statistikdaten'}</h3><div class="value">${p?num(p.metrics[key].average):'—'}</div><small>${unit} / Partie mit Daten</small><small>${p?p.metrics[key].samples+' von '+p.games+' Partien mit Daten':'Wartet auf ein Replay mit Statistikdaten'}</small></article>`;}).join('');
 const pairs=data.pairs.filter(p=>p.decided>=2).slice(0,4);
 $('#top-pairs').innerHTML=pairs.map((p,i)=>`<div class="row"><span class="rank">0${i+1}</span><div class="grow"><strong>${p.names.map(esc).join(' + ')}</strong><small>${p.wins} Siege · ${p.decided} gemeinsam entschieden</small></div><span class="pct">${pct(p.win_rate)}</span></div>`).join('')||empty('Für die Duo-Rangliste fehlen noch entschiedene Partien. Also: nächste Runde!');
 $('#recent').innerHTML=data.games.slice(0,4).map(g=>`<div class="row"><div class="grow"><button class="match-link" data-game="${esc(g.id)}"><strong>${esc(g.title)} <span class="muted">#${esc(g.id.slice(0,12))}</span></strong></button><small>${date(g.played_at)} · ${g.participant_count ?? g.players.length} Spieler · ${duration(g.duration)}</small></div><span class="status ${g.outcome}">${g.outcome==='resolved'?'Team '+esc(g.winner)+' gewinnt':outcomeText(g.outcome)}</span></div>`).join('')||empty('Hier ist noch Ruhe vor dem Sturm. Legt Replays in den Replay-Ordner.');
 renderPlayers();renderPairs();renderMatches();renderImports();renderRoster();
}
function renderPlayers(){
 const agg=$('#aggregation').value;
 const cols=[['name','Spieler'],['games','Partien'],['wins','Siege'],['win_rate','Siegquote'],['reclaim','Reclaim-Masse'],['experimentals','Experimentals'],['mass','Eco · Masse rein'],['energy','Energie rein'],['mass_wasted','Masseüberschuss']];
 const value=p=>p.metrics[sortKey]?p.metrics[sortKey][agg]:p[sortKey];
 const players=data.players.slice().sort((a,b)=>{let x=value(a),y=value(b);if(x==null)return 1;if(y==null)return -1;return sortDirection*(typeof x==='string'?x.localeCompare(y):x-y);});
 $('#players-table').innerHTML=players.length?`<table><thead><tr>${cols.map(([k,l])=>`<th><button data-sort="${k}">${l}${sortKey===k?(sortDirection===-1?' ↓':' ↑'):''}</button></th>`).join('')}</tr></thead><tbody>${players.map(p=>`<tr>${cols.map(([k])=>`<td>${k==='name'?`<strong>${esc(p.name)}</strong><small>FAF ${esc(p.id)}</small>`:k==='win_rate'?`${pct(p.win_rate)}<small>${p.decided} entschieden · ${p.unknown} unbekannt · ${p.draws} unentschieden</small>`:p.metrics[k]?`${num(p.metrics[k][agg])}<small>${p.metrics[k].samples}/${p.games} mit Daten</small>`:p[k]}</td>`).join('')}</tr>`).join('')}</tbody></table>`:empty('Mit diesen Filtern ist die Truppe wohl gerade in der Kantine. Keine passenden Partien.');
}
function renderPairs(){
 const ps=data.players.slice().sort((a,b)=>a.name.localeCompare(b.name));
 const find=(a,b)=>data.pairs.find(p=>p.ids.includes(a.id)&&p.ids.includes(b.id));
 $('#matrix').innerHTML=ps.length?`<table class="matrix"><thead><tr><th>Siegquote / Partien</th>${ps.map(p=>`<th>${esc(p.name)}</th>`).join('')}</tr></thead><tbody>${ps.map(a=>`<tr><th>${esc(a.name)}</th>${ps.map(b=>{if(a.id===b.id)return '<td>·</td>';const p=find(a,b);return `<td>${p?`<button class="cell ${!p.eligible?'unknown':p.win_rate<.5?'low':''}" data-pair="${esc(p.ids.join('|'))}" aria-label="${esc(a.name+' und '+b.name)}">${pct(p.win_rate)}<small>${p.decided} Partien${p.eligible?'':' *'}</small></button>`:'—'}</td>`;}).join('')}</tr>`).join('')}</tbody></table>`:empty('Noch keine gemeinsamen Partien. Das Dreamteam muss erst loslegen.');
 const pairs=data.pairs.filter(p=>p.eligible);
 $('#pairs-table').innerHTML=pairs.length?`<table><thead><tr><th>Duo</th><th>Siege / Niederlagen</th><th>Bisherige Siegquote</th><th>Geglättete Schätzung</th><th>95-%-Intervall</th></tr></thead><tbody>${pairs.map(p=>`<tr><td>${p.names.map(esc).join(' + ')}</td><td>${p.wins} / ${p.losses}</td><td>${pct(p.win_rate)}</td><td>${pct(p.estimate)}</td><td>${pct(p.interval[0])}–${pct(p.interval[1])}</td></tr>`).join('')}</tbody></table>`:empty('Noch kein Duo erfüllt die Mindestzahl. Grenze senken oder ein paar Runden nachlegen.');
}
function renderMatches(){
 const q=$('#search').value.toLowerCase();
 const games=data.games.filter(g=>[g.id,g.title,g.map,...g.players.map(p=>p.name)].join(' ').toLowerCase().includes(q));
 $('#match-list').innerHTML=games.map(g=>`<article class="archive-card"><div><button class="match-link" data-game="${esc(g.id)}"><h3>${esc(g.title)} <span class="muted">#${esc(g.id.slice(0,12))} ↗</span></h3></button><div class="map-name" title="${esc(g.map)}">${esc(g.map)}</div><small class="muted">${date(g.played_at)} · ${duration(g.duration)} · ${g.participant_count ?? g.players.length} Spieler</small></div><div><span class="status ${g.outcome}">${g.outcome==='resolved'?'Team '+esc(g.winner)+' gewinnt':g.outcome==='draw'?'Unentschieden':'Ergebnis unbekannt'}</span><br><small class="muted">${g.players.filter(p=>p.stats_tick!=null).length}/${g.players.length} Freunde mit Statistikdaten</small></div></article>`).join('')||empty('Keine passende Partie gefunden. Die Ausrede ist vorerst sicher.');
}
function renderImports(){
 const counts=status.counts;
 $('#import-info').textContent=status.error?'Der Replay-Import braucht gerade Aufmerksamkeit. Bereits verfügbare Statistiken bleiben abrufbar.':`${counts.imported} Dateien importiert · ${counts.excluded} ausgeschlossen · ${counts.error} nicht verarbeitet. Mehrere Replays derselben Partie zählen nur einmal.`;
 $('#import-counts').innerHTML=[['Importiert',counts.imported,'Erfolgreich eingelesene Replay-Dateien.'],['Ausgeschlossen',counts.excluded,'Diese Replays passen nicht zur Freundesregel.'],['Nicht verarbeitet',counts.error,'Diese Replays konnten noch nicht eingelesen werden.']].map(([label,count,description])=>`<article class="panel"><h2>${label}</h2><strong class="pct">${num(count)}</strong><p>${description}</p></article>`).join('');
}
function showGame(id){
 const g=data.games.find(g=>g.id===id);if(!g)return;
 const teams=[...new Set(g.players.map(p=>p.team))];
 $('#game-detail').innerHTML=`<div class="eyebrow">DAS GEFECHTSPROTOKOLL</div><h2>${esc(g.title)} · #${esc(g.id)}</h2><p class="game-meta">${esc(g.map)}<br>${date(g.played_at)} · ${duration(g.duration)}<br>${g.players.length} Freunde · ${g.guest_count || 0} Gäste · Statistiken nur für die Freundesliste.</p>${teams.map(t=>`<div class="team"><h3>Team ${esc(t)} ${g.winner===t?'· SIEG':''}</h3><div class="scroll"><table><thead><tr><th>Spieler</th><th>Teamergebnis</th><th>Reclaim-Masse</th><th>Experimentals</th><th>Masse eingenommen</th><th>Energie eingenommen</th><th>Letzter Datenstand</th></tr></thead><tbody>${g.players.filter(p=>p.team===t).map(p=>`<tr><td>${esc(p.name)}<small>${['Unbekannt','UEF','Aeon','Cybran','Seraphim'][p.faction]||'Andere'} · ${esc(p.reported_result ? p.reported_result.split(', ').map(outcomeText).join(', ') : 'kein Einzelergebnis')}</small></td><td>${outcomeText(p.result)}</td><td>${num(p.reclaim)}</td><td>${num(p.experimentals)}</td><td>${num(p.mass)}</td><td>${num(p.energy)}</td><td>${p.stats_tick==null?'Fehlt':duration(p.stats_tick/10)}</td></tr>`).join('')}</tbody></table></div></div>`).join('')}<p class="footnote">Der letzte Datenstand kann vor dem Ende der Partie liegen. Die Werte sind aufgezeichnete Zwischenstände und nicht immer Endergebnisse. Wer früh ausscheidet, gewinnt trotzdem mit, wenn das Team später siegt.</p>`;
 $('#game-dialog').showModal();
}
function renderRoster(){
 const policy=rosterData.policy;
 $('#roster-banner').textContent=policy.error?'Die Freundesliste ist nicht lesbar oder ungültig. Bis sie korrigiert ist, bleiben die Statistiken ausgeblendet.':`${policy.player_ids.length} Freunde auf der Liste · ${policy.max_outsiders===0?'Nur Partien unter Freunden':'Höchstens ein Gast pro Partie'}. In die Statistik kommen nur Freunde.`;
}
document.addEventListener('click',e=>{
 const tab=e.target.closest('[data-tab]');if(tab){document.querySelectorAll('.tab').forEach(el=>el.hidden=el.id!==tab.dataset.tab);document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b===tab));}
 const game=e.target.closest('[data-game]');if(game)showGame(game.dataset.game);
 const sort=e.target.closest('[data-sort]');if(sort){sortDirection=sortKey===sort.dataset.sort?-sortDirection:-1;sortKey=sort.dataset.sort;renderPlayers();}
 const pair=e.target.closest('[data-pair]');if(pair){const p=data.pairs.find(p=>p.ids.join('|')===pair.dataset.pair);$('#pair-detail').textContent=`${p.names.join(' + ')}: ${p.wins} Siege, ${p.losses} Niederlagen, ${p.draws} Unentschieden, ${p.unknown} unbekannte Ergebnisse in ${p.games} gemeinsamen Partien. Bisherige Siegquote ${pct(p.win_rate)}; geglättete Schätzung ${pct(p.estimate)}; 95-%-Intervall ${pct(p.interval[0])}–${pct(p.interval[1])}.${p.eligible?'':' * Weniger entschiedene Partien als die gewählte Mindestzahl.'}`;}
});
$('.close').onclick=()=>$('#game-dialog').close();
$('#refresh').onclick=refresh;
['period','player','minimum'].forEach(id=>$('#'+id).onchange=refresh);
$('#aggregation').onchange=()=>renderPlayers();$('#search').oninput=()=>renderMatches();
refresh();setInterval(refresh,15000);
