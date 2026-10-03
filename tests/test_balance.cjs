const assert=require('node:assert/strict');
const {balancedTeams}=require('../app/static/balance.js');
const people=ratings=>ratings.map((rating,i)=>({id:String(i),rating}));
const perfect=balancedTeams(people([800,1000,800,1000]));
assert.equal(perfect[0].gap,0);
assert.equal(perfect.length,3);
for(const option of perfect){assert.equal(new Set([...option.a,...option.b].map(p=>p.id)).size,4);assert.equal(option.a.length,2);}
const odd=balancedTeams(people([1000,1000,1000,1000,1000]));
assert.equal(odd[0].a.length,2);assert.equal(odd[0].b.length,3);assert.equal(odd[0].chance,.4);
assert.equal(balancedTeams(people([1000])).length,0);
assert.equal(balancedTeams(people(Array(21).fill(1000))).length,0);
assert.equal(balancedTeams(people([1000,1400]))[0].chance,1/11);
// Exhaustive independent bitmask reference for a nontrivial odd-sized lobby.
const players=people([750,1300,1100,900,1500,1020,990]);let optimum=Infinity;
for(let mask=0;mask<1<<players.length;mask++){
 const team=players.filter((_,i)=>mask>>i&1);if(team.length!==3)continue;
 const power=ps=>ps.reduce((s,p)=>s+10**((p.rating-1000)/400),0);
 optimum=Math.min(optimum,Math.abs(power(team)/power(players)-.5));
}
assert.equal(balancedTeams(players)[0].gap,optimum);
console.log('Team balancing passed: optimum, even/odd lobbies, unique coverage, and player advantage.');
const {currentGameBalance}=require('../app/static/balance.js');
const match={players:[{id:'a',team:'2'},{id:'b',team:'3'}],team_sizes:{'2':2,'3':1}};
assert.deepEqual(currentGameBalance(match,{players:[{id:'a',rating:1000},{id:'b',rating:1000}]}),{'2':2/3,'3':1/3});
assert.deepEqual(currentGameBalance(match,{players:[{id:'a',rating:1000},{id:'b',rating:1400}]}),{'2':1/6,'3':5/6});
assert.equal(currentGameBalance({...match,team_sizes:{'2':1,'3':1,'4':1}},{players:[]}),null);
const {balanceVerdict}=require('../app/static/balance.js');
const elo={players:[{id:'a',rating:1000},{id:'b',rating:1000}]};
assert.equal(balanceVerdict({...match,outcome:'resolved',winner:'2'},elo).kind,'correct');
assert.equal(balanceVerdict({...match,outcome:'resolved',winner:'3'},elo).kind,'upset');
assert.equal(balanceVerdict({...match,outcome:'draw'},elo).kind,'neutral');
assert.match(balanceVerdict({...match,team_sizes:{'2':1,'3':1},outcome:'resolved',winner:'2'},elo).text,/50:50/);
