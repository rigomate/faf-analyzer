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
