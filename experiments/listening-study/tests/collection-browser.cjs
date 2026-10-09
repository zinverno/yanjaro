/* Synthetic collection acceptance: real HTTP, SQLite and media, no real participants. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium, webkit, devices} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const demo = path.resolve(process.argv[2] || 'work/demo');
const out = path.resolve(process.argv[3] || 'work/collection-browser');
fs.mkdirSync(out, {recursive:true});
const base='http://127.0.0.1:8766', checks=[], errors=[], outbound=[];
let server, desktop, mobileBrowser;
const wait = (p,s) => p.locator(s).waitFor({state:'visible'});
async function serve() {
  server=spawn(process.env.STUDY_PYTHON || 'python3', ['-m','listening_study','collect',path.join(demo,'study.json'),path.join(out,'responses.sqlite'),path.join(demo,'collection.demo.json'),'--port','8766'], {stdio:['ignore','pipe','pipe']});
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(Error('Server startup timed out')),10000);
    server.stdout.once('data',()=>{clearTimeout(timer);resolve();});
    server.once('exit',c=>{clearTimeout(timer);reject(Error('Server exited: '+c));});
  });
}
async function page(context) {
  const p=await context.newPage();
  p.on('pageerror',e=>errors.push(e.message));
  await p.route('**/*',r=> {
    const u=r.request().url();
    if(u==='https://recruitment.invalid/') return r.fulfill({contentType:'text/html',body:`<a href="${base}/">Open listening study</a>`});
    if(u.startsWith(base+'/') || /^(data:|blob:)/.test(u)) return r.continue();
    outbound.push(u); return r.abort();
  });
  return p;
}
async function start(p) {
  await p.goto(base); await wait(p,'#restore-card');
  await p.locator('#consent').check(); await p.locator('#start').click(); await wait(p,'#trial');
}
async function listen(p) {
  for(const r of ['source','left','right']) {
    await p.locator('#'+r).evaluate(a=>a.play());
    await p.waitForFunction(r=>document.getElementById('heard-'+r).textContent.includes('✓'),r,{timeout:15000});
    await p.locator('#'+r).evaluate(a=>a.pause());
  }
}
async function skip(p, count) {
  for(let i=0;i<count;i++) {
    const n=await p.locator('#progress-text').textContent();
    await p.locator('#skip').click();
    await p.waitForFunction(n=>document.getElementById('trial').hidden || document.getElementById('progress-text').textContent!==n,n);
  }
}
async function state(context) {return (await context.request.get(base+'/api/state')).json();}
(async()=>{
  await serve(); desktop=await chromium.launch();
  const ctx=await desktop.newContext({viewport:{width:1200,height:1000}});
  let p=await page(ctx);
  await p.goto('https://recruitment.invalid/');
  await p.locator('a').click(); await wait(p,'#restore-card');
  checks.push('cross-site recruitment link opens landing page without allocating a session');
  assert.equal((await ctx.cookies()).length,0);
  assert.equal((await state(ctx)).status,'new');
  await p.locator('#decline').click(); await wait(p,'#withdrawn');
  assert.equal((await state(ctx)).status,'new'); checks.push('no collection/cookie before consent; decline');
  await start(p);
  const initial=await state(ctx), recovery=await p.locator('#recovery-code').textContent();
  const cookie=(await ctx.cookies())[0];
  assert.equal(cookie.httpOnly,true); assert.equal(cookie.sameSite,'Strict'); assert.ok(cookie.expires>0);
  assert.equal(await p.evaluate(()=>document.cookie), '');
  assert.equal(await p.evaluate(()=>localStorage.length+sessionStorage.length),0);
  assert.equal(/genre|artist_id|first_left|rights|source_sha256/.test(JSON.stringify(initial)),false);
  await p.screenshot({path:path.join(out,'collection-desktop.png'),fullPage:true,mask:[p.locator('#recovery-code')]});
  await listen(p); await p.locator('#choose-left').click();
  await p.waitForFunction(()=>document.getElementById('progress-text').textContent==='Задание 2 из 8');
  assert.equal((await state(ctx)).response.answers[0].choice,'left');
  // Lose acknowledgement AFTER commit: retry must not duplicate the answer.
  await p.route('**/api/answer',async r=>{await r.fetch(); await r.abort();});
  await p.locator('#skip').click();
  await p.waitForFunction(()=>document.getElementById('status').textContent.includes('не подтвердил'));
  assert.equal((await state(ctx)).response.answers.length,2);
  await p.unroute('**/api/answer'); await p.locator('#skip').click();
  await p.waitForFunction(()=>document.getElementById('progress-text').textContent==='Задание 3 из 8');
  assert.equal((await state(ctx)).response.answers.length,2);
  checks.push('real audio and autosave', 'lost acknowledgement and idempotent retry');
  await p.close();
  await new Promise(resolve=>{server.once('exit',resolve);server.kill('SIGTERM');}); await serve();
  p=await page(ctx); await p.goto(base); await wait(p,'#resume');
  await p.locator('#continue').click(); await wait(p,'#trial');
  assert.equal(await p.locator('#progress-text').textContent(),'Задание 3 из 8');
  assert.equal((await state(ctx)).response.participant_id,initial.response.participant_id);
  await listen(p); await p.locator('#neither').click();
  await p.waitForFunction(()=>document.getElementById('progress-text').textContent==='Задание 4 из 8');
  await skip(p,5); await wait(p,'#finished');
  assert.equal((await state(ctx)).status,'in_progress');
  assert.equal(await p.locator('#reward').isVisible(),false);
  await p.route('**/api/complete',r=>r.fulfill({status:503,body:'{}'}));
  await p.locator('#submit').click();
  await p.waitForFunction(()=>document.getElementById('status').textContent.includes('не подтвердил'));
  assert.equal((await state(ctx)).status,'in_progress');
  await p.unroute('**/api/complete'); await p.locator('#submit').click(); await wait(p,'#reward');
  const complete=await state(ctx);
  assert.equal(complete.status,'complete');
  assert.equal(await p.locator('#status').textContent(),'');
  assert.deepEqual(complete.response.answers.map(a=>a.choice),['left','skip','neither','skip','skip','skip','skip','skip']);
  assert.equal(await p.locator('#download').isVisible(),false);
  await p.screenshot({path:path.join(out,'collection-finished.png'),fullPage:true,mask:[p.locator('#recovery-code')]});
  checks.push('tab close + server restart recovery', 'explicit completion with retry', 'reward/credits only after completion');
  const restoredCtx=await desktop.newContext(); const restored=await page(restoredCtx);
  await restored.goto(base); await wait(restored,'#restore-card');
  await restored.locator('#restore-code').fill(recovery); await restored.locator('#restore').click(); await wait(restored,'#reward');
  assert.equal((await state(restoredCtx)).response.participant_id,complete.response.participant_id);
  assert.equal((await state(ctx)).status,'unavailable');
  await restored.locator('#discard').click(); await wait(restored,'#withdrawn');
  assert.equal((await state(restoredCtx)).status,'withdrawn');
  assert.equal('response' in await state(restoredCtx),false);
  checks.push('recovery code in another browser + old cookie revoked', 'completed answers deleted');
  mobileBrowser=await webkit.launch();
  const mctx=await mobileBrowser.newContext({...devices['iPhone 13']}); const m=await page(mctx);
  await start(m); await listen(m);
  await m.locator('#neither').click(); await m.waitForFunction(()=>document.getElementById('progress-text').textContent==='Задание 2 из 8');
  await m.reload(); await wait(m,'#resume'); await m.locator('#continue').click(); await wait(m,'#trial');
  assert.equal(await m.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await m.screenshot({path:path.join(out,'collection-mobile.png'),fullPage:true});
  await m.route('**/api/withdraw',r=>r.fulfill({status:503,body:'{}'}));
  await m.locator('#withdraw').click();
  await m.waitForFunction(()=>document.getElementById('status').textContent.includes('не подтвердил'));
  assert.equal((await state(mctx)).status,'in_progress'); assert.equal(await m.locator('#withdrawn').isVisible(),false);
  await m.unroute('**/api/withdraw'); await m.locator('#withdraw').click(); await wait(m,'#withdrawn');
  assert.equal((await state(mctx)).status,'withdrawn');
  assert.equal(await m.locator('#status').textContent(),'');
  checks.push('mobile WebKit real playback, neither, reload', 'mobile width and withdrawal failure/retry');
  const bad=await fetch(base+'/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({consent:true,consent_version:'collection-consent-v1'})});
  assert.equal(bad.status,403);
  assert.equal((await fetch(base+initial.bundle.trials[0].source)).status,403);
  assert.equal((await fetch(base+'/responses.sqlite')).status,404);
  assert.equal((await fetch(base+'/api/answer',{method:'POST',headers:{Origin:base,'Content-Type':'application/json'},body:'{}'})).status,400);
  assert.deepEqual(outbound,[]); assert.deepEqual(errors,[]);
  checks.push('CSRF, session and database access boundaries', 'HttpOnly cookie; no localStorage/fingerprinting/external requests');
  fs.writeFileSync(path.join(out,'collection-checks.json'),JSON.stringify({demo:true,chromium:await desktop.version(),webkit:await mobileBrowser.version(),checks,externalRequests:outbound.length,pageErrors:errors},null,2));
  console.log(`PASS: ${checks.length} collection acceptance groups`);
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{
  if(desktop) await desktop.close(); if(mobileBrowser) await mobileBrowser.close(); if(server) server.kill('SIGTERM');
});
