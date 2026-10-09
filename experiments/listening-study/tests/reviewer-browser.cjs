/* Synthetic offline researcher acceptance; no real recordings leave the workstation. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {execFileSync} = require('node:child_process');
const {chromium, webkit, devices} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const demo = path.resolve(process.argv[2] || 'work/demo');
const out = path.resolve(process.argv[3] || 'work/reviewer-browser');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'yanjaro-review-'));
fs.mkdirSync(out, {recursive:true});
const code = `import copy,sys
from pathlib import Path
from listening_study.common import read_json
from listening_study.reviewer import export_review
c=read_json(Path(sys.argv[1])/'prepared/catalog.json')
p={'tracks':[{'id':t['id'],'title':'Demo '+t['id']+' <img src=https://forbidden.invalid/x>','artist':t['artist_id']} for t in c['tracks']]}
export_review(c,p,Path(sys.argv[2])/'pages')
empty=copy.deepcopy(c)
for t in empty['tracks']:t['instrument']=[]
export_review(empty,p,Path(sys.argv[2])/'empty')
`;
const checks=[], errors=[], outbound=[];
let desktop, mobile;
async function open(ctx, file) {
  const p=await ctx.newPage(); p.on('pageerror',e=>errors.push(e.message));
  p.on('request',r=>{if(!/^(file:|data:|blob:)/.test(r.url()))outbound.push(r.url());});
  await p.goto(pathToFileURL(file).href); await p.locator('#track-form textarea').first().waitFor(); return p;
}
async function exported(p) {
  const event=p.waitForEvent('download'); await p.locator('#export').click();
  const download=await event; const filename=path.join(temp,download.suggestedFilename());
  await download.saveAs(filename); return {filename,data:JSON.parse(fs.readFileSync(filename))};
}
(async()=>{
  execFileSync(process.env.STUDY_PYTHON || 'python3',['-c',code,demo,temp]);
  desktop=await chromium.launch();
  const ctx=await desktop.newContext({viewport:{width:1280,height:950},acceptDownloads:true});
  const p=await open(ctx,path.join(temp,'pages/reviewer-1.html'));
  assert.match(await p.locator('#identity').textContent(),/reviewer-1.*DEMO/);
  assert.equal(await p.locator('img').count(),0);
  assert.match(await p.locator('#comparison-status').textContent(),/диагностическое/);
  checks.push('researcher labels escaped; diagnostic comparisons distinguished from strict triples');
  const audio=p.locator('#players audio');
  await audio.nth(0).evaluate(a=>a.play()); await p.waitForFunction(()=>document.querySelector('#players audio').currentTime>.2);
  await audio.nth(1).evaluate(a=>a.play()); assert.equal(await audio.nth(0).evaluate(a=>a.paused),true); await audio.nth(1).evaluate(a=>a.pause());
  checks.push('offline embedded WAV playback and exclusive audio');
  await p.locator('#track-form [data-field=perceived_bpm]').fill('125');
  await p.locator('#track-form [data-field=bpm_wrong]').check();
  await p.locator('#track-form [data-field=instruments]').fill('Synthetic reviewer one observation');
  await p.locator('#track-form [data-field=decision]').selectOption('uncertain');
  await p.locator('#export').click(); assert.match(await p.locator('#error').textContent(),/причину/);
  await p.locator('#track-form [data-field=reason]').fill('DEMO: needs a different pulse interpretation');
  const pair=p.locator('#comparisons .card').first();
  await pair.locator('[data-field=rhythm_relation]').selectOption('far');
  await pair.locator('[data-field=similarity_wrong]').check();
  await pair.locator('[data-field=decision]').selectOption('unfit');
  await pair.locator('[data-field=reason]').fill('DEMO: rhythm judged different');
  const saved=await exported(p);
  assert.equal(saved.data.status,'PROVISIONAL'); assert.equal(saved.data.reviewer,'reviewer-1');
  assert.equal(Object.values(saved.data.tracks)[0].perceived_bpm,125);
  assert.equal(Object.values(saved.data.pairs)[0].similarity_wrong,true);
  assert.equal(/source_sha256|data:audio|\/tmp\/|rights|attribution/.test(JSON.stringify(saved.data)),false);
  checks.push('track/pair decisions and reasons; error flags; private bounded JSON export stays provisional');
  await p.reload(); await p.locator('#track-form textarea').first().waitFor();
  assert.equal(await p.locator('#track-form [data-field=perceived_bpm]').inputValue(),'125');
  checks.push('close/reload local draft recovery');
  await p.locator('#track-form [data-field=perceived_bpm]').fill('501');
  await p.locator('#export').click(); assert.match(await p.locator('#error').textContent(),/BPM/);
  await p.locator('#track-form [data-field=perceived_bpm]').fill('125');
  const second=await open(ctx,path.join(temp,'pages/reviewer-2.html'));
  assert.equal(await second.locator('#track-form [data-field=instruments]').inputValue(),'');
  await second.locator('#import').setInputFiles(saved.filename);
  await second.waitForFunction(()=>document.getElementById('error').textContent.includes('другому проверяющему'));
  assert.match(await second.locator('#error').textContent(),/другому проверяющему/);
  const secondSaved=await exported(second);
  assert.equal(secondSaved.data.reviewer,'reviewer-2');
  assert.equal(Object.values(secondSaved.data.tracks)[0].instruments,'');
  checks.push('reviewer two is independent and refuses reviewer one import; invalid BPM blocked');
  const importedCtx=await desktop.newContext({acceptDownloads:true});
  const restored=await open(importedCtx,path.join(temp,'pages/reviewer-1.html'));
  await restored.locator('#import').setInputFiles(saved.filename);
  await restored.waitForFunction(()=>document.querySelector('#track-form [data-field=instruments]').value==='Synthetic reviewer one observation');
  assert.equal(await restored.locator('#track-form [data-field=instruments]').inputValue(),'Synthetic reviewer one observation');
  const original=await restored.locator('#selectors select').first().inputValue();
  await restored.locator('#selectors select').nth(1).selectOption(original);
  assert.match(await restored.locator('#comparison-status').textContent(),/исключено/);
  assert.equal(await restored.locator('#comparisons .card').count(),0);
  checks.push('same-reviewer import in a fresh browser; repeated recording excluded');
  const empty=await open(ctx,path.join(temp,'empty/reviewer-1.html'));
  assert.match(await empty.locator('#pool-status').textContent(),/Строгих вариантов троек: 0/);
  await empty.locator('#import').setInputFiles(saved.filename);
  await empty.waitForFunction(()=>document.getElementById('error').textContent.includes('другому проверяющему или набору'));
  assert.match(await empty.locator('#error').textContent(),/другому проверяющему или набору/);
  assert.equal(await empty.locator('#players audio').count(),3);
  checks.push('zero-triple pool still playable; mismatched catalog import rejected');
  await p.screenshot({path:path.join(out,'review-desktop.png'),fullPage:true});
  const blockedCtx=await desktop.newContext({acceptDownloads:true});
  await blockedCtx.addInitScript(()=>Object.defineProperty(window,'localStorage',{get(){throw Error('storage unavailable');}}));
  const blocked=await open(blockedCtx,path.join(temp,'pages/reviewer-1.html'));
  await blocked.locator('#track-form [data-field=instruments]').fill('memory only');
  assert.match(await blocked.locator('#save-status').textContent(),/только в памяти/);
  assert.equal(Object.values((await exported(blocked)).data.tracks)[0].instruments,'memory only');
  checks.push('storage denial is explicit; JSON export still works');
  mobile=await webkit.launch();
  const mobileCtx=await mobile.newContext({...devices['iPhone 13'],acceptDownloads:true});
  const phone=await open(mobileCtx,path.join(temp,'pages/reviewer-2.html'));
  await phone.screenshot({path:path.join(out,'review-mobile.png'),fullPage:true});
  const fits=await phone.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth);
  if (!fits)
    console.error('Mobile overflow:',await phone.evaluate(()=>{
      const measure=()=>({inner:innerWidth,client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,body:document.body.scrollWidth,visual:visualViewport.width});
      const original=measure(), results={};
      const overflowing=[...document.querySelectorAll('main *')].filter(e=>e.scrollWidth>e.clientWidth+1).slice(0,12).map(e=>({tag:e.tagName,id:e.id,client:e.clientWidth,scroll:e.scrollWidth,box:e.getBoundingClientRect().width}));
      for(const selector of ['select','audio','input','details','header','footer']) {
        const nodes=[...document.querySelectorAll(selector)], previous=nodes.map(e=>e.style.display);
        nodes.forEach(e=>e.style.display='none');results[selector]=measure();nodes.forEach((e,i)=>e.style.display=previous[i]);
      }
      return {original,overflowing,hiddenElementDiagnostics:results};
    }));
  assert.equal(fits,true);
  await phone.locator('#players audio').first().evaluate(a=>a.play());
  await phone.waitForFunction(()=>document.querySelector('#players audio').currentTime>.2);
  await phone.locator('#players audio').first().evaluate(a=>a.pause());
  const mobileTrack=await phone.locator('#track option').last().getAttribute('value');
  await phone.locator('#track').selectOption(mobileTrack);
  await phone.locator('#track-form [data-field=tempo_note]').fill('DEMO mobile observation');
  const phoneSaved=await exported(phone);
  assert.equal(phoneSaved.data.tracks[mobileTrack].tempo_note,'DEMO mobile observation');
  await phone.screenshot({path:path.join(out,'review-mobile.png'),fullPage:true});
  checks.push('WebKit mobile layout, actual playback and independent JSON download');
  assert.deepEqual(errors,[]); assert.deepEqual(outbound,[]);
  fs.writeFileSync(path.join(out,'review-checks.json'),JSON.stringify({demo:true,chromium:desktop.version(),webkit:mobile.version(),checks,externalRequests:outbound.length,pageErrors:errors},null,2));
  console.log(JSON.stringify({checks:checks.length,result:'PASS'}));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{
  if(desktop)await desktop.close();if(mobile)await mobile.close();fs.rmSync(temp,{recursive:true,force:true});
});
