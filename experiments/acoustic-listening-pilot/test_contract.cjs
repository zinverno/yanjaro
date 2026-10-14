'use strict';
const assert = require('node:assert/strict');
const C = require('./app.js');
const p = {schema:'yanjaro.acoustic-listening.v1',kind:'technical-test-only',reviewer:'TEST_ONLY',
  package:'TEST_ONLY',trials:Array.from({length:14},(_,i)=>({token:'TEST_ONLY_'+i}))};
let s = C.empty(p);
assert(s.responses.every(r=>r.choice === null && r.aspect === null && r.confidence === null));
assert.deepEqual(C.validate(JSON.parse(JSON.stringify(s)),p),s);
// Isolated enum serialization; no human session, music key, or response artifact is created.
for (const choice of ['A','B','tie','neither','uncertain']) {
  s.responses[0].choice = choice;
  assert.deepEqual(C.validate(JSON.parse(JSON.stringify(s)),p),s);
}
assert.equal(s.responses.filter(r=>r.choice === null).length,13);
for (const change of [{reviewer:'OTHER'},{package:'OTHER'},{position:true},{correct_answer:'A'}]) {
  assert.throws(()=>C.validate({...s,...change},p));
}
for (const change of [{choice:'correct'},{aspect:'genre'},{confidence:0},{confidence:6},{confidence:true},{token:'OTHER'},{answer:'B'}]) {
  const bad = structuredClone(s); Object.assign(bad.responses[0],change);
  assert.throws(()=>C.validate(bad,p));
}
s = C.empty(p);
assert.equal(C.csv(s).trim().split('\n').length,15);
assert(!C.csv(s).includes('correct'));
console.log('PASS: blank defaults, partial in-memory enum roundtrip, strict fields, session isolation, anonymous CSV');
