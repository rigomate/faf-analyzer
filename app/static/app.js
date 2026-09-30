const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = v => v == null ? '—' : Intl.NumberFormat('en', {maximumFractionDigits:1, notation:Math.abs(v)>=10000?'compact':'standard'}).format(v);
const pct = v => v == null ? '—' : `${Math.round(v*100)}%`;
const date = v => v ? new Date(v*1000).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'}) : 'Date unknown';
const duration = v => `${Math.floor(v/60)}m ${Math.floor(v%60)}s`;
const empty = text => `<div class="empty">${esc(text)}</div>`;
let rosterData;
let data, status, sortKey='wins', sortDirection=-1, requestId=0;
async function get(url) {const r=await fetch(url);if(!r.ok)throw new Error(`Request failed (${r.status})`);return r.json();}
async function refresh() {
  const id=++requestId; $('#refresh').disabled=true;
  try {
    const params=new URLSearchParams({minimum:$('#minimum').value});
    if($('#player').value) params.set('player',$('#player').value);
    if($('#period').value!=='all') params.set('since',Date.now()/1000-Number($('#period').value)*86400);
    const result=await Promise.all([get('/api/dashboard?'+params),get('/api/status'),get('/api/roster')]);
    if(id!==requestId)return;
    [data,status,rosterData]=result;$('#error').hidden=true;
    if(!$('#player').value){const options=data.players.slice().sort((a,b)=>a.name.localeCompare(b.name));$('#player').innerHTML='<option value="">Everyone</option>'+options.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');}
    $('.download').href='/api/dashboard?'+params;
    render();
  }catch(e){$('#error').textContent='Could not load the archive. '+e.message;$('#error').hidden=false;$('#sync').textContent='Connection unavailable';}
  finally{if(id===requestId)$('#refresh').disabled=false;}
}
function render(){
 $('#sync').textContent=(status.error||status.files.some(f=>f.status==='error'))?'Scanner needs attention':status.running?'● Importing replays…':`● Auto-scan every ${status.interval}s · ${status.last_scan ? 'checked '+new Date(status.last_scan*1000).toLocaleTimeString() : 'starting'}`;
 const t=data.totals;
 $('#summary').innerHTML=[[t.games,'Replays in view','ARCHIVE'],[t.players,'Players in the squad','ROSTER'],[t.decided,'Decided team results','RESULTS'],[`${t.stats_games}/${t.games}`,'Games with recorded stats','COVERAGE']].map(([v,l,s])=>`<div><small>${s}</small><strong>${v}</strong><span>${l}</span></div>`).join('');
 $('#leaders').innerHTML=[['reclaim','RECLAIM ROYALTY','⌁','mass reclaimed'],['experimentals','EXPERIMENTAL ENTHUSIAST','◇','experimentals built'],['mass','THE ECO ENGINE','↗','mass income']].map(([key,label,icon,unit])=>{const p=data.players.filter(p=>p.metrics[key].samples).sort((a,b)=>b.metrics[key].average-a.metrics[key].average)[0];return `<article class="leader"><span class="eyebrow">${label}</span><span class="icon">${icon}</span><h3>${p?esc(p.name):'No recorded stats'}</h3><div class="value">${p?num(p.metrics[key].average):'—'}</div><small>${unit} / recorded game</small><small>${p?p.metrics[key].samples+' of '+p.games+' games with data':'Awaiting a replay with JsonStats'}</small></article>`;}).join('');
 const pairs=data.pairs.filter(p=>p.decided>=2).slice(0,4);
 $('#top-pairs').innerHTML=pairs.map((p,i)=>`<div class="row"><span class="rank">0${i+1}</span><div class="grow"><strong>${p.names.map(esc).join(' + ')}</strong><small>${p.wins} wins · ${p.decided} decided together</small></div><span class="pct">${pct(p.win_rate)}</span></div>`).join('')||empty('More decided games needed to rank teammate pairs.');
 $('#recent').innerHTML=data.games.slice(0,4).map(g=>`<div class="row"><div class="grow"><button class="match-link" data-game="${esc(g.id)}"><strong>${esc(g.title)} <span class="muted">#${esc(g.id.slice(0,12))}</span></strong></button><small>${date(g.played_at)} · ${g.players.length} players · ${duration(g.duration)}</small></div><span class="status ${g.outcome}">${g.outcome==='resolved'?'Team '+esc(g.winner)+' won':g.outcome}</span></div>`).join('')||empty('No replays yet. Add files to the replay folder.');
 renderPlayers();renderPairs();renderMatches();renderImports();renderRoster();
}
function renderPlayers(){
 const agg=$('#aggregation').value;
 const cols=[['name','Player'],['games','Games'],['wins','Wins'],['win_rate','Win rate'],['reclaim','Reclaim mass'],['experimentals','Experimentals'],['mass','Eco · mass in'],['energy','Energy in'],['mass_wasted','Mass overflow']];
 const value=p=>p.metrics[sortKey]?p.metrics[sortKey][agg]:p[sortKey];
 const players=data.players.slice().sort((a,b)=>{let x=value(a),y=value(b);if(x==null)return 1;if(y==null)return -1;return sortDirection*(typeof x==='string'?x.localeCompare(y):x-y);});
 $('#players-table').innerHTML=players.length?`<table><thead><tr>${cols.map(([k,l])=>`<th><button data-sort="${k}">${l}${sortKey===k?(sortDirection===-1?' ↓':' ↑'):''}</button></th>`).join('')}</tr></thead><tbody>${players.map(p=>`<tr>${cols.map(([k])=>`<td>${k==='name'?`<strong>${esc(p.name)}</strong><small>FAF ${esc(p.id)}</small>`:k==='win_rate'?`${pct(p.win_rate)}<small>${p.decided} decided · ${p.unknown} unknown · ${p.draws} draws</small>`:p.metrics[k]?`${num(p.metrics[k][agg])}<small>${p.metrics[k].samples}/${p.games} recorded</small>`:p[k]}</td>`).join('')}</tr>`).join('')}</tbody></table>`:empty('No players match these filters.');
}
function renderPairs(){
 const ps=data.players.slice().sort((a,b)=>a.name.localeCompare(b.name));
 const find=(a,b)=>data.pairs.find(p=>p.ids.includes(a.id)&&p.ids.includes(b.id));
 $('#matrix').innerHTML=ps.length?`<table class="matrix"><thead><tr><th>Win rate / games</th>${ps.map(p=>`<th>${esc(p.name)}</th>`).join('')}</tr></thead><tbody>${ps.map(a=>`<tr><th>${esc(a.name)}</th>${ps.map(b=>{if(a.id===b.id)return '<td>·</td>';const p=find(a,b);return `<td>${p?`<button class="cell ${!p.eligible?'unknown':p.win_rate<.5?'low':''}" data-pair="${esc(p.ids.join('|'))}" aria-label="${esc(a.name+' and '+b.name)}">${pct(p.win_rate)}<small>${p.decided} games${p.eligible?'':' *'}</small></button>`:'—'}</td>`;}).join('')}</tr>`).join('')}</tbody></table>`:empty('No teammate data yet.');
 const pairs=data.pairs.filter(p=>p.eligible);
 $('#pairs-table').innerHTML=pairs.length?`<table><thead><tr><th>Teammates</th><th>Win / loss</th><th>Observed win rate</th><th>Smoothed estimate</th><th>95% interval</th></tr></thead><tbody>${pairs.map(p=>`<tr><td>${p.names.map(esc).join(' + ')}</td><td>${p.wins} / ${p.losses}</td><td>${pct(p.win_rate)}</td><td>${pct(p.estimate)}</td><td>${pct(p.interval[0])}–${pct(p.interval[1])}</td></tr>`).join('')}</tbody></table>`:empty('No pairs meet the minimum. Lower the threshold or import more matches.');
}
function renderMatches(){
 const q=$('#search').value.toLowerCase();
 const games=data.games.filter(g=>[g.id,g.title,g.map,...g.players.map(p=>p.name)].join(' ').toLowerCase().includes(q));
 $('#match-list').innerHTML=games.map(g=>`<article class="archive-card"><div><button class="match-link" data-game="${esc(g.id)}"><h3>${esc(g.title)} <span class="muted">#${esc(g.id.slice(0,12))} ↗</span></h3></button><div class="map-name" title="${esc(g.map)}">${esc(g.map)}</div><small class="muted">${date(g.played_at)} · ${duration(g.duration)} · ${g.players.length} players</small></div><div><span class="status ${g.outcome}">${g.outcome==='resolved'?'Team '+esc(g.winner)+' won':g.outcome==='draw'?'Draw':'Result unknown'}</span><br><small class="muted">${g.players.filter(p=>p.stats_tick!=null).length}/${g.players.length} player snapshots</small></div></article>`).join('')||empty('No matches found.');
}
function renderImports(){
 $('#import-info').textContent=status.error||`${status.files.filter(f=>f.status==='imported').length} files imported · ${status.files.filter(f=>f.status==='excluded').length} excluded · ${status.files.filter(f=>f.status==='error').length} errors. Duplicate game IDs count as one match. Archived matches remain in the database if the original file is removed.`;
 $('#files').innerHTML=status.files.length?`<table><thead><tr><th>Replay file</th><th>Status</th><th>Details</th></tr></thead><tbody>${status.files.map(f=>`<tr><td>${esc(f.path)}</td><td class="status ${f.status==='error'?'unknown':''}">${esc(f.status)}</td><td>${esc(f.error||'Game #'+f.game_id)}</td></tr>`).join('')}</tbody></table>`:empty('Waiting for the first folder scan.');
}
function showGame(id){
 const g=data.games.find(g=>g.id===id);if(!g)return;
 const teams=[...new Set(g.players.map(p=>p.team))];
 $('#game-detail').innerHTML=`<div class="eyebrow">MATCH REPORT</div><h2>${esc(g.title)} · #${esc(g.id)}</h2><p class="game-meta">${esc(g.map)}<br>${date(g.played_at)} · ${duration(g.duration)} · ${esc(g.filename)}</p>${teams.map(t=>`<div class="team"><h3>Team ${esc(t)} ${g.winner===t?'· VICTORY':''}</h3><div class="scroll"><table><thead><tr><th>Player</th><th>Team outcome</th><th>Reclaim mass</th><th>Experimentals</th><th>Mass income</th><th>Energy income</th><th>Snapshot time</th></tr></thead><tbody>${g.players.filter(p=>p.team===t).map(p=>`<tr><td>${esc(p.name)}<small>${['Unknown','UEF','Aeon','Cybran','Seraphim'][p.faction]||'Other'} · ${esc(p.reported_result||'no individual result')}</small></td><td>${p.result}</td><td>${num(p.reclaim)}</td><td>${num(p.experimentals)}</td><td>${num(p.mass)}</td><td>${num(p.energy)}</td><td>${p.stats_tick==null?'Missing':duration(p.stats_tick/10)}</td></tr>`).join('')}</tbody></table></div></div>`).join('')}<p class="footnote">Snapshot time is the last statistics update for that player and can precede the end of the recording. Totals are observed snapshots, not guaranteed final totals. Individual defeat does not override a later team victory.</p>${g.warnings.map(w=>`<p class="notice">${esc(w)}</p>`).join('')}`;
 $('#game-dialog').showModal();
}
function renderRoster(){
 const policy=rosterData.policy;
 $('#roster-banner').textContent=policy.error?'Match statistics are unavailable because the friend configuration needs attention.':`${policy.player_ids.length} friends on the list · ${policy.max_outsiders===0?'Friends-only matches':'Up to one outsider per match'}. Applies to both teams.`;
}
document.addEventListener('click',e=>{
 const tab=e.target.closest('[data-tab]');if(tab){document.querySelectorAll('.tab').forEach(el=>el.hidden=el.id!==tab.dataset.tab);document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b===tab));}
 const game=e.target.closest('[data-game]');if(game)showGame(game.dataset.game);
 const sort=e.target.closest('[data-sort]');if(sort){sortDirection=sortKey===sort.dataset.sort?-sortDirection:-1;sortKey=sort.dataset.sort;renderPlayers();}
 const pair=e.target.closest('[data-pair]');if(pair){const p=data.pairs.find(p=>p.ids.join('|')===pair.dataset.pair);$('#pair-detail').textContent=`${p.names.join(' + ')}: ${p.wins} wins, ${p.losses} losses, ${p.draws} draws, ${p.unknown} unknown across ${p.games} shared games. Observed win rate ${pct(p.win_rate)}; smoothed estimate ${pct(p.estimate)}; 95% interval ${pct(p.interval[0])}–${pct(p.interval[1])}.${p.eligible?'':' * Below the selected minimum sample size.'}`;}
});
$('.close').onclick=()=>$('#game-dialog').close();
$('#refresh').onclick=refresh;
['period','player','minimum'].forEach(id=>$('#'+id).onchange=refresh);
$('#aggregation').onchange=()=>renderPlayers();$('#search').oninput=()=>renderMatches();
refresh();setInterval(refresh,15000);
