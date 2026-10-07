const assert=require('node:assert/strict');
const {balancedTeams,currentGameBalance,historicalGameBalance,balanceVerdict}=require('../app/static/balance.js');
const people=ratings=>ratings.map((rating,i)=>({id:String(i),rating}));
const perfect=balancedTeams(people([800,1000,800,1000]));
assert.equal(perfect[0].gap,0);
assert.equal(perfect.length,3);
for(const option of perfect){assert.equal(new Set([...option.a,...option.b].map(p=>p.id)).size,4);assert.equal(option.a.length,2);}
const odd=balancedTeams(people([1000,1000,1000,1000,1000]));
assert.equal(odd[0].a.length,2);assert.equal(odd[0].b.length,3);assert.equal(odd[0].chance,.5);
assert.equal(balancedTeams(people([1000])).length,0);
assert.equal(balancedTeams(people(Array(21).fill(1000))).length,0);
assert.equal(balancedTeams(people([1000,1500]))[0].chance,1/11);
// Independent exhaustive reference using team averages.
const players=people([750,1300,1100,900,1500,1020,990]);let optimum=Infinity;
for(let mask=0;mask<1<<players.length;mask++){
 const team=players.filter((_,i)=>mask>>i&1);if(team.length!==3)continue;
 const other=players.filter((_,i)=>!(mask>>i&1));
 const mean=ps=>ps.reduce((s,p)=>s+p.rating,0)/ps.length;
 const chance=1/(1+10**((mean(other)-mean(team))/500));
 optimum=Math.min(optimum,Math.abs(chance-.5));
}
assert.ok(Math.abs(balancedTeams(players)[0].gap-optimum)<1e-12);
const match={id:'match',players:[{id:'a',team:'2'},{id:'b',team:'3'}],team_sizes:{'2':2,'3':1}};
assert.deepEqual(currentGameBalance(match,{players:[{id:'a',rating:1000},{id:'b',rating:1000}]}),{'2':.5,'3':.5});
const expected=1/(1+10**(400/500));
assert.deepEqual(currentGameBalance(match,{players:[{id:'a',rating:1000},{id:'b',rating:1400}]}),{'2':expected,'3':1-expected});
assert.equal(currentGameBalance({...match,team_sizes:{'2':1,'3':1,'4':1}},{players:[]}),null);
const elo={players:[{id:'a',rating:800},{id:'b',rating:1500}],predictions:{match:{probabilities:{'2':.6,'3':.4}}}};
assert.equal(balanceVerdict({...match,outcome:'resolved',winner:'2'},elo).kind,'correct');
assert.equal(balanceVerdict({...match,outcome:'resolved',winner:'3'},elo).kind,'upset');
assert.equal(balanceVerdict({...match,outcome:'draw'},elo).kind,'neutral');
assert.match(balanceVerdict({...match,outcome:'resolved',winner:'2'},{predictions:{match:{probabilities:{'2':.5,'3':.5}}}}).text,/50:50/);
// Form and API parameters apply in both balancing paths.
const formPlayers=[{id:'a',rating:1000,form:1},{id:'b',rating:1000,form:0}];
const formChance=1/(1+10**(-20/500));
assert.ok(Math.abs(balancedTeams(formPlayers)[0].chance-formChance)<1e-12);
assert.ok(Math.abs(currentGameBalance({...match,team_sizes:{'2':1,'3':1}},{players:formPlayers})['2']-formChance)<1e-12);
assert.ok(Math.abs(currentGameBalance(match,{players:formPlayers})['2']-1/(1+10**(-15/500)))<1e-12);
const custom={base:1000,scale:1000,form_strength:40};
assert.ok(Math.abs(balancedTeams(formPlayers,custom)[0].chance-formChance)<1e-12);
assert.ok(Math.abs(currentGameBalance({...match,team_sizes:{'2':1,'3':1}},{...custom,players:formPlayers})['2']-formChance)<1e-12);
assert.equal(currentGameBalance({...match,team_sizes:{'2':0,'3':1}},elo),null);
assert.deepEqual(currentGameBalance({...match,players:match.players.map(p=>({...p,kills_mass:1e9,score:1e9}))},elo),currentGameBalance(match,elo));
assert.equal(balancedTeams([{id:'1'},{id:'2'}])[0].chance,.5);
console.log('Team balancing passed: optimum, even/odd lobbies, identity, form, parameters, guests, and predictions.');

assert.deepEqual(historicalGameBalance(match,elo),{'2':.6,'3':.4});
assert.equal(historicalGameBalance({...match,id:'missing'},elo),null);
assert.equal(balanceVerdict({...match,id:'missing',outcome:'resolved',winner:'2'},elo).kind,'neutral');
assert.match(balanceVerdict({...match,outcome:'resolved',winner:'2'},{players:elo.players}).text,/nicht verfügbar/);
