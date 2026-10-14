/* Real-browser smoke: blank real sessions only, no acoustic answers are supplied. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const run = process.argv[2], out = process.argv[3];
if (!run || !out) throw Error('Usage: node browser_check.cjs PRIVATE_RUN NEW_REPORT.json');
(async()=>{
  const errors=[], requests=[], checks=[];
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM,
    args:['--disable-gpu','--disable-background-networking']});
  try {
  const context = await browser.newContext({acceptDownloads:true});
  await context.route(/^https?:/,route=>{requests.push(route.request().url());return route.abort();});
  const page=await context.newPage();
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error') errors.push(m.text());});
  await page.goto(pathToFileURL(path.resolve(run,'listener-1.html')).href);
  await page.locator('#start').click();
  assert.equal(await page.locator('[name=choice]:checked').count(),0);
  for (const role of ['X','A','B']) {
    await page.locator(`[data-play="${role}"]`).click();
    await page.waitForFunction(()=>document.querySelector('audio').readyState>=2);
    assert.equal(await page.locator('audio').evaluate(a=>a.duration),15);
    await page.waitForFunction(()=>document.querySelector('audio').currentTime>0);
  }
  checks.push('X/A/B float WAV loads, duration 15, playback clock advances; no judgment');
  await page.locator('#next').click();
  await page.reload(); await page.locator('#start').click();
  assert.match(await page.locator('#progress').innerText(),/Сравнение 2 из 14/);
  assert.equal(await page.locator('[name=choice]:checked').count(),0);
  checks.push('Blank unfinished session position survives reload; answers remain null');
  const jsonEvent=page.waitForEvent('download'); await page.locator('#json').click();
  const download=await jsonEvent;
  const state=JSON.parse(fs.readFileSync(await download.path(),'utf8'));
  assert(state.responses.every(r=>r.choice===null));
  assert.equal(state.responses.length,14);
  page.on('dialog',d=>d.accept());
  await page.locator('#withdraw').click();
  await page.locator('#import').setInputFiles({name:'blank-backup.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(state))});
  await page.waitForFunction(()=>document.querySelector('#progress').textContent.includes('Сравнение 2'));
  const csvEvent=page.waitForEvent('download'); await page.locator('#csv').click();
  const csv=fs.readFileSync(await (await csvEvent).path(),'utf8'); assert.equal(csv.trim().split('\n').length,15);
  checks.push('Voluntary blank JSON/CSV export, withdrawal, same-session import');
  await page.goto(pathToFileURL(path.resolve(run,'listener-2.html')).href);
  await page.locator('#start').click();
  assert.match(await page.locator('#progress').innerText(),/Сравнение 1 из 14/);
  await page.locator('#import').setInputFiles({name:'wrong-reviewer.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(state))});
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Файл не принят'));
  checks.push('Independent reviewer state and wrong-reviewer import rejection');
  for (const width of [390,1280]) {
    await page.setViewportSize({width,height:900});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
  const text=await page.locator('body').innerText();
  for(const forbidden of ['u01','s04','Bossa Nova','Joth','Junkala','score','rank']) assert(!text.includes(forbidden));
  assert.deepEqual(errors,[]); assert.deepEqual(requests,[]);
  checks.push('Mobile/desktop no overflow, blind DOM, no external requests or page errors');
  const version=browser.version();
  fs.writeFileSync(out,JSON.stringify({status:'PASS',browser:version,checks,human_answers_created:0,external_requests:0},null,2)+'\n',{flag:'wx',mode:0o600});
  } finally { await browser.close(); }
})().catch(e=>{console.error(e.message);process.exitCode=1;});
