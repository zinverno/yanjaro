/* Node DOM/storage adapter: transport tests only. Never creates human response files. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code=fs.readFileSync(__dirname+'/app.js','utf8');
const C=require('./app.js');
const p={schema:'yanjaro.acoustic-listening.v1',kind:'technical-test-only',reviewer:'TEST_REVIEWER',
  package:'TEST_PACKAGE',trials:Array.from({length:14},(_,i)=>({token:'TEST_'+i,X:'opaque',A:'opaque',B:'opaque'})),clips:{}};
const storage=new Map();
function mount(pack=p) {
  const elements=new Map(), downloads=[];
  function element(id) {
    if(!elements.has(id)) elements.set(id,{value:'',textContent:'',hidden:false,checked:false,disabled:false,
      classList:{toggle(){}},pause(){},removeAttribute(){},load(){},click(){return this.onclick?.();},files:[]});
    return elements.get(id);
  }
  const radios=['A','B','tie','neither','uncertain'].map(v=>({...element('radio'+v),value:v}));
  const document={getElementById:element,querySelectorAll:s=>s==='[name=choice]'?radios:[],
    createElement:()=>({click(){downloads.push(this.href);}})};
  const blobs=new Map(); let n=0;
  const context={PILOT:pack,document,localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    confirm:()=>true,Blob,URL:{createObjectURL:b=>{const k='blob:'+(n++);blobs.set(k,b);return k;},revokeObjectURL(){}},setTimeout:()=>{}};
  vm.runInNewContext(code,context);
  return {element,radios,downloads,blobs};
}
(async()=>{
  let ui=mount(); ui.element('start').click();
  assert(ui.radios.every(r=>!r.checked));
  ui.element('next').click();
  assert.match(ui.element('progress').textContent,/Сравнение 2/);
  // One technical enum event tests save/resume; there is no audio, human, or real package key.
  ui.radios[0].onchange();
  ui=mount(); ui.element('start').click();
  assert(ui.radios[0].checked); assert(!ui.radios[1].checked);
  ui.element('json').click();
  const exported=JSON.parse(await ui.blobs.get(ui.downloads.at(-1)).text());
  assert.equal(exported.kind,'technical-test-only');
  C.validate(exported,p); assert.equal(exported.responses.filter(r=>r.choice!==null).length,1);
  const other=mount({...p,reviewer:'TEST_OTHER',package:'TEST_OTHER_PACKAGE'});
  other.element('start').click(); assert(other.radios.every(r=>!r.checked));
  other.element('import').files=[{size:1000,text:async()=>JSON.stringify(exported)}];
  await other.element('import').onchange(); assert.match(other.element('status').textContent,/Файл не принят/);
  ui.element('withdraw').click(); assert(ui.radios.every(r=>!r.checked));
  ui.element('import').files=[{size:1000,text:async()=>JSON.stringify(exported)}];
  await ui.element('import').onchange(); assert(ui.radios[0].checked);
  // Parallel tabs must not silently overwrite the stored response.
  const stale=mount(); ui.element('next').click();
  const saved=[...storage.values()]; stale.element('next').click();
  assert.match(stale.element('status').textContent,/другая вкладка/); assert.deepEqual([...storage.values()],saved);
  ui.element('clear').click();
  ui.element('withdraw').click();
  assert.equal(storage.size,0);
  console.log('PASS: UI handlers, partial save/resume/import, reviewer separation, conflict guard, withdrawal. Technical in-memory fixtures only.');
})().catch(e=>{console.error(e);process.exitCode=1;});
